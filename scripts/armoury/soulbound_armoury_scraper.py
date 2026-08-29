#!/usr/bin/env python3
"""
Soulbound: Online — Armoury scraper
====================================

Парсит публичные страницы https://soulbound.game/armoury/<region>/<slug>/
и вытаскивает: имя, уровень, регион, last updated, last seen, экипировку,
скиллы, ачивки.

Установка зависимостей:
    pip install requests beautifulsoup4 --break-system-packages

Использование:
    # один игрок
    python soulbound_armoury_scraper.py us/diovani-c1mky

    # несколько игроков -> CSV
    python soulbound_armoury_scraper.py us/diovani-c1mky us/other-abc12 -o out.csv

    # список slug'ов по региону (собрать со страницы списка) -> потом распарсить всех
    python soulbound_armoury_scraper.py --list-region us -o us_players.csv

    # все регионы сразу — листает общий список ?sb_page=N (без фильтра региона)
    python soulbound_armoury_scraper.py --all-regions -o all_players.csv

    # с явными настройками задержки
    python soulbound_armoury_scraper.py --all-regions --start-delay 0.1 --min-delay 0.02

Конфиг задержки:
  - По завершении работы скрипт сохраняет найденную оптимальную задержку в
    armoury_scraper_config.json (рядом со скриптом). При следующем запуске
    БЕЗ явного --start-delay она подхватывается автоматически — не нужно
    заново нащупывать минимум с нуля. Отключается флагом --no-save-config.

Замечания об этичности/лимитах:
  - Задержка между запросами адаптивная (см. класс AdaptiveRateLimiter):
    стартует с --start-delay (по умолчанию 0.1s). Каждые 8 успешных
    запросов подряд лимитер АКТИВНО пробует срезать задержку вдвое —
    это не осторожное "восстановление после инцидента", а поиск нижней
    границы. При первой ошибке (403/429/5xx/timeout) — запоминает эту
    зону как проблемную (unsafe_floor) и больше туда не спускается,
    задержка растёт экспоненциально и запрос ретраится (уважая
    Retry-After, если сервер его прислал). В конце печатается сводка:
    итоговая задержка, минимальная подтверждённая рабочая задержка и
    обнаруженная проблемная граница — их удобно передать как
    --start-delay в следующий запуск.
  - Пагинация общего списка (все регионы) — ?sb_page=N без фильтра region.
    Комбинация region+sb_page для одного региона отдельно НЕ подтверждена,
    поэтому --all-regions использует общий список и определяет регион
    каждого игрока по его собственной ссылке.
  - Данные на сайте обновляются раз в сутки ("Data refreshes daily") —
    смысла опрашивать чаще нет.
  - Используйте для личных/некоммерческих целей и не заваливайте сайт
    параллельными запросами.
"""

import argparse
import csv
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://soulbound.game"
ARMOURY_URL = f"{BASE_URL}/armoury"
TIMEOUT = 15
MAX_RETRIES = 6
CONFIG_PATH = Path(__file__).with_name("armoury_scraper_config.json")

# Известные коды регионов (значение query-параметра ?region=...), подтверждённые
# по ссылкам в навигации сайта и уточнённые вручную.
KNOWN_REGIONS = ["us", "euro", "asia", "sam", "usa3", "euro3"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; SoulboundArmouryScraper/1.0; "
        "personal use; +https://soulbound.game/armoury/)"
    )
}


def load_delay_config(path: Path = CONFIG_PATH) -> Optional[dict]:
    """
    Читает сохранённые с прошлого запуска параметры задержки.
    Формат файла: {"start_delay": 0.0275, "unsafe_floor": 0.025, "updated": "..."}
    Возвращает None, если файла нет или он повреждён.
    """
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if "start_delay" not in cfg:
            return None
        return cfg
    except (json.JSONDecodeError, OSError) as e:
        print(f"[!] Не удалось прочитать конфиг {path}: {e}", file=sys.stderr)
        return None


def save_delay_config(limiter: "AdaptiveRateLimiter", path: Path = CONFIG_PATH):
    """
    Сохраняет найденную по итогам сессии задержку, чтобы в следующий раз
    не начинать поиск заново. Пишем не последнюю текущую delay (она могла
    вырасти после недавней ошибки и ещё не успеть спуститься обратно), а
    чуть выше unsafe_floor, если он обнаружен, либо наблюдённый минимум.
    """
    if limiter.unsafe_floor is not None:
        suggested = limiter.unsafe_floor * 1.1
    else:
        suggested = limiter.observed_min_working_delay

    cfg = {
        "start_delay": round(suggested, 4),
        "observed_min_working_delay": round(limiter.observed_min_working_delay, 4),
        "unsafe_floor": round(limiter.unsafe_floor, 4) if limiter.unsafe_floor is not None else None,
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        print(f"[i] Сохранил найденную задержку ({cfg['start_delay']}s) в {path}", file=sys.stderr)
    except OSError as e:
        print(f"[!] Не удалось сохранить конфиг {path}: {e}", file=sys.stderr)


class AdaptiveRateLimiter:
    """
    Адаптивная задержка между запросами с активным поиском минимума.

    Стартует с start_delay (можно очень маленькой, напр. 0.1s или ниже).
    Каждые probe_after_successes успешных запросов подряд ПРОБУЕТ снизить
    задержку на probe_factor (агрессивнее, чем плавный recovery — это
    активный поиск нижней границы, а не осторожное восстановление после
    инцидента). Если после снижения снова словили ошибку — сразу помечаем
    эту зону как "плохую" и откатываемся выше неё с запасом, чтобы не
    колебаться туда-сюда вокруг точки отказа.

    При ошибке (403/429/5xx/timeout/connection error) — увеличивает
    задержку экспоненциально, уважая Retry-After, если сервер его прислал,
    и запоминает эту задержку как нижнюю границу "проблемной зоны" —
    больше не пробует спускаться ниже unsafe_floor без явного запроса.
    """

    def __init__(
        self,
        start_delay: float = 0.1,
        min_delay: float = 0.0,
        max_delay: float = 30.0,
        backoff_factor: float = 2.0,
        probe_after_successes: int = 8,
        probe_factor: float = 0.5,
    ):
        self.delay = start_delay
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.probe_after_successes = probe_after_successes
        self.probe_factor = probe_factor
        self._consecutive_successes = 0
        self.observed_min_working_delay = start_delay  # лучший подтверждённый минимум
        self.unsafe_floor: Optional[float] = None  # задержка, при которой словили ошибку
        self.total_errors = 0

    def wait(self):
        if self.delay > 0:
            time.sleep(self.delay)

    def on_success(self):
        self._consecutive_successes += 1
        self.observed_min_working_delay = min(self.observed_min_working_delay, self.delay)

        if self._consecutive_successes >= self.probe_after_successes:
            self._consecutive_successes = 0
            candidate = self.delay * self.probe_factor
            new_delay = max(self.min_delay, candidate)
            # не пробуем повторно спускаться в зону, где уже была ошибка
            if self.unsafe_floor is not None and new_delay <= self.unsafe_floor:
                new_delay = self.unsafe_floor * 1.1  # чуть выше проблемной границы
            if new_delay < self.delay - 1e-9:
                print(
                    f"[i] {self.probe_after_successes} успешных запросов подряд — "
                    f"пробую снизить задержку {self.delay:.3f}s -> {new_delay:.3f}s",
                    file=sys.stderr,
                )
                self.delay = new_delay

    def on_error(self, retry_after: Optional[float] = None):
        self.total_errors += 1
        self._consecutive_successes = 0
        # запоминаем, что на этой задержке (или ниже) уже была ошибка —
        # больше не пробуем опускаться сюда снова
        if self.unsafe_floor is None or self.delay < self.unsafe_floor:
            self.unsafe_floor = self.delay
        base = max(self.delay, self.min_delay)
        new_delay = base * self.backoff_factor
        if retry_after is not None:
            new_delay = max(new_delay, retry_after)
        new_delay = min(new_delay, self.max_delay)
        print(
            f"[!] Увеличиваю задержку {self.delay:.3f}s -> {new_delay:.3f}s после ошибки "
            f"(нижняя проблемная граница теперь {self.unsafe_floor:.3f}s)",
            file=sys.stderr,
        )
        self.delay = new_delay

    def summary(self) -> str:
        floor_str = f"{self.unsafe_floor:.3f}s" if self.unsafe_floor is not None else "не обнаружена"
        return (
            f"Итоговая задержка: {self.delay:.3f}s | "
            f"минимальная рабочая задержка за сессию: {self.observed_min_working_delay:.3f}s | "
            f"проблемная граница (где были ошибки): {floor_str} | "
            f"всего ошибок/ретраев: {self.total_errors}"
        )


@dataclass
class PlayerData:
    slug: str
    region: str
    name: Optional[str] = None
    level: Optional[str] = None
    last_updated: Optional[str] = None
    last_seen: Optional[str] = None
    skills_count: Optional[str] = None
    achievements_count: Optional[str] = None
    achievement_points: Optional[str] = None
    equipment: dict = field(default_factory=dict)
    skills: dict = field(default_factory=dict)
    url: str = ""


def fetch(
    session: requests.Session,
    url: str,
    limiter: "AdaptiveRateLimiter",
    max_retries: int = MAX_RETRIES,
    max_outage_wait: float = 3600.0,
) -> Optional[BeautifulSoup]:
    """
    Делает GET с ретраями и адаптивной задержкой. Задержка выдерживается
    ПЕРЕД каждой попыткой (включая первую), её длительность управляется
    limiter'ом снаружи.

    Первые max_retries попыток — обычный адаптивный ретрай (как раньше).
    Если после них сайт всё ещё не отвечает (лежит целиком — 502/504/timeout
    и т.п.), скрипт НЕ переходит к следующему игроку, а переходит в режим
    "ожидания оживления сайта": ждёт max_delay (потолок лимитера, обычно 30s)
    между попытками и пробует бесконечно (до max_outage_wait секунд суммарно
    в этом режиме), пока сайт не ответит 200 или пока не поймает не-серверную
    ошибку (404 и т.п., которую ретраить бессмысленно).
    """
    for attempt in range(1, max_retries + 1):
        limiter.wait()
        try:
            resp = session.get(url, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException as e:
            print(f"[!] Попытка {attempt}/{max_retries}: ошибка соединения {url}: {e}", file=sys.stderr)
            limiter.on_error()
            continue

        if resp.status_code == 200:
            limiter.on_success()
            return BeautifulSoup(resp.text, "html.parser")

        if resp.status_code in (403, 429, 500, 502, 503, 504):
            retry_after = None
            ra_header = resp.headers.get("Retry-After")
            if ra_header:
                try:
                    retry_after = float(ra_header)
                except ValueError:
                    retry_after = None
            print(
                f"[!] Попытка {attempt}/{max_retries}: HTTP {resp.status_code} для {url}",
                file=sys.stderr,
            )
            limiter.on_error(retry_after=retry_after)
            continue

        # Прочие коды (404 и т.п.) — ретраить бессмысленно
        print(f"[!] HTTP {resp.status_code} для {url}, не ретраю.", file=sys.stderr)
        return None

    # Обычные ретраи исчерпаны — сайт, похоже, лёг целиком.
    # Не идём дальше по списку игроков: ждём и продолжаем стучаться сюда же.
    print(
        f"[!] {url} не отвечает после {max_retries} попыток — похоже, сайт лёг. "
        f"Перехожу в режим ожидания (жду и повторяю тот же запрос, "
        f"не двигаясь к следующему игроку)...",
        file=sys.stderr,
    )
    waited = 0.0
    outage_attempt = 0
    outage_poll_delay = 1.0
    while waited < max_outage_wait:
        outage_attempt += 1
        wait_for = outage_poll_delay
        print(f"[i] Ожидание оживления сайта: попытка {outage_attempt}, жду {wait_for:.0f}s...", file=sys.stderr)
        time.sleep(wait_for)
        waited += wait_for
        try:
            resp = session.get(url, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException as e:
            print(f"[!] Сайт всё ещё недоступен ({e}), жду дальше (суммарно {waited:.0f}s)...", file=sys.stderr)
            continue

        if resp.status_code == 200:
            print(f"[✓] Сайт снова отвечает после {waited:.0f}s ожидания. Продолжаю сканирование.", file=sys.stderr)
            limiter.on_success()
            return BeautifulSoup(resp.text, "html.parser")

        if resp.status_code in (403, 429, 500, 502, 503, 504):
            print(
                f"[!] Всё ещё HTTP {resp.status_code} (суммарно ждал {waited:.0f}s), жду дальше...",
                file=sys.stderr,
            )
            continue

        print(f"[!] HTTP {resp.status_code} для {url}, не ретраю.", file=sys.stderr)
        return None

    print(
        f"[!] Сайт не ожил за {max_outage_wait:.0f}s ожидания — пропускаю {url} "
        f"и продолжаю со следующим игроком.",
        file=sys.stderr,
    )
    return None


def parse_player_page(soup: BeautifulSoup, slug: str, region: str, url: str) -> PlayerData:
    data = PlayerData(slug=slug, region=region, url=url)

    # Имя — обычно единственный <h1>
    h1 = soup.find("h1")
    if h1:
        data.name = h1.get_text(strip=True)

    # Уровень + регион ("Level 68 US")
    level_block = soup.find(string=re.compile(r"Level\s+\d+"))
    if level_block:
        m = re.search(r"Level\s+(\d+)", level_block)
        if m:
            data.level = m.group(1)

    # "Last updated <date> Last seen in game <date>"
    text_all = soup.get_text(" ", strip=True)
    m_updated = re.search(
        r"Last updated\s+([A-Za-z]+ \d{1,2},\s*\d{4})", text_all
    )
    if m_updated:
        data.last_updated = m_updated.group(1)

    m_seen = re.search(
        r"Last seen in game\s+([A-Za-z]+ \d{1,2},\s*\d{4})", text_all
    )
    if m_seen:
        data.last_seen = m_seen.group(1)

    # Skills N
    m_skills = re.search(r"Skills\s+(\d+)", text_all)
    if m_skills:
        data.skills_count = m_skills.group(1)

    # Achievements N achievements / points
    m_ach = re.search(r"Achievements\s+(\d+)\s+achievements", text_all)
    if m_ach:
        data.achievements_count = m_ach.group(1)

    m_points = re.search(r"([\d,]+)\s+Achievement points", text_all)
    if m_points:
        data.achievement_points = m_points.group(1).replace(",", "")

    # Экипировка: элементы списка вида "HeadNecrotic Warrior Crown"
    # Ищем все <li> под секцией Equipment по слоту
    equipment_slots = [
        "Head", "Chest", "Back", "Belt", "Feet",
        "Weapon", "Neck", "Ring 1", "Ring 2",
    ]
    for li in soup.find_all("li"):
        li_text = li.get_text(" ", strip=True)
        for slot in equipment_slots:
            if li_text.startswith(slot) and slot not in data.equipment:
                item_name = li_text[len(slot):].strip()
                if item_name and item_name != "—":
                    data.equipment[slot] = item_name

    # Скиллы: img alt/следующий текст с уровнем скилла, например "Crafting84"
    skill_names = [
        "Crafting", "Farming", "Cooking", "Strength", "Chemistry",
        "Foraging", "Hacking", "Mining", "Knowledge", "Dexterity",
        "Fishing", "Technology", "Gearforging", "Marksmanship",
    ]
    for li in soup.find_all("li"):
        li_text = li.get_text(" ", strip=True)
        for skill in skill_names:
            m = re.match(rf"^{skill}\s*(\d+)$", li_text.replace(" ", ""))
            if m:
                data.skills[skill] = m.group(1)

    return data


def scrape_player(session: requests.Session, region: str, slug: str, limiter: AdaptiveRateLimiter) -> Optional[PlayerData]:
    url = f"{ARMOURY_URL}/{region}/{slug}/"
    soup = fetch(session, url, limiter)
    if soup is None:
        return None
    return parse_player_page(soup, slug, region, url)


def list_region_slugs(session: requests.Session, region: str, limiter: AdaptiveRateLimiter, max_pages: int = 50) -> list[str]:
    """
    Собирает slug'и игроков одного региона со страницы списка армоури.
    ВНИМАНИЕ: подтверждено, что пагинация без фильтра региона (просто
    ?sb_page=N) листает общий список ("All regions"). Комбинация
    ?region=X&sb_page=N с фильтром по конкретному региону НЕ проверена —
    если она не работает, используйте list_all_slugs() и отфильтруйте
    результат по региону вручную (slug уже содержит регион в href).
    """
    slugs: list[str] = []
    seen_urls = set()

    for page in range(1, max_pages + 1):
        if page == 1:
            url = f"{ARMOURY_URL}/?region={region}"
        else:
            url = f"{ARMOURY_URL}/?region={region}&sb_page={page}"

        if url in seen_urls:
            break
        seen_urls.add(url)

        soup = fetch(session, url, limiter)
        if soup is None:
            break

        found_this_page = 0
        for a in soup.find_all("a", href=True):
            href = a["href"]
            m = re.search(rf"/armoury/{region}/([a-z0-9\-]+)/?$", href)
            if m:
                slug = m.group(1)
                if slug not in slugs:
                    slugs.append(slug)
                    found_this_page += 1

        print(f"[i] Страница {page}: найдено {found_this_page} новых игроков", file=sys.stderr)

        if found_this_page == 0:
            break

    return slugs


def list_all_slugs(session: requests.Session, limiter: AdaptiveRateLimiter, max_pages: int = 500) -> list[tuple[str, str]]:
    """
    Собирает (region, slug) ВСЕХ игроков со всех регионов сразу, листая
    общий список через ?sb_page=N (без фильтра региона — подтверждено,
    что без region пагинация листает общий список всех регионов).
    Регион для каждого игрока берётся прямо из его href
    (напр. /armoury/us/diovani-c1mky/ -> region='us').
    Останавливается, когда страница не даёт новых игроков, или по max_pages.
    """
    results: list[tuple[str, str]] = []
    seen_pairs = set()

    for page in range(1, max_pages + 1):
        if page == 1:
            url = f"{ARMOURY_URL}/"
        else:
            url = f"{ARMOURY_URL}/?sb_page={page}"

        soup = fetch(session, url, limiter)
        if soup is None:
            break

        found_this_page = 0
        for a in soup.find_all("a", href=True):
            href = a["href"]
            m = re.search(r"/armoury/([a-z0-9]+)/([a-z0-9\-]+)/?$", href)
            if m:
                region, slug = m.group(1), m.group(2)
                pair = (region, slug)
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    results.append(pair)
                    found_this_page += 1

        print(f"[i] Страница {page}: найдено {found_this_page} новых игроков (всего {len(results)})", file=sys.stderr)

        if found_this_page == 0:
            print("[i] Новых игроков не найдено — похоже, дошли до конца списка.", file=sys.stderr)
            break

    return results


def main():
    parser = argparse.ArgumentParser(description="Soulbound Armoury scraper")
    parser.add_argument(
        "players", nargs="*",
        help="Игроки в формате region/slug, напр. us/diovani-c1mky",
    )
    parser.add_argument(
        "--list-region", metavar="REGION",
        help=(
            "Сначала собрать список slug'ов по региону со страницы списка. "
            "Известные значения: us, euro, asia, sam, usa3 (US West), "
            "euro3 (Europe 3)."
        ),
    )
    parser.add_argument(
        "--all-regions", action="store_true",
        help=(
            "Собрать ВСЕХ игроков сразу, листая общий список через ?sb_page=N "
            "(без фильтра региона — так пагинация отдаёт общий список всех "
            "регионов). Регион каждого игрока определяется из его собственной "
            "ссылки. Это быстрее, чем обходить регионы по отдельности."
        ),
    )
    parser.add_argument(
        "-o", "--output", default="armoury_data.csv",
        help="Путь к выходному CSV файлу (по умолчанию armoury_data.csv)",
    )
    parser.add_argument(
        "--start-delay", type=float, default=None,
        help=(
            "Начальная задержка между запросами в секундах. Если не указана — "
            f"берётся из сохранённого конфига ({CONFIG_PATH.name}), если он есть, "
            "иначе используется 0.1"
        ),
    )
    parser.add_argument(
        "--min-delay", type=float, default=0.0,
        help=(
            "Абсолютный пол задержки в секундах (по умолчанию 0 — лимитер сам "
            "агрессивно нащупывает минимум методом проб, отступая вверх при "
            "первой же ошибке; --min-delay задаёт лишь жёсткую нижнюю границу, "
            "ниже которой он не полезет даже пробуя)"
        ),
    )
    parser.add_argument(
        "--no-save-config", action="store_true",
        help="Не сохранять найденную задержку в конфиг по завершении работы",
    )
    args = parser.parse_args()

    session = requests.Session()

    start_delay = args.start_delay
    if start_delay is None:
        cfg = load_delay_config()
        if cfg is not None:
            start_delay = cfg["start_delay"]
            print(
                f"[i] Беру стартовую задержку из конфига: {start_delay}s "
                f"(сохранён {cfg.get('updated', '?')})",
                file=sys.stderr,
            )
        else:
            start_delay = 0.1
            print(f"[i] Конфиг не найден, стартую с задержки по умолчанию: {start_delay}s", file=sys.stderr)

    limiter = AdaptiveRateLimiter(start_delay=start_delay, min_delay=args.min_delay)

    targets: list[tuple[str, str]] = []  # (region, slug)

    for p in args.players:
        if "/" not in p:
            print(f"[!] Пропускаю '{p}': ожидается формат region/slug", file=sys.stderr)
            continue
        region, slug = p.split("/", 1)
        targets.append((region.strip("/"), slug.strip("/")))

    if args.list_region:
        print(f"[i] Собираю список игроков региона '{args.list_region}'...", file=sys.stderr)
        slugs = list_region_slugs(session, args.list_region, limiter)
        print(f"[i] Всего найдено: {len(slugs)}", file=sys.stderr)
        targets.extend((args.list_region, s) for s in slugs)

    if args.all_regions:
        print("[i] Собираю всех игроков (общий список, все регионы)...", file=sys.stderr)
        pairs = list_all_slugs(session, limiter)
        print(f"[i] Всего найдено: {len(pairs)}", file=sys.stderr)
        targets.extend(pairs)

    if not targets:
        parser.print_help()
        sys.exit(1)

    results: list[PlayerData] = []
    for i, (region, slug) in enumerate(targets, 1):
        print(f"[{i}/{len(targets)}] Парсинг {region}/{slug} (задержка {limiter.delay:.3f}s) ...", file=sys.stderr)
        pdata = scrape_player(session, region, slug, limiter)
        if pdata:
            results.append(pdata)

    print(f"[i] {limiter.summary()}", file=sys.stderr)

    if not args.no_save_config:
        save_delay_config(limiter)

    if not results:
        print("[!] Не удалось получить данные ни по одному игроку.", file=sys.stderr)
        sys.exit(1)

    # Собираем все возможные названия скиллов и слотов экипировки для колонок CSV
    all_skills = sorted({k for r in results for k in r.skills})
    all_equip = sorted({k for r in results for k in r.equipment})

    fieldnames = [
        "slug", "region", "name", "level",
        "last_updated", "last_seen",
        "skills_count", "achievements_count", "achievement_points",
        "url",
    ] + [f"equip:{e}" for e in all_equip] + [f"skill:{s}" for s in all_skills]

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            row = {
                "slug": r.slug, "region": r.region, "name": r.name, "level": r.level,
                "last_updated": r.last_updated, "last_seen": r.last_seen,
                "skills_count": r.skills_count,
                "achievements_count": r.achievements_count,
                "achievement_points": r.achievement_points,
                "url": r.url,
            }
            for e in all_equip:
                row[f"equip:{e}"] = r.equipment.get(e, "")
            for s in all_skills:
                row[f"skill:{s}"] = r.skills.get(s, "")
            writer.writerow(row)

    print(f"[✓] Готово. Записано {len(results)} игроков в {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
