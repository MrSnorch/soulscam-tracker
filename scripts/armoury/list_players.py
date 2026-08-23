#!/usr/bin/env python3
"""
Job 1 шардированного пайплайна: листает общий список armoury (все регионы)
и пишет полный список (region, slug) в один JSON-файл, который затем
скачивается остальными job'ами матрицы (через actions/upload-artifact +
download-artifact) и делится между ними на диапазоны.

Не скрапит сами страницы игроков — только список. Использует ту же
адаптивную задержку, что и остальной скрапер, но не сохраняет конфиг
задержки (это делает merge_shards.py, после того как все шарды
отработают — см. его докстринг).

Использование:
    python list_players.py -o players_list.json
"""

import argparse
import json
import sys

import requests

sys.path.insert(0, __file__.rsplit("/", 1)[0] if "/" in __file__ else ".")
from soulbound_armoury_scraper import AdaptiveRateLimiter, list_all_slugs, load_delay_config


def main():
    parser = argparse.ArgumentParser(description="Собрать полный список игроков armoury")
    parser.add_argument("-o", "--output", default="players_list.json")
    args = parser.parse_args()

    session = requests.Session()
    cfg = load_delay_config()
    start_delay = cfg["start_delay"] if cfg else 0.1
    limiter = AdaptiveRateLimiter(start_delay=start_delay)

    print("[i] Собираю список всех игроков...", file=sys.stderr)
    pairs = list_all_slugs(session, limiter)
    print(f"[i] Всего найдено: {len(pairs)}", file=sys.stderr)

    if not pairs:
        print("[!] Список пуст — не пишу файл.", file=sys.stderr)
        sys.exit(1)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump([{"region": r, "slug": s} for r, s in pairs], f, ensure_ascii=False, separators=(",", ":"))

    print(f"[✓] Записал {len(pairs)} игроков в {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
