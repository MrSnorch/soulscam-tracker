#!/usr/bin/env python3
"""
Job 1b двухфазного шардированного пайплайна сбора списка армоури
(запускается в матрице, по одному процессу на диапазон страниц): берёт
диапазон страниц общего списка [--start-page, --end-page] (границы уже
известны заранее из find_last_page.py, найдены разведкой) и парсит их,
пишет найденные (region, slug) в свой собственный файл —
list_shard_<N>.json. Аналогично scrape_shard.py, но для сбора списка,
а не скрапинга страниц игроков.

Задержка стартует одинаково безопасно для каждого шарда (как и в
scrape_shard.py) — параллельные раннеры с разных IP не имеют смысла
координировать друг с другом.

Использование:
    python scan_list_shard.py --start-page 1 --end-page 50 -o list_shard_0.json
"""

import argparse
import json
import sys

import requests

sys.path.insert(0, __file__.rsplit("/", 1)[0] if "/" in __file__ else ".")
from soulbound_armoury_scraper import AdaptiveRateLimiter, scan_list_pages

SAFE_START_DELAY = 0.05
SAFE_PROBE_FLOOR = 0.02


def main():
    parser = argparse.ArgumentParser(description="Парсит диапазон страниц общего списка armoury")
    parser.add_argument("--start-page", type=int, required=True, help="первая страница диапазона (включительно)")
    parser.add_argument("--end-page", type=int, required=True, help="последняя страница диапазона (включительно)")
    parser.add_argument("-o", "--output", required=True)
    args = parser.parse_args()

    if args.start_page > args.end_page:
        print(f"[!] Пустой диапазон страниц ({args.start_page}..{args.end_page}) — пишу пустой файл.", file=sys.stderr)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump([], f)
        return

    session = requests.Session()
    limiter = AdaptiveRateLimiter(start_delay=SAFE_START_DELAY, min_delay=SAFE_PROBE_FLOOR)

    print(f"[i] Диапазон страниц: {args.start_page}..{args.end_page}", file=sys.stderr)
    pairs = scan_list_pages(session, limiter, args.start_page, args.end_page)
    print(f"[i] {limiter.summary()}", file=sys.stderr)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump([{"region": r, "slug": s} for r, s in pairs], f, ensure_ascii=False, separators=(",", ":"))

    print(f"[✓] Записал {len(pairs)} записей в {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
