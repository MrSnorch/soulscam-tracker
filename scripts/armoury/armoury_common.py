"""Общие хелперы для шардированного armoury-пайплайна (list_players.py,
scrape_shard.py, merge_shards.py)."""

from datetime import datetime

# "August 23, 2026" -> сравнимая с сегодняшней датой (UTC)
DATE_FMT = "%B %d, %Y"


def parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, DATE_FMT).date()
    except ValueError:
        return None
