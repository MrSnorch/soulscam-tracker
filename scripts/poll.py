#!/usr/bin/env python3
"""
Poll Steam's GetNumberOfCurrentPlayers every 60s for one run (~5.5h, staying
under GitHub Actions' 6h job limit), buffer points in memory, and flush one
gzip JSON file per UTC hour into docs/hourly/. The workflow commits after
each flush and re-triggers itself when the run ends.
"""

import gzip
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

APPID = 4369490
API_URL = f"https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid={APPID}"
POLL_INTERVAL_SEC = 60
RUN_DURATION_SEC = int(os.environ.get("RUN_DURATION_SEC", 5.5 * 3600))
HOURLY_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "hourly")


def fetch_player_count():
    delays = [0, 5, 15]  # immediate try, then two retries with backoff
    last_err = None
    for delay in delays:
        if delay:
            time.sleep(delay)
        try:
            with urllib.request.urlopen(API_URL, timeout=15) as resp:
                data = json.load(resp)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_err = e
            print(f"WARN: request failed (retry in {delay or 'n/a'}s pattern): {e}", file=sys.stderr)
            continue

        result = data.get("response", {})
        if result.get("result") != 1:
            last_err = f"unexpected API result: {result}"
            print(f"WARN: {last_err}", file=sys.stderr)
            continue

        count = result.get("player_count")
        if count is None:
            last_err = "missing player_count in response"
            print(f"WARN: {last_err}", file=sys.stderr)
            continue

        return count

    print(f"ERROR: all retries exhausted, skipping this poll ({last_err})", file=sys.stderr)
    return None


# How many recent non-null readings to remember, purely to sanity-check a
# fresh 0 against - Steam's endpoint occasionally returns result=1 with
# player_count=0 as a transient glitch. Seen in practice: a run of ~19
# consecutive zero readings (roughly 19 minutes) sandwiched between
# normal ~100-150 values a minute apart - long enough that even a single
# 5-second re-confirmation still reads 0, so that approach isn't reliable
# on its own. This is NOT meant to hide a genuine drop to zero for a
# low-population game - it only withholds an unexpected 0 from the
# recorded data until it's been confirmed by several independent polls
# in a row, rather than trusting the very first one.
RECENT_HISTORY_LEN = 5
_recent_counts = []

# A suspicious 0 must be seen on this many consecutive ~60s poll ticks
# before it's accepted and written to the buffer. Below this, the point
# is withheld entirely (not recorded as 0, not recorded as anything) -
# a short gap in the data is preferable to a fabricated reading, and the
# gap disappears retroactively once the streak resolves one way or the
# other (see _pending_zero_run below).
ZERO_CONFIRM_STREAK = 3

# State for a suspected-zero run in progress, carried across poll() calls
# in the main loop (each call is one ~60s tick, not a busy-wait - the
# whole point is spacing confirmations a full poll interval apart, since
# the glitches observed in practice lasted many consecutive *minutes*,
# not seconds). None when there's no run in progress.
#   "start_ts": ISO timestamp of the first 0 in the current run
#   "streak": how many consecutive 0 readings seen so far
#   "pending_ts": list of (ts, count) tuples withheld pending confirmation
_pending_zero_run = None


def is_suspicious_zero(count):
    """A fresh 0 reading right after a run of healthy nonzero readings is
    treated as suspicious and worth confirming rather than recorded
    immediately. A 0 that follows other recent 0s (or no history yet) is
    not suspicious - could be a genuinely dead/delisted game, and we
    shouldn't withhold data forever once a drop is already established."""
    if count != 0:
        return False
    if not _recent_counts:
        return False
    return any(c > 0 for c in _recent_counts)


def process_reading(ts_iso, count):
    """Takes one raw poll reading and returns a list of (ts, count) points
    that are now safe to record - either the reading itself (if it wasn't
    a suspicious zero), or a batch of previously-withheld zero readings
    that just reached the confirmation streak, or an empty list while a
    suspected glitch is still being confirmed.

    This replaces a single 5-second re-check (too short for the multi-
    minute glitches actually observed) with withholding points across
    consecutive real poll ticks - a real Steam outage will keep reading
    0 every ~60s and eventually get confirmed and backfilled; a
    transient glitch will resolve back to a healthy number within a
    tick or two and the withheld 0(s) are simply discarded.
    """
    global _pending_zero_run

    if not is_suspicious_zero(count):
        # Not suspicious: if we were mid-confirmation and got a healthy
        # reading, the glitch is over - discard whatever zeros were
        # pending (they were transient) and resume normally.
        if _pending_zero_run is not None:
            discarded = len(_pending_zero_run["pending"])
            print(f"INFO: got player_count={count}, discarding {discarded} withheld "
                  f"zero reading(s) as a transient glitch", file=sys.stderr)
            _pending_zero_run = None
        _recent_counts.append(count)
        if len(_recent_counts) > RECENT_HISTORY_LEN:
            _recent_counts.pop(0)
        return [(ts_iso, count)]

    # Suspicious zero: withhold it, don't touch _recent_counts yet (a
    # withheld reading isn't "recorded" and shouldn't count as evidence
    # for or against future readings until it's resolved).
    if _pending_zero_run is None:
        _pending_zero_run = {"pending": []}
    _pending_zero_run["pending"].append((ts_iso, count))
    streak = len(_pending_zero_run["pending"])
    print(f"WARN: player_count=0 at {ts_iso} after nonzero history {_recent_counts} "
          f"(streak {streak}/{ZERO_CONFIRM_STREAK}), withholding until confirmed", file=sys.stderr)

    if streak >= ZERO_CONFIRM_STREAK:
        print(f"INFO: 0 confirmed by {streak} consecutive polls, backfilling withheld reading(s)",
              file=sys.stderr)
        points = list(_pending_zero_run["pending"])
        _pending_zero_run = None
        _recent_counts.append(0)
        if len(_recent_counts) > RECENT_HISTORY_LEN:
            _recent_counts.pop(0)
        return points

    return []  # still withheld, not confirmed yet


def fetch_player_count_confirmed():
    """Thin wrapper kept for API compatibility with the rest of the
    script - just calls fetch_player_count(). The actual
    confirm-before-recording logic now lives in process_reading(),
    since it needs to span multiple poll() calls rather than a single
    short re-check."""
    return fetch_player_count()


def hour_key(dt):
    return dt.strftime("%Y-%m-%dT%H")


def flush_hour(hour, points, final=False):
    if not points:
        return
    os.makedirs(HOURLY_DIR, exist_ok=True)
    path = os.path.join(HOURLY_DIR, f"{hour}.json.gz")

    # Merge with existing file for this hour, if present (resumed run or
    # an earlier partial flush of the same hour).
    existing = []
    if os.path.exists(path):
        with gzip.open(path, "rt") as f:
            existing = json.load(f).get("points", [])

    merged = existing + points
    with gzip.open(path, "wt") as f:
        json.dump({"appid": APPID, "hour": hour, "points": merged}, f)

    tag = "final" if final else "partial"
    print(f"Flushed {len(points)} points ({tag}) -> docs/hourly/{hour}.json.gz ({len(merged)} total)", flush=True)


def main():
    print(f"Starting poll loop: interval={POLL_INTERVAL_SEC}s, run_duration={RUN_DURATION_SEC}s", flush=True)
    start = time.time()
    buffer = {}  # hour_key -> list of {ts, player_count} not yet flushed
    current_hour = None
    last_flush = start
    FLUSH_INTERVAL_SEC = 60  # write partial data every minute so the site updates that often

    while time.time() - start < RUN_DURATION_SEC:
        now = datetime.now(timezone.utc)
        hk = hour_key(now)

        if current_hour is not None and hk != current_hour:
            flush_hour(current_hour, buffer.get(current_hour, []))
            buffer.pop(current_hour, None)
        current_hour = hk

        count = fetch_player_count()
        if count is not None:
            confirmed_points = process_reading(now.isoformat(), count)
            for ts_iso, c in confirmed_points:
                # Use each point's own timestamp to pick its hour bucket
                # (not the current tick's `hk`) - a withheld reading that
                # gets confirmed a couple minutes later could in principle
                # straddle an hour boundary, and it should land in the
                # hourly file matching when it actually happened.
                point_hk = hour_key(datetime.fromisoformat(ts_iso))
                buffer.setdefault(point_hk, []).append({"ts": ts_iso, "player_count": c})
                print(f"{ts_iso} player_count={c}", flush=True)

        if time.time() - last_flush >= FLUSH_INTERVAL_SEC:
            flush_hour(current_hour, buffer.get(current_hour, []))
            buffer[current_hour] = []
            last_flush = time.time()

        time.sleep(POLL_INTERVAL_SEC)

    # Flush whatever's left for the current (partial) hour before exiting.
    if current_hour is not None:
        flush_hour(current_hour, buffer.get(current_hour, []), final=True)


if __name__ == "__main__":
    main()
