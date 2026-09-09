"""Общие хелперы для шардированного armoury-пайплайна (list_players.py,
scrape_shard.py, merge_shards.py)."""

from datetime import datetime

# "August 23, 2026" -> сравнимая с сегодняшней датой (UTC)
DATE_FMT = "%B %d, %Y"

# Поля снапшота игрока, изменение любого из которых означает, что персонаж
# реально играл (в отличие от last_updated, которое сайт может пере-рендерить
# без реальной игровой активности — с сентября 2026 сайт больше не отдаёт
# "Last seen in game", поэтому активность вычисляется сравнением снапшота
# с прошлым сохранённым, а не по одному полю).
SNAPSHOT_FIELDS = [
    "level", "skills_count", "achievements_count", "achievement_points",
    "equipment", "skills", "achievements", "dungeon_records",
]


def parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, DATE_FMT).date()
    except ValueError:
        return None


def _dungeon_records_scores_only(records):
    """dungeon_records хранит вместе со score ещё global_rank/server_rank/
    rooms. Ранги "дышат" каждый день из-за чужой активности на лидерборде -
    сравнивать их наравне со score нельзя, иначе игрок ложно считается
    активным просто потому, что кто-то другой сыграл и подвинул таблицу.
    Оставляем для сравнения только dungeon+mode+score."""
    if not records:
        return records
    return [
        {"dungeon": r.get("dungeon"), "mode": r.get("mode"), "score": r.get("score")}
        for r in records
    ]


def player_snapshot(p: dict) -> dict:
    """Извлекает только поля снапшота из записи игрока (dict), в стабильном
    порядке — для сравнения "изменилось ли что-то с прошлого раза"."""
    snap = {k: p.get(k) for k in SNAPSHOT_FIELDS}
    snap["dungeon_records"] = _dungeon_records_scores_only(snap.get("dungeon_records"))
    return snap


def snapshot_changed(old: dict | None, new: dict) -> bool:
    """True, если снапшот игрока реально изменился (значит играл), сравнивая
    только поля из SNAPSHOT_FIELDS. old=None (игрок новый) считается
    изменением."""
    if old is None:
        return True
    return player_snapshot(old) != player_snapshot(new)


def latest_achievement_date(p: dict):
    """Дата самой недавней ачивки игрока (сайт отдаёт их от новой к старой,
    но на всякий случай берём максимум по всем датам), либо None."""
    best = None
    for a in p.get("achievements") or []:
        d = parse_date(a.get("date"))
        if d and (best is None or d > best):
            best = d
    return best
