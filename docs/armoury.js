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
  sortKey: 'last_seen',
  sortDir: 'desc',
  search: '',
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
      <div class="label">Онлайн сегодня (armoury)</div>
      <div class="value mono green">${summary.online_today}</div>
      <div class="sub">заходили в игру ${summary.today_date}</div>
    </div>
    <div class="stat">
      <div class="label">Всего персонажей в реестре</div>
      <div class="value mono">${summary.total_players}</div>
    </div>
  `;
  document.getElementById('generated-at').textContent =
    'Обновлено: ' + new Date(summary.generated_at).toLocaleString('ru-RU');
}

function sortPlayers(list) {
  const { sortKey, sortDir } = state;
  const dir = sortDir === 'asc' ? 1 : -1;
  return [...list].sort((a, b) => {
    let av = a[sortKey] || '';
    let bv = b[sortKey] || '';
    if (sortKey === 'level') {
      av = Number(av) || 0;
      bv = Number(bv) || 0;
    }
    if (sortKey === 'last_seen') {
      av = av ? Date.parse(av) || 0 : 0;
      bv = bv ? Date.parse(bv) || 0 : 0;
    }
    if (av < bv) return -1 * dir;
    if (av > bv) return 1 * dir;
    return 0;
  });
}

function renderPlayersTable() {
  const tbody = document.getElementById('players-tbody');
  const q = state.search.trim().toLowerCase();
  let rows = state.players;
  if (q) rows = rows.filter(p => (p.name || '').toLowerCase().includes(q));
  rows = sortPlayers(rows);

  tbody.innerHTML = rows.slice(0, 500).map(p => `
    <tr>
      <td class="name-cell"><a href="${escapeHTML(p.url)}" target="_blank" rel="noopener">${escapeHTML(p.name || p.slug)}</a></td>
      <td class="mono">${escapeHTML(p.region)}</td>
      <td class="mono">${escapeHTML(p.level || '—')}</td>
      <td class="mono">${escapeHTML(p.last_seen || '—')}</td>
    </tr>
  `).join('');

  document.querySelectorAll('#players-table thead th[data-sort]').forEach(th => {
    th.classList.toggle('sorted', th.dataset.sort === state.sortKey);
  });
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

  renderStats(summary);
  renderPlayersTable();
  renderDuplicates();

  // Графики — из отдельных файлов, которые появляются только начиная с
  // первого прогона обновлённого build_armoury_data.py. Их отсутствие
  // (старый снапшот до апдейта) не должно ронять остальную страницу.
  loadJSON('armoury/online-history.json')
    .then(renderOnlineHistoryChart)
    .catch(() => renderOnlineHistoryChart([]));
  loadJSON('armoury/by-region.json')
    .then(renderByRegionChart)
    .catch(() => renderByRegionChart({}));

  document.getElementById('players-search').addEventListener('input', e => {
    state.search = e.target.value;
    renderPlayersTable();
  });

  document.querySelectorAll('#players-table thead th[data-sort]').forEach(th => {
    th.addEventListener('click', () => {
      if (state.sortKey === th.dataset.sort) {
        state.sortDir = state.sortDir === 'asc' ? 'desc' : 'asc';
      } else {
        state.sortKey = th.dataset.sort;
        state.sortDir = 'asc';
      }
      renderPlayersTable();
    });
  });

  document.getElementById('show-same-region-dupes').addEventListener('change', renderDuplicates);

  initTabs();

  document.getElementById('loading').style.display = 'none';
  document.getElementById('content').style.display = '';
}

init();
