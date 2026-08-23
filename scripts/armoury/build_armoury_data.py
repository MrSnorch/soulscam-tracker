#!/usr/bin/env python3
"""
Прогоняет soulbound_armoury_scraper.py по всем игрокам (--all-regions) и
пишет результат в docs/armoury/ для дашборда:

- docs/armoury/players.json — по одному объекту на игрока (slug, region,
  name, level, last_seen, url). Экипировку/скиллы сюда не кладём — они
  нужны только для CSV-выгрузки, не для дашборда, и раздувают файл.
- docs/armoury/summary.json — { generated_at, total_players, online_today,
  today_date }. online_today = число игроков, у которых last_seen
  парсится в сегодняшнюю дату (UTC) — единственная имеющаяся у нас метрика
  "реального" онлайна, отдельная от Steam concurrent players.
- docs/armoury/duplicates.json — группы игроков с одинаковым именем
  (без учёта регистра) на разных серверах/регионах.
- docs/armoury/online-history.json — по одной точке {date, online, total}
  за каждый успешный прогон (перезаписывает точку за тот же today_date,
  если прогон уже был сегодня), хранит последние 90 дней — источник для
  графика тренда "реальный онлайн по дням" на armoury.html.

Использует ту же адаптивную задержку и сохранённый конфиг, что и сам
скрапер (armoury_scraper_config.json рядом со скриптом).
"""

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

import requests

sys.path.insert(0, os.path.dirname(__file__))
from soulbound_armoury_scraper import (
    AdaptiveRateLimiter,
    list_all_slugs,
    load_delay_config,
    save_delay_config,
    scrape_player,
)

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "armoury")

# "August 23, 2026" -> сравнимая с сегодняшней датой (UTC)
DATE_FMT = "%B %d, %Y"


def parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, DATE_FMT).date()
    except ValueError:
        return None


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    session = requests.Session()

    cfg = load_delay_config()
    start_delay = cfg["start_delay"] if cfg else 0.1
    limiter = AdaptiveRateLimiter(start_delay=start_delay)

    print("[i] Собираю список всех игроков...", file=sys.stderr)
    pairs = list_all_slugs(session, limiter)
    print(f"[i] Всего найдено: {len(pairs)}", file=sys.stderr)

    players = []
    for i, (region, slug) in enumerate(pairs, 1):
        print(f"[{i}/{len(pairs)}] {region}/{slug} (задержка {limiter.delay:.3f}s)", file=sys.stderr)
        p = scrape_player(session, region, slug, limiter)
        if p:
            players.append({
                "slug": p.slug,
                "region": p.region,
                "name": p.name,
                "level": p.level,
                "last_seen": p.last_seen,
                "url": p.url,
            })

    print(f"[i] {limiter.summary()}", file=sys.stderr)
    save_delay_config(limiter)

    if not players:
        print("[!] Не удалось получить данные ни по одному игроку — файлы не перезаписываю.", file=sys.stderr)
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

    # История для графика тренда: одна точка на день, последняя точка за
    # today_date перезаписывается каждым новым прогоном в течение дня.
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
        f"[✓] {len(players)} игроков, {online_today} онлайн сегодня, "
        f"{len(duplicates)} повторяющихся ников",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
