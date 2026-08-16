#!/usr/bin/env python3
"""
Cross-checks steamids collected from the forum (scrape_forum.py's output)
against:
  - the official Steam Web API: does this account actually own/play the
    game, how many hours, is the profile public
  - our own review dataset (docs/reviews/latest.json): did this account
    leave a review, and if so was it flagged suspicious

This answers the actual question behind forum scraping: "of the people
talking about this game, how many are real players vs how many show up
on the forum but never touch the game or leave a review" - which is a
much stronger signal than the raw list of steamids alone.

Requires a Steam Web API key (same one used by enrich_accounts.py):
https://steamcommunity.com/dev/apikey

Usage:
    python scripts/reviews/enrich_forum_profiles.py \
        --appid 4369490 \
        --forum-profiles docs/reviews/forum-profiles.json \
        --reviews docs/reviews/latest.json \
        --out docs/reviews/forum-activity.json \
        --api-key $STEAM_WEB_API_KEY
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SUMMARIES_URL = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"
OWNED_GAMES_URL = "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/"
USER_AGENT = "Mozilla/5.0 (compatible; steam-review-watch/1.0)"


def http_get_json(url: str, params: dict, max_retries: int = 4) -> dict:
    full_url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full_url, headers={"User-Agent": USER_AGENT})
    backoff = 2.0
    for attempt in range(1, max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as e:
            print(f"  [warn] attempt {attempt}/{max_retries} failed for {url}: {e}", file=sys.stderr)
            if attempt == max_retries:
                return {}
            time.sleep(backoff)
            backoff *= 2
    return {}


def fetch_player_summaries(steamids: list[str], api_key: str, sleep_s: float = 0.6) -> dict:
    out = {}
    for i in range(0, len(steamids), 100):
        chunk = steamids[i:i + 100]
        data = http_get_json(SUMMARIES_URL, {"key": api_key, "steamids": ",".join(chunk)})
        players = data.get("response", {}).get("players", [])
        for p in players:
            out[p.get("steamid")] = p
        print(f"  [info] summaries batch {i // 100 + 1}: {len(players)}/{len(chunk)} "
              f"({len(out)} total so far)", flush=True)
        time.sleep(sleep_s)
    return out


def fetch_owned_games_for_appid(steamid: str, appid: int, api_key: str) -> dict | None:
    """Unlike enrich_accounts.py's version (which sums the whole library),
    this looks specifically for the tracked appid in the owned-games list,
    since the question here is "do they own/play *this* game", not their
    overall library size."""
    data = http_get_json(OWNED_GAMES_URL, {
        "key": api_key,
        "steamid": steamid,
        "include_appinfo": 0,
        "include_played_free_games": 1,
    })
    resp = data.get("response", {})
    if "game_count" not in resp:
        return None  # private profile or API error
    games = resp.get("games", [])
    match = next((g for g in games if g.get("appid") == appid), None)
    return {
        "profile_public": True,
        "total_games_owned": resp.get("game_count", 0),
        "owns_tracked_game": match is not None,
        "playtime_forever_minutes": match.get("playtime_forever", 0) if match else 0,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--appid", type=int, required=True)
    ap.add_argument("--forum-profiles", required=True)
    ap.add_argument("--reviews", required=True, help="docs/reviews/latest.json, for the reviewed-steamid cross-check")
    ap.add_argument("--out", required=True)
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--sleep", type=float, default=0.6)
    ap.add_argument("--max-accounts", type=int, default=300,
                     help="cap on how many forum accounts to check per run, to keep run time bounded")
    args = ap.parse_args()

    api_key = args.api_key
    if not api_key:
        print("ERROR: no Steam Web API key provided (--api-key or STEAM_WEB_API_KEY).", file=sys.stderr)
        sys.exit(1)

    with open(args.forum_profiles) as f:
        forum_data = json.load(f)
    forum_steamids = list(forum_data.get("profiles", {}).keys())

    try:
        with open(args.reviews) as f:
            reviews_data = json.load(f)
        reviewed_steamids = {r["steamid"]: r for r in reviews_data.get("reviews", []) if r.get("steamid")}
    except (OSError, json.JSONDecodeError):
        reviewed_steamids = {}
        print("WARN: could not load reviews dataset, review cross-check will be empty.", file=sys.stderr)

    # Only check accounts we haven't already resolved in a prior run -
    # forum activity accumulates over time but a given steamid's
    # ownership/review status doesn't change on every 12h cycle, so
    # there's no need to re-spend an API call on someone already checked.
    existing = {}
    try:
        with open(args.out) as f:
            existing = {e["steamid"]: e for e in json.load(f).get("accounts", [])}
    except (OSError, json.JSONDecodeError, KeyError):
        pass

    to_check = [sid for sid in forum_steamids if sid not in existing][:args.max_accounts]
    print(f"Forum steamids: {len(forum_steamids)}, already checked: {len(existing)}, "
          f"checking {len(to_check)} new this run.")

    summaries = fetch_player_summaries(to_check, api_key, args.sleep) if to_check else {}

    accounts = dict(existing)
    for i, sid in enumerate(to_check, 1):
        summary = summaries.get(sid, {})
        visibility = summary.get("communityvisibilitystate")  # 3 = public
        owned_info = None
        if visibility == 3:
            owned_info = fetch_owned_games_for_appid(sid, args.appid, api_key)
            time.sleep(args.sleep)

        review = reviewed_steamids.get(sid)
        accounts[sid] = {
            "steamid": sid,
            "forum_source": forum_data["profiles"].get(sid, {}).get("source"),
            "first_seen_on_forum": forum_data["profiles"].get(sid, {}).get("first_seen"),
            "profile_public": visibility == 3,
            "owns_tracked_game": owned_info["owns_tracked_game"] if owned_info else None,
            "playtime_forever_minutes": owned_info["playtime_forever_minutes"] if owned_info else None,
            "total_games_owned": owned_info["total_games_owned"] if owned_info else None,
            "left_a_review": review is not None,
            "review_suspicion_score": review.get("suspicion_score") if review else None,
        }
        if i % 20 == 0 or i == len(to_check):
            print(f"  [{i}/{len(to_check)}] checked", flush=True)

    forum_only_no_review_no_play = sum(
        1 for a in accounts.values()
        if a["profile_public"] and a["owns_tracked_game"] is False and not a["left_a_review"]
    )
    played_but_no_review = sum(
        1 for a in accounts.values()
        if a["owns_tracked_game"] and not a["left_a_review"]
    )
    reviewed_and_suspicious = sum(
        1 for a in accounts.values()
        if a["left_a_review"] and (a.get("review_suspicion_score") or 0) >= 40
    )

    out = {
        "appid": args.appid,
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "total_forum_accounts": len(forum_steamids),
        "total_checked": len(accounts),
        "summary": {
            "forum_active_but_never_owned_or_reviewed": forum_only_no_review_no_play,
            "owns_game_but_never_reviewed": played_but_no_review,
            "reviewed_and_suspicious": reviewed_and_suspicious,
        },
        "accounts": list(accounts.values()),
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"Wrote {args.out}: {len(accounts)} accounts checked total.")
    print(f"  Forum-active, never owned/reviewed: {forum_only_no_review_no_play}")
    print(f"  Owns game, never left a review: {played_but_no_review}")
    print(f"  Reviewed AND suspicious: {reviewed_and_suspicious}")


if __name__ == "__main__":
    main()
