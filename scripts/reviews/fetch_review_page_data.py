#!/usr/bin/env python3
"""
Scrape per-review data that ONLY exists on Steam's community pages, not
in the appreviews JSON API: the "Product refunded" tag, and the actual
text of ALL comments posted under the review (not just the first page).

Refund status comes from the review's own page:

    https://steamcommunity.com/profiles/{steamid}/recommended/{appid}

    <div class="refunded tooltip" data-tooltip-text="...">
        Product refunded
    </div>

Comment text comes from Steam's comment-thread pagination endpoint:

    POST https://steamcommunity.com/comment/Recommendation/render/{steamid}/{appid}/
    body: start={n}&count={page_size}

Both are confirmed working ANONYMOUSLY - tested for real, not assumed:
the refund tag was checked in an actual incognito browser window against
a live review page, and the comment endpoint was checked with a fresh
anonymous sessionid cookie obtained in incognito (not a logged-in
session), both against this project's real appid. This directly
contradicts this project's own earlier finding that the render/ endpoint
requires authentication - that conclusion was wrong (or Steam's behavior
here has changed since); trust this file's docstring over any older
comment in this repo's history that says otherwise.

IMPORTANT: "anonymous" here means "no login required", not "no cookies
required". The comment/render/ endpoint intermittently returns
{"success": false, "error": "This profile is private."} for requests
that carry no sessionid cookie at all (confirmed directly in CI logs -
about half of requests with zero cookies failed this way, the rest
succeeded). A real browser - logged in or not - always has an anonymous
sessionid cookie the moment it loads any steamcommunity.com page, since
Steam issues one via Set-Cookie on first visit; a bare script making
one-off requests never picks one up unless it explicitly keeps a cookie
jar across requests, which is what this script now does
(ensure_session_cookie() + a shared http.cookiejar.CookieJar via
urllib.request.HTTPCookieProcessor).

The endpoint pages through the full comment thread (e.g. 10 per page,
109 total across 11 pages for a busy review) rather than being capped at
whatever the main review page server-renders on first load (~10), so
this captures the complete comment history, not just a sample.

Response shape:
    {
      "success": true,
      "start": 10, "pagesize": "10", "total_count": 109,
      "comments_html": "<div class=\"commentthread_comment ...\" id=\"comment_{id}\">...",
      ...
    }

comments_html has the same per-comment markup as the main review page
(author link+name, unix timestamp, comment text), so the same regex
extraction is reused for both.

Both are still HTML/AJAX scraping, not a documented API, so the same
caveats apply:
  - Two-plus HTTP requests per review (one for refund status, one or
    more for comment pages) - no bulk endpoint exists for any of this.
  - Fragile: Valve can change class names/markup or endpoint behavior
    without notice.
  - Hitting steamcommunity.com at volume from a datacenter IP (like a
    GitHub Actions runner) may get rate-limited or CAPTCHA'd even though
    it worked fine from a residential IP in manual testing - watch the
    first few CI runs after enabling this.
  - Reviews with very large comment counts mean very large numbers of
    requests (a comment count of 1000+ would be 100+ paginated
    requests just for that one review) - --max-comment-pages caps this
    per review so one busy review thread can't eat the whole run's
    request budget.

To keep load reasonable, only reviews not yet in --out get checked each
run (by default), so a normal CI run only pays for reviews new since
last time. Pass --recheck-all to force a full re-scan.

Usage:
    python scripts/reviews/fetch_review_page_data.py \
        --reviews-in docs/reviews/latest.json \
        --out docs/reviews/review_page_data.json \
        --recent-comments-out docs/reviews/recent-comments.json \
        --report-out tmp/report_page_data.json
"""
import argparse
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
from html import unescape

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"

# Steam's comment/Recommendation/render/ endpoint intermittently returns
# {"success": false, "error": "This profile is private."} for anonymous
# requests that carry no sessionid cookie at all - seen directly in CI
# logs, mixed in with plenty of requests that succeed with no cookie.
# Confirmed in a real incognito browser that this endpoint DOES work
# anonymously as long as Steam has issued that browser an anonymous
# sessionid cookie (which it does automatically as soon as you load any
# steamcommunity.com page, no login required) - the earlier bare
# urllib.request calls here just never picked one up in the first place.
# A shared cookiejar across the whole run picks up and reuses that
# anonymous sessionid automatically via Set-Cookie, the same way a real
# browser tab would.
_cookie_jar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cookie_jar))

REFUND_RE = re.compile(
    r'<div\s+class="refunded\s+tooltip"[^>]*>\s*Product refunded\s*</div>',
    re.IGNORECASE,
)

# One capture group per comment "envelope" (id), then we pull author/
# timestamp/text out of the slice between this comment's start and the
# next one, rather than one giant regex, since comment blocks can nest
# other divs with similar-looking attributes and a single top-to-bottom
# regex risks matching across comment boundaries. Same markup appears in
# both the main review page and the comment/render/ AJAX response.
COMMENT_BLOCK_START_RE = re.compile(
    r'<div[^>]+class="commentthread_comment responsive_body_text[^"]*"\s+id="comment_(\d+)"',
)
AUTHOR_RE = re.compile(
    r'class="hoverunderline commentthread_author_link"\s+href="([^"]+)"[^>]*>\s*<bdi>([^<]*)</bdi>',
)
TIMESTAMP_RE = re.compile(
    r'class="commentthread_comment_timestamp"\s+title="[^"]*"\s+data-timestamp="(\d+)"',
)
TEXT_RE = re.compile(
    r'class="commentthread_comment_text"\s+id="comment_content_\d+">\s*(.*?)\s*</div>',
    re.DOTALL,
)


def extract_comments(html: str) -> list[dict]:
    """Split the page/fragment into per-comment slices using each comment
    block's start position as a boundary, then extract author/timestamp/
    text from within each slice. Returns in document order (Steam's own
    ordering, which is newest-first per page)."""
    starts = list(COMMENT_BLOCK_START_RE.finditer(html))
    comments = []
    for i, m in enumerate(starts):
        comment_id = m.group(1)
        slice_start = m.start()
        slice_end = starts[i + 1].start() if i + 1 < len(starts) else len(html)
        chunk = html[slice_start:slice_end]

        author_m = AUTHOR_RE.search(chunk)
        ts_m = TIMESTAMP_RE.search(chunk)
        text_m = TEXT_RE.search(chunk)
        if not text_m:
            continue  # malformed/unexpected chunk, skip rather than guess

        raw_text = re.sub(r"<br\s*/?>", "\n", text_m.group(1), flags=re.IGNORECASE)
        text = re.sub(r"[ \t]+", " ", raw_text).strip()
        text = unescape(text)
        if not text:
            continue

        comments.append({
            "comment_id": comment_id,
            "author_name": unescape(author_m.group(2)) if author_m else None,
            "author_profile_url": author_m.group(1) if author_m else None,
            "timestamp": int(ts_m.group(1)) if ts_m else None,
            "text": text,
        })
    return comments


def load_existing(path: str) -> dict:
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                data.setdefault("by_recommendationid", {})
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"generated_at": None, "by_recommendationid": {}}


def _request(url: str, method: str = "GET", data: bytes | None = None,
             extra_headers: dict | None = None, max_retries: int = 3,
             timeout: int = 15) -> str | None:
    """Shared GET/POST fetch with retry+backoff. Returns decoded text body,
    or None on failure after retries."""
    headers = {"User-Agent": USER_AGENT}
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    backoff = 2.0
    for attempt in range(1, max_retries + 1):
        try:
            with _opener.open(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print(f"    [warn] rate limited (429) for {url}", file=sys.stderr)
            else:
                print(f"    [warn] HTTP {e.code} for {url}", file=sys.stderr)
            if attempt == max_retries:
                return None
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"    [warn] attempt {attempt}/{max_retries} failed for {url}: {e}", file=sys.stderr)
            if attempt == max_retries:
                return None
        time.sleep(backoff)
        backoff *= 2
    return None


def fetch_refund_status(steamid: str, appid: str) -> bool | None:
    """Returns True/False, or None if the page couldn't be fetched."""
    url = f"https://steamcommunity.com/profiles/{steamid}/recommended/{appid}"
    html = _request(url)
    if html is None:
        return None
    return bool(REFUND_RE.search(html))


def ensure_session_cookie() -> bool:
    """Loads the plain steamcommunity.com homepage once so Steam issues an
    anonymous sessionid via Set-Cookie into the shared cookiejar, the same
    way a fresh incognito tab gets one just from opening the site. Returns
    whether a sessionid cookie is present afterward (it should be, but
    this makes the assumption checkable rather than silent)."""
    _request("https://steamcommunity.com/")
    return any(c.name == "sessionid" for c in _cookie_jar)


def fetch_all_comments(steamid: str, appid: str, page_size: int = 10,
                        max_pages: int = 15, sleep: float = 1.0) -> tuple[list[dict], bool]:
    """Pages through comment/Recommendation/render/ to collect every
    comment on the review. Returns (comments, complete) where `complete`
    is False if we stopped early due to max_pages or a fetch failure
    partway through - callers can use that to avoid treating a partial
    scrape as the final word on a review's comments."""
    render_url = f"https://steamcommunity.com/comment/Recommendation/render/{steamid}/{appid}/"
    referer = f"https://steamcommunity.com/profiles/{steamid}/recommended/{appid}"
    headers = {
        "Referer": referer,
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }

    all_comments = []
    start = 0
    total_count = None
    page_num = 0

    while True:
        page_num += 1
        if page_num > max_pages:
            return all_comments, False

        body = urllib.parse.urlencode({"start": start, "count": page_size}).encode()
        raw = _request(render_url, method="POST", data=body, extra_headers=headers)
        if raw is None:
            return all_comments, False  # _request already logged the HTTP/network error

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            print(f"    [warn] non-JSON response from comment render endpoint "
                  f"(page {page_num}, first 200 chars: {raw[:200]!r})", file=sys.stderr)
            return all_comments, False

        if not payload.get("success"):
            print(f"    [warn] comment render endpoint returned success=false "
                  f"(page {page_num}): {payload}", file=sys.stderr)
            return all_comments, False

        if total_count is None:
            total_count = payload.get("total_count", 0)

        page_comments = extract_comments(payload.get("comments_html", ""))
        if not page_comments:
            if page_num == 1 and total_count and total_count > 0:
                print(f"    [warn] API reports total_count={total_count} but page 1 "
                      f"parsed 0 comments - extraction regex may not match this "
                      f"response's markup", file=sys.stderr)
            break
        all_comments.extend(page_comments)

        start += page_size
        if start >= total_count:
            break
        time.sleep(sleep)

    return all_comments, True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reviews-in", required=True)
    ap.add_argument("--out", required=True,
                     help="main output: per-review refund status + full comment list")
    ap.add_argument("--recent-comments-out", default=None,
                     help="optional: flat, newest-first list of individual comments across "
                          "all checked reviews, for the site's 'recent comments' feed")
    ap.add_argument("--recent-limit", type=int, default=200)
    ap.add_argument("--sleep", type=float, default=1.5,
                     help="seconds between requests - be polite, this hits steamcommunity.com directly")
    ap.add_argument("--limit", type=int, default=100,
                     help="max number of reviews to check in this run")
    ap.add_argument("--comment-page-size", type=int, default=10)
    ap.add_argument("--max-comment-pages", type=int, default=15,
                     help="cap on paginated requests per review, so one review with a huge "
                          "comment thread can't consume the whole run's request budget")
    ap.add_argument("--recheck-all", action="store_true",
                     help="ignore the 'already checked' cache and re-check every review "
                          "(expensive - use deliberately, e.g. to pick up new comments on "
                          "already-checked reviews, or after a markup change)")
    ap.add_argument("--report-out", default=None)
    args = ap.parse_args()

    have_session = ensure_session_cookie()
    if have_session:
        print("Anonymous session cookie acquired.")
    else:
        print("[warn] no sessionid cookie after warmup request - comment "
              "fetches may fail with 'This profile is private.'", file=sys.stderr)

    with open(args.reviews_in, encoding="utf-8") as f:
        latest = json.load(f)
    reviews = latest.get("reviews", [])
    appid = latest.get("appid")

    data = load_existing(args.out)
    by_recid = data["by_recommendationid"]

    if args.recheck_all:
        to_check = reviews
    else:
        to_check = [r for r in reviews if r.get("recommendationid") not in by_recid]

    to_check = to_check[: args.limit]

    print(f"Checking {len(to_check)} review(s) "
          f"(of {len(reviews)} total, {len(by_recid)} already cached)...")

    checked = 0
    refunded_found = 0
    comments_found = 0
    failed = 0
    incomplete = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    for i, r in enumerate(to_check, 1):
        recid = r.get("recommendationid")
        steamid = r.get("steamid")
        if not recid or not steamid or not appid:
            continue

        refunded = fetch_refund_status(steamid, appid)
        time.sleep(args.sleep)
        comments, complete = fetch_all_comments(
            steamid, appid,
            page_size=args.comment_page_size,
            max_pages=args.max_comment_pages,
            sleep=args.sleep,
        )
        checked += 1

        if refunded is None:
            failed += 1
            print(f"  [{i}/{len(to_check)}] {recid}: refund check failed, skipping this review")
        else:
            by_recid[recid] = {
                "recommendationid": recid,
                "steamid": steamid,
                "review_voted_up": r.get("voted_up"),
                "review_author_personaname": r.get("personaname"),
                "review_excerpt": (r.get("review") or "")[:200],
                "review_url": f"https://steamcommunity.com/profiles/{steamid}/recommended/{appid}",
                "refunded": refunded,
                "comments": comments,
                "comments_complete": complete,
                "checked_at": now_iso,
            }
            if refunded:
                refunded_found += 1
            comments_found += len(comments)
            if not complete:
                incomplete += 1
            status = "" if complete else " (partial - hit page cap or a request failed)"
            print(f"  [{i}/{len(to_check)}] {recid}: refunded={refunded}, "
                  f"comments={len(comments)}{status}")

        if i < len(to_check):
            time.sleep(args.sleep)

    data["generated_at"] = now_iso
    data["appid"] = appid

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    total_refunded = sum(1 for e in by_recid.values() if e.get("refunded"))
    total_comments = sum(len(e.get("comments") or []) for e in by_recid.values())
    print(f"Wrote {args.out}: {len(by_recid)} reviews checked total, "
          f"{total_refunded} refunded, {total_comments} comments captured "
          f"({comments_found} found this run, {failed} fetch failures, "
          f"{incomplete} partial comment scrapes)")

    if args.recent_comments_out:
        flat = []
        for entry in by_recid.values():
            for c in (entry.get("comments") or []):
                flat.append({
                    "recommendationid": entry["recommendationid"],
                    "comment_id": c["comment_id"],
                    "author_name": c.get("author_name"),
                    "author_profile_url": c.get("author_profile_url"),
                    "text": c.get("text"),
                    "timestamp": c.get("timestamp"),
                    "review_steamid": entry.get("steamid"),
                    "review_author_personaname": entry.get("review_author_personaname"),
                    "review_voted_up": entry.get("review_voted_up"),
                    "review_excerpt": entry.get("review_excerpt"),
                    "review_url": entry.get("review_url"),
                })
        flat.sort(key=lambda c: c.get("timestamp") or 0, reverse=True)
        flat = flat[: args.recent_limit]
        recent_payload = {
            "generated_at": now_iso,
            "appid": appid,
            "comments": flat,
        }
        with open(args.recent_comments_out, "w", encoding="utf-8") as f:
            json.dump(recent_payload, f, ensure_ascii=False, separators=(",", ":"))
        print(f"Wrote {args.recent_comments_out} ({len(flat)} recent comments)")

    if args.report_out:
        report = {
            "step": "fetch_review_page_data",
            "ok": failed < checked or checked == 0,
            "error": None,
            "checked_this_run": checked,
            "failed_this_run": failed,
            "incomplete_this_run": incomplete,
            "refunded_found_this_run": refunded_found,
            "comments_found_this_run": comments_found,
            "total_checked": len(by_recid),
            "total_refunded": total_refunded,
            "total_comments": total_comments,
            "remaining_unchecked": max(0, len(reviews) - len(by_recid)),
        }
        with open(args.report_out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False)


if __name__ == "__main__":
    main()
