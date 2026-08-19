#!/usr/bin/env python3
"""
Cross-checks steamids collected from the forum (scrape_forum.py's output)
against:
  - the official Steam Web API: does this account actually own/play the
    game, how many hours, is the profile public
  - our own review dataset (docs/reviews/latest.json): did this account
    leave a review, and if so was it flagged suspicious
  - optionally, a breadth-first walk of each account's Steam friends list:
    same ownership/review cross-check run on friends, and if a friend
    ALSO owns/plays the tracked game, their friends get queued and walked
    too - the walk only continues through players of the game, so a
    friend with no connection to it is a dead end rather than a branch
    point.

The friends walk exists because a "review farm" (or any coordinated
group) often shows up as clusters of accounts that are friends with each
other - checking a forum poster's friends (and friends-of-friends who
also play the game, and so on) for the same owns-game/left-a-review
pattern surfaces those clusters even when most of them never posted on
the forum themselves.

This is a real graph walk, not a fixed one-hop check, so it's bounded by
a hard total account budget (--max-friend-accounts) rather than depth -
depth alone doesn't prevent a blowup (a popular game with heavily
interconnected players could have every account reachable within 2-3
hops), so the budget is what actually keeps a run's time and API usage
predictable.

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
        --api-key $STEAM_WEB_API_KEY \
        --check-friends
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

SUMMARIES_URL = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"
OWNED_GAMES_URL = "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/"
FRIEND_LIST_URL = "https://api.steampowered.com/ISteamUser/GetFriendList/v1/"
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


def fetch_friend_list(steamid: str, api_key: str) -> list[str]:
    """GetFriendList only returns anything if the account's friends list is
    public (most accounts default to private for this) - a private/empty
    result just means "no visible friends", not an error, so this returns
    an empty list rather than None in that case."""
    data = http_get_json(FRIEND_LIST_URL, {"key": api_key, "steamid": steamid, "relationship": "friend"})
    friends = data.get("friendslist", {}).get("friends", [])
    return [f["steamid"] for f in friends if f.get("steamid")]


def check_account(sid: str, appid: int, api_key: str, summary: dict,
                   reviewed_steamids: dict, sleep_s: float, extra_fields: dict) -> dict:
    """Runs the owns-game/left-a-review check for one steamid and returns
    the account record. extra_fields lets callers attach context (forum
    source info for direct forum accounts, or which account's friends list
    a discovered friend came from) without duplicating this function."""
    visibility = summary.get("communityvisibilitystate")  # 3 = public
    owned_info = None
    if visibility == 3:
        owned_info = fetch_owned_games_for_appid(sid, appid, api_key)
        time.sleep(sleep_s)

    review = reviewed_steamids.get(sid)
    record = {
        "steamid": sid,
        "profile_public": visibility == 3,
        "owns_tracked_game": owned_info["owns_tracked_game"] if owned_info else None,
        "playtime_forever_minutes": owned_info["playtime_forever_minutes"] if owned_info else None,
        "total_games_owned": owned_info["total_games_owned"] if owned_info else None,
        "left_a_review": review is not None,
        "review_suspicion_score": review.get("suspicion_score") if review else None,
    }
    record.update(extra_fields)
    return record


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--appid", type=int, required=True)
    ap.add_argument("--forum-profiles", required=True)
    ap.add_argument("--reviews", required=True, help="docs/reviews/latest.json, for the reviewed-steamid cross-check")
    ap.add_argument("--out", required=True)
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--sleep", type=float, default=0.6)
    ap.add_argument("--max-accounts", type=int, default=300,
                     help="cap on how many NEW forum accounts to check per run, to keep run time bounded")
    ap.add_argument("--check-friends", action="store_true",
                     help="also walk each checked forum account's friends list (if public), "
                          "breadth-first, continuing through any friend who also owns/plays "
                          "the tracked game (see module docstring)")
    ap.add_argument("--max-friends-per-account", type=int, default=50,
                     help="cap on how many friends to pull per account, since some accounts have hundreds")
    ap.add_argument("--max-friend-accounts", type=int, default=500,
                     help="hard total budget on NEW friend-graph accounts checked per run - this is "
                          "the real safety valve for the walk (depth alone can't bound it, see docstring)")
    ap.add_argument("--max-friend-depth", type=int, default=6,
                     help="extra safety cap on hops from a forum account, on top of the account "
                          "budget above - mainly a backstop in case the budget is set very high")
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
    existing_accounts = {}
    existing_friends = {}
    saved_queue: list[list] = []  # [steamid, depth, friend_of] triples, JSON-serialized
    try:
        with open(args.out) as f:
            prior = json.load(f)
        existing_accounts = {e["steamid"]: e for e in prior.get("accounts", [])}
        existing_friends = {e["steamid"]: e for e in prior.get("friend_accounts", [])}
        saved_queue = prior.get("friend_walk_queue", [])
    except (OSError, json.JSONDecodeError, KeyError):
        pass

    to_check = [sid for sid in forum_steamids if sid not in existing_accounts][:args.max_accounts]
    print(f"Forum steamids: {len(forum_steamids)}, already checked: {len(existing_accounts)}, "
          f"checking {len(to_check)} new this run.")

    summaries = fetch_player_summaries(to_check, api_key, args.sleep) if to_check else {}

    accounts = dict(existing_accounts)
    for i, sid in enumerate(to_check, 1):
        extra = {
            "forum_source": forum_data["profiles"].get(sid, {}).get("source"),
            "first_seen_on_forum": forum_data["profiles"].get(sid, {}).get("first_seen"),
        }
        accounts[sid] = check_account(sid, args.appid, api_key, summaries.get(sid, {}),
                                       reviewed_steamids, args.sleep, extra)
        if i % 20 == 0 or i == len(to_check):
            print(f"  [{i}/{len(to_check)}] checked", flush=True)

    # --- friends pass: breadth-first walk, continuing through players --------
    friend_accounts = dict(existing_friends)
    remaining_queue: list[list] = []  # persisted so a budget-limited walk resumes, not restarts
    if args.check_friends:
        already_known = set(accounts) | set(friend_accounts)

        # Seed the queue with:
        #   1. this run's freshly-checked forum accounts with a public
        #      profile (friends lists are unfetchable for most private
        #      profiles anyway)
        #   2. whatever was still queued and unwalked from a prior run that
        #      hit the account budget mid-walk - without this, a long
        #      friend chain would get stuck re-discovering the same first
        #      --max-friend-accounts nodes forever instead of progressing
        #      deeper on each scheduled run.
        queue: list[tuple[str, int, str]] = [
            (sid, 1, sid) for sid in to_check
            if accounts.get(sid, {}).get("profile_public") is True
        ]
        # Restored entries are nodes whose OWN friends list still needs to
        # be fetched - they were already checked (owns-game/review status
        # resolved) on a prior run, that's *why* they made it into the
        # queue in the first place. So `already_known` (which just means
        # "already has a resolved account record") is the wrong filter
        # here; only dedupe against nodes already sitting in this run's
        # queue.
        queued_sids = {sid for sid, _, _ in queue}
        for entry in saved_queue:
            try:
                sid, depth, source = entry[0], entry[1], entry[2]
            except (IndexError, TypeError):
                continue
            if sid not in queued_sids:
                queue.append((sid, depth, source))
                queued_sids.add(sid)

        visited_for_friends: set[str] = set()  # accounts whose friend list we've already pulled
        walked = 0

        print(f"Starting friends walk from {len(queue)} queued account(s) "
              f"({len(saved_queue)} carried over from a prior run), "
              f"budget {args.max_friend_accounts} NEW accounts this run, depth cap {args.max_friend_depth}...")

        while queue and walked < args.max_friend_accounts:
            sid, depth, source = queue.pop(0)
            if sid in visited_for_friends or depth > args.max_friend_depth:
                continue
            visited_for_friends.add(sid)

            friends = fetch_friend_list(sid, api_key)
            time.sleep(args.sleep)
            new_friend_ids = [
                fsid for fsid in friends[:args.max_friends_per_account]
                if fsid not in already_known
            ]
            if not new_friend_ids:
                continue

            # Check this batch of newly-discovered friends right away (rather
            # than collecting the whole graph before checking anyone) so a
            # run that hits its time/account budget mid-walk still has fully
            # resolved records for everyone it did reach, instead of a pile
            # of unchecked candidate ids.
            remaining_budget = args.max_friend_accounts - walked
            batch = new_friend_ids[:remaining_budget]
            batch_summaries = fetch_player_summaries(batch, api_key, args.sleep) if batch else {}

            for fsid in batch:
                already_known.add(fsid)
                record = check_account(fsid, args.appid, api_key, batch_summaries.get(fsid, {}),
                                        reviewed_steamids, args.sleep, {"friend_of": source})
                friend_accounts[fsid] = record
                walked += 1
                # Only players of the tracked game get their own friends
                # list queued - this is the actual bound on the walk: a
                # friend with no connection to the game is a dead end, not
                # a branch point, so unrelated social graphs don't get
                # pulled in just because one person happens to know a lot
                # of people.
                if record.get("owns_tracked_game") and record.get("profile_public"):
                    queue.append((fsid, depth + 1, fsid))

                if walked >= args.max_friend_accounts:
                    break

            if walked % 20 < len(batch) or walked >= args.max_friend_accounts:
                print(f"  walked {walked} friend account(s) so far, "
                      f"{len(queue)} queued, depth reached up to {depth}", flush=True)

        if walked >= args.max_friend_accounts:
            print(f"WARN: hit --max-friend-accounts ({args.max_friend_accounts} new this run); "
                  f"{len(queue)} account(s) still queued will be picked up on a future run "
                  f"once more of the existing graph is cached.")
        remaining_queue = [[sid, depth, source] for sid, depth, source in queue]
        print(f"Friends walk done: {walked} new account(s) checked this run "
              f"({len(friend_accounts)} total in friend graph, {len(remaining_queue)} still queued).")

    def summarize(pool: dict) -> dict:
        return {
            "never_owned_or_reviewed": sum(
                1 for a in pool.values()
                if a["profile_public"] and a["owns_tracked_game"] is False and not a["left_a_review"]
            ),
            "owns_game_never_reviewed": sum(
                1 for a in pool.values()
                if a["owns_tracked_game"] and not a["left_a_review"]
            ),
            "reviewed_and_suspicious": sum(
                1 for a in pool.values()
                if a["left_a_review"] and (a.get("review_suspicion_score") or 0) >= 40
            ),
        }

    forum_summary = summarize(accounts)
    friend_summary = summarize(friend_accounts) if friend_accounts else None

    out = {
        "appid": args.appid,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_forum_accounts": len(forum_steamids),
        "total_checked": len(accounts),
        "summary": {
            "forum_active_but_never_owned_or_reviewed": forum_summary["never_owned_or_reviewed"],
            "owns_game_but_never_reviewed": forum_summary["owns_game_never_reviewed"],
            "reviewed_and_suspicious": forum_summary["reviewed_and_suspicious"],
        },
        "accounts": list(accounts.values()),
    }
    if friend_accounts:
        out["total_friend_accounts_checked"] = len(friend_accounts)
        out["friend_summary"] = {
            "never_owned_or_reviewed": friend_summary["never_owned_or_reviewed"],
            "owns_game_but_never_reviewed": friend_summary["owns_game_never_reviewed"],
            "reviewed_and_suspicious": friend_summary["reviewed_and_suspicious"],
        }
        out["friend_accounts"] = list(friend_accounts.values())
    if remaining_queue:
        out["friend_walk_queue"] = remaining_queue

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"Wrote {args.out}: {len(accounts)} forum accounts checked total.")
    print(f"  Forum-active, never owned/reviewed: {forum_summary['never_owned_or_reviewed']}")
    print(f"  Owns game, never left a review: {forum_summary['owns_game_never_reviewed']}")
    print(f"  Reviewed AND suspicious: {forum_summary['reviewed_and_suspicious']}")
    if friend_summary:
        print(f"  Friends checked: {len(friend_accounts)}")
        print(f"  Friends: never owned/reviewed: {friend_summary['never_owned_or_reviewed']}")
        print(f"  Friends: owns game, never reviewed: {friend_summary['owns_game_never_reviewed']}")
        print(f"  Friends: reviewed AND suspicious: {friend_summary['reviewed_and_suspicious']}")


if __name__ == "__main__":
    main()
