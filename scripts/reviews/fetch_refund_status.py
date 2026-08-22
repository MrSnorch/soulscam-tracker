#!/usr/bin/env python3
"""
Check whether reviews have Steam's "Product refunded" tag.

Unlike comment text (see fetch_review_comments.py's docstring), this tag
IS visible anonymously - it's rendered server-side on the public review
page for anyone, logged in or not:

    https://steamcommunity.com/profiles/{steamid}/recommended/{appid}

...as a plain <div class="refunded tooltip" data-tooltip-text="...">
Product refunded</div> when present, and simply absent from the page
otherwise. Confirmed against a real review page (see recommendationid
233... on this project's appid) rather than guessed at.

This is NOT available through the public appreviews JSON API at all (no
`refunded` field exists there - checked against the official Steamworks
docs), so this has to hit the HTML page directly, one request per review.
That's expensive and fragile compared to the JSON API:

  - One HTTP request per review, no batching - Steam doesn't expose a
    bulk endpoint for this.
  - It's screen-scraping: Valve can change class names/markup any time
    without notice, silently breaking this.
  - Hitting steamcommunity.com (not the store API) at volume from a
    datacenter IP risks rate limiting or CAPTCHAs, unlike the official
    appreviews API which is designed for this kind of polling.

To keep the load reasonable, by default this only checks reviews it
hasn't checked before (tracked in the --out file), so a normal CI run
only pays the cost for reviews new since last time, not the whole
history. Pass --recheck-all to force a full re-scan (e.g. after a schema
change), and --limit to cap how many get checked in a single run.

Usage:
    python scripts/reviews/fetch_refund_status.py \
        --reviews-in docs/reviews/latest.json \
        --out docs/reviews/refunds.json \
        --report-out tmp/report_refunds.json
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

USER_AGENT = "Mozilla/5.0 (compatible; steam-review-watch/1.0; +https://github.com/)"
REFUND_RE = re.compile(
    r'<div\s+class="refunded\s+tooltip"[^>]*>\s*Product refunded\s*</div>',
    re.IGNORECASE,
)


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


def check_review_page(steamid: str, appid: str, max_retries: int = 3,
                       timeout: int = 15) -> bool | None:
    """Returns True/False for refunded status, or None on fetch failure
    (page missing, network error, etc - callers should skip updating the
    record on None rather than assume 'not refunded')."""
    url = f"https://steamcommunity.com/profiles/{steamid}/recommended/{appid}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    backoff = 2.0
    for attempt in range(1, max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                html = resp.read().decode("utf-8", errors="replace")
                return bool(REFUND_RE.search(html))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print(f"    [warn] rate limited (429), backing off", file=sys.stderr)
            else:
                print(f"    [warn] HTTP {e.code} for {url}", file=sys.stderr)
            if attempt == max_retries:
                return None
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"    [warn] attempt {attempt}/{max_retries} failed: {e}", file=sys.stderr)
            if attempt == max_retries:
                return None
        time.sleep(backoff)
        backoff *= 2
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reviews-in", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sleep", type=float, default=1.5,
                     help="seconds between requests - be polite, this hits steamcommunity.com directly")
    ap.add_argument("--limit", type=int, default=150,
                     help="max number of reviews to check in this run")
    ap.add_argument("--recheck-all", action="store_true",
                     help="ignore the 'already checked' cache and re-check every review "
                          "(expensive - only use deliberately, e.g. after a markup change)")
    ap.add_argument("--report-out", default=None)
    args = ap.parse_args()

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

    print(f"Checking refund status for {len(to_check)} review(s) "
          f"(of {len(reviews)} total, {len(by_recid)} already cached)...")

    checked = 0
    refunded_found = 0
    failed = 0

    for i, r in enumerate(to_check, 1):
        recid = r.get("recommendationid")
        steamid = r.get("steamid")
        if not recid or not steamid or not appid:
            continue

        result = check_review_page(steamid, appid)
        checked += 1
        if result is None:
            failed += 1
            print(f"  [{i}/{len(to_check)}] {recid}: fetch failed, skipping")
        else:
            by_recid[recid] = {
                "recommendationid": recid,
                "steamid": steamid,
                "refunded": result,
                "checked_at": None,  # filled in below after we know now_iso
            }
            if result:
                refunded_found += 1
            print(f"  [{i}/{len(to_check)}] {recid}: refunded={result}")

        if i < len(to_check):
            time.sleep(args.sleep)

    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    for entry in by_recid.values():
        if entry.get("checked_at") is None:
            entry["checked_at"] = now_iso

    data["generated_at"] = now_iso
    data["appid"] = appid

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    total_refunded = sum(1 for e in by_recid.values() if e.get("refunded"))
    print(f"Wrote {args.out}: {len(by_recid)} reviews checked total, "
          f"{total_refunded} marked refunded ({refunded_found} newly found this run, "
          f"{failed} fetch failures)")

    if args.report_out:
        report = {
            "step": "fetch_refund_status",
            "ok": failed < checked or checked == 0,
            "error": None,
            "checked_this_run": checked,
            "failed_this_run": failed,
            "refunded_found_this_run": refunded_found,
            "total_checked": len(by_recid),
            "total_refunded": total_refunded,
            "remaining_unchecked": max(0, len(reviews) - len(by_recid)),
        }
        with open(args.report_out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False)


if __name__ == "__main__":
    main()
