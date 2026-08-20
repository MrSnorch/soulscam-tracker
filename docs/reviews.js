/* Review Watch — no build step, no dependencies, plain SVG charts. */

// --- i18n ---------------------------------------------------------------
// Same dictionary-based approach as the main dashboard (docs/index.html):
// t(key, vars) looks up a string for the current language, substitutes
// {placeholders}, and falls back to Russian (then the raw key) if a
// translation is missing. Language choice is shared with the main
// dashboard via the same localStorage key, so switching on one page
// carries over to the other.
const I18N_STORAGE_KEY = 'soulscam-lang'; // 'ru' | 'en' - shared with index.html

const I18N = {
  ru: {
    'page.title': 'REVIEW WATCH — Steam review forensics',
    'page.description': 'Отслеживание накрутки и подозрительных отзывов Steam: анализ playtime, дубликатов текста и всплесков активности.',
    'header.subtitle': 'steam review forensics',
    'header.backLink': '&larr; назад к трекеру онлайна',
    'header.generatedAt': 'обновлено: {date}',
    'header.appid': 'appid {id}',
    'header.appidPlaceholder': 'appid (по умолчанию latest.json)',
    'header.openBtn': 'Открыть',
    'header.appidFormTitle': 'Просмотреть снапшот для другого appid, если он есть в docs/reviews/',
    'loading': 'Загружаю данные&hellip;',
    'error.loadFailed': 'Ошибка загрузки данных: {message}. Если это первый запуск &mdash; дождитесь первого прогона GitHub Actions, который создаст docs/reviews/latest.json.',
    'error.fetchFailed': 'Не удалось загрузить {path} (HTTP {status})',

    'crosscheck.title': 'Сверка с официальными данными Steam',
    'crosscheck.desc': 'Независимая проверка: то, что считает сам Steam по <b>всем</b> отзывам игры, а не только по собранной нами выборке. Если наша выборка сильно расходится с этим &mdash; значит либо сбор не полный, либо ситуация резко изменилась совсем недавно.',
    'crosscheck.totalSteam': 'Всего отзывов (Steam)',
    'crosscheck.coverage': 'Покрытие выборки',
    'crosscheck.coverageSub': 'собрано {sample} из {total}',
    'crosscheck.positive30d': '% позитива, последние 30д',
    'crosscheck.positive30dSub': 'по данным Steam, {count} отзывов',
    'crosscheck.velocity': 'Скорость отзывов, нед/нед',
    'crosscheck.velocitySub': '~{count} отзывов/день сейчас',
    'crosscheck.spikeDays': 'Дней-всплесков (Steam)',
    'crosscheck.spikeDaysSub': 'по официальной гистограмме',

    'histogram.title': 'Playtime lie-detector',
    'histogram.desc': 'Распределение &laquo;сколько часов было наиграно на момент отзыва&raquo; отдельно для положительных и отрицательных отзывов. Если у зелёной (позитив) кривой аномально много отзывов слева от порога &mdash; это и есть люди, хвалящие игру, в которую почти не играли.',
    'histogram.positive': 'Положительные',
    'histogram.negative': 'Отрицательные',
    'histogram.thresholdLabel': 'Порог подозрительности:',
    'histogram.thresholdMin': '{n} мин',
    'histogram.belowThreshold': '{count} позитивных отзывов ниже порога',
    'histogram.tooltipPositive': '{count} позитивных, {from}-{to} мин',
    'histogram.tooltipNegative': '{count} отрицательных, {from}-{to} мин',
    'histogram.axisHours': '{n}ч',
    'unit.min': '{n} мин',
    'unit.hours': '{n} ч',

    'history.title': 'История метрик по снапшотам',
    'history.desc': 'Как менялись % позитивных отзывов и число подозрительных с каждым запуском сбора данных. Полезно, чтобы увидеть момент начала накрутки, а не только текущее состояние.',
    'history.positivePct': '% позитивных',
    'history.suspiciousScore': 'Подозрительные (score&ge;40)',
    'history.tooltip': '{date}: {count} подозрительных, {pct}% позитив',

    'timeline.title': 'Динамика по дням',
    'timeline.desc': 'Всплески объёма &mdash; типичный признак ревью-бомбинга или скоординированной накрутки.',
    'timeline.tooltip': '{date}: {count} подозрительных',

    'reasons.title': 'Причины флагов',
    'reasons.desc': 'Из чего складывается suspicion score по датасету.',
    'reasons.none': 'Флагов не найдено',

    'table.title': 'Все отзывы',
    'table.desc': 'Полная таблица с фильтрами и сортировкой. Клик по строке &mdash; разворачивает текст и метаданные.',
    'table.exportCsv': 'Экспорт CSV (текущий фильтр)',
    'table.colDate': 'Дата',
    'table.colType': 'Тип',
    'table.colPlaytime': 'Playtime',
    'table.colScore': 'Score',
    'table.colFlags': 'Флаги',
    'table.colText': 'Текст',
    'table.resultCount': '<b>{count}</b> отзывов найдено (из {total} всего)',
    'table.empty': 'Ничего не найдено под текущие фильтры',
    'table.pagePrev': '&larr; назад',
    'table.pageNext': 'вперёд &rarr;',
    'table.pageOf': 'стр. {page} / {total}',
    'table.votePositive': '&#9650; Позитив',
    'table.voteNegative': '&#9660; Негатив',
    'table.noFlags': '&mdash;',
    'table.emptyText': '(пустой текст)',
    'table.noReasons': 'без флагов',
    'table.devReplyDate': ' ({date})',
    'table.devReplyLabel': '&#128172; Ответ разработчика{date}',
    'table.gamesOwned': 'игр в библиотеке: {n}',
    'table.reviewsByAuthor': 'отзывов от автора: {n}',
    'table.viaSteam': 'куплено в Steam: {v}',
    'table.gotFree': 'получено бесплатно: {v}',
    'table.yes': 'да',
    'table.no': 'нет',
    'table.votesUpFunny': 'votes up / funny: {up} / {funny}',
    'table.language': 'язык: {lang}',
    'table.openInSteam': '&#8599; открыть отзыв в Steam',
    'table.nickname': 'ник: {name}',
    'table.playtimeForever': 'playtime forever: {v}',
    'table.playtimeAtReview': 'playtime at review: {v}',
    'table.playtime2w': 'playtime last 2 weeks: {v}',

    'filters.type': 'Тип',
    'filters.all': 'Все',
    'filters.positive': 'Позитив',
    'filters.negative': 'Негатив',
    'filters.playtimeBucket': 'Playtime bucket',
    'filters.any': 'Любой',
    'filters.minScore': 'Мин. suspicion score',
    'filters.onlyLabel': 'Только',
    'filters.suspiciousOnly': '&#128681; Подозрительные',
    'filters.freeOnly': 'Free key',
    'filters.dupeOnly': 'Дубли текста',
    'filters.editedOnly': 'Отредактировано позже',
    'filters.devResponseOnly': '&#128172; Есть ответ разработчика',
    'filters.searchLabel': 'Поиск по тексту',
    'filters.searchPlaceholder': 'подстрока&hellip;',
    'filters.searchNickLabel': 'Поиск по нику',
    'filters.searchNickPlaceholder': 'ник или steamid&hellip;',
    'filters.devResponseDate': 'Дата ответа разработчика',
    'filters.reset': 'сбросить фильтры',

    'stats.totalReviews': 'Всего отзывов',
    'stats.totalReviewsSub': '{pct}% положительных',
    'stats.posNeg': 'Positive / Negative',
    'stats.playtimePositive': 'Playtime, позитив',
    'stats.playtimeNegative': 'Playtime, негатив',
    'stats.medianSub': 'медиана {n}ч',
    'stats.suspicious': 'Подозрительные',
    'stats.suspiciousSub': '{pct}% от позитивных',
    'stats.highlySuspicious': 'Сильно подозрительные',
    'stats.highlySuspiciousSub': 'score &ge; 60',
    'stats.devResponse': 'С ответом разработчика',
    'stats.devResponseSub': '{pct}% от всех',
    'stats.newAccounts': 'Новые аккаунты (позитив, <7д)',
    'stats.newAccountsSub': 'из {n} обогащённых',
    'stats.privateProfiles': 'Приватные профили',
    'stats.editedLater': 'Отредактировано позже',
    'stats.editedLaterSub': 'возможна смена позиции',

    'footer.text': 'Данные собираются автоматически из публичного Steam appreviews API по расписанию GitHub Actions. Suspicion score &mdash; эвристика (playtime на момент отзыва, free-ключи, повторяющийся текст, всплески активности, паттерны аккаунта), а не доказательство накрутки: проверяйте отмеченные отзывы вручную.',
    'footer.repoLink': 'Исходники и скрипты сбора данных на GitHub',

    'reason.positive_zero_playtime': 'позитив, 0 часов наиграно',
    'reason.positive_under_30min': 'позитив, <30 мин на момент отзыва',
    'reason.positive_under_1h': 'позитив, <1ч на момент отзыва',
    'reason.free_key_not_purchased': 'бесплатный ключ, не куплено в Steam',
    'reason.prolific_reviewer_few_games': 'много отзывов, мало игр в библиотеке',
    'reason.duplicate_text_cluster': 'повторяющийся/шаблонный текст',
    'reason.posted_during_review_burst': 'опубликовано во время всплеска активности',
    'reason.negative_zero_playtime': 'негатив, 0 часов наиграно',
    'reason.edited_days_later': 'отзыв отредактирован спустя дни (возможна смена позиции)',
    'reason.account_under_7d_old_at_review': 'аккаунту < 7 дней на момент отзыва',
    'reason.account_under_30d_old_at_review': 'аккаунту < 30 дней на момент отзыва',
    'reason.private_profile': 'приватный профиль',
    'reason.owns_2_or_fewer_games_total': 'во всей библиотеке &le;2 игры',
    'reason.low_effort_text': 'низкосодержательный текст',
    'reason.high_votes_low_effort_text': 'много votes при пустом тексте',
  },
  en: {
    'page.title': 'REVIEW WATCH — Steam review forensics',
    'page.description': 'Tracking Steam review manipulation and suspicious reviews: playtime analysis, duplicate text, and activity spikes.',
    'header.subtitle': 'steam review forensics',
    'header.backLink': '&larr; back to online tracker',
    'header.generatedAt': 'updated: {date}',
    'header.appid': 'appid {id}',
    'header.appidPlaceholder': 'appid (defaults to latest.json)',
    'header.openBtn': 'Open',
    'header.appidFormTitle': 'View a snapshot for a different appid, if one exists in docs/reviews/',
    'loading': 'Loading data&hellip;',
    'error.loadFailed': 'Failed to load data: {message}. If this is the first run &mdash; wait for the first GitHub Actions run, which will create docs/reviews/latest.json.',
    'error.fetchFailed': 'Failed to load {path} (HTTP {status})',

    'crosscheck.title': "Cross-check against Steam's official data",
    'crosscheck.desc': "Independent check: what Steam itself counts across <b>all</b> of the game's reviews, not just our collected sample. If our sample diverges sharply from this &mdash; either the collection isn't complete, or the situation changed very recently.",
    'crosscheck.totalSteam': 'Total reviews (Steam)',
    'crosscheck.coverage': 'Sample coverage',
    'crosscheck.coverageSub': 'collected {sample} of {total}',
    'crosscheck.positive30d': '% positive, last 30d',
    'crosscheck.positive30dSub': 'per Steam, {count} reviews',
    'crosscheck.velocity': 'Review velocity, w/w',
    'crosscheck.velocitySub': '~{count} reviews/day now',
    'crosscheck.spikeDays': 'Spike days (Steam)',
    'crosscheck.spikeDaysSub': 'per the official histogram',

    'histogram.title': 'Playtime lie-detector',
    'histogram.desc': 'Distribution of "hours played at time of review", separately for positive and negative reviews. If the green (positive) curve has an unusually high pile-up left of the threshold &mdash; those are people praising a game they barely played.',
    'histogram.positive': 'Positive',
    'histogram.negative': 'Negative',
    'histogram.thresholdLabel': 'Suspicion threshold:',
    'histogram.thresholdMin': '{n} min',
    'histogram.belowThreshold': '{count} positive reviews below the threshold',
    'histogram.tooltipPositive': '{count} positive, {from}-{to} min',
    'histogram.tooltipNegative': '{count} negative, {from}-{to} min',
    'histogram.axisHours': '{n}h',
    'unit.min': '{n} min',
    'unit.hours': '{n}h',

    'history.title': 'Metrics history across snapshots',
    'history.desc': 'How the % positive and suspicious count changed with each data-collection run. Useful for spotting when manipulation started, not just the current state.',
    'history.positivePct': '% positive',
    'history.suspiciousScore': 'Suspicious (score&ge;40)',
    'history.tooltip': '{date}: {count} suspicious, {pct}% positive',

    'timeline.title': 'Daily activity',
    'timeline.desc': 'Volume spikes are a typical sign of review-bombing or a coordinated campaign.',
    'timeline.tooltip': '{date}: {count} suspicious',

    'reasons.title': 'Flag reasons',
    'reasons.desc': "What the dataset's suspicion score is made up of.",
    'reasons.none': 'No flags found',

    'table.title': 'All reviews',
    'table.desc': 'Full table with filters and sorting. Click a row to expand its text and metadata.',
    'table.exportCsv': 'Export CSV (current filter)',
    'table.colDate': 'Date',
    'table.colType': 'Type',
    'table.colPlaytime': 'Playtime',
    'table.colScore': 'Score',
    'table.colFlags': 'Flags',
    'table.colText': 'Text',
    'table.resultCount': '<b>{count}</b> reviews found (of {total} total)',
    'table.empty': 'Nothing matches the current filters',
    'table.pagePrev': '&larr; prev',
    'table.pageNext': 'next &rarr;',
    'table.pageOf': 'page {page} / {total}',
    'table.votePositive': '&#9650; Positive',
    'table.voteNegative': '&#9660; Negative',
    'table.noFlags': '&mdash;',
    'table.emptyText': '(empty text)',
    'table.noReasons': 'no flags',
    'table.devReplyDate': ' ({date})',
    'table.devReplyLabel': '&#128172; Developer response{date}',
    'table.gamesOwned': 'games owned: {n}',
    'table.reviewsByAuthor': "reviews by author: {n}",
    'table.viaSteam': 'purchased on Steam: {v}',
    'table.gotFree': 'received for free: {v}',
    'table.yes': 'yes',
    'table.no': 'no',
    'table.votesUpFunny': 'votes up / funny: {up} / {funny}',
    'table.language': 'language: {lang}',
    'table.openInSteam': '&#8599; open review on Steam',
    'table.nickname': 'nickname: {name}',
    'table.playtimeForever': 'playtime forever: {v}',
    'table.playtimeAtReview': 'playtime at review: {v}',
    'table.playtime2w': 'playtime last 2 weeks: {v}',

    'filters.type': 'Type',
    'filters.all': 'All',
    'filters.positive': 'Positive',
    'filters.negative': 'Negative',
    'filters.playtimeBucket': 'Playtime bucket',
    'filters.any': 'Any',
    'filters.minScore': 'Min. suspicion score',
    'filters.onlyLabel': 'Only',
    'filters.suspiciousOnly': '&#128681; Suspicious',
    'filters.freeOnly': 'Free key',
    'filters.dupeOnly': 'Duplicate text',
    'filters.editedOnly': 'Edited later',
    'filters.devResponseOnly': '&#128172; Has dev response',
    'filters.searchLabel': 'Search text',
    'filters.searchPlaceholder': 'substring&hellip;',
    'filters.searchNickLabel': 'Search by nickname',
    'filters.searchNickPlaceholder': 'nickname or steamid&hellip;',
    'filters.devResponseDate': 'Developer response date',
    'filters.reset': 'reset filters',

    'stats.totalReviews': 'Total reviews',
    'stats.totalReviewsSub': '{pct}% positive',
    'stats.posNeg': 'Positive / Negative',
    'stats.playtimePositive': 'Playtime, positive',
    'stats.playtimeNegative': 'Playtime, negative',
    'stats.medianSub': 'median {n}h',
    'stats.suspicious': 'Suspicious',
    'stats.suspiciousSub': '{pct}% of positive',
    'stats.highlySuspicious': 'Highly suspicious',
    'stats.highlySuspiciousSub': 'score &ge; 60',
    'stats.devResponse': 'With dev response',
    'stats.devResponseSub': '{pct}% of all',
    'stats.newAccounts': 'New accounts (positive, <7d)',
    'stats.newAccountsSub': 'of {n} enriched',
    'stats.privateProfiles': 'Private profiles',
    'stats.editedLater': 'Edited later',
    'stats.editedLaterSub': 'position may have changed',

    'footer.text': "Data is collected automatically from Steam's public appreviews API on a GitHub Actions schedule. Suspicion score is a heuristic (playtime at time of review, free keys, repeated text, activity spikes, account patterns), not proof of manipulation: check flagged reviews manually.",
    'footer.repoLink': 'Source code and data-collection scripts on GitHub',

    'reason.positive_zero_playtime': 'positive, 0 hours played',
    'reason.positive_under_30min': 'positive, <30 min at time of review',
    'reason.positive_under_1h': 'positive, <1h at time of review',
    'reason.free_key_not_purchased': 'free key, not purchased on Steam',
    'reason.prolific_reviewer_few_games': 'many reviews, few games owned',
    'reason.duplicate_text_cluster': 'repeated/template text',
    'reason.posted_during_review_burst': 'posted during an activity burst',
    'reason.negative_zero_playtime': 'negative, 0 hours played',
    'reason.edited_days_later': 'review edited days later (position may have changed)',
    'reason.account_under_7d_old_at_review': 'account < 7 days old at time of review',
    'reason.account_under_30d_old_at_review': 'account < 30 days old at time of review',
    'reason.private_profile': 'private profile',
    'reason.owns_2_or_fewer_games_total': '&le;2 games owned total',
    'reason.low_effort_text': 'low-effort text',
    'reason.high_votes_low_effort_text': 'many votes, empty text',
  },
};

function getLang() {
  try {
    const stored = localStorage.getItem(I18N_STORAGE_KEY);
    return stored === 'en' ? 'en' : 'ru';
  } catch (e) {
    return 'ru';
  }
}
function setLang(lang) {
  try { localStorage.setItem(I18N_STORAGE_KEY, lang); } catch (e) { /* ignore */ }
}
function t(key, vars) {
  const dict = I18N[getLang()] || I18N.ru;
  let str = dict[key];
  if (str == null) str = I18N.ru[key];
  if (str == null) return key;
  if (vars) {
    Object.keys(vars).forEach(k => {
      str = str.split('{' + k + '}').join(vars[k]);
    });
  }
  return str;
}
function reasonLabel(key) {
  const label = t('reason.' + key);
  return label === 'reason.' + key ? key : label;
}
function applyStaticTranslations() {
  document.title = t('page.title');
  document.querySelectorAll('[data-i18n]').forEach(el => {
    el.textContent = t(el.getAttribute('data-i18n'));
  });
  document.querySelectorAll('[data-i18n-html]').forEach(el => {
    el.innerHTML = t(el.getAttribute('data-i18n-html'));
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    el.setAttribute('placeholder', t(el.getAttribute('data-i18n-placeholder')));
  });
  document.querySelectorAll('[data-i18n-title]').forEach(el => {
    el.setAttribute('title', t(el.getAttribute('data-i18n-title')));
  });
  const desc = document.querySelector('meta[name="description"]');
  if (desc) desc.setAttribute('content', t('page.description'));
  document.documentElement.lang = getLang();
}

const state = {
  data: null,
  reviews: [],
  filtered: [],
  sortKey: 'timestamp_created',
  sortDir: 'desc',
  page: 1,
  pageSize: 50,
  threshold: 60, // minutes
  filters: {
    vote: new Set(['all', 'up', 'down']),
    bucket: '',
    minScore: 0,
    suspiciousOnly: false,
    freeOnly: false,
    dupeOnly: false,
    editedOnly: false,
    devResponseOnly: false,
    devResponseFrom: '',
    devResponseTo: '',
    search: '',
    searchNick: '',
  },
};

const PLAYTIME_BUCKET_ORDER = ['<1h', '1-5h', '5-20h', '20-100h', '100h+'];

function fmtHours(minutes) {
  if (minutes === null || minutes === undefined) return '—';
  const h = minutes / 60;
  if (h < 1) return t('unit.min', { n: Math.round(minutes) });
  return t('unit.hours', { n: h.toFixed(1) });
}

function fmtDate(ts) {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  return d.toISOString().slice(0, 10);
}

function escapeHtml(s) {
  if (!s) return '';
  return s.replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

async function loadData(appid) {
  const path = appid ? `reviews/${appid}.json` : 'reviews/latest.json';
  const res = await fetch(path, { cache: 'no-store' });
  if (!res.ok) throw new Error(t('error.fetchFailed', { path, status: res.status }));
  return res.json();
}

async function loadHistory() {
  try {
    const res = await fetch('reviews/snapshots/history.json', { cache: 'no-store' });
    if (!res.ok) return null;
    const hist = await res.json();
    return Array.isArray(hist) && hist.length >= 2 ? hist : null;
  } catch {
    return null;
  }
}

function init() {
  applyStaticTranslations();

  const langButtons = document.querySelectorAll('#lang-toggle .lang-btn');
  function syncLangButtons() {
    const lang = getLang();
    langButtons.forEach(b => b.classList.toggle('active', b.dataset.mode === lang));
  }
  langButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      if (btn.dataset.mode === getLang()) return;
      setLang(btn.dataset.mode);
      // A full reload is simplest and safest here: this page renders many
      // independent SVG charts and a large filtered/sorted/paginated table
      // built directly from state, and re-running every render function in
      // place risks missing one and leaving stale text behind. A reload
      // re-fetches nothing new (browser cache handles the JSON) and takes
      // a fraction of a second, so the extra round-trip isn't noticeable.
      location.reload();
    });
  });
  syncLangButtons();

  const params = new URLSearchParams(location.search);
  const appidParam = params.get('appid');
  if (appidParam) document.getElementById('appid-input').value = appidParam;

  loadData(appidParam)
    .then(data => {
      state.data = data;
      state.reviews = data.reviews || [];
      document.getElementById('loading').style.display = 'none';
      document.getElementById('content').style.display = 'block';
      renderHeader(data);
      applyFiltersAndRender();
      bindControls();
      renderSteamCrossCheck(data.summary);
      loadHistory().then(hist => {
        if (hist) {
          document.getElementById('history-panel').style.display = 'block';
          renderHistory(hist);
        }
      });
    })
    .catch(err => {
      document.getElementById('loading').style.display = 'none';
      const el = document.getElementById('error');
      el.style.display = 'block';
      el.innerHTML = t('error.loadFailed', { message: err.message });
    });

  document.getElementById('appid-form').addEventListener('submit', e => {
    e.preventDefault();
    const v = document.getElementById('appid-input').value.trim();
    const url = new URL(location.href);
    if (v) url.searchParams.set('appid', v); else url.searchParams.delete('appid');
    location.href = url.toString();
  });
}

function renderHeader(data) {
  document.getElementById('appname-sub').textContent = data.appname
    ? `${data.appname} — ${t('header.subtitle')}`
    : t('header.subtitle');
  document.getElementById('appid-line').textContent = t('header.appid', { id: data.appid });
  document.getElementById('generated-at').textContent = t('header.generatedAt', { date: data.generated_at });
  const repoLink = document.getElementById('repo-link');
  // leave default href as-is; user should point this at their own repo
}

function renderStats(summary) {
  const grid = document.getElementById('stats-grid');
  const items = [
    {
      label: t('stats.totalReviews'), value: summary.total_reviews, cls: '',
      sub: t('stats.totalReviewsSub', { pct: summary.positive_pct }),
    },
    {
      label: t('stats.posNeg'), value: `${summary.positive_count} / ${summary.negative_count}`, cls: 'green',
      sub: '',
    },
    {
      label: t('stats.playtimePositive'), value: t('unit.hours', { n: summary.avg_playtime_hours_positive }), cls: 'green',
      sub: t('stats.medianSub', { n: summary.median_playtime_hours_positive }),
    },
    {
      label: t('stats.playtimeNegative'), value: t('unit.hours', { n: summary.avg_playtime_hours_negative }), cls: 'red',
      sub: t('stats.medianSub', { n: summary.median_playtime_hours_negative }),
    },
    {
      label: t('stats.suspicious'), value: summary.suspicious_count, cls: 'red',
      sub: t('stats.suspiciousSub', { pct: summary.suspicious_pct_of_positive }),
    },
    {
      label: t('stats.highlySuspicious'), value: summary.highly_suspicious_count, cls: 'amber',
      sub: t('stats.highlySuspiciousSub'),
    },
    {
      label: t('stats.devResponse'), value: summary.dev_response_count || 0, cls: 'green',
      sub: summary.total_reviews ? t('stats.devResponseSub', { pct: Math.round(100 * (summary.dev_response_count || 0) / summary.total_reviews) }) : '',
    },
  ];

  if (summary.enrichment_coverage) {
    items.push(
      {
        label: t('stats.newAccounts'), value: summary.new_accounts_positive_under_7d || 0, cls: 'red',
        sub: t('stats.newAccountsSub', { n: summary.enrichment_coverage }),
      },
      {
        label: t('stats.privateProfiles'), value: summary.private_profile_count || 0, cls: 'amber',
        sub: '',
      },
      {
        label: t('stats.editedLater'), value: summary.edited_review_later_count || 0, cls: 'amber',
        sub: t('stats.editedLaterSub'),
      },
    );
  }
  grid.innerHTML = items.map(it => `
    <div class="stat">
      <div class="label">${it.label}</div>
      <div class="value ${it.cls}">${it.value}</div>
      ${it.sub ? `<div class="sub">${it.sub}</div>` : ''}
    </div>
  `).join('');
}

function renderSteamCrossCheck(summary) {
  if (!summary.steam_official_total_reviews) return; // fetch_steam_summary.py didn't run
  document.getElementById('steam-crosscheck-panel').style.display = 'block';
  const grid = document.getElementById('steam-crosscheck-grid');

  const velocity = summary.steam_velocity_change_pct_week_over_week;
  const velocityCls = velocity > 20 ? 'red' : (velocity < -20 ? 'green' : '');
  const velocitySign = velocity > 0 ? '+' : '';

  const items = [
    {
      label: t('crosscheck.totalSteam'), value: summary.steam_official_total_reviews, cls: '',
      sub: summary.steam_official_review_score_desc || '',
    },
    {
      label: t('crosscheck.coverage'), value: `${summary.our_sample_coverage_pct ?? '—'}%`, cls: '',
      sub: t('crosscheck.coverageSub', { sample: summary.total_reviews, total: summary.steam_official_total_reviews }),
    },
    {
      label: t('crosscheck.positive30d'), value: `${summary.steam_recent_30d_positive_pct ?? '—'}%`, cls: '',
      sub: t('crosscheck.positive30dSub', { count: summary.steam_recent_30d_total_reviews ?? '—' }),
    },
    {
      label: t('crosscheck.velocity'), value: `${velocitySign}${velocity ?? '—'}%`, cls: velocityCls,
      sub: t('crosscheck.velocitySub', { count: summary.steam_avg_reviews_per_day_last_7d ?? '—' }),
    },
    {
      label: t('crosscheck.spikeDays'), value: summary.steam_spike_days_count ?? 0,
      cls: summary.steam_spike_days_count > 0 ? 'red' : '',
      sub: t('crosscheck.spikeDaysSub'),
    },
  ];

  grid.innerHTML = items.map(it => `
    <div class="stat">
      <div class="label">${it.label}</div>
      <div class="value ${it.cls}">${it.value}</div>
      ${it.sub ? `<div class="sub">${it.sub}</div>` : ''}
    </div>
  `).join('');
}

/* ---------------- Histogram (signature chart) ---------------- */

function computeHistogramBins(reviews, binSizeMin = 30, maxMin = 600) {
  const nBins = Math.ceil(maxMin / binSizeMin);
  const pos = new Array(nBins).fill(0);
  const neg = new Array(nBins).fill(0);
  for (const r of reviews) {
    const m = Math.min(r.playtime_at_review || 0, maxMin - 1);
    const bin = Math.floor(m / binSizeMin);
    if (r.voted_up) pos[bin]++; else neg[bin]++;
  }
  return { pos, neg, binSizeMin, nBins };
}

function renderHistogram(reviews, thresholdMin) {
  const svg = document.getElementById('histogram');
  const { pos, neg, binSizeMin, nBins } = computeHistogramBins(reviews);
  const W = 900, H = 280, padL = 36, padB = 24, padT = 10, padR = 10;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;
  const maxVal = Math.max(1, ...pos, ...neg);
  const barW = plotW / nBins;

  let bars = '';
  for (let i = 0; i < nBins; i++) {
    const x = padL + i * barW;
    const hPos = (pos[i] / maxVal) * plotH;
    const hNeg = (neg[i] / maxVal) * plotH;
    const yPos = padT + plotH - hPos;
    const yNeg = padT + plotH - hNeg;
    bars += `<rect x="${x}" y="${yPos}" width="${barW * 0.42}" height="${hPos}" fill="var(--green)" opacity="0.85"><title>${t('histogram.tooltipPositive', { count: pos[i], from: i * binSizeMin, to: (i + 1) * binSizeMin })}</title></rect>`;
    bars += `<rect x="${x + barW * 0.46}" y="${yNeg}" width="${barW * 0.42}" height="${hNeg}" fill="var(--red)" opacity="0.85"><title>${t('histogram.tooltipNegative', { count: neg[i], from: i * binSizeMin, to: (i + 1) * binSizeMin })}</title></rect>`;
  }

  // axis labels every ~2 hours
  let labels = '';
  for (let i = 0; i <= nBins; i += Math.round(120 / binSizeMin)) {
    const x = padL + i * barW;
    const hrs = Math.round((i * binSizeMin) / 60);
    labels += `<text x="${x}" y="${H - 6}" fill="var(--text-dimmer)" font-family="var(--mono)" font-size="10">${t('histogram.axisHours', { n: hrs })}</text>`;
  }

  const threshX = padL + (thresholdMin / binSizeMin) * barW;
  const thresholdLine = `<line x1="${threshX}" y1="${padT}" x2="${threshX}" y2="${padT + plotH}" stroke="var(--amber)" stroke-width="1.5" stroke-dasharray="4,3"/>`;

  const gridLines = [0.25, 0.5, 0.75, 1].map(f => {
    const y = padT + plotH * (1 - f);
    return `<line x1="${padL}" y1="${y}" x2="${W - padR}" y2="${y}" stroke="var(--border)" stroke-width="1"/>`;
  }).join('');

  svg.innerHTML = `${gridLines}${bars}${thresholdLine}${labels}`;
}

/* ---------------- Timeline chart ---------------- */

function renderTimeline(timeline) {
  const svg = document.getElementById('timeline');
  if (!timeline || !timeline.length) { svg.innerHTML = ''; return; }
  const W = 560, H = 220, padL = 30, padB = 20, padT = 10, padR = 10;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;
  const n = timeline.length;
  const maxVal = Math.max(1, ...timeline.map(d => d.positive + d.negative));
  const stepX = n > 1 ? plotW / (n - 1) : 0;

  function pathFor(getter, color) {
    let d = '';
    timeline.forEach((pt, i) => {
      const x = padL + i * stepX;
      const y = padT + plotH - (getter(pt) / maxVal) * plotH;
      d += (i === 0 ? 'M' : 'L') + x.toFixed(1) + ',' + y.toFixed(1) + ' ';
    });
    return `<path d="${d}" fill="none" stroke="${color}" stroke-width="1.6"/>`;
  }

  const suspiciousDots = timeline.map((pt, i) => {
    if (!pt.suspicious) return '';
    const x = padL + i * stepX;
    const y = padT + plotH - ((pt.positive + pt.negative) / maxVal) * plotH;
    const r = Math.min(2 + pt.suspicious * 0.6, 8);
    return `<circle cx="${x}" cy="${y}" r="${r}" fill="var(--red)" opacity="0.55"><title>${t('timeline.tooltip', { date: pt.date, count: pt.suspicious })}</title></circle>`;
  }).join('');

  const gridLines = [0.5, 1].map(f => {
    const y = padT + plotH * (1 - f);
    return `<line x1="${padL}" y1="${y}" x2="${W - padR}" y2="${y}" stroke="var(--border)" stroke-width="1"/>`;
  }).join('');

  const firstLabel = timeline[0].date;
  const lastLabel = timeline[n - 1].date;

  svg.innerHTML = `
    ${gridLines}
    ${pathFor(d => d.positive, 'var(--green)')}
    ${pathFor(d => d.negative, 'var(--red)')}
    ${suspiciousDots}
    <text x="${padL}" y="${H - 4}" fill="var(--text-dimmer)" font-family="var(--mono)" font-size="10">${firstLabel}</text>
    <text x="${W - padR}" y="${H - 4}" fill="var(--text-dimmer)" font-family="var(--mono)" font-size="10" text-anchor="end">${lastLabel}</text>
  `;
}

/* ---------------- History chart (across snapshot runs) ---------------- */

function renderHistory(history) {
  const svg = document.getElementById('history-chart');
  const W = 900, H = 220, padL = 40, padR = 40, padT = 10, padB = 24;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;
  const n = history.length;
  const stepX = n > 1 ? plotW / (n - 1) : 0;

  const maxSuspicious = Math.max(1, ...history.map(d => d.suspicious_count || 0));

  function pathFor(getter, maxVal, color, dashed) {
    let d = '';
    history.forEach((pt, i) => {
      const x = padL + i * stepX;
      const v = getter(pt);
      const y = padT + plotH - (v == null ? 0 : (v / maxVal) * plotH);
      d += (i === 0 ? 'M' : 'L') + x.toFixed(1) + ',' + y.toFixed(1) + ' ';
    });
    return `<path d="${d}" fill="none" stroke="${color}" stroke-width="1.8" ${dashed ? 'stroke-dasharray="5,4"' : ''}/>`;
  }

  const dots = history.map((pt, i) => {
    const x = padL + i * stepX;
    const y = padT + plotH - ((pt.suspicious_count || 0) / maxSuspicious) * plotH;
    return `<circle cx="${x}" cy="${y}" r="2.5" fill="var(--red)"><title>${t('history.tooltip', { date: pt.date, count: pt.suspicious_count, pct: pt.positive_pct })}</title></circle>`;
  }).join('');

  const gridLines = [0.25, 0.5, 0.75, 1].map(f => {
    const y = padT + plotH * (1 - f);
    return `<line x1="${padL}" y1="${y}" x2="${W - padR}" y2="${y}" stroke="var(--border)" stroke-width="1"/>`;
  }).join('');

  svg.innerHTML = `
    ${gridLines}
    ${pathFor(d => d.positive_pct, 100, 'var(--green)', false)}
    ${pathFor(d => d.suspicious_count, maxSuspicious, 'var(--red)', true)}
    ${dots}
    <text x="${padL}" y="${H - 4}" fill="var(--text-dimmer)" font-family="var(--mono)" font-size="10">${history[0].date}</text>
    <text x="${W - padR}" y="${H - 4}" fill="var(--text-dimmer)" font-family="var(--mono)" font-size="10" text-anchor="end">${history[n - 1].date}</text>
    <text x="${padL}" y="${padT + 4}" fill="var(--text-dimmer)" font-family="var(--mono)" font-size="10">100%</text>
    <text x="${padL}" y="${padT + plotH}" fill="var(--text-dimmer)" font-family="var(--mono)" font-size="10">0%</text>
  `;
}

/* ---------------- Reasons bar chart ---------------- */

function renderReasons(reasonCounts) {
  const svg = document.getElementById('reasons');
  const entries = Object.entries(reasonCounts || {}).sort((a, b) => b[1] - a[1]).slice(0, 8);
  if (!entries.length) { svg.innerHTML = `<text x="10" y="20" fill="var(--text-dim)" font-family="var(--mono)" font-size="12">${t('reasons.none')}</text>`; return; }
  const W = 560, H = 220, padL = 10, padR = 60, rowH = H / entries.length;
  const maxVal = Math.max(...entries.map(e => e[1]));

  let bars = '';
  entries.forEach(([key, count], i) => {
    const y = i * rowH + rowH * 0.2;
    const barH = rowH * 0.5;
    const barW = ((count / maxVal) * (W - padL - padR - 140));
    const label = reasonLabel(key);
    bars += `
      <text x="0" y="${y + barH * 0.75}" fill="var(--text-dim)" font-family="var(--mono)" font-size="10.5">${escapeHtml(label)}</text>
      <rect x="140" y="${y}" width="${Math.max(barW, 2)}" height="${barH}" fill="var(--red)" opacity="0.75"/>
      <text x="${140 + barW + 8}" y="${y + barH * 0.75}" fill="var(--text)" font-family="var(--mono)" font-size="11" font-weight="700">${count}</text>
    `;
  });
  svg.innerHTML = bars;
}

/* ---------------- Filtering / sorting ---------------- */

function passesFilters(r) {
  const f = state.filters;

  if (!f.vote.has('all')) {
    if (r.voted_up && !f.vote.has('up')) return false;
    if (!r.voted_up && !f.vote.has('down')) return false;
  }
  if (f.bucket && r.playtime_bucket !== f.bucket) return false;
  if (f.minScore && (r.suspicion_score || 0) < f.minScore) return false;
  if (f.suspiciousOnly && (r.suspicion_score || 0) < 40) return false;
  if (f.freeOnly && !r.received_for_free) return false;
  if (f.dupeOnly && (!r.duplicate_cluster_size || r.duplicate_cluster_size < 2)) return false;
  if (f.editedOnly && !(r.suspicion_reasons || []).includes('edited_days_later')) return false;
  if (f.devResponseOnly && !r.developer_response) return false;
  if (f.devResponseFrom || f.devResponseTo) {
    if (!r.developer_response || !r.timestamp_dev_responded) return false;
    const day = fmtDate(r.timestamp_dev_responded); // 'YYYY-MM-DD' string, sortable
    if (f.devResponseFrom && day < f.devResponseFrom) return false;
    if (f.devResponseTo && day > f.devResponseTo) return false;
  }
  if (f.search) {
    const s = f.search.toLowerCase();
    if (!(r.review || '').toLowerCase().includes(s)) return false;
  }
  if (f.searchNick) {
    const s = f.searchNick.toLowerCase();
    const nick = (r.personaname || '').toLowerCase();
    const sid = (r.steamid || '').toLowerCase();
    if (!nick.includes(s) && !sid.includes(s)) return false;
  }
  return true;
}

function sortReviews(list) {
  const { sortKey, sortDir } = state;
  const mul = sortDir === 'asc' ? 1 : -1;
  return [...list].sort((a, b) => {
    let va = a[sortKey], vb = b[sortKey];
    if (sortKey === 'voted_up') { va = va ? 1 : 0; vb = vb ? 1 : 0; }
    if (va === undefined || va === null) va = -Infinity;
    if (vb === undefined || vb === null) vb = -Infinity;
    if (va < vb) return -1 * mul;
    if (va > vb) return 1 * mul;
    return 0;
  });
}

function applyFiltersAndRender() {
  state.filtered = sortReviews(state.reviews.filter(passesFilters));
  state.page = 1;
  renderStats(state.data.summary);
  renderHistogram(state.reviews, state.threshold);
  renderTimeline(state.data.timeline);
  renderReasons(state.data.summary.suspicion_reason_counts);
  renderTable();
  updateThresholdCount();
}

function updateThresholdCount() {
  const count = state.reviews.filter(r => r.voted_up && (r.playtime_at_review || 0) < state.threshold).length;
  document.getElementById('threshold-count').textContent = t('histogram.belowThreshold', { count });
}

/* ---------------- Table rendering ---------------- */

function renderTable() {
  const tbody = document.getElementById('table-body');
  const total = state.filtered.length;
  const totalPages = Math.max(1, Math.ceil(total / state.pageSize));
  state.page = Math.min(state.page, totalPages);
  const start = (state.page - 1) * state.pageSize;
  const pageItems = state.filtered.slice(start, start + state.pageSize);

  document.getElementById('result-count').innerHTML = t('table.resultCount', { count: total, total: state.reviews.length });

  if (!pageItems.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty">${t('table.empty')}</td></tr>`;
  } else {
    tbody.innerHTML = pageItems.map(r => rowHtml(r)).join('');
  }

  renderPagination(totalPages);
  bindRowClicks();

  // update sort arrows
  document.querySelectorAll('th[data-sort]').forEach(th => {
    th.classList.toggle('sorted', th.dataset.sort === state.sortKey);
    th.querySelector('.arrow').textContent = th.dataset.sort === state.sortKey
      ? (state.sortDir === 'asc' ? '▲' : '▼') : '';
  });
}

function rowHtml(r) {
  const flagged = (r.suspicion_score || 0) >= 40;
  const tags = [];
  if (r.received_for_free) tags.push('<span class="tag free">FREE KEY</span>');
  if (r.duplicate_cluster_size >= 3) tags.push(`<span class="tag">DUPE×${r.duplicate_cluster_size}</span>`);
  if ((r.suspicion_reasons || []).includes('posted_during_review_burst')) tags.push('<span class="tag">BURST</span>');
  if ((r.suspicion_reasons || []).includes('prolific_reviewer_few_games')) tags.push('<span class="tag">FARM?</span>');
  if ((r.suspicion_reasons || []).includes('edited_days_later')) tags.push('<span class="tag">EDITED</span>');
  if (r.developer_response) tags.push('<span class="tag" style="color:var(--green);border-color:var(--green-dim);">💬 DEV REPLY</span>');

  return `
    <tr class="${flagged ? 'flagged' : ''}" data-rid="${r.recommendationid}">
      <td class="td-date">${fmtDate(r.timestamp_created)}</td>
      <td><span class="td-vote ${r.voted_up ? 'up' : 'down'}">${r.voted_up ? t('table.votePositive') : t('table.voteNegative')}</span></td>
      <td class="td-playtime">${fmtHours(r.playtime_at_review)}<span class="bucket">${r.playtime_bucket || ''}</span></td>
      <td class="td-score">
        <span class="score-bar"><i style="width:${r.suspicion_score || 0}%"></i></span>${r.suspicion_score || 0}
      </td>
      <td>${tags.join('') || '—'}</td>
      <td class="td-text">${escapeHtml((r.review || '').slice(0, 140))}</td>
    </tr>
  `;
}

function detailHtml(r) {
  const reasons = (r.suspicion_reasons || []).map(k => {
    const label = reasonLabel(k.split('_size_')[0]);
    return `<span class="tag" style="color:var(--red);border-color:var(--red-dim);">${escapeHtml(label)}</span>`;
  }).join(' ');

  const devResponseHtml = r.developer_response ? `
        <div class="detail-dev-response">
          <div class="detail-dev-response-label">${t('table.devReplyLabel', { date: r.timestamp_dev_responded ? t('table.devReplyDate', { date: fmtDate(r.timestamp_dev_responded) }) : '' })}</div>
          <div class="detail-dev-response-text">${escapeHtml(r.developer_response)}</div>
        </div>` : '';

  return `
    <tr class="detail-row"><td colspan="6">
      <div class="detail-grid">
        <div class="detail-text">${escapeHtml(r.review || t('table.emptyText'))}${devResponseHtml}</div>
        <div class="detail-meta">
          ${r.personaname ? `<div>${t('table.nickname', { name: escapeHtml(r.personaname) })}</div>` : ''}
          <div>steamid: ${r.steamid ? `<a href="https://steamcommunity.com/profiles/${r.steamid}" target="_blank" rel="noopener">${r.steamid}</a>` : '—'}</div>
          <div>${r.steamid && state.data.appid ? `<a href="https://steamcommunity.com/profiles/${r.steamid}/recommended/${state.data.appid}" target="_blank" rel="noopener">${t('table.openInSteam')}</a>` : ''}</div>
          <div>${t('table.playtimeForever', { v: fmtHours(r.playtime_forever) })}</div>
          <div>${t('table.playtimeAtReview', { v: fmtHours(r.playtime_at_review) })}</div>
          <div>${t('table.playtime2w', { v: fmtHours(r.playtime_last_two_weeks) })}</div>
          <div>${t('table.gamesOwned', { n: r.num_games_owned ?? '—' })}</div>
          <div>${t('table.reviewsByAuthor', { n: r.num_reviews ?? '—' })}</div>
          <div>${t('table.viaSteam', { v: r.steam_purchase ? t('table.yes') : t('table.no') })}</div>
          <div>${t('table.gotFree', { v: r.received_for_free ? t('table.yes') : t('table.no') })}</div>
          <div>${t('table.votesUpFunny', { up: r.votes_up ?? 0, funny: r.votes_funny ?? 0 })}</div>
          <div>${t('table.language', { lang: r.language || '—' })}</div>
          <div class="detail-reasons">${reasons || t('table.noReasons')}</div>
        </div>
      </div>
    </td></tr>
  `;
}

function bindRowClicks() {
  document.querySelectorAll('#table-body tr[data-rid]').forEach(tr => {
    tr.addEventListener('click', () => {
      const rid = tr.dataset.rid;
      const existing = tr.nextElementSibling;
      if (existing && existing.classList.contains('detail-row')) {
        existing.remove();
        return;
      }
      document.querySelectorAll('.detail-row').forEach(el => el.remove());
      const r = state.filtered.find(x => x.recommendationid === rid);
      if (!r) return;
      tr.insertAdjacentHTML('afterend', detailHtml(r));
    });
  });
}

function renderPagination(totalPages) {
  const el = document.getElementById('pagination');
  el.innerHTML = `
    <button id="pg-prev" ${state.page <= 1 ? 'disabled' : ''}>${t('table.pagePrev')}</button>
    <span>${t('table.pageOf', { page: state.page, total: totalPages })}</span>
    <button id="pg-next" ${state.page >= totalPages ? 'disabled' : ''}>${t('table.pageNext')}</button>
  `;
  document.getElementById('pg-prev').addEventListener('click', () => { state.page--; renderTable(); });
  document.getElementById('pg-next').addEventListener('click', () => { state.page++; renderTable(); });
}

/* ---------------- Controls binding ---------------- */

function bindControls() {
  // sortable headers
  document.querySelectorAll('th[data-sort]').forEach(th => {
    th.addEventListener('click', () => {
      const key = th.dataset.sort;
      if (state.sortKey === key) {
        state.sortDir = state.sortDir === 'asc' ? 'desc' : 'asc';
      } else {
        state.sortKey = key;
        state.sortDir = 'desc';
      }
      state.filtered = sortReviews(state.filtered);
      renderTable();
    });
  });

  // vote type chips (multi-toggle, 'all' resets to all three)
  document.querySelectorAll('#filter-vote .chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const val = chip.dataset.val;
      const f = state.filters.vote;
      if (val === 'all') {
        f.clear(); f.add('all'); f.add('up'); f.add('down');
      } else {
        f.delete('all');
        if (f.has(val)) f.delete(val); else f.add(val);
        if (!f.has('up') && !f.has('down')) { f.add('all'); f.add('up'); f.add('down'); }
      }
      document.querySelectorAll('#filter-vote .chip').forEach(c => {
        c.classList.toggle('active', f.has(c.dataset.val));
      });
      applyFiltersAndRender();
    });
  });

  document.getElementById('filter-bucket').addEventListener('change', e => {
    state.filters.bucket = e.target.value;
    applyFiltersAndRender();
  });

  document.getElementById('filter-minscore').addEventListener('input', e => {
    state.filters.minScore = parseInt(e.target.value, 10) || 0;
    applyFiltersAndRender();
  });

  const suspBtn = document.getElementById('filter-suspicious-only');
  suspBtn.addEventListener('click', () => {
    state.filters.suspiciousOnly = !state.filters.suspiciousOnly;
    suspBtn.classList.toggle('active', state.filters.suspiciousOnly);
    applyFiltersAndRender();
  });

  const freeBtn = document.getElementById('filter-free-only');
  freeBtn.addEventListener('click', () => {
    state.filters.freeOnly = !state.filters.freeOnly;
    freeBtn.classList.toggle('active', state.filters.freeOnly);
    applyFiltersAndRender();
  });

  const dupeBtn = document.getElementById('filter-dupe-only');
  dupeBtn.addEventListener('click', () => {
    state.filters.dupeOnly = !state.filters.dupeOnly;
    dupeBtn.classList.toggle('active', state.filters.dupeOnly);
    applyFiltersAndRender();
  });

  const editedBtn = document.getElementById('filter-edited-only');
  editedBtn.addEventListener('click', () => {
    state.filters.editedOnly = !state.filters.editedOnly;
    editedBtn.classList.toggle('active', state.filters.editedOnly);
    applyFiltersAndRender();
  });

  const devResponseBtn = document.getElementById('filter-devresponse-only');
  const devResponseDateField = document.getElementById('field-devresponse-date');
  devResponseBtn.addEventListener('click', () => {
    state.filters.devResponseOnly = !state.filters.devResponseOnly;
    devResponseBtn.classList.toggle('active', state.filters.devResponseOnly);
    devResponseDateField.style.display = state.filters.devResponseOnly ? 'flex' : 'none';
    applyFiltersAndRender();
  });

  document.getElementById('filter-devresponse-from').addEventListener('change', e => {
    state.filters.devResponseFrom = e.target.value;
    applyFiltersAndRender();
  });
  document.getElementById('filter-devresponse-to').addEventListener('change', e => {
    state.filters.devResponseTo = e.target.value;
    applyFiltersAndRender();
  });

  let searchTimer;
  document.getElementById('filter-search').addEventListener('input', e => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.filters.search = e.target.value.trim();
      applyFiltersAndRender();
    }, 200);
  });

  let searchNickTimer;
  document.getElementById('filter-search-nick').addEventListener('input', e => {
    clearTimeout(searchNickTimer);
    searchNickTimer = setTimeout(() => {
      state.filters.searchNick = e.target.value.trim();
      applyFiltersAndRender();
    }, 200);
  });

  document.getElementById('filter-reset').addEventListener('click', () => {
    state.filters = {
      vote: new Set(['all', 'up', 'down']),
      bucket: '', minScore: 0, suspiciousOnly: false, freeOnly: false, dupeOnly: false, editedOnly: false,
      devResponseOnly: false, devResponseFrom: '', devResponseTo: '', search: '', searchNick: '',
    };
    document.getElementById('filter-bucket').value = '';
    document.getElementById('filter-minscore').value = 0;
    document.getElementById('filter-search').value = '';
    document.getElementById('filter-search-nick').value = '';
    document.getElementById('filter-devresponse-from').value = '';
    document.getElementById('filter-devresponse-to').value = '';
    document.getElementById('field-devresponse-date').style.display = 'none';
    document.querySelectorAll('#filter-vote .chip').forEach(c => c.classList.add('active'));
    document.getElementById('filter-suspicious-only').classList.remove('active');
    document.getElementById('filter-free-only').classList.remove('active');
    document.getElementById('filter-dupe-only').classList.remove('active');
    document.getElementById('filter-edited-only').classList.remove('active');
    document.getElementById('filter-devresponse-only').classList.remove('active');
    applyFiltersAndRender();
  });

  document.getElementById('threshold-slider').addEventListener('input', e => {
    state.threshold = parseInt(e.target.value, 10);
    document.getElementById('threshold-val').textContent = t('histogram.thresholdMin', { n: state.threshold });
    renderHistogram(state.reviews, state.threshold);
    updateThresholdCount();
  });

  document.getElementById('export-csv').addEventListener('click', exportCsv);
}

function exportCsv() {
  const cols = ['recommendationid', 'timestamp_created', 'voted_up', 'playtime_at_review',
    'playtime_forever', 'suspicion_score', 'suspicion_reasons', 'received_for_free',
    'steam_purchase', 'num_reviews', 'num_games_owned', 'language', 'steamid', 'personaname', 'review'];
  const rows = [cols.join(',')];
  for (const r of state.filtered) {
    const row = cols.map(c => {
      let v = r[c];
      if (Array.isArray(v)) v = v.join('|');
      if (v === null || v === undefined) v = '';
      v = String(v).replace(/"/g, '""');
      return `"${v}"`;
    });
    rows.push(row.join(','));
  }
  const blob = new Blob([rows.join('\n')], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `reviews_export_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

init();
