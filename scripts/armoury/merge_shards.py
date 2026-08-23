#!/usr/bin/env python3
"""
Job 3 шардированного пайплайна: собирает все shard_*.json от матрицы job'ов
(scrape_shard.py) в один список игроков и пишет финальные файлы для
дашборда в docs/armoury/ — та же логика вывода, что раньше была в
build_armoury_data.py (теперь только сборка, без самого скрапинга):

- docs/armoury/players.json — по одному объекту на игрока.
- docs/armoury/summary.json — { generated_at, total_players, online_today,
  today_date }.
- docs/armoury/duplicates.json — группы игроков с одинаковым именем на
  разных серверах/регионах.
- docs/armoury/online-history.json — по одной точке в день за 90 дней,
  источник графика тренда.
- docs/armoury/by-region.json — распределение по серверам.

Использование:
    python merge_shards.py shard_0.json shard_1.json shard_2.json shard_3.json shard_4.json
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from armoury_common import parse_date

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "armoury")


def main():
    parser = argparse.ArgumentParser(description="Сшить шарды armoury-скрапинга в финальные данные дашборда")
    parser.add_argument("shards", nargs="+", help="JSON-файлы от scrape_shard.py")
    args = parser.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)

    players = []
    for path in args.shards:
        with open(path, "r", encoding="utf-8") as f:
            players.extend(json.load(f))

    if not players:
        print("[!] Все шарды пусты — файлы не перезаписываю.", file=sys.stderr)
        sys.exit(1)

    with open(os.path.join(OUT_DIR, "players.json"), "w", encoding="utf-8") as f:
        json.dump(players, f, ensure_ascii=False, separators=(",", ":"))

    today = datetime.now(timezone.utc).date()
    online_today = sum(1 for p in players if parse_date(p["last_seen"]) == today)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_players": len(players),
        "online_today": online_today,
        "today_date": today.isoformat(),
    }
    with open(os.path.join(OUT_DIR, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    history_path = os.path.join(OUT_DIR, "online-history.json")
    try:
        with open(history_path, "r", encoding="utf-8") as f:
            history = json.load(f)
    except (OSError, json.JSONDecodeError):
        history = []
    history = [h for h in history if h["date"] != summary["today_date"]]
    history.append({"date": summary["today_date"], "online": online_today, "total": len(players)})
    history.sort(key=lambda h: h["date"])
    history = history[-90:]
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, separators=(",", ":"))

    by_region = defaultdict(int)
    for p in players:
        by_region[p["region"]] += 1
    with open(os.path.join(OUT_DIR, "by-region.json"), "w", encoding="utf-8") as f:
        json.dump(dict(sorted(by_region.items(), key=lambda kv: -kv[1])), f, ensure_ascii=False, separators=(",", ":"))

    by_name = defaultdict(list)
    for p in players:
        if p["name"]:
            by_name[p["name"].strip().lower()].append(p)
    duplicates = [
        {
            "name": group[0]["name"],
            "players": group,
            "cross_region": len({p["region"] for p in group}) > 1,
        }
        for group in by_name.values()
        if len(group) > 1
    ]
    duplicates.sort(key=lambda g: (not g["cross_region"], -len(g["players"])))
    with open(os.path.join(OUT_DIR, "duplicates.json"), "w", encoding="utf-8") as f:
        json.dump(duplicates, f, ensure_ascii=False, separators=(",", ":"))

    print(
        f"[✓] {len(players)} игроков ({len(args.shards)} шардов), {online_today} онлайн сегодня, "
        f"{len(duplicates)} повторяющихся ников",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
