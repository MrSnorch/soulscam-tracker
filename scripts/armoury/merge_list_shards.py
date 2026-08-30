#!/usr/bin/env python3
"""
Job 1c двухфазного шардированного пайплайна сбора списка армоури:
сливает list_shard_*.json (результаты scan_list_shard.py, по одному на
диапазон страниц) в единый players_list.json — тот же формат, который
раньше писал list_players.py, так что scrape_shard.py (job 2 основного
пайплайна) не нуждается в изменениях.

Дедуплицирует по (region, slug) и сохраняет порядок первого появления,
на случай пересечения диапазонов страниц или дублей на самом сайте.

Использование:
    python merge_list_shards.py list_shard_0.json list_shard_1.json ... -o players_list.json
"""

import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser(description="Слить шарды списка armoury в один файл")
    parser.add_argument("shards", nargs="+", help="list_shard_*.json файлы для слияния")
    parser.add_argument("-o", "--output", default="players_list.json")
    args = parser.parse_args()

    seen = set()
    merged: list[dict] = []
    for path in args.shards:
        try:
            with open(path, "r", encoding="utf-8") as f:
                entries = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"[!] Не удалось прочитать {path}: {e}", file=sys.stderr)
            continue

        added = 0
        for entry in entries:
            key = (entry["region"], entry["slug"])
            if key not in seen:
                seen.add(key)
                merged.append(entry)
                added += 1
        print(f"[i] {path}: {len(entries)} записей, {added} новых", file=sys.stderr)

    if not merged:
        print("[!] Итоговый список пуст — не пишу файл.", file=sys.stderr)
        sys.exit(1)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, separators=(",", ":"))

    print(f"[✓] Записал {len(merged)} игроков в {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
