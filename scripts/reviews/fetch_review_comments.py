#!/usr/bin/env python3
"""
Track new comments appearing under Steam reviews, WITHOUT scraping comment
text.

Background (read before "fixing" this again): the public appreviews API
(fetch_reviews.py) gives us `comment_count` per review (how many comments
exist) but never the comment text itself. Getting the actual text requires
Steam's comment-thread render endpoint

    POST https://steamcommunity.com/comment/Recommendation/render/{steamid}/{recommendationid}/

which - confirmed after extensive testing (direct connection, residential
proxies, free public proxies, Tor, and a real headless-Chromium Playwright
session, all with headers copied verbatim from a real browser HAR) - only
returns real content for an AUTHENTICATED Steam session. An anonymous
`sessionid` gets "This profile is private" on every single review,
including ones whose authors have fully public profiles, 100% of the time.
This is not an IP/datacenter-flagging issue and no amount of proxying
fixes it; it requires real login cookies (steamLoginSecure + sessionid)
from a session that's actually signed in, which isn't something we're
doing in an unattended CI job.

So instead of chasing comment text, this script tracks *presence*: it
diffs `comment_count` for each review between the current run and the
last time this script ran, and records an event any time a review's
comment_count goes up. No network requests, no auth needed - it works
entirely off data fetch_reviews.py already collected.

Usage:
    python scripts/reviews/fetch_review_comments.py \
        --reviews-in docs/reviews/latest.json \
        --out docs/reviews/comments.json \
        --recent-out docs/reviews/recent-comments.json
"""
import argparse
import json
import os
from datetime import datetime, timezone


def load_existing(path: str) -> dict:
    """Load the previous comments.json. Its by_recommendationid map is
    also our source of truth for 'what comment_count did we last see for
    this review', so a missing/corrupt file just means every review looks
    new on this run (no crash, no data loss - it self-heals next run)."""
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                data.setdefault("by_recommendationid", {})
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"generated_at": None, "by_recommendationid": {}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reviews-in", required=True,
                     help="path to latest.json (or any file with a top-level 'reviews' list)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--recent-out", default=None,
                     help="optional path to write a flat 'most recent new-comment events "
                          "across all reviews' list, sorted newest first, for the site's "
                          "recent-comments view")
    ap.add_argument("--recent-limit", type=int, default=200)
    ap.add_argument("--report-out", default=None)
    args = ap.parse_args()

    with open(args.reviews_in, encoding="utf-8") as f:
        latest = json.load(f)
    reviews = latest.get("reviews", [])

    data = load_existing(args.out)
    by_recid = data["by_recommendationid"]

    now_iso = datetime.now(timezone.utc).isoformat()

    new_events = 0
    reviews_with_comments = 0
    checked = 0

    for r in reviews:
        recid = r.get("recommendationid")
        count = r.get("comment_count") or 0
        if not recid:
            continue
        checked += 1
        if count <= 0:
            # Comments can also get deleted (count going back down) - we
            # don't try to represent that, just leave the last-known
            # entry alone rather than deleting history over it.
            continue

        prev = by_recid.get(recid)
        prev_count = prev.get("comment_count", 0) if prev else 0

        entry = {
            "recommendationid": recid,
            "review_steamid": r.get("steamid"),
            "review_author_personaname": r.get("personaname"),
            "review_voted_up": r.get("voted_up"),
            "review_excerpt": (r.get("review") or "")[:200],
            "review_url": (
                f"https://steamcommunity.com/profiles/{r.get('steamid')}"
                f"/recommended/{recid}"
            ) if r.get("steamid") else None,
            "comment_count": count,
            "last_seen_at": now_iso,
        }

        if count > prev_count:
            entry["previous_comment_count"] = prev_count
            entry["new_comments_detected"] = count - prev_count
            entry["last_increase_at"] = now_iso
            new_events += (count - prev_count)
        elif prev:
            # No change since last run - keep the last known increase
            # timestamp so the "recent" feed doesn't treat an unchanged
            # review as freshly new on every run.
            entry["previous_comment_count"] = prev.get("previous_comment_count", prev_count)
            entry["new_comments_detected"] = 0
            entry["last_increase_at"] = prev.get("last_increase_at")
        else:
            # First time we've ever seen this review with comment_count>0.
            # Not a "new" event in the delta sense (we have no prior
            # baseline to compare against), but still worth surfacing once
            # so it doesn't disappear from the feed forever.
            entry["previous_comment_count"] = 0
            entry["new_comments_detected"] = count
            entry["last_increase_at"] = now_iso
            new_events += count

        by_recid[recid] = entry
        reviews_with_comments += 1

    data["generated_at"] = now_iso
    data["appid"] = latest.get("appid")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Wrote {args.out} ({len(by_recid)} reviews with comments tracked, "
          f"{new_events} new comments detected this run)")

    if args.recent_out:
        flat = [
            {
                "recommendationid": e["recommendationid"],
                "review_steamid": e.get("review_steamid"),
                "review_author_personaname": e.get("review_author_personaname"),
                "review_voted_up": e.get("review_voted_up"),
                "review_excerpt": e.get("review_excerpt"),
                "review_url": e.get("review_url"),
                "comment_count": e.get("comment_count"),
                "previous_comment_count": e.get("previous_comment_count"),
                "new_comments_detected": e.get("new_comments_detected", 0),
                "last_increase_at": e.get("last_increase_at"),
            }
            for e in by_recid.values()
            if e.get("last_increase_at")
        ]
        # newest increase first; ISO8601 strings sort correctly as text
        flat.sort(key=lambda e: e.get("last_increase_at") or "", reverse=True)
        flat = flat[:args.recent_limit]
        recent_payload = {
            "generated_at": data["generated_at"],
            "appid": data.get("appid"),
            "comments": flat,
        }
        with open(args.recent_out, "w", encoding="utf-8") as f:
            json.dump(recent_payload, f, ensure_ascii=False, separators=(",", ":"))
        print(f"Wrote {args.recent_out} ({len(flat)} recent comment events)")

    if args.report_out:
        report = {
            "step": "fetch_review_comments",
            "ok": True,
            "error": None,
            "reviews_checked": checked,
            "reviews_with_comments": reviews_with_comments,
            "new_comments_detected": new_events,
        }
        with open(args.report_out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False)


if __name__ == "__main__":
    main()
