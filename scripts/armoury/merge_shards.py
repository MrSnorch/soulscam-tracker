#!/usr/bin/env python3
"""
Job 3 шардированного пайплайна: собирает все shard_*.json от матрицы job'ов
(scrape_shard.py) и обновляет накопительную базу известных игроков в
docs/armoury/ — та же логика вывода, что раньше была в build_armoury_data.py
(теперь только сборка, без самого скрапинга):

- docs/armoury/players.json — НАКОПИТЕЛЬНАЯ база: каждый игрок, увиденный
  хотя бы одним прогоном, остаётся здесь навсегда, даже если сайт перестал
  его отдавать (удалён/скрыт/недоступен в моменте). Ключ — slug (постоянный
  и уникальный, в отличие от name). У игроков из текущего скрейпа
  name/level/last_seen/url обновляются и last_seen_scrape = сегодня; у
  игроков, не встреченных в этом прогоне, все поля остаются как были
  зафиксированы в последний раз, когда их видели. first_seen у уже
  известных игроков не трогается.
- docs/armoury/summary.json — { generated_at, total_players_known,
  total_players_seen_today, online_today, today_date }.
  total_players_known — размер всей накопленной базы, total_players_seen_today —
  сколько из них реально ответил сайт сегодняшним скрейпом (online_today —
  подмножество этого по дате last_seen на самой странице игрока).
- docs/armoury/duplicates.json — группы игроков с одинаковым именем на
  разных серверах/регионах (по всей накопленной базе).
- docs/armoury/online-history.json — по одной точке в день за 90 дней,
  источник графика тренда. Точка за день пишется только если сайт реально
  обновил данные в этот день (есть хотя бы один игрок с last_seen ==
  сегодня) — иначе на сайте просто отдаётся вчерашний слепок ("Last
  updated <вчера>" у всех игроков), и писать за сегодня online_today как
  фактическое число было бы искажением графика; в этом случае за сегодня
  остаётся дыра, прогон при этом не пропускается — players.json/summary.json
  всё равно обновляются как обычно.
- docs/armoury/by-region.json — распределение по серверам (по всей
  накопленной базе).

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
PLAYERS_PATH = os.path.join(OUT_DIR, "players.json")


def load_known_players():
    """Читает уже накопленную базу как dict {slug: player}. Пустая база,
    если файла ещё нет, битый JSON, или записи в старом (не-накопительном)
    формате без first_seen — тогда просто начинаем копить с этого прогона
    (те же игроки заново попадут в базу на первом же скрейпе, где встретятся)."""
    try:
        with open(PLAYERS_PATH, "r", encoding="utf-8") as f:
            existing = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return {p["slug"]: p for p in existing if "slug" in p and "first_seen" in p}


def main():
    parser = argparse.ArgumentParser(description="Сшить шарды armoury-скрапинга в накопительную базу игроков")
    parser.add_argument("shards", nargs="+", help="JSON-файлы от scrape_shard.py")
    args = parser.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)

    scraped = []
    for path in args.shards:
        with open(path, "r", encoding="utf-8") as f:
            scraped.extend(json.load(f))

    if not scraped:
        print("[!] Все шарды пусты — базу не трогаю.", file=sys.stderr)
        sys.exit(1)

    today_iso = datetime.now(timezone.utc).date().isoformat()

    known = load_known_players()
    for p in scraped:
        slug = p["slug"]
        existing = known.get(slug)
        first_seen = existing["first_seen"] if existing else today_iso
        known[slug] = {
            **p,
            "first_seen": first_seen,
            "last_seen_scrape": today_iso,
        }

    players = sorted(known.values(), key=lambda p: p["slug"])

    with open(PLAYERS_PATH, "w", encoding="utf-8") as f:
        json.dump(players, f, ensure_ascii=False, separators=(",", ":"))

    today = datetime.now(timezone.utc).date()
    online_today = sum(1 for p in players if parse_date(p["last_seen"]) == today)
    seen_today = sum(1 for p in players if p["last_seen_scrape"] == today_iso)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_players_known": len(players),
        "total_players_seen_today": seen_today,
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
    if online_today > 0:
        # Сайт реально обновил хотя бы чей-то last_seen сегодняшней датой —
        # значит данные свежие, точку можно писать. Если online_today == 0,
        # это значит сайт не обновлялся (last_seen у всех датирован вчера
        # или раньше — та же ситуация, что и "Last updated August 23" на
        # самом сайте, когда уже 24-е) - в этом случае за сегодня в графике
        # остаётся дыра, а не ложный ноль.
        history = [h for h in history if h["date"] != summary["today_date"]]
        history.append({"date": summary["today_date"], "online": online_today, "total": len(players)})
        history.sort(key=lambda h: h["date"])
        history = history[-90:]
        with open(history_path, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, separators=(",", ":"))
    else:
        print(f"[i] online_today=0 — сайт, похоже, не обновлял last_seen сегодня ({today_iso}), точку в историю не пишу.", file=sys.stderr)

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
        f"[✓] база: {len(players)} игроков известно всего, {seen_today} видели сегодня "
        f"({online_today} реально онлайн), {len(duplicates)} повторяющихся ников",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
