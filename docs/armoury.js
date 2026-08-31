async function loadJSON(path) {
  const res = await fetch(path, { cache: 'no-store' });
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return res.json();
}

function escapeHTML(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

let state = {
  players: [],
  duplicates: [],
  todayDate: null,
  // Per-table state (players / missing), each with its own sort/search/page
  // so switching tabs doesn't reset the other table's view.
  tables: {
    players: { sortKey: 'last_seen', sortDir: 'desc', search: '', page: 0, pageSize: 500 },
    missing: { sortKey: 'last_seen_scrape', sortDir: 'desc', search: '', page: 0, pageSize: 500 },
  },
};

function renderOnlineHistoryChart(history) {
  const svg = document.getElementById('online-history-chart');
  if (!history || !history.length) {
    svg.innerHTML = `<text x="10" y="20" fill="var(--text-dim)" font-family="var(--mono)" font-size="12">Пока недостаточно данных &mdash; появится после нескольких дней прогонов.</text>`;
    return;
  }
  const W = 700, H = 220, padL = 36, padR = 10, padB = 24, padT = 10;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const maxVal = Math.max(...history.map(h => h.online), 1);
  const stepX = history.length > 1 ? plotW / (history.length - 1) : 0;

  const points = history.map((h, i) => {
    const x = padL + (history.length > 1 ? i * stepX : plotW / 2);
    const y = padT + plotH - (h.online / maxVal) * plotH;
    return { x, y, h };
  });

  const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ');
  const areaPath = `${linePath} L ${points[points.length - 1].x.toFixed(1)} ${(padT + plotH).toFixed(1)} L ${points[0].x.toFixed(1)} ${(padT + plotH).toFixed(1)} Z`;

  const labelEvery = Math.max(1, Math.ceil(history.length / 8));
  let labels = '';
  points.forEach((p, i) => {
    if (i % labelEvery === 0 || i === points.length - 1) {
      labels += `<text x="${p.x.toFixed(1)}" y="${H - 6}" fill="var(--text-dim)" font-family="var(--mono)" font-size="9.5" text-anchor="middle">${escapeHTML(p.h.date.slice(5))}</text>`;
    }
  });

  const dots = points.map(p => `
    <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="2.5" fill="var(--green)">
      <title>${escapeHTML(p.h.date)}: ${p.h.online} онлайн из ${p.h.total}</title>
    </circle>
  `).join('');

  svg.innerHTML = `
    <line x1="${padL}" y1="${padT}" x2="${padL}" y2="${padT + plotH}" stroke="var(--border)"/>
    <line x1="${padL}" y1="${padT + plotH}" x2="${padL + plotW}" y2="${padT + plotH}" stroke="var(--border)"/>
    <text x="4" y="${padT + 8}" fill="var(--text-dim)" font-family="var(--mono)" font-size="9.5">${maxVal}</text>
    <path d="${areaPath}" fill="var(--green)" opacity="0.12"/>
    <path d="${linePath}" fill="none" stroke="var(--green)" stroke-width="2"/>
    ${dots}
    ${labels}
  `;
}

// Retention trend: same visual treatment as the online-history chart, but
// plotting pct (0-100) instead of a raw count, from docs/armoury/retention-history.json.
function renderRetentionChart(history) {
  const svg = document.getElementById('retention-chart');
  if (!history || !history.length) {
    svg.innerHTML = `<text x="10" y="20" fill="var(--text-dim)" font-family="var(--mono)" font-size="12">Пока недостаточно данных &mdash; появится после нескольких дней прогонов.</text>`;
    return;
  }
  const W = 700, H = 220, padL = 36, padR = 10, padB = 24, padT = 10;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const maxVal = 100; // pct scale, fixed 0-100 so the chart is comparable day to day
  const stepX = history.length > 1 ? plotW / (history.length - 1) : 0;

  const points = history.map((h, i) => {
    const x = padL + (history.length > 1 ? i * stepX : plotW / 2);
    const y = padT + plotH - (h.pct / maxVal) * plotH;
    return { x, y, h };
  });

  const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ');
  const areaPath = `${linePath} L ${points[points.length - 1].x.toFixed(1)} ${(padT + plotH).toFixed(1)} L ${points[0].x.toFixed(1)} ${(padT + plotH).toFixed(1)} Z`;

  const labelEvery = Math.max(1, Math.ceil(history.length / 8));
  let labels = '';
  points.forEach((p, i) => {
    if (i % labelEvery === 0 || i === points.length - 1) {
      labels += `<text x="${p.x.toFixed(1)}" y="${H - 6}" fill="var(--text-dim)" font-family="var(--mono)" font-size="9.5" text-anchor="middle">${escapeHTML(p.h.date.slice(5))}</text>`;
    }
  });

  const dots = points.map(p => `
    <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="2.5" fill="var(--green)">
      <title>${escapeHTML(p.h.date)}: ${p.h.pct}% (${p.h.seen} из ${p.h.total})</title>
    </circle>
  `).join('');

  svg.innerHTML = `
    <line x1="${padL}" y1="${padT}" x2="${padL}" y2="${padT + plotH}" stroke="var(--border)"/>
    <line x1="${padL}" y1="${padT + plotH}" x2="${padL + plotW}" y2="${padT + plotH}" stroke="var(--border)"/>
    <text x="4" y="${padT + 8}" fill="var(--text-dim)" font-family="var(--mono)" font-size="9.5">100%</text>
    <path d="${areaPath}" fill="var(--green)" opacity="0.12"/>
    <path d="${linePath}" fill="none" stroke="var(--green)" stroke-width="2"/>
    ${dots}
    ${labels}
  `;
}

// Bar chart of all known players grouped by their last_seen date (in-game
// last login, from armoury), not to be confused with online-history.json
// which counts scraper visits per day. Computed client-side from state.players.
function renderLastSeenChart(players) {
  const svg = document.getElementById('last-seen-chart');
  const counts = new Map();
  players.forEach(p => {
    if (!p.last_seen) return;
    counts.set(p.last_seen, (counts.get(p.last_seen) || 0) + 1);
  });
  const entries = [...counts.entries()]
    .map(([date, count]) => ({ date, count, ts: Date.parse(date) || 0 }))
    .filter(e => e.ts)
    .sort((a, b) => a.ts - b.ts);

  if (!entries.length) {
    svg.innerHTML = `<text x="10" y="20" fill="var(--text-dim)" font-family="var(--mono)" font-size="12">Нет данных.</text>`;
    return;
  }

  const W = 700, H = 220, padL = 36, padR = 10, padB = 40, padT = 10;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const maxVal = Math.max(...entries.map(e => e.count), 1);
  const barGap = 2;
  const barW = Math.max((plotW / entries.length) - barGap, 1);

  let bars = '';
  entries.forEach((e, i) => {
    const x = padL + i * (plotW / entries.length);
    const barH = (e.count / maxVal) * plotH;
    const y = padT + plotH - barH;
    bars += `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barW.toFixed(1)}" height="${barH.toFixed(1)}" fill="var(--green)" opacity="0.75">
      <title>${escapeHTML(e.date)}: ${e.count} игроков</title>
    </rect>`;
  });

  const labelEvery = Math.max(1, Math.ceil(entries.length / 8));
  let labels = '';
  entries.forEach((e, i) => {
    if (i % labelEvery === 0 || i === entries.length - 1) {
      const x = padL + i * (plotW / entries.length) + barW / 2;
      labels += `<text x="${x.toFixed(1)}" y="${H - 6}" fill="var(--text-dim)" font-family="var(--mono)" font-size="9.5" text-anchor="middle">${escapeHTML(e.date.slice(0, -6))}</text>`;
    }
  });

  svg.innerHTML = `
    <line x1="${padL}" y1="${padT}" x2="${padL}" y2="${padT + plotH}" stroke="var(--border)"/>
    <line x1="${padL}" y1="${padT + plotH}" x2="${padL + plotW}" y2="${padT + plotH}" stroke="var(--border)"/>
    <text x="4" y="${padT + 8}" fill="var(--text-dim)" font-family="var(--mono)" font-size="9.5">${maxVal}</text>
    ${bars}
    ${labels}
  `;
}

function renderByRegionChart(byRegion) {
  const svg = document.getElementById('by-region-chart');
  const entries = Object.entries(byRegion || {}).sort((a, b) => b[1] - a[1]);
  if (!entries.length) {
    svg.innerHTML = `<text x="10" y="20" fill="var(--text-dim)" font-family="var(--mono)" font-size="12">Нет данных.</text>`;
    return;
  }
  const W = 700, H = 220, padL = 10, padR = 60, rowH = H / entries.length;
  const maxVal = Math.max(...entries.map(e => e[1]));

  let bars = '';
  entries.forEach(([region, count], i) => {
    const y = i * rowH + rowH * 0.2;
    const barH = rowH * 0.5;
    const barW = (count / maxVal) * (W - padL - padR - 100);
    bars += `
      <text x="0" y="${y + barH * 0.75}" fill="var(--text-dim)" font-family="var(--mono)" font-size="11">${escapeHTML(region)}</text>
      <rect x="100" y="${y}" width="${Math.max(barW, 2)}" height="${barH}" fill="var(--green)" opacity="0.75"/>
      <text x="${100 + barW + 8}" y="${y + barH * 0.75}" fill="var(--text)" font-family="var(--mono)" font-size="11" font-weight="700">${count}</text>
    `;
  });
  svg.innerHTML = bars;
}

function renderStats(summary) {
  const grid = document.getElementById('stats-grid');
  grid.innerHTML = `
    <div class="stat">
      <div class="label">Заходили сегодня (armoury)</div>
      <div class="value mono green">${summary.online_today}</div>
      <div class="sub">заходили в игру ${summary.today_date}</div>
    </div>
    <div class="stat">
      <div class="label">Известно всего (накопительная база)</div>
      <div class="value mono">${summary.total_players_known}</div>
    </div>
    <div class="stat">
      <div class="label">Отвечали сегодняшнему прогону</div>
      <div class="value mono">${summary.total_players_seen_today}</div>
    </div>
    <div class="stat">
      <div class="label">Новых сегодня</div>
      <div class="value mono">${summary.new_players_today != null ? summary.new_players_today : '—'}</div>
    </div>
  `;
  document.getElementById('generated-at').textContent =
    'Обновлено: ' + new Date(summary.generated_at).toLocaleString('ru-RU');
}

function sortRows(list, sortKey, sortDir) {
  const dir = sortDir === 'asc' ? 1 : -1;
  return [...list].sort((a, b) => {
    let av = a[sortKey] || '';
    let bv = b[sortKey] || '';
    if (sortKey === 'level') {
      av = Number(av) || 0;
      bv = Number(bv) || 0;
    }
    if (sortKey === 'last_seen' || sortKey === 'first_seen' || sortKey === 'last_seen_scrape') {
      av = av ? Date.parse(av) || 0 : 0;
      bv = bv ? Date.parse(bv) || 0 : 0;
    }
    if (av < bv) return -1 * dir;
    if (av > bv) return 1 * dir;
    return 0;
  });
}

// Shared renderer for the "players" and "missing" tables - same sort/search/
// pagination mechanics, different source rows and row template.
function renderTable(tableKey, sourceRows, tbodyId, tableId, rowTemplate) {
  const ts = state.tables[tableKey];
  const tbody = document.getElementById(tbodyId);
  const q = ts.search.trim().toLowerCase();
  let rows = sourceRows;
  if (q) rows = rows.filter(p => (p.name || '').toLowerCase().includes(q));
  rows = sortRows(rows, ts.sortKey, ts.sortDir);

  const totalPages = Math.max(1, Math.ceil(rows.length / ts.pageSize));
  if (ts.page >= totalPages) ts.page = totalPages - 1;
  if (ts.page < 0) ts.page = 0;

  const start = ts.page * ts.pageSize;
  const pageRows = rows.slice(start, start + ts.pageSize);

  tbody.innerHTML = pageRows.map(rowTemplate).join('');

  document.querySelectorAll(`#${tableId} thead th[data-sort]`).forEach(th => {
    th.classList.toggle('sorted', th.dataset.sort === ts.sortKey);
  });

  const info = document.getElementById(`${tableKey}-page-info`);
  if (rows.length === 0) {
    info.textContent = 'ничего не найдено';
  } else {
    info.textContent = `${start + 1}\u2013${Math.min(start + ts.pageSize, rows.length)} из ${rows.length} \u00b7 стр. ${ts.page + 1}/${totalPages}`;
  }
  document.getElementById(`${tableKey}-page-prev`).disabled = ts.page <= 0;
  document.getElementById(`${tableKey}-page-next`).disabled = ts.page >= totalPages - 1;
}

function playerRowTemplate(p) {
  const missing = state.todayDate && p.last_seen_scrape !== state.todayDate;
  const isNew = !missing && state.todayDate && p.first_seen === state.todayDate;
  const rowClass = missing ? 'missing-today' : (isNew ? 'new-today' : '');
  return `
    <tr class="${rowClass}">
      <td class="name-cell"><a href="#" class="player-link" data-slug="${escapeHTML(p.slug)}">${escapeHTML(p.name || p.slug)}</a></td>
      <td class="mono">${escapeHTML(p.region)}</td>
      <td class="mono">${escapeHTML(p.level || '—')}</td>
      <td class="mono">${escapeHTML(p.last_seen || '—')}</td>
      <td class="mono">${escapeHTML(p.first_seen || '—')}</td>
      <td class="mono">${escapeHTML(p.last_seen_scrape || '—')}</td>
    </tr>
  `;
}

function missingRowTemplate(p) {
  return `
    <tr>
      <td class="name-cell"><a href="#" class="player-link" data-slug="${escapeHTML(p.slug)}">${escapeHTML(p.name || p.slug)}</a></td>
      <td class="mono">${escapeHTML(p.region)}</td>
      <td class="mono">${escapeHTML(p.level || '—')}</td>
      <td class="mono">${escapeHTML(p.last_seen || '—')}</td>
      <td class="mono">${escapeHTML(p.last_seen_scrape || '—')}</td>
    </tr>
  `;
}

function renderPlayersTable() {
  renderTable('players', state.players, 'players-tbody', 'players-table', playerRowTemplate);
}

function renderMissingTable() {
  const missingRows = state.todayDate
    ? state.players.filter(p => p.last_seen_scrape !== state.todayDate)
    : [];
  renderTable('missing', missingRows, 'missing-tbody', 'missing-table', missingRowTemplate);
}

function renderDuplicates() {
  const includeSameRegion = document.getElementById('show-same-region-dupes').checked;
  const groups = state.duplicates.filter(g => includeSameRegion || g.cross_region);
  const container = document.getElementById('duplicates-list');

  if (!groups.length) {
    container.innerHTML = '<div class="empty">Совпадений не найдено.</div>';
    return;
  }

  container.innerHTML = groups.map(g => `
    <div class="dupe-group">
      <div class="dupe-group-head">
        <span class="name">${escapeHTML(g.name)}</span>
        <span class="count">${g.players.length} персонажей</span>
        ${g.cross_region ? '<span class="cross-badge">разные серверы</span>' : ''}
      </div>
      <div class="table-scroll">
        <table class="reviews armoury">
          <tbody>
            ${g.players.map(p => `
              <tr>
                <td class="mono">${escapeHTML(p.region)}</td>
                <td class="mono">${escapeHTML(p.level || '—')}</td>
                <td class="mono">${escapeHTML(p.last_seen || '—')}</td>
                <td><a href="${escapeHTML(p.url)}" target="_blank" rel="noopener">${escapeHTML(p.slug)}</a></td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    </div>
  `).join('');
}

function switchTab(tabName) {
  document.querySelectorAll('.tab-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === tabName);
  });
  document.querySelectorAll('.tab-panel').forEach(p => {
    p.classList.toggle('active', p.dataset.tab === tabName);
  });
}

function initTabs() {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });
}

// Wires search input, sortable headers, and prev/next buttons for one of
// the two tables (players / missing) - same event plumbing, parameterized
// by which render function to call after each interaction.
function wireTableControls(tableKey, tableId, renderFn) {
  const ts = state.tables[tableKey];

  document.getElementById(`${tableKey}-search`).addEventListener('input', e => {
    ts.search = e.target.value;
    ts.page = 0;
    renderFn();
  });

  document.querySelectorAll(`#${tableId} thead th[data-sort]`).forEach(th => {
    th.addEventListener('click', () => {
      if (ts.sortKey === th.dataset.sort) {
        ts.sortDir = ts.sortDir === 'asc' ? 'desc' : 'asc';
      } else {
        ts.sortKey = th.dataset.sort;
        ts.sortDir = 'asc';
      }
      ts.page = 0;
      renderFn();
    });
  });

  document.getElementById(`${tableKey}-page-prev`).addEventListener('click', () => {
    ts.page -= 1;
    renderFn();
  });
  document.getElementById(`${tableKey}-page-next`).addEventListener('click', () => {
    ts.page += 1;
    renderFn();
  });
}

// Player history modal - fetched lazily per-slug on click, not preloaded,
// since most players will never be clicked and docs/armoury/history/<slug>.json
// only exists for players who've actually changed at least once (see
// merge_shards.py) - many clicks will legitimately find nothing yet.
function openPlayerHistory(slug, displayName) {
  const modal = document.getElementById('player-history-modal');
  const title = document.getElementById('player-history-title');
  const body = document.getElementById('player-history-body');
  title.textContent = displayName || slug;
  body.textContent = 'Загружаю…';
  modal.style.display = 'flex';

  loadJSON(`armoury/history/${encodeURIComponent(slug)}.json`)
    .then(history => {
      if (!history.length) {
        body.innerHTML = '<div class="empty">История изменений пока не зафиксирована.</div>';
        return;
      }
      body.innerHTML = [...history].reverse().map(h => `
        <div class="history-row">
          <span class="hdate">${escapeHTML(h.date)}</span>
          <span>уровень ${escapeHTML(h.level || '—')}, последний вход: ${escapeHTML(h.last_seen || '—')}</span>
        </div>
      `).join('');
    })
    .catch(() => {
      body.innerHTML = '<div class="empty">Изменений уровня или даты входа с момента первого появления не зафиксировано.</div>';
    });
}

function initPlayerHistoryModal() {
  const modal = document.getElementById('player-history-modal');
  document.getElementById('player-history-close').addEventListener('click', () => {
    modal.style.display = 'none';
  });
  modal.addEventListener('click', e => {
    if (e.target === modal) modal.style.display = 'none';
  });
  document.addEventListener('click', e => {
    const link = e.target.closest('.player-link');
    if (!link) return;
    e.preventDefault();
    openPlayerHistory(link.dataset.slug, link.textContent);
  });
}

async function init() {
  let summary, players, duplicates;
  try {
    [summary, players, duplicates] = await Promise.all([
      loadJSON('armoury/summary.json'),
      loadJSON('armoury/players.json'),
      loadJSON('armoury/duplicates.json'),
    ]);
  } catch (e) {
    document.getElementById('loading').style.display = 'none';
    document.getElementById('error').style.display = '';
    document.getElementById('error').textContent =
      'Не удалось загрузить данные armoury — пайплайн fetch-armoury ещё не запускался или не настроен.';
    return;
  }

  state.players = players;
  state.duplicates = duplicates;
  state.todayDate = summary.today_date;

  renderStats(summary);
  renderPlayersTable();
  renderMissingTable();
  renderDuplicates();
  renderLastSeenChart(state.players);

  // Графики — из отдельных файлов, которые появляются только начиная с
  // первого прогона обновлённого merge_shards.py. Их отсутствие (старый
  // снапшот до апдейта) не должно ронять остальную страницу.
  loadJSON('armoury/online-history.json')
    .then(renderOnlineHistoryChart)
    .catch(() => renderOnlineHistoryChart([]));
  loadJSON('armoury/retention-history.json')
    .then(renderRetentionChart)
    .catch(() => renderRetentionChart([]));
  loadJSON('armoury/by-region.json')
    .then(renderByRegionChart)
    .catch(() => renderByRegionChart({}));

  wireTableControls('players', 'players-table', renderPlayersTable);
  wireTableControls('missing', 'missing-table', renderMissingTable);

  document.getElementById('show-same-region-dupes').addEventListener('change', renderDuplicates);

  initTabs();
  initPlayerHistoryModal();

  document.getElementById('loading').style.display = 'none';
  document.getElementById('content').style.display = '';
}

init();
