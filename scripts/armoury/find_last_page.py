#!/usr/bin/env python3
"""
Job 1a двухфазного шардированного пайплайна сбора списка армоури.

Быстро находит номер последней непустой страницы общего списка
(?sb_page=N) через экспоненциальный рост + бинарный поиск, вместо
последовательного обхода всех страниц одним раннером (что раньше
упиралось в timeout job'а по мере роста списка игроков — см. докстринг
find_last_list_page() в soulbound_armoury_scraper.py).

Результат — просто число, которое дальше используется, чтобы разбить
диапазон страниц [1, last_page] между раннерами матрицы (см.
scan_list_shard.py).

Использование:
    python find_last_page.py -o last_page.txt [--hint 250]
"""

import argparse
import sys

import requests

sys.path.insert(0, __file__.rsplit("/", 1)[0] if "/" in __file__ else ".")
from soulbound_armoury_scraper import AdaptiveRateLimiter, find_last_list_page, load_delay_config


def main():
    parser = argparse.ArgumentParser(description="Найти номер последней страницы общего списка armoury")
    parser.add_argument("-o", "--output", default="last_page.txt")
    parser.add_argument(
        "--hint", type=int, default=None,
        help="Примерный номер последней страницы с прошлого запуска - ускоряет разведку, если передан",
    )
    args = parser.parse_args()

    session = requests.Session()
    cfg = load_delay_config()
    start_delay = cfg["start_delay"] if cfg else 0.1
    limiter = AdaptiveRateLimiter(start_delay=start_delay)

    last_page = find_last_list_page(session, limiter, hint=args.hint)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(str(last_page))

    print(f"[✓] Последняя страница списка: {last_page}", file=sys.stderr)


if __name__ == "__main__":
    main()
