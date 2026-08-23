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
