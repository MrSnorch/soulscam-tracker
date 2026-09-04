#!/usr/bin/env python3
"""
One-off cleanup for player_count=0 glitch readings recorded before
poll.py gained its own re-confirmation guard against them (see the
is_suspicious_zero()/fetch_player_count_confirmed() functions there).

This does NOT delete every 0 - a game can genuinely have zero
concurrent players, especially a small/dead one, and that's real data
worth keeping. It only removes a 0 that's "sandwiched": surrounded on
both sides (within a short time window) by clearly nonzero readings,
which is the exact pattern a transient API glitch produces and a real
population crash to zero does not (a real crash doesn't un-crash a
minute later).

Usage:
    python3 scripts/clean_glitch_zeros.py --dry-run     # just report
    python3 scripts/clean_glitch_zeros.py                # apply + rebuild index

After removing points, run build-index.py again (this script does that
automatically unless --skip-rebuild is passed) so recent.json,
points.json, and points-by-day/*.json.gz reflect the cleaned data. Any
hour/day this script actually changes is also evicted from
build-index.py's own caches (.recent-cache.json, points-index.json)
first, since build-index.py otherwise trusts cached data for anything
outside the current UTC hour and the last couple of days - without
this, a fix to an older hourly file wouldn't show up in the aggregated
files at all.
"""

import argparse
import gzip
import io
import json
import os
import glob
import subprocess
import sys
from datetime import datetime, timedelta, timezone

HOURLY_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "hourly")
RECENT_CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", ".recent-cache.json")
POINTS_INDEX_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "points-index.json")

# A 0 is only considered a glitch if both its immediate neighbors (by
# time, not just adjacent in the file) are within this many seconds and
# both nonzero. This deliberately does not touch a 0 that sits next to
# another 0, or one with no nonzero neighbor close by in time - those
# look like a real (possibly sustained) drop, not a one-poll blip.
#
# Set well above the 60s poll interval: fetch_player_count() itself can
# take up to ~20s across its retry backoff (delays of 0/5/15s), and a
# 180s cap was observed in practice to miss a run whose nearest healthy
# neighbor was 182s away - a false negative caused by a real glitch that
# happened to line up with normal request jitter, not a case that needed
# to be excluded.
MAX_NEIGHBOR_GAP_SEC = 300

# Skip the current UTC hour and the one before it - poll.py may be
# actively appending to those exact hourly files right now (it flushes
# every minute). Rewriting a file poll.py is mid-write to is a real race:
# whichever of the two processes writes last wins and the other's change
# is silently lost. Every older hour is finalized and safe to touch, so
# this cleanup can run any time without needing to wait for the poller
# to be idle (no concurrency lock required in the workflow).
def live_hour_keys():
    now = datetime.now(timezone.utc)
    return {
        now.strftime("%Y-%m-%dT%H"),
        (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H"),
    }


def write_gzip_json(path, obj):
    payload = json.dumps(obj).encode("utf-8")
    buf = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buf, mtime=0) as gz:
        gz.write(payload)
    with open(path, "wb") as f:
        f.write(buf.getvalue())


def clean_points(points):
    """Returns (cleaned_points, changed_points).

    A run of consecutive player_count=0 readings that is bounded on both
    sides (within MAX_NEIGHBOR_GAP_SEC of the run's edges) by clearly
    nonzero readings is treated as an API glitch, not a real drop to
    zero - a real crash to zero doesn't un-crash a few minutes later on
    its own. Each 0 in such a run is replaced with a value linearly
    interpolated between the last known-good reading before the run and
    the first known-good reading after it (weighted by each point's own
    timestamp), rather than deleted or forward-filled, so the timeline
    keeps its normal point spacing and follows the trend between the two
    real readings instead of flattening it.

    A 0 that isn't bounded like this (leading/trailing run with no
    healthy neighbor close by, or the very first/last points overall) is
    left untouched - that looks like a real and possibly still-ongoing
    drop, and forward-filling it would be fabricating data instead of
    correcting a known glitch pattern.
    """
    pts = sorted(points, key=lambda p: p["ts"])
    n = len(pts)
    changed = []
    result = [dict(p) for p in pts]

    i = 0
    while i < n:
        if result[i]["player_count"] != 0:
            i += 1
            continue

        # found the start of a run of zeros; find its end
        j = i
        while j < n and result[j]["player_count"] == 0:
            j += 1
        run = result[i:j]  # zeros at indices [i, j)

        prev_point = pts[i - 1] if i > 0 else None
        next_point = pts[j] if j < n else None

        prev_ok = (
            prev_point is not None and prev_point["player_count"] > 0
            and abs((datetime.fromisoformat(run[0]["ts"]) - datetime.fromisoformat(prev_point["ts"])).total_seconds()) <= MAX_NEIGHBOR_GAP_SEC
        )
        next_ok = (
            next_point is not None and next_point["player_count"] > 0
            and abs((datetime.fromisoformat(next_point["ts"]) - datetime.fromisoformat(run[-1]["ts"])).total_seconds()) <= MAX_NEIGHBOR_GAP_SEC
        )

        if prev_ok and next_ok:
            prev_count = prev_point["player_count"]
            next_count = next_point["player_count"]
            prev_ts = datetime.fromisoformat(prev_point["ts"])
            next_ts = datetime.fromisoformat(next_point["ts"])
            span = (next_ts - prev_ts).total_seconds()
            for k in range(i, j):
                if span > 0:
                    frac = (datetime.fromisoformat(pts[k]["ts"]) - prev_ts).total_seconds() / span
                else:
                    frac = 0.5
                fill_value = round(prev_count + (next_count - prev_count) * frac)
                result[k]["player_count"] = fill_value
                changed.append({"ts": pts[k]["ts"], "from": 0, "to": fill_value})

        i = j

    return result, changed


def invalidate_caches(touched_hours):
    """build-index.py trusts its own caches for anything that isn't the
    current/previous UTC hour or one of the last two days - a rewritten
    hourly .gz file on disk isn't enough on its own to make it re-read
    a day/hour it now considers old. Force it to by removing exactly
    the hours/days this run actually changed from those caches, so
    build-index.py's normal "not live -> trust the cache" fast path is
    bypassed only for what changed, not for everything.
    """
    if not touched_hours:
        return

    if os.path.exists(RECENT_CACHE_PATH):
        try:
            with open(RECENT_CACHE_PATH) as f:
                cache = json.load(f)
        except (json.JSONDecodeError, OSError):
            cache = {}
        removed_hours = [h for h in touched_hours if cache.pop(h, None) is not None]
        if removed_hours:
            with open(RECENT_CACHE_PATH, "w") as f:
                json.dump(cache, f)
            print(f"Invalidated {len(removed_hours)} hour(s) in .recent-cache.json so build-index.py re-reads them.")

    touched_days = {h[:10] for h in touched_hours}
    if os.path.exists(POINTS_INDEX_PATH):
        try:
            with open(POINTS_INDEX_PATH) as f:
                index = json.load(f)
        except (json.JSONDecodeError, OSError):
            index = []
        new_index = [d for d in index if d.get("day") not in touched_days]
        if len(new_index) != len(index):
            with open(POINTS_INDEX_PATH, "w") as f:
                json.dump(new_index, f)
            print(f"Invalidated {len(index) - len(new_index)} day(s) in points-index.json so build-index.py rebuilds their points-by-day file.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report what would be removed, don't write anything")
    ap.add_argument("--skip-rebuild", action="store_true", help="don't run build-index.py afterward")
    args = ap.parse_args()

    live_hours = live_hour_keys()
    skipped_live = 0

    # Load every non-live hourly file into one combined, time-sorted stream
    # of points before cleaning - a glitch run can straddle an hour
    # boundary (e.g. 4 zeros at the end of hour N, 12 more at the start of
    # hour N+1), and cleaning each file in isolation would see a run like
    # that as having no healthy neighbor on one side, missing it entirely.
    all_points = []  # each: dict with the point's fields plus "_hour"
    file_data = {}   # hour -> parsed json object (for writing back)
    for path in sorted(glob.glob(os.path.join(HOURLY_DIR, "*.json.gz"))):
        hour = os.path.basename(path).removesuffix(".json.gz")
        if hour in live_hours:
            skipped_live += 1
            continue
        with gzip.open(path, "rt") as f:
            data = json.load(f)
        file_data[hour] = data
        for p in data.get("points", []):
            tagged = dict(p)
            tagged["_hour"] = hour
            all_points.append(tagged)

    if not all_points:
        print("No non-live hourly files with points found.")
        return

    cleaned, removed = clean_points(all_points)

    if not removed:
        print("No glitch zeros found.")
        if skipped_live:
            print(f"Skipped {skipped_live} file(s) for the current/previous UTC hour: {sorted(live_hours)}")
        return

    print(f"Found {len(removed)} glitch zero point(s):")
    for r in removed:
        print(f"  - {r['ts']} player_count=0 -> {r['to']}")

    if args.dry_run:
        print()
        print(f"DRY RUN: would fix {len(removed)} glitch zero point(s).")
        print("Re-run without --dry-run to apply.")
        return

    # Regroup cleaned points back by their original file's hour and
    # rewrite only the files that actually changed.
    by_hour = {}
    for p in cleaned:
        by_hour.setdefault(p["_hour"], []).append({k: v for k, v in p.items() if k != "_hour"})

    touched_files = 0
    touched_hours = set()
    for hour, data in file_data.items():
        new_points = by_hour.get(hour, [])
        if new_points != data.get("points", []):
            data["points"] = new_points
            path = os.path.join(HOURLY_DIR, f"{hour}.json.gz")
            write_gzip_json(path, data)
            touched_files += 1
            touched_hours.add(hour)

    invalidate_caches(touched_hours)

    print()
    if skipped_live:
        print(f"Skipped {skipped_live} file(s) for the current/previous UTC hour (may be actively written by the poller): {sorted(live_hours)}")
    print(f"Fixed {len(removed)} glitch zero point(s) across {touched_files} file(s).")

    if not args.skip_rebuild:
        print("Rebuilding recent.json / points.json / points-by-day/ from cleaned hourly files...")
        build_index = os.path.join(os.path.dirname(__file__), "build-index.py")
        subprocess.run([sys.executable, build_index], check=True)


if __name__ == "__main__":
    main()
