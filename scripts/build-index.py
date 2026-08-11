#!/usr/bin/env python3
"""
Read docs/hourly/*.json.gz snapshots and build:
- docs/recent.json: one row per hour with avg/max/min player_count (small,
  used by the hourly overview/compare charts).
- docs/points.json: raw {ts, player_count} points for the last RECENT_HOURS
  hours only, used by the live chart for an instant first paint.
- docs/points-by-day/YYYY-MM-DD.json.gz: full-resolution points for every
  day, one small gzip file each. The dashboard fetches these lazily when
  the person zooms/pans into a day not already in memory, so all history
  stays reachable without shipping it all up front.
- docs/points-index.json: which days have a points-by-day file and how
  many points each has, so the dashboard knows what it can fetch.

This runs on a tight schedule (as often as once a minute), so it's built
to stay cheap and to avoid both wasted I/O and spurious git diffs:
- docs/recent.json is rebuilt from a *cache* (docs/.recent-cache.json) that
  already holds the parsed hour/avg/max/min for every hour except the
  live ones, so old hourly .gz files are only ever decoded once, not on
  every run. Only "live" hours (this UTC hour + the previous one, to
  cover late-arriving flushes right after an hour boundary) are re-read.
- Only "live" days (today + yesterday) get their points-by-day file and
  their contribution to points.json recomputed; older days are trusted
  from the cache/existing files.
- gzip output uses mtime=0 so re-writing identical content produces byte-
  identical files - git sees no diff and doesn't commit a no-op change.
"""

import gzip
import io
import json
import os
import glob
from datetime import datetime, timedelta, timezone

HOURLY_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "hourly")
BY_DAY_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "points-by-day")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "recent.json")
POINTS_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "points.json")
POINTS_INDEX_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "points-index.json")
RECENT_CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", ".recent-cache.json")

RECENT_HOURS = 48  # how much raw history ships inline in points.json


def write_gzip_json(path, obj):
    """Write gzip with a fixed mtime so identical content -> identical
    bytes -> no spurious git diff on every run."""
    payload = json.dumps(obj).encode("utf-8")
    buf = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buf, mtime=0) as gz:
        gz.write(payload)
    data = buf.getvalue()
    # Skip the write entirely if content is unchanged, so mtime on disk
    # (and any git diff) stays untouched too.
    if os.path.exists(path):
        with open(path, "rb") as f:
            if f.read() == data:
                return False
    with open(path, "wb") as f:
        f.write(data)
    return True


def read_hour_file(path):
    with gzip.open(path, "rt") as f:
        data = json.load(f)
    points = data.get("points", [])
    if not points:
        return None, []
    counts = [p["player_count"] for p in points]
    row = {
        "hour": data["hour"],
        "avg": round(sum(counts) / len(counts)),
        "max": max(counts),
        "min": min(counts),
    }
    return row, points


def main():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=RECENT_HOURS)
    # Days that points.json's rolling window can touch, plus "today" so
    # a fresh UTC-midnight rollover is covered even before any hour of
    # the new day has 48h-old data yet. These are the only days whose
    # points-by-day file / points.json contribution get recomputed.
    live_days = set()
    d = cutoff.date()
    while d <= now.date():
        live_days.add(d.isoformat())
        d += timedelta(days=1)

    this_hour = now.strftime("%Y-%m-%dT%H")
    prev_hour = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H")
    live_hours = {this_hour, prev_hour}

    # --- recent.json rows, using a row-level cache so old hours aren't
    # re-decoded from gzip every run -----------------------------------
    cache = {}
    if os.path.exists(RECENT_CACHE_PATH):
        try:
            with open(RECENT_CACHE_PATH) as f:
                cache = json.load(f)
        except (json.JSONDecodeError, OSError):
            cache = {}

    rows_by_hour = {}
    points_by_day = {}  # only populated for live_days, see below
    hour_paths = sorted(glob.glob(os.path.join(HOURLY_DIR, "*.json.gz")))

    for path in hour_paths:
        hour = os.path.basename(path).removesuffix(".json.gz")
        day = hour[:10]
        need_points = day in live_days  # only live days need raw points reloaded

        if hour in live_hours or hour not in cache or need_points:
            row, points = read_hour_file(path)
            if row is None:
                continue
            rows_by_hour[hour] = row
            cache[hour] = row
            if need_points:
                points_by_day.setdefault(day, []).extend(points)
        else:
            rows_by_hour[hour] = cache[hour]

    with open(RECENT_CACHE_PATH, "w") as f:
        json.dump(cache, f)

    rows = [rows_by_hour[h] for h in sorted(rows_by_hour)]
    with open(OUTPUT_PATH, "w") as f:
        json.dump(rows, f)

    # --- points-by-day/ + points-index.json -----------------------------
    # Older days: keep whatever's already on disk and already in the index
    # (loaded once, long ago) instead of re-reading every hourly file for
    # them on every run - that's the O(history) cost this rewrite avoids.
    os.makedirs(BY_DAY_DIR, exist_ok=True)

    prev_index = {}
    if os.path.exists(POINTS_INDEX_PATH):
        try:
            with open(POINTS_INDEX_PATH) as f:
                prev_index = {d["day"]: d["count"] for d in json.load(f)}
        except (json.JSONDecodeError, OSError):
            prev_index = {}

    index_map = dict(prev_index)
    written = 0
    for day, pts in points_by_day.items():
        pts = sorted(pts, key=lambda p: p["ts"])
        day_path = os.path.join(BY_DAY_DIR, f"{day}.json.gz")
        if write_gzip_json(day_path, pts):
            written += 1
        index_map[day] = len(pts)

    # Any day that has a hourly file on disk but wasn't in prev_index yet
    # (first run, or a gap) still needs to be captured once.
    known_days = {os.path.basename(p)[:10] for p in hour_paths}
    missing_days = known_days - set(index_map) - live_days
    for day in missing_days:
        day_points = []
        for path in hour_paths:
            if os.path.basename(path).startswith(day):
                _, points = read_hour_file(path)
                day_points.extend(points)
        day_points.sort(key=lambda p: p["ts"])
        day_path = os.path.join(BY_DAY_DIR, f"{day}.json.gz")
        if write_gzip_json(day_path, day_points):
            written += 1
        index_map[day] = len(day_points)

    index = [{"day": d, "count": c} for d, c in sorted(index_map.items())]
    with open(POINTS_INDEX_PATH, "w") as f:
        json.dump(index, f)

    # --- points.json: last RECENT_HOURS worth, for instant first paint --
    # live_days was computed from the same RECENT_HOURS cutoff above, so
    # every point that could fall in this window was already re-decoded
    # into points_by_day - no need to touch older days' files at all.
    all_recent_points = [
        p for pts in points_by_day.values() for p in pts
        if datetime.fromisoformat(p["ts"]) >= cutoff
    ]
    all_recent_points.sort(key=lambda p: p["ts"])
    with open(POINTS_PATH, "w") as f:
        json.dump(all_recent_points, f)

    print(f"Wrote docs/recent.json: {len(rows)} hours ({len(hour_paths) - len(rows_by_hour) + len(rows_by_hour)} files seen, cache hit for non-live hours)")
    print(f"Wrote docs/points.json: {len(all_recent_points)} points (last {RECENT_HOURS}h)")
    print(f"docs/points-by-day/: {len(index)} days tracked, {written} file(s) actually rewritten this run")


if __name__ == "__main__":
    main()

