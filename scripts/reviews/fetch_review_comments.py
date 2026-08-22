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
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://steamcommunity.com/",
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


# One comment block, non-greedy up to the next block or end of list.
COMMENT_BLOCK_RE = re.compile(
    r'<div class="commentthread_comment[^"]*"\s+id="comment_(?P<cid>\d+)"',
)
AUTHOR_LINK_RE = re.compile(
    r'<a[^>]*\shref="(?P<url>[^"]+)"[^>]*\sdata-miniprofile="(?P<miniprofile>\d+)"'
    r'|<a[^>]*\sdata-miniprofile="(?P<miniprofile2>\d+)"[^>]*\shref="(?P<url2>[^"]+)"',
)
PERSONA_RE = re.compile(r'<bdi>(?P<name>.*?)</bdi>', re.DOTALL)
TIMESTAMP_RE = re.compile(r'data-timestamp="(?P<ts>\d+)"')
# Comment body text sits in a nested <div class="commentthread_comment_text">;
# grab everything up to the matching close by stopping at the next sibling
# div with a *_timestamp or *_actions class, which is more reliable than
# balancing generic </div> tags across nested markup.
TEXT_RE = re.compile(
    r'<div class="commentthread_comment_text"[^>]*id="comment_content_\d+">'
    r'(?:\s*<bdi>.*?</bdi>)?'
    r'(?P<text>.*?)'
    r'(?:<div class="commentthread_comment_actions"|<span class="commentthread_comment_timestamp"|$)',
    re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]+>")


def http_post(url: str, data: dict, max_retries: int = 4) -> dict | None:
    """POST form-encoded data using the shared cookiejar opener, return
    parsed JSON or None on failure."""
    body = urllib.parse.urlencode(data).encode("utf-8")
    backoff = 2.0
    for attempt in range(1, max_retries + 1):
        req = urllib.request.Request(url, data=body, headers=HEADERS, method="POST")
        try:
            with _opener.open(req, timeout=20) as resp:
                raw = resp.read()
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                print(f"  [warn] HTTP {e.code} on {url}, backing off {backoff:.0f}s", file=sys.stderr)
                time.sleep(backoff)
                backoff *= 2
                continue
            print(f"  [warn] HTTP {e.code} on {url}", file=sys.stderr)
            return None
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
            print(f"  [warn] attempt {attempt}/{max_retries} failed on {url}: {e}", file=sys.stderr)
            if attempt == max_retries:
                return None
            time.sleep(backoff)
            backoff *= 2
    return None


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
            "comment_id": m.group("cid"),
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
                               debug_dump_path: str | None = None) -> tuple[list[dict], int | None]:
    """Returns (comments, total_count). total_count is Steam's reported
    total so callers can tell if pagination is needed (rare for reviews -
    comment threads under reviews are typically short)."""
    all_comments: list[dict] = []
    start = 0
    total_count = None
    seen_ids: set[str] = set()

    while True:
        url = COMMENT_URL.format(steamid=steamid, recid=recommendationid)
        payload = http_post(url, {"start": start, "count": count, "sessionid": session_id})

        if debug_dump_path and start == 0:
            # One-shot raw dump of the very first request/response this run,
            # so a "0 comments everywhere" failure can be diagnosed from the
            # CI artifact instead of guessing blind - see --debug-dump-first.
            try:
                with open(debug_dump_path, "w", encoding="utf-8") as f:
                    json.dump({
                        "url": url,
                        "steamid": steamid,
                        "recommendationid": recommendationid,
                        "session_id_present": bool(session_id),
                        "payload": payload,
                    }, f, ensure_ascii=False, indent=2)
            except OSError:
                pass

        if not payload or not payload.get("success"):
            break
        total_count = payload.get("total_count", total_count)
        comments_html = payload.get("comments_html") or ""
        batch = parse_comments_html(comments_html, recommendationid, steamid)
        new_batch = [c for c in batch if c["comment_id"] not in seen_ids]
        if not new_batch:
            break
        for c in new_batch:
            seen_ids.add(c["comment_id"])
        all_comments.extend(new_batch)

        if total_count is not None and len(all_comments) >= total_count:
            break
        if len(batch) < count:
            break
        start += count
        time.sleep(sleep_s)

    return all_comments, total_count


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

    print(f"Fetching comment threads for {len(candidates)} reviews "
          f"(out of {len(reviews)} total reviews)...")

    data = load_existing(args.out)
    data.setdefault("by_recommendationid", {})

    error = None
    fetched_reviews = 0
    fetched_comments = 0
    session_id = get_session_id()
    print(f"Obtained sessionid: {'<empty>' if not session_id else session_id[:6] + '...'}")
    try:
        for i, r in enumerate(candidates, 1):
            recid = r["recommendationid"]
            steamid = r["steamid"]
            dump_path = args.debug_dump_first if i == 1 else None
            comments, total_count = fetch_comments_for_review(steamid, recid, args.sleep, session_id,
                                                                debug_dump_path=dump_path)
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
