#!/usr/bin/env python3
"""
Fetch the actual Steam comment-thread text posted under reviews.

The public appreviews API (fetch_reviews.py) only gives us `comment_count`
(how many comments exist under a review) - never the comment text itself.
To get real comment text we have to hit Steam's separate, undocumented-but-
stable comment-thread endpoint per review:

    POST https://steamcommunity.com/comment/Recommendation/render/{steamid}/{recommendationid}/
         start=0&count=100&sessionid=

This returns JSON with a `comments_html` blob (server-rendered HTML
fragment) rather than structured comment objects, so we regex-parse it -
same tradeoff scrape_forum.py makes, to avoid adding a BeautifulSoup
dependency to the CI environment.

IMPORTANT CAVEATS (read before relying on this in CI):
- This is HTML scraping, not Steam's official Web API. If Steam changes
  the comment thread markup, the regex extraction below can silently
  start returning nothing - if comments.json stops growing despite
  reviews with comment_count>0 existing, check the markup first.
- We only bother fetching threads for reviews where comment_count > 0
  (per the reviews API), which keeps the request volume small - in
  practice a low double-digit number of reviews per run for most apps.
- Datacenter IPs (GitHub Actions runners) can get rate-limited. A failed
  fetch for one review is skipped, not fatal - existing docs/reviews/
  comments.json data is left untouched on totally failed runs, so a bad
  run doesn't wipe prior data (see load_existing()).
- Deleted comments, deleted authors, or authors with restricted profiles
  can produce partially-empty fields (author name/avatar missing) - we
  keep the comment with whatever we could parse rather than dropping it.

Usage:
    python scripts/reviews/fetch_review_comments.py \
        --reviews-in docs/reviews/latest.json \
        --out docs/reviews/comments.json \
        --sleep 1.0
"""
import argparse
import html as html_lib
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
              "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "ru,uk;q=0.9,en-US;q=0.8,en;q=0.7",
    # A captured real-browser HAR request to a review page (no login, no
    # cookies sent) still got comments back inline in the HTML - that
    # request's exact header set is reproduced here (User-Agent, Accept,
    # Accept-Language, Referer) since Steam's response differs depending
    # on them; the previous minimal header set got a page ~33KB shorter
    # with no comment thread block in it at all.
    "Referer": "https://store.steampowered.com/",
}

COMMENT_URL = "https://steamcommunity.com/comment/Recommendation/render/{steamid}/{recid}/"

# Steam's comment-render endpoint expects a sessionid matching the
# anonymous session cookie it hands out on any normal page load - without
# it the endpoint can silently respond success=1 with an empty/short
# comments_html instead of erroring, which is why "0 comments everywhere"
# can happen with no visible HTTP error. We do one GET against the store
# front page first (via a cookiejar-backed opener) purely to pick up that
# cookie, then reuse the jar/opener for every comment request below.
_cookie_jar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cookie_jar))


def get_session_id(max_retries: int = 3) -> str:
    """GET steamcommunity.com once to obtain an anonymous `sessionid` cookie,
    which the comment-render endpoint requires to return real data."""
    req = urllib.request.Request("https://steamcommunity.com/", headers=HEADERS)
    backoff = 2.0
    for attempt in range(1, max_retries + 1):
        try:
            with _opener.open(req, timeout=20) as resp:
                resp.read()
            for cookie in _cookie_jar:
                if cookie.name == "sessionid":
                    return cookie.value
            print("  [warn] no sessionid cookie found after GET /", file=sys.stderr)
            return ""
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            print(f"  [warn] session-id GET attempt {attempt}/{max_retries} failed: {e}", file=sys.stderr)
            if attempt == max_retries:
                return ""
            time.sleep(backoff)
            backoff *= 2
    return ""


def fetch_review_page_html(steamid: str, recommendationid: str, max_retries: int = 4) -> str | None:
    """GET the review page itself and return its HTML.

    We used to POST to comment/Recommendation/render/ for comment data,
    but that AJAX endpoint requires a real logged-in session - an
    anonymous sessionid gets "This profile is private." on every request,
    regardless of the review author's actual visibility (confirmed via
    CI logs: 58/58 reviews, including public ones, all failed the same
    way).

    Fetching the review page itself doesn't work either, even with
    headers copied verbatim from a real browser's HAR capture, and even
    through a real headless Chromium (Playwright) with a genuine TLS
    fingerprint - the page comes back ~33KB shorter with no comment
    thread block at all, while the same URL from a residential IP
    (confirmed via that same HAR, an ordinary logged-out browser
    session) includes it, and a captured HAR of that session shows the
    full comment thread arriving in the *initial* HTML response, with
    no follow-up XHR/fetch for it - so this isn't a JS-timing issue
    either. That leaves the CI runner's datacenter IP: Akamai (Steam's
    CDN) is known to quietly degrade/strip content for datacenter IP
    ranges without an explicit block. PROXY_URL (below) routes the
    request through a proxy to test that theory - set it to bypass the
    runner's own IP.
    """
    review_url = f"https://steamcommunity.com/profiles/{steamid}/recommended/{recommendationid}"

    html = _fetch_via_browser(review_url)
    if html is not None:
        return html

    return _fetch_via_urllib(review_url, max_retries)


# Set via the PROXY_URL env var (e.g. a GitHub secret) to route requests
# through a proxy instead of the runner's own IP - e.g.
# "http://user:pass@host:port". Empty/unset means no proxy (direct).
#
# If PROXY_URL isn't set, we fall back to AUTO_PROXY: pull a batch of free
# public HTTP proxies from GitHub-hosted lists (updated every few minutes
# by their own scrapers) and test each one against a *known* review that
# has comments, until we find one that actually returns the comment
# thread block (not just "connects OK" - a proxy that connects but still
# gets the datacenter-stripped page is useless to us). Most free proxies
# are dead or are themselves datacenter IPs already blocked by the same
# Akamai rule, so this is a best-effort scan, not a guarantee.
PROXY_URL = os.environ.get("PROXY_URL", "").strip()
AUTO_PROXY = os.environ.get("AUTO_PROXY", "1").strip() not in ("0", "false", "False", "")

# A review known (as of writing) to have a real, publicly visible comment
# thread - used only to *validate* a candidate proxy actually gets the
# full page through, not to fetch real data for the dataset.
_PROXY_TEST_STEAMID = "76561198139136627"
_PROXY_TEST_RECID = "231090656"

# Free proxy lists hosted on GitHub, refreshed on a schedule by their own
# maintainers. Plain "ip:port" HTTP proxies, one per line / one per JSON
# entry depending on source.
FREE_PROXY_LIST_URLS = [
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/http/data.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
]

_auto_proxy_cache: dict[str, str | None] = {}


def _fetch_free_proxy_candidates(limit: int = 40) -> list[str]:
    """Pull a deduplicated batch of candidate 'http://ip:port' proxies
    from the public GitHub-hosted lists above. Best-effort: a list source
    that's down or empty is skipped, not fatal."""
    candidates: list[str] = []
    seen: set[str] = set()
    for url in FREE_PROXY_LIST_URLS:
        print(f"  [auto-proxy] fetching list: {url}", flush=True)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": HEADERS["User-Agent"]})
            with urllib.request.urlopen(req, timeout=15) as resp:
                text = resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            print(f"  [warn] couldn't fetch proxy list {url}: {e}", file=sys.stderr, flush=True)
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # normalize "ip:port" -> "http://ip:port"; ignore anything
            # that already has a scheme other than http
            if "://" not in line:
                line = "http://" + line
            if not line.startswith("http://"):
                continue
            if line in seen:
                continue
            seen.add(line)
            candidates.append(line)
        if len(candidates) >= limit:
            break
    return candidates[:limit]


def _proxy_returns_full_page(proxy_url: str, timeout: int = 6) -> bool:
    """Test one proxy against a review known to have comments. Returns
    True only if the response actually contains the comment thread
    marker - a proxy that merely connects but still gets the stripped
    datacenter-flavored page is not useful and must not be selected.

    Uses socket.setdefaulttimeout as a hard backstop: dead free proxies
    often hang on the TCP connect itself rather than refusing quickly,
    and urllib's timeout kwarg doesn't always cover that phase, which is
    what made earlier runs look "stuck" rather than just slow."""
    test_url = (
        f"https://steamcommunity.com/profiles/{_PROXY_TEST_STEAMID}"
        f"/recommended/{_PROXY_TEST_RECID}"
    )
    import socket
    prev_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    try:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"https": proxy_url, "http": proxy_url})
        )
        req = urllib.request.Request(test_url, headers=HEADERS)
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                import gzip
                raw = gzip.decompress(raw)
            html = raw.decode("utf-8", errors="replace")
            return "commentthread_comment" in html
    except Exception:
        return False
    finally:
        socket.setdefaulttimeout(prev_timeout)


def _find_working_free_proxy(max_candidates_to_try: int = 25, overall_deadline_s: float = 90.0) -> str | None:
    """Scan free public proxy lists for one that actually gets through
    with the full comment thread intact. Cached for the life of the
    process so we don't re-scan per review.

    Tests candidates concurrently (most free proxies are dead and would
    otherwise burn max_candidates_to_try * timeout seconds serially) and
    gives up after overall_deadline_s regardless of how many candidates
    were checked, so a bad proxy list can't stall the whole job."""
    if "result" in _auto_proxy_cache:
        return _auto_proxy_cache["result"]

    print("  [auto-proxy] no PROXY_URL set - scanning free public proxy lists...", flush=True)
    candidates = _fetch_free_proxy_candidates(limit=max_candidates_to_try)
    print(f"  [auto-proxy] {len(candidates)} candidate proxies pulled, testing "
          f"(up to {overall_deadline_s:.0f}s total)...", flush=True)

    if not candidates:
        print("  [auto-proxy] no candidates available - falling back to direct connection.", flush=True)
        _auto_proxy_cache["result"] = None
        return None

    import concurrent.futures
    start = time.monotonic()
    checked = 0
    found: str | None = None
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(10, len(candidates))) as pool:
        future_to_proxy = {pool.submit(_proxy_returns_full_page, p): p for p in candidates}
        try:
            for fut in concurrent.futures.as_completed(future_to_proxy, timeout=overall_deadline_s):
                proxy = future_to_proxy[fut]
                checked += 1
                elapsed = time.monotonic() - start
                try:
                    ok = fut.result()
                except Exception:
                    ok = False
                print(f"  [auto-proxy] [{checked}/{len(candidates)}, {elapsed:.0f}s] "
                      f"{proxy.split('@')[-1]}: {'OK' if ok else 'failed'}", flush=True)
                if ok:
                    found = proxy
                    break
        except concurrent.futures.TimeoutError:
            print(f"  [auto-proxy] overall deadline ({overall_deadline_s:.0f}s) reached, "
                  f"stopping scan ({checked}/{len(candidates)} checked).", flush=True)

    if found:
        print(f"  [auto-proxy] using {found.split('@')[-1]}", flush=True)
    else:
        print(f"  [auto-proxy] none of {checked} tested proxies worked - "
              f"falling back to direct connection.", flush=True)
    _auto_proxy_cache["result"] = found
    return found


def get_effective_proxy() -> str | None:
    """Returns the proxy URL to use: explicit PROXY_URL takes priority,
    otherwise auto-discovers a free one (if AUTO_PROXY is enabled),
    otherwise None (direct connection)."""
    if PROXY_URL:
        return PROXY_URL
    if AUTO_PROXY:
        return _find_working_free_proxy()
    return None


def _fetch_via_browser(review_url: str) -> str | None:
    """Fetch review_url with a real headless Chromium via Playwright.
    Returns None (not an error) if Playwright isn't installed, so the
    caller can fall back to the plain HTTP GET."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    try:
        with sync_playwright() as p:
            launch_kwargs = {}
            proxy = get_effective_proxy()
            if proxy:
                launch_kwargs["proxy"] = {"server": proxy}
            browser = p.chromium.launch(**launch_kwargs)
            page = browser.new_page(
                user_agent=HEADERS["User-Agent"],
                extra_http_headers={"Accept-Language": HEADERS["Accept-Language"]},
            )
            page.goto(review_url, timeout=20000, wait_until="domcontentloaded")
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        print(f"  [warn] Playwright fetch failed for {review_url}: {e}", file=sys.stderr)
        return None


def _fetch_via_urllib(review_url: str, max_retries: int) -> str | None:
    opener = _opener
    proxy = get_effective_proxy()
    if proxy:
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(_cookie_jar),
            urllib.request.ProxyHandler({"https": proxy, "http": proxy}),
        )
    backoff = 2.0
    for attempt in range(1, max_retries + 1):
        req = urllib.request.Request(review_url, headers=HEADERS)
        try:
            with opener.open(req, timeout=20) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    import gzip
                    raw = gzip.decompress(raw)
                return raw.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                print(f"  [warn] HTTP {e.code} on {review_url}, backing off {backoff:.0f}s", file=sys.stderr)
                time.sleep(backoff)
                backoff *= 2
                continue
            print(f"  [warn] HTTP {e.code} on {review_url}", file=sys.stderr)
            return None
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"  [warn] attempt {attempt}/{max_retries} failed on {review_url}: {e}", file=sys.stderr)
            if attempt == max_retries:
                return None
            time.sleep(backoff)
            backoff *= 2
    return None


# One comment block. Real Steam markup interleaves data-panel/style
# attributes between class= and id= in varying order (confirmed via a
# captured HAR: class comes with a trailing style="" before id, not
# adjacent to it as originally assumed) - match id="comment_NNN" and
# class="commentthread_comment..." independent of attribute order and
# spacing, rather than requiring one directly after the other.
COMMENT_BLOCK_RE = re.compile(
    r'<div[^>]*\bclass="commentthread_comment\b[^"]*"[^>]*\bid="comment_(?P<cid>\d+)"'
    r'|<div[^>]*\bid="comment_(?P<cid2>\d+)"[^>]*\bclass="commentthread_comment\b[^"]*"'
)
# Author link/name sits on an <a class="... commentthread_author_link ...">
# with data-miniprofile - real markup has other attributes (data-panel)
# between the tag open and href, so match on the author_link class marker
# rather than assuming href is the first attribute.
AUTHOR_LINK_RE = re.compile(
    r'<a[^>]*\bclass="[^"]*commentthread_author_link[^"]*"[^>]*\shref="(?P<url>[^"]+)"[^>]*\sdata-miniprofile="(?P<miniprofile>\d+)"'
    r'|<a[^>]*\bclass="[^"]*commentthread_author_link[^"]*"[^>]*\sdata-miniprofile="(?P<miniprofile2>\d+)"[^>]*\shref="(?P<url2>[^"]+)"',
)
PERSONA_RE = re.compile(r'<bdi>(?P<name>.*?)</bdi>', re.DOTALL)
TIMESTAMP_RE = re.compile(r'data-timestamp="(?P<ts>\d+)"')
# Comment body text sits in a nested <div class="commentthread_comment_text"
# id="comment_content_NNN">; grab everything up to the next sibling
# div.comment_footer_ctn (real markup) or the older commentthread_comment_actions
# div, whichever comes first.
TEXT_RE = re.compile(
    r'<div class="commentthread_comment_text"[^>]*id="comment_content_\d+">'
    r'(?P<text>.*?)'
    r'(?:<div class="comment_footer_ctn"|<div class="commentthread_comment_actions"|$)',
    re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]+>")


def clean_text(raw_html: str) -> str:
    """Strip tags from a comment body, unescape entities, collapse whitespace."""
    text = TAG_RE.sub(" ", raw_html)
    text = html_lib.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def parse_comments_html(comments_html: str, recommendationid: str, review_steamid: str) -> list[dict]:
    """Best-effort regex parse of the comments_html fragment into structured
    comment dicts. Steam doesn't hand us JSON for the comments themselves,
    only this pre-rendered HTML blob."""
    out = []
    # Split into per-comment chunks using the block start markers, then
    # scan each chunk for the fields we care about.
    starts = list(COMMENT_BLOCK_RE.finditer(comments_html))
    for i, m in enumerate(starts):
        chunk_start = m.start()
        chunk_end = starts[i + 1].start() if i + 1 < len(starts) else len(comments_html)
        chunk = comments_html[chunk_start:chunk_end]

        author_m = AUTHOR_LINK_RE.search(chunk)
        persona_m = PERSONA_RE.search(chunk)
        ts_m = TIMESTAMP_RE.search(chunk)
        text_m = TEXT_RE.search(chunk)

        author_url = None
        if author_m:
            author_url = author_m.group("url") or author_m.group("url2")

        out.append({
            "comment_id": m.group("cid") or m.group("cid2"),
            "recommendationid": recommendationid,
            "review_steamid": review_steamid,
            "author_steamid": None,  # data-miniprofile is a 32-bit account id, not the 64-bit steamid; keep profile_url instead
            "author_profile_url": author_url,
            "author_name": clean_text(persona_m.group("name")) if persona_m else None,
            "timestamp": int(ts_m.group("ts")) if ts_m else None,
            "text": clean_text(text_m.group("text")) if text_m else "",
        })
    return out


def fetch_comments_for_review(steamid: str, recommendationid: str, sleep_s: float,
                               session_id: str, count: int = 100,
                               debug_dump_path: str | None = None,
                               debug_print: bool = False) -> tuple[list[dict], int | None]:
    """Returns (comments, total_count).

    Pulls comments from the server-rendered review page HTML rather than
    the comment/Recommendation/render AJAX endpoint - that endpoint
    requires a real logged-in session and returns "This profile is
    private." for every anonymous request regardless of the review
    author's actual visibility. total_count is unknown from the page
    (Steam doesn't expose it there), so it's None; the page only includes
    the comments Steam chose to render, which may be fewer than the
    review's full comment_count for threads with many comments (no
    anonymous-accessible pagination beyond this without a logged-in
    session).
    """
    html = fetch_review_page_html(steamid, recommendationid)

    if debug_print:
        print(f"  [debug] page fetch for {recommendationid}: "
              f"{'got ' + str(len(html)) + ' chars' if html else 'FAILED'}")

    if debug_dump_path:
        try:
            # Dump the full HTML this time - the page is small (~80-110KB)
            # and prior snippet-around-a-marker dumps came back empty both
            # times, meaning neither "commentthread_comments" nor "Comments"
            # appear anywhere in what CI actually receives. Need to see the
            # whole thing to tell what page this even is.
            with open(debug_dump_path, "w", encoding="utf-8") as f:
                json.dump({
                    "steamid": steamid,
                    "recommendationid": recommendationid,
                    "html_len": len(html) if html else 0,
                    "html_full": html,
                }, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    if not html:
        return [], None

    comments = parse_comments_html(html, recommendationid, steamid)
    if debug_print and not comments:
        print(f"  [debug] page HTML fetched ({len(html)} chars) but parser "
              f"extracted 0 comments - markup may have changed or comments "
              f"aren't inlined in the page.")

    time.sleep(sleep_s)
    return comments, None


def load_existing(path: str) -> dict:
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"generated_at": None, "by_recommendationid": {}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reviews-in", required=True,
                     help="path to latest.json (or any file with a top-level 'reviews' list)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--recent-out", default=None,
                     help="optional path to write a flat 'most recent comments across all "
                          "reviews' list, sorted newest first, for the site's recent-comments view")
    ap.add_argument("--recent-limit", type=int, default=200)
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--max-reviews", type=int, default=None,
                     help="safety cap on how many distinct reviews to hit per run")
    ap.add_argument("--debug-dump-first", default=None,
                     help="optional path to dump the raw first request/response JSON, "
                          "for diagnosing a run that unexpectedly fetches 0 comments everywhere")
    ap.add_argument("--report-out", default=None)
    args = ap.parse_args()

    with open(args.reviews_in, encoding="utf-8") as f:
        latest = json.load(f)
    reviews = latest.get("reviews", [])

    candidates = [r for r in reviews if (r.get("comment_count") or 0) > 0
                  and r.get("steamid") and r.get("recommendationid")]
    if args.max_reviews:
        candidates = candidates[:args.max_reviews]

    # Steam's comment-render endpoint 403s with "This profile is private"
    # for any review whose author has a private profile - there's no way
    # around that anonymously, so skip those up front rather than wasting
    # a request (and a log line) on a guaranteed failure. account_visibility
    # comes from enrich_accounts.py; 3 = public, 2 = friends-only (also
    # blocked), 1 = private. Reviews without this field (enrichment didn't
    # run) are still attempted, since we can't tell in advance.
    skipped_private = [r for r in candidates if r.get("account_visibility") in (1, 2)]
    candidates = [r for r in candidates if r.get("account_visibility") not in (1, 2)]
    if skipped_private:
        print(f"Skipping {len(skipped_private)} reviews upfront: author profile is "
              f"private or friends-only (account_visibility 1/2) - Steam blocks "
              f"anonymous comment access to these regardless of the review itself.")

    print(f"Fetching comment threads for {len(candidates)} reviews "
          f"(out of {len(reviews)} total reviews)...")

    data = load_existing(args.out)
    data.setdefault("by_recommendationid", {})

    error = None
    fetched_reviews = 0
    fetched_comments = 0
    session_id = get_session_id()
    print(f"Obtained sessionid: {'<empty>' if not session_id else session_id[:6] + '...'}")
    _effective_proxy = get_effective_proxy()
    if PROXY_URL:
        print(f"Proxy: explicit PROXY_URL set (host={PROXY_URL.split('@')[-1]})")
    elif _effective_proxy:
        print(f"Proxy: auto-discovered free proxy (host={_effective_proxy.split('@')[-1]})")
    else:
        print("Proxy: none available - direct connection (datacenter IP, comments may come back empty)")
    # Dump the review with the highest comment_count, not just the first
    # candidate - the first candidate can have comment_count as low as 1
    # (nothing wrong there, just not representative), which made earlier
    # debug dumps misleading about what a real comment thread looks like.
    dump_recid = None
    if candidates:
        dump_recid = max(candidates, key=lambda r: r.get("comment_count") or 0)["recommendationid"]
    try:
        for i, r in enumerate(candidates, 1):
            recid = r["recommendationid"]
            steamid = r["steamid"]
            dump_path = args.debug_dump_first if recid == dump_recid else None
            comments, total_count = fetch_comments_for_review(steamid, recid, args.sleep, session_id,
                                                                debug_dump_path=dump_path,
                                                                debug_print=(i == 1 or recid == dump_recid))
            if comments:
                data["by_recommendationid"][recid] = {
                    "recommendationid": recid,
                    "review_steamid": steamid,
                    "review_author_personaname": r.get("personaname"),
                    "review_voted_up": r.get("voted_up"),
                    "review_excerpt": (r.get("review") or "")[:200],
                    "total_count": total_count,
                    "comments": comments,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }
                fetched_reviews += 1
                fetched_comments += len(comments)
            print(f"  [{i}/{len(candidates)}] review {recid}: +{len(comments)} comments "
                  f"(total kept: {fetched_comments})", flush=True)
            time.sleep(args.sleep)
    except Exception as e:
        error = str(e)
        print(f"[error] fetch_review_comments failed: {error}", file=sys.stderr)

    data["generated_at"] = datetime.now(timezone.utc).isoformat()
    data["appid"] = latest.get("appid")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Wrote {args.out} ({len(data['by_recommendationid'])} reviews with comments)")

    if args.recent_out:
        flat = []
        for entry in data["by_recommendationid"].values():
            for c in entry.get("comments", []):
                flat.append({
                    "comment_id": c.get("comment_id"),
                    "recommendationid": entry.get("recommendationid"),
                    "author_name": c.get("author_name"),
                    "author_profile_url": c.get("author_profile_url"),
                    "timestamp": c.get("timestamp"),
                    "text": c.get("text"),
                    "review_author_personaname": entry.get("review_author_personaname"),
                    "review_voted_up": entry.get("review_voted_up"),
                    "review_excerpt": entry.get("review_excerpt"),
                })
        flat.sort(key=lambda c: c.get("timestamp") or 0, reverse=True)
        flat = flat[:args.recent_limit]
        recent_payload = {
            "generated_at": data["generated_at"],
            "appid": data.get("appid"),
            "comments": flat,
        }
        with open(args.recent_out, "w", encoding="utf-8") as f:
            json.dump(recent_payload, f, ensure_ascii=False, separators=(",", ":"))
        print(f"Wrote {args.recent_out} ({len(flat)} recent comments)")

    if args.report_out:
        report = {
            "step": "fetch_review_comments",
            "ok": error is None,
            "error": error,
            "reviews_with_comments_checked": len(candidates),
            "reviews_with_comments_fetched": fetched_reviews,
            "comments_fetched": fetched_comments,
        }
        with open(args.report_out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False)

    if error:
        sys.exit(1)


if __name__ == "__main__":
    main()
