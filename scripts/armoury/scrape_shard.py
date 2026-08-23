#!/usr/bin/env python3
"""
Job 2 шардированного пайплайна (запускается в матрице, по одному процессу
на шард): берёт диапазон [--start, --end) из общего списка игроков
(players_list.json, собранного list_players.py) и скрапит только его,
пишет результат в свой собственный файл — shard_<N>.json.

Задержка стартует одинаково безопасно для каждого шарда (не подхватывает
общий сохранённый конфиг и не пытается пробовать до нуля) — при 5
параллельных ранерах с разных IP GitHub Actions нет смысла синхронизировать
их адаптацию друг с другом, а агрессивный проб на несколько параллельных
процессов сразу может неприятно удивить сайт. Так что --start-delay фиксирован
и вынесен в --probe-floor, ниже которого шард не спускается.

Использование:
    python scrape_shard.py players_list.json --start 0 --end 400 -o shard_0.json
"""

import argparse
import json
import sys

import requests

sys.path.insert(0, __file__.rsplit("/", 1)[0] if "/" in __file__ else ".")
from soulbound_armoury_scraper import AdaptiveRateLimiter, scrape_player

SAFE_START_DELAY = 0.05
SAFE_PROBE_FLOOR = 0.02


def main():
    parser = argparse.ArgumentParser(description="Скрапит диапазон игроков из общего списка")
    parser.add_argument("players_list", help="JSON-файл со списком [{region, slug}, ...] от list_players.py")
    parser.add_argument("--start", type=int, required=True, help="начало диапазона (включительно)")
    parser.add_argument("--end", type=int, required=True, help="конец диапазона (не включая)")
    parser.add_argument("-o", "--output", required=True)
    args = parser.parse_args()

    with open(args.players_list, "r", encoding="utf-8") as f:
        all_players = json.load(f)

    shard = all_players[args.start:args.end]
    print(f"[i] Шард: игроки {args.start}..{args.end} ({len(shard)} шт.)", file=sys.stderr)

    if not shard:
        print("[!] Пустой диапазон — пишу пустой файл.", file=sys.stderr)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump([], f)
        return

    session = requests.Session()
    limiter = AdaptiveRateLimiter(start_delay=SAFE_START_DELAY, min_delay=SAFE_PROBE_FLOOR)

    results = []
    for i, entry in enumerate(shard, 1):
        region, slug = entry["region"], entry["slug"]
        print(f"[{i}/{len(shard)}] {region}/{slug} (задержка {limiter.delay:.3f}s)", file=sys.stderr)
        p = scrape_player(session, region, slug, limiter)
        if p:
            results.append({
                "slug": p.slug,
                "region": p.region,
                "name": p.name,
                "level": p.level,
                "last_seen": p.last_seen,
                "url": p.url,
            })

    print(f"[i] {limiter.summary()}", file=sys.stderr)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, separators=(",", ":"))

    print(f"[✓] Записал {len(results)}/{len(shard)} игроков в {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
