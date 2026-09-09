"""
Разовая коррекция после первого скана "с нуля" (когда docs/armoury/ был
удалён и накопительная база начата заново). Первый прогон помечает ВСЕХ
игроков last_active=today, потому что сравнивать не с чем -
snapshot_changed(None, p) всегда True. Это технически корректно ("нет
предыдущих данных"), но выглядит как "все играли сегодня", что неверно.

Этот скрипт откатывает last_active/is_active_today к нейтральному
состоянию сразу после первого скана, чтобы база вела себя так, будто
первый снапшот - это точка отсчёта, а не зафиксированная активность.
history/<slug>.json трогает так же - убирает ложный "активен: <дата>"
из единственной записи.

Запускать РОВНО ОДИН РАЗ, сразу после первого прогона с чистой базой,
до того как накопится вторая точка данных.
"""
import json
import os

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "armoury")
PLAYERS_PATH = os.path.join(OUT_DIR, "players.json")
HISTORY_DIR = os.path.join(OUT_DIR, "history")


def main():
    with open(PLAYERS_PATH, "r", encoding="utf-8") as f:
        players = json.load(f)

    fixed = 0
    for p in players:
        if p.get("is_active_today"):
            p["is_active_today"] = False
            p["last_active"] = None  # честно: неизвестно, играл ли он до этого
            fixed += 1

    with open(PLAYERS_PATH, "w", encoding="utf-8") as f:
        json.dump(players, f, ensure_ascii=False, separators=(",", ":"))

    hist_fixed = 0
    if os.path.isdir(HISTORY_DIR):
        for fname in os.listdir(HISTORY_DIR):
            path = os.path.join(HISTORY_DIR, fname)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    hist = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            changed = False
            for rec in hist:
                if rec.get("last_active"):
                    rec["last_active"] = None
                    changed = True
            if changed:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(hist, f, ensure_ascii=False, separators=(",", ":"))
                hist_fixed += 1

    print(f"players.json: сброшено {fixed} ложных is_active_today")
    print(f"history/: поправлено {hist_fixed} файлов")


if __name__ == "__main__":
    main()
