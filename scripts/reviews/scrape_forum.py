#!/usr/bin/env python3
"""
Headless Steam forum scraper for GitHub Actions.

Walks every discussion thread under the app's Steam Community forum,
extracts steamids from profile links on each thread page, and writes them
to docs/reviews/forum-profiles.json. This is the CI-friendly counterpart of
a local interactive tool (Flask UI) someone might run by hand - same
extraction logic, but no server, no manual review UI, just collect and
write out for the rest of the pipeline to consume.

IMPORTANT CAVEATS (read before relying on this in CI):
- This scrapes HTML, it isn't Steam's official Web API. Steam's page
  markup can change without notice and silently break the regex-based
  extraction below - if forum-profiles.json stops growing, check whether
  the extraction still matches real profile links before assuming there's
  just no new activity.
- Datacenter IPs (including GitHub Actions runners) are more likely to be
  rate-limited or blocked by Steam's anti-bot protections than a residential
  IP. A run failing outright (HTTP 403/429) is treated as "no profiles
  found this run", not a fatal Steam Watch (there is no persistent captcha
  handling here) - the existing data file is left untouched rather than
  wiped, so a bad run doesn't lose prior data.
- This only *discovers* steamids that posted somewhere on the forum. It
  says nothing on its own about whether that account plays the game or
  left a review - see enrich_forum_profiles.py for that cross-check.

Usage:
    python scripts/reviews/scrape_forum.py --appid 4369490 \
        --out docs/reviews/forum-profiles.json --max-threads 40
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}

PROFILE_RE = re.compile(r"steamcommunity\.com/profiles/(\d{17})")
THREAD_LINK_RE = re.compile(r"/discussions/\d+/\d+")


def http_get(url: str, max_retries: int = 3) -> str | None:
    """GET a page's HTML. Returns None (not raises) on failure, so one bad
    request doesn't kill the whole run - the caller just skips that page."""
    backoff = 2.0
    last_err = None
    for attempt in range(max_retries):
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (403, 429):
                # Likely anti-bot / rate limit - back off harder, but don't
                # keep hammering a blocked endpoint for long.
                print(f"  WARN: HTTP {e.code} on {url}, backing off {backoff:.0f}s", file=sys.stderr)
                time.sleep(backoff)
                backoff *= 2
                continue
            print(f"  WARN: HTTP {e.code} on {url}", file=sys.stderr)
            return None
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = e
            print(f"  WARN: request failed on {url}: {e}", file=sys.stderr)
            time.sleep(backoff)
            backoff *= 2
    print(f"  ERROR: giving up on {url} after {max_retries} attempts ({last_err})", file=sys.stderr)
    return None


def extract_profile_ids(html: str) -> set[str]:
    return set(PROFILE_RE.findall(html))


def extract_thread_links(html: str, base_url: str) -> list[str]:
    hrefs = re.findall(r'href="([^"]+)"', html)
    links = []
    seen = set()
    for href in hrefs:
        if THREAD_LINK_RE.search(href):
            href = href.split("?")[0]
            if href.startswith("/"):
                href = "https://steamcommunity.com" + href
            if href not in seen:
                seen.add(href)
                links.append(href)
    return links


def find_next_page(html: str, kind: str) -> str | None:
    """kind='list' looks for a discussions-list pagination link; kind='thread'
    looks for a ?ctp=N (comment/thread page) link. Both are best-effort
    regex over raw HTML rather than a DOM parse, to avoid a BeautifulSoup
    dependency in the CI environment - if Steam changes this markup, this
    is the first thing to check."""
    if kind == "thread":
        m = re.search(r'href="([^"]*\?ctp=(\d+)[^"]*)"', html)
        return m.group(1) if m else None
    # list pagination: look for a "Next" / ">" link pointing at discussions
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>\s*(&gt;|Next|»)\s*</a>', html):
        href = m.group(1)
        if "discussions" in href:
            return href
    return None


def load_existing(path: str) -> dict:
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"app_id": None, "last_updated": None, "profiles": {}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--appid", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--max-runtime-sec", type=int, default=18000,
                     help="wall-clock safety cap (default 5h) so a CI job can't run "
                          "forever if Steam serves an unexpected infinite-pagination "
                          "loop or similar - not a per-thread/per-page cap, since the "
                          "goal here is to walk every thread/page like the local tool "
                          "does, just with a backstop against genuinely running away")
    args = ap.parse_args()
    start_time = time.monotonic()

    def time_left() -> bool:
        return (time.monotonic() - start_time) < args.max_runtime_sec

    data = load_existing(args.out)
    data["app_id"] = args.appid
    data.setdefault("profiles", {})

    forum_url = f"https://steamcommunity.com/app/{args.appid}/discussions/"
    thread_links: list[str] = []
    list_url = forum_url
    list_pages = 0
    seen_list_urls: set[str] = set()

    while list_url and time_left():
        if list_url in seen_list_urls:
            # defensive: a pagination bug could otherwise loop forever
            # even within the time budget
            print(f"  list page {list_url} already visited, stopping pagination")
            break
        seen_list_urls.add(list_url)
        list_pages += 1
        print(f"List page #{list_pages}: {list_url}")
        html = http_get(list_url)
        if html is None:
            break
        new_links = extract_thread_links(html, list_url)
        for link in new_links:
            if link not in thread_links:
                thread_links.append(link)
        print(f"  threads found so far: {len(thread_links)}")
        list_url = find_next_page(html, "list")
        if list_url:
            time.sleep(args.sleep * 2)

    if not time_left():
        print(f"WARN: hit --max-runtime-sec ({args.max_runtime_sec}s) while paging through "
              f"the thread list; stopping with {len(thread_links)} threads found so far.")

    added_total = 0
    threads_visited = 0

    for link in thread_links:
        if not time_left():
            print(f"WARN: hit --max-runtime-sec ({args.max_runtime_sec}s) after visiting "
                  f"{threads_visited}/{len(thread_links)} threads; stopping early. "
                  f"Remaining threads will be picked up on the next scheduled run.")
            break
        turl = link
        tpage = 1
        seen_thread_urls: set[str] = set()
        while turl and time_left():
            if turl in seen_thread_urls:
                break
            seen_thread_urls.add(turl)
            html = http_get(turl)
            if html is None:
                break
            added = 0
            for sid in extract_profile_ids(html):
                if sid not in data["profiles"]:
                    data["profiles"][sid] = {
                        "url": f"https://steamcommunity.com/profiles/{sid}",
                        "checked": False,
                        "note": "",
                        "first_seen": datetime.now(timezone.utc).isoformat(),
                        "source": link,
                    }
                    added += 1
            added_total += added
            next_turl = find_next_page(html, "thread")
            turl = next_turl
            if turl:
                tpage += 1
                time.sleep(args.sleep)
        threads_visited += 1
        print(f"  [{threads_visited}/{len(thread_links)}] {link} -> +{added_total} total so far")
        time.sleep(args.sleep)

    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    data["total_profiles"] = len(data["profiles"])

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Done. Visited {threads_visited} threads, +{added_total} new profiles, {len(data['profiles'])} total.")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
