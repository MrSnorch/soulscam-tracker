#!/usr/bin/env python3
"""
Job 3 шардированного пайплайна: собирает все shard_*.json от матрицы job'ов
(scrape_shard.py) и обновляет накопительную базу известных игроков в
docs/armoury/ — та же логика вывода, что раньше была в build_armoury_data.py
(теперь только сборка, без самого скрапинга).

С сентября 2026 сайт больше не отдаёт "Last seen in game" вообще (только
"Last updated <дата>", которая означает лишь момент пересчёта данных на
стороне сайта, а не реальный визит игрока). Поэтому активность теперь
вычисляется сравнением ПОЛНОГО снапшота игрока (level, экипировка, скиллы,
ачивки, дандж-рекорды — см. armoury_common.SNAPSHOT_FIELDS) с прошлым
сохранённым: если хоть что-то изменилось — значит играл. Метрика:

- last_active — дата (UTC), когда снапшот игрока в последний раз реально
  менялся (при первом появлении игрока — дата, когда его увидели впервые).
- is_active_today — bool, True если снапшот изменился именно в этом прогоне
  (т.е. last_active == сегодня).

Выходные файлы:
- docs/armoury/players.json — НАКОПИТЕЛЬНАЯ база: каждый игрок, увиденный
  хотя бы одним прогоном, остаётся здесь навсегда, даже если сайт перестал
  его отдавать (удалён/скрыт/недоступен в моменте). Ключ — slug (постоянный
  и уникальный, в отличие от name). У игроков из текущего скрейпа все поля
  снапшота обновляются, last_seen_scrape = сегодня, last_active/
  is_active_today пересчитываются; у игроков, не встреченных в этом
  прогоне, все поля остаются как были зафиксированы в последний раз, когда
  их видели. first_seen у уже известных игроков не трогается.
- docs/armoury/summary.json — { generated_at, total_players_known,
  total_players_seen_today, online_today, today_date }. online_today теперь
  = число игроков с is_active_today == True (реальное изменение снапшота
  сегодня), а не по старому текстовому last_seen.
- docs/armoury/duplicates.json — группы игроков с одинаковым именем на
  разных серверах/регионах (по всей накопленной базе).
- docs/armoury/online-history.json — по одной точке в день за 90 дней,
  источник графика тренда. Точка за день пишется только если сайт реально
  дал хоть одно новое изменение снапшота сегодня (online_today > 0) —
  иначе на сайте просто отдаётся вчерашний слепок у всех, и писать
  online_today=0 как факт было бы искажением графика; в этом случае за
  сегодня остаётся дыра, прогон при этом не пропускается —
  players.json/summary.json всё равно обновляются как обычно.
- docs/armoury/new-players-history.json — по одной точке в день за 90 дней:
  { date, count } — сколько новых slug'ов впервые попало в накопительную
  базу (first_seen == этот день) за конкретный календарный день. В отличие
  от online-history, пишется всегда, даже если сегодня новых 0 — "сегодня
  никого нового не нашли" (в отличие от online-history) не искажает
  график, это просто нулевая, но настоящая точка.
- docs/armoury/retention-history.json — по одной точке в день за 90 дней:
  { date, seen, total, pct } — какая доля всей известной на тот момент
  базы (total = total_players_known в тот день) реально "откликнулась"
  сайту в этот день (seen = сколько игроков получили last_seen_scrape ==
  этот день). Отвечает на вопрос "сколько аккаунтов ещё живые, а не
  мёртвые" - пишется всегда, даже 0%, по тем же соображениям, что и
  new-players-history.
- docs/armoury/history/<slug>.json — история изменений одного игрока:
  список { date, level, last_active } с одной новой записью только когда
  снапшот реально изменился относительно последней сохранённой записи (не
  пишется на каждый прогон - иначе на 1999+ игроков это тысячи файлов,
  растущих каждый час без всякой новой информации). Отдельный файл на
  игрока, а не поле в players.json, чтобы не раздувать основной файл,
  который целиком читается на каждой загрузке страницы.
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
from armoury_common import parse_date, snapshot_changed, latest_achievement_date, player_snapshot

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "armoury")
PLAYERS_PATH = os.path.join(OUT_DIR, "players.json")
HISTORY_DIR = os.path.join(OUT_DIR, "history")


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


def load_player_history(slug):
    """Читает docs/armoury/history/<slug>.json целиком (список записей
    {date, level, last_active}), [] если файла ещё нет. Используется, чтобы
    отличить "игрок правда новый" от "игрок уже был известен, но выпал из
    players.json на несколько прогонов" - см. merge() выше."""
    path = os.path.join(HISTORY_DIR, f"{slug}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return []


def update_player_history(slug, level, last_active, today_iso):
    """Дописывает docs/armoury/history/<slug>.json новой записью
    {date, level, last_active}, но только если level или last_active реально
    изменились относительно последней сохранённой записи - иначе на
    1999+ игроков история росла бы на файл в час без всякой новой
    информации. Файл создаётся при первом реальном изменении, не при
    первом появлении игрока (иначе на каждого сразу пишется файл с
    единственной записью, дублирующей players.json без пользы)."""
    path = os.path.join(HISTORY_DIR, f"{slug}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            history = json.load(f)
    except (OSError, json.JSONDecodeError):
        history = []

    last = history[-1] if history else None
    # last.get("last_active") может отсутствовать в записях, сделанных до
    # сентябрьской смены схемы сайта (там было "last_seen" вместо
    # "last_active") - такие старые записи не сравниваем по last_active,
    # чтобы не ловить ложное "изменение" на первой сверке после миграции.
    if last and last.get("level") == level and (
        "last_active" not in last or last.get("last_active") == last_active
    ):
        return  # ничего не изменилось - не пишем

    history.append({"date": today_iso, "level": level, "last_active": last_active})
    os.makedirs(HISTORY_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, separators=(",", ":"))


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
    debug_log = []  # DEBUG: какое конкретно поле триггернуло changed=True для каждого игрока
    for p in scraped:
        slug = p["slug"]
        existing = known.get(slug)
        prior_history = load_player_history(slug)  # [] если файла ещё нет
        # Если игрок отсутствует в текущей накопительной базе (existing is
        # None), это может значить либо что он правда новый, либо что он
        # ранее уже был известен, но выпал из недавних прогонов (не
        # докачался шард / пропущена страница списка) и сегодня "нашёлся"
        # снова. snapshot_changed(None, p) всегда возвращает True и ложно
        # помечает такого игрока активным сегодня, даже если его снапшот не
        # менялся месяцами - см. кейс WeapC (разрыв в history/, last_active
        # скакнул на сегодня, хотя последняя ачивка - за август). Наличие
        # файла истории - надёжный признак "мы его уже видели раньше", даже
        # если он выпал из players.json.
        first_seen = existing["first_seen"] if existing else today_iso
        is_returning_after_gap = existing is None and bool(prior_history)

        is_new_player = existing is None and not prior_history

        if is_returning_after_gap:
            # Полного прошлого снапшота у нас нет (history/ хранит только
            # level+last_active, не equipment/skills/achievements), так что
            # честно сравнить весь снапшот нельзя. Считаем игрока активным
            # сегодня по двум сигналам:
            #   1) новая ачивка новее last_known_active - даёт честную дату
            #      (ачивки - единственное поле, где сайт вообще отдаёт дату);
            #   2) level изменился с последней записи в history - факт есть,
            #      но точной даты нет, используем дату скана.
            last_record = prior_history[-1]
            # Тот же баг форматов, что и ниже: last_active в history тоже
            # хранится в ISO (YYYY-MM-DD), а не в формате сайта - parse_date
            # молча вернёт None. Парсим ISO вручную.
            last_known_active = None
            if last_record.get("last_active"):
                try:
                    last_known_active = datetime.strptime(last_record["last_active"], "%Y-%m-%d").date()
                except ValueError:
                    last_known_active = None
            if last_known_active is None:
                # Старые записи (до сентябрьской смены схемы сайта) хранят
                # last_seen вместо last_active - там last_active просто
                # отсутствует. Раз честной даты активности нет, используем
                # дату самой записи как консервативную границу снизу
                # (мы точно знаем, что игрок существовал уже тогда), а не
                # None - иначе "newest_achievement > None" всегда true и
                # ложное срабатывание на WeapC-подобных кейсах повторится.
                try:
                    last_known_active = datetime.strptime(last_record["date"], "%Y-%m-%d").date()
                except (KeyError, ValueError):
                    last_known_active = None
            newest_achievement = latest_achievement_date(p)
            achievement_is_new = newest_achievement and (
                last_known_active is None or newest_achievement > last_known_active
            )
            level_changed = (
                last_record.get("level") is not None
                and p.get("level") is not None
                and str(last_record.get("level")) != str(p.get("level"))
            )
            changed_today = bool(achievement_is_new or level_changed)
            if achievement_is_new:
                # Точная дата с сайта - предпочитаем её дате скана.
                last_active = newest_achievement.isoformat()
            elif level_changed:
                # Level изменился, но без новой ачивки - точной даты нет,
                # используем дату скана как консервативную оценку.
                last_active = today_iso
            else:
                last_active = last_record.get("last_active") or last_record.get("date") or today_iso
        else:
            changed = snapshot_changed(existing, p)
            # DEBUG: если снапшот изменился и это НЕ новый игрок, записываем
            # точно какое поле отличается - чтобы понять природу ложных
            # срабатываний (временно, для диагностики).
            if changed and existing is not None:
                so, sn = player_snapshot(existing), player_snapshot(p)
                diff_fields = [k for k in so if so.get(k) != sn.get(k)]
                debug_log.append({
                    "slug": slug,
                    "diff_fields": diff_fields,
                    "old": {k: so.get(k) for k in diff_fields},
                    "new": {k: sn.get(k) for k in diff_fields},
                })
            # Игрок, впервые попавший в базу (existing=None, истории нет
            # тоже), - это НЕ активность, это просто первое обнаружение.
            # snapshot_changed(None, p) всегда True (сравнивать не с чем),
            # но это не значит, что игрок "играл сегодня" - мы его просто
            # раньше не сканировали. Активным сегодня считаем только того,
            # кто уже был в базе и у кого что-то реально поменялось.
            changed_today = changed and not is_new_player
            if changed:
                # Снапшот реально изменился в этом прогоне. Предпочитаем
                # точную дату последней ачивки сайта (achievements[].date) -
                # единственное поле, где сайт даёт реальную дату события,
                # если она новее того, что мы уже знали. Если ачивок нет или
                # их дата не новее прежней (поменялось что-то другое -
                # equipment/level/dungeon_records, без новых ачивок), точной
                # даты нет вообще (сайт не отдаёт "last seen in game" ни в
                # каком виде - см. soulbound_armoury_scraper.py) - используем
                # дату скана как консервативную оценку "играл не позже этого".
                # Внимание: last_active хранится в ISO-формате (YYYY-MM-DD,
                # см. .isoformat() ниже), а НЕ в формате сайта "%B %d, %Y" -
                # parse_date() ожидает именно формат сайта и на ISO-строке
                # молча вернёт None (см. armoury_common.parse_date). Из-за
                # этого prev_date всегда получался None, и любая уже
                # известная дата ачивки бесконечно "переоткрывалась" как
                # новая на каждом прогоне - вот откуда ложные is_active_today
                # у одних и тех же игроков день за днём. Парсим ISO вручную.
                prev_last_active = existing.get("last_active") if existing else None
                prev_date = None
                if prev_last_active:
                    try:
                        prev_date = datetime.strptime(prev_last_active, "%Y-%m-%d").date()
                    except ValueError:
                        prev_date = None
                newest_achievement = latest_achievement_date(p)
                if newest_achievement and (prev_date is None or newest_achievement > prev_date):
                    last_active = newest_achievement.isoformat()
                else:
                    last_active = today_iso
            else:
                # снапшот не изменился - активность остаётся на прошлом
                # зафиксированном значении (или сегодня, если это первый раз,
                # когда мы вообще видим игрока)
                last_active = existing.get("last_active", today_iso) if existing else today_iso
        known[slug] = {
            **p,
            "first_seen": first_seen,
            "last_seen_scrape": today_iso,
            "last_active": last_active,
            # "активен сегодня" = снапшот реально изменился в ЭТОМ прогоне,
            # а не буквально last_active == today_iso - last_active теперь
            # может быть точной (более ранней) датой ачивки, даже когда
            # изменение зафиксировано именно сегодня.
            "is_active_today": bool(changed_today),
        }
        update_player_history(slug, p.get("level"), last_active, today_iso)

    # Игроки, не встреченные в этом прогоне (сайт не отдал их сегодня) -
    # is_active_today не может оставаться True со вчера, раз мы сегодня их
    # даже не проверяли.
    scraped_slugs = {p["slug"] for p in scraped}
    for slug, p in known.items():
        if slug not in scraped_slugs:
            p["is_active_today"] = False

    players = sorted(known.values(), key=lambda p: p["slug"])

    with open(PLAYERS_PATH, "w", encoding="utf-8") as f:
        json.dump(players, f, ensure_ascii=False, separators=(",", ":"))

    today = datetime.now(timezone.utc).date()
    online_today = sum(1 for p in players if p.get("is_active_today"))
    seen_today = sum(1 for p in players if p["last_seen_scrape"] == today_iso)
    new_today = sum(1 for p in players if p["first_seen"] == today_iso)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_players_known": len(players),
        "total_players_seen_today": seen_today,
        "online_today": online_today,
        "new_players_today": new_today,
        "today_date": today.isoformat(),
    }
    with open(os.path.join(OUT_DIR, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # DEBUG: временный лог причин is_active_today - какое конкретно поле
    # снапшота отличалось для каждого игрока, у которого changed=True (не
    # новый игрок). Убрать, когда диагностика больше не нужна.
    with open(os.path.join(OUT_DIR, "debug-active-log.json"), "w", encoding="utf-8") as f:
        json.dump(debug_log, f, ensure_ascii=False, indent=2)
    print(f"[debug] записано {len(debug_log)} причин в docs/armoury/debug-active-log.json", file=sys.stderr)

    history_path = os.path.join(OUT_DIR, "online-history.json")
    try:
        with open(history_path, "r", encoding="utf-8") as f:
            history = json.load(f)
    except (OSError, json.JSONDecodeError):
        history = []
    if online_today > 0:
        # Хотя бы у одного игрока снапшот реально изменился сегодня —
        # значит сайт дал свежие данные, точку можно писать. Если
        # online_today == 0, значит ни у кого снапшот не поменялся (та же
        # ситуация, что и "Last updated <вчера>" у всех на самом сайте) -
        # в этом случае за сегодня в графике остаётся дыра, а не ложный ноль.
        history = [h for h in history if h["date"] != summary["today_date"]]
        history.append({"date": summary["today_date"], "online": online_today, "total": len(players)})
        history.sort(key=lambda h: h["date"])
        history = history[-90:]
        with open(history_path, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, separators=(",", ":"))
    else:
        print(f"[i] online_today=0 — ни у кого снапшот не изменился сегодня ({today_iso}), точку в историю не пишу.", file=sys.stderr)

    new_history_path = os.path.join(OUT_DIR, "new-players-history.json")
    try:
        with open(new_history_path, "r", encoding="utf-8") as f:
            new_history = json.load(f)
    except (OSError, json.JSONDecodeError):
        new_history = []
    new_history = [h for h in new_history if h["date"] != summary["today_date"]]
    new_history.append({"date": summary["today_date"], "count": new_today})
    new_history.sort(key=lambda h: h["date"])
    new_history = new_history[-90:]
    with open(new_history_path, "w", encoding="utf-8") as f:
        json.dump(new_history, f, ensure_ascii=False, separators=(",", ":"))

    retention_path = os.path.join(OUT_DIR, "retention-history.json")
    try:
        with open(retention_path, "r", encoding="utf-8") as f:
            retention_history = json.load(f)
    except (OSError, json.JSONDecodeError):
        retention_history = []
    retention_history = [h for h in retention_history if h["date"] != summary["today_date"]]
    retention_pct = round(100 * seen_today / len(players), 1) if players else 0
    retention_history.append({
        "date": summary["today_date"],
        "seen": seen_today,
        "total": len(players),
        "pct": retention_pct,
    })
    retention_history.sort(key=lambda h: h["date"])
    retention_history = retention_history[-90:]
    with open(retention_path, "w", encoding="utf-8") as f:
        json.dump(retention_history, f, ensure_ascii=False, separators=(",", ":"))

    by_region = defaultdict(int)
    for p in players:
        by_region[p["region"]] += 1
    with open(os.path.join(OUT_DIR, "by-region.json"), "w", encoding="utf-8") as f:
        json.dump(dict(sorted(by_region.items(), key=lambda kv: -kv[1])), f, ensure_ascii=False, separators=(",", ":"))

    # Компактная проекция игрока для duplicates.json — полные снапшоты
    # (equipment/skills/achievements/dungeon_records) там не нужны и заметно
    # раздули бы файл, который целиком читается при каждой загрузке страницы.
    def _dupe_entry(p):
        return {
            "slug": p["slug"], "region": p["region"], "level": p.get("level"),
            "last_active": p.get("last_active"), "url": p.get("url"),
        }

    by_name = defaultdict(list)
    for p in players:
        if p["name"]:
            by_name[p["name"].strip().lower()].append(p)
    duplicates = [
        {
            "name": group[0]["name"],
            "players": [_dupe_entry(p) for p in group],
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
        f"({online_today} реально онлайн, {new_today} новых сегодня), {len(duplicates)} повторяющихся ников",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
