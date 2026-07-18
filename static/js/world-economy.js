/* ══ THE COMPANY — economics / finances dashboard ══
   Reads _worldState (already fetched by tab-world.js) — no backend calls. Aggregates
   per-agent economy into a company P&L view. Shared global-scope classic script. */

// shared modal helper (reuses the world modal); also used by world-character.js
function _worldModal(title, html) {
  const t = document.getElementById('world-modal-title');
  const b = document.getElementById('world-modal-body');
  if (!t || !b) return;
  t.textContent = title;
  b.style.whiteSpace = 'normal';
  _consoleStrip();
  b.innerHTML = html;
  document.getElementById('world-modal').style.display = 'flex';
}

/* ── the consolidated God Console ─────────────────────────────────────────────
   One modal, one tab strip — every command surface (prayers, work, control,
   republic, finances, settings, …) lives behind the single 🏛️ button instead
   of a wall of header buttons. Each tab still renders through its own
   world*() function + _worldModal; while a console session is active the
   strip persists across those renders, so in-tab refreshes keep the tabs. */
const WORLD_CONSOLE_TABS = [
  { key: 'god',       icon: '🏛️', label: 'Prayers',    fn: () => worldGod() },
  { key: 'workboard', icon: '🗂️', label: 'Workboard',  fn: () => worldWorkboard() },
  { key: 'work',      icon: '📌', label: 'Priorities', fn: () => worldWorkTab() },
  { key: 'control',   icon: '🎛️', label: 'Control',    fn: () => worldControl() },
  { key: 'republic',  icon: '⚖️', label: 'Republic',   fn: () => worldRepublic() },
  { key: 'board',     icon: '📋', label: 'Board',      fn: () => worldBoard() },
  { key: 'bible',     icon: '📖', label: 'Bible',      fn: () => worldBible() },
  { key: 'finances',  icon: '📊', label: 'Finances',   fn: () => worldFinances() },
  { key: 'roster',    icon: '🧑‍🤝‍🧑', label: 'Roster',  fn: () => worldRoster() },
  { key: 'research',  icon: '🔬', label: 'Research',   fn: () => worldResearch() },
  { key: 'schedule',  icon: '🕐', label: 'Schedule',   fn: () => worldSchedule() },
  { key: 'settings',  icon: '⚙️', label: 'Settings',   fn: () => worldSettings() },
];
let _consoleActive = null;
function worldConsole(key) {
  const tab = WORLD_CONSOLE_TABS.find(x => x.key === key) || WORLD_CONSOLE_TABS[0];
  _consoleActive = tab.key;
  try { tab.fn(); } catch (e) { toast?.(e.message); }
}
function _consoleStrip() {
  const strip = document.getElementById('world-modal-tabs');
  if (!strip) return;
  if (!_consoleActive) { strip.style.display = 'none'; strip.innerHTML = ''; return; }
  strip.style.display = 'flex';
  strip.innerHTML = WORLD_CONSOLE_TABS.map(tb =>
    `<button class="btn" style="padding:3px 9px;font-size:.7rem;white-space:nowrap;${tb.key === _consoleActive
       ? 'background:#2a1f4a;border-color:#6d5aff;color:#c4b5fd' : ''}"
       onclick="worldConsole('${tb.key}')">${tb.icon} ${tb.label}</button>`).join('');
}
window.worldConsole = worldConsole;

function _finStat(label, val, color) {
  return `<div style="background:#0e1626;border:1px solid #26324a;border-radius:8px;padding:8px 10px">
    <div style="font-size:.64rem;color:#7a86a0">${label}</div>
    <div style="font-size:1.1rem;font-weight:700;color:${color || '#e8eefc'}">${val}</div></div>`;
}

function worldFinances() {
  const st = _worldState;
  if (!st) { toast?.('World not loaded yet'); return; }
  const co = st.company || {}, econ = st.economy || {}, ags = st.agents || [], depts = st.departments || [];

  // per-department P&L
  const byDept = {};
  for (const a of ags) {
    const d = a.dept || 'none';
    const g = byDept[d] || (byDept[d] = { n: 0, coins: 0, earned: 0, debt: 0, lvl: 0, jobs: 0 });
    g.n++; g.coins += a.coins || 0; g.earned += a.coins_earned || 0; g.debt += a.debt || 0;
    g.lvl += a.level || 0; g.jobs += a.jobs_done || 0;
  }
  const deptLabel = k => (depts.find(d => d.key === k)?.label) || k;
  const deptRows = Object.entries(byDept).sort((a, b) => b[1].earned - a[1].earned).map(([k, g]) => `
    <tr style="border-top:1px solid #1b2740">
      <td style="padding:4px 0">${esc(deptLabel(k))}</td><td>${g.n}</td>
      <td style="color:#fcd34d">🪙${g.coins}</td><td>${g.earned}</td><td>${g.jobs}</td>
      <td style="color:${g.debt ? '#f87171' : '#54607a'}">${g.debt || '—'}</td>
      <td>${(g.lvl / g.n).toFixed(1)}</td></tr>`).join('');

  const top = (key, n = 5) => [...ags].sort((a, b) => (b[key] || 0) - (a[key] || 0)).slice(0, n);
  const lb = (arr, key, pre, suf) => arr.map(a => `
    <div style="display:flex;justify-content:space-between;font-size:.78rem;padding:2px 0">
      <span style="color:#c7d2e5">${esc(a.name)}</span>
      <span style="color:#fcd34d">${pre || ''}${a[key] || 0}${suf || ''}</span></div>`).join('');

  const totalEarned = ags.reduce((s, a) => s + (a.coins_earned || 0), 0);
  const totalCoins = ags.reduce((s, a) => s + (a.coins || 0), 0);

  const html = `
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(104px,1fr));gap:10px;margin-bottom:14px">
      ${_finStat('🏦 Treasury', co.treasury ?? econ.treasury ?? 0)}
      ${_finStat('💼 Company fund', co.company_fund ?? econ.company_fund ?? 0)}
      ${_finStat('💸 Total debt', co.total_debt ?? econ.debt ?? 0, (co.total_debt || econ.debt) ? '#f87171' : null)}
      ${_finStat('🪙 In wallets', totalCoins)}
      ${_finStat('👥 Population', co.pop ?? ags.length)}
      ${_finStat('✅ Jobs done', co.total_jobs ?? 0)}
    </div>
    <div style="font-weight:600;margin:6px 0 4px;color:#e8eefc">🏢 Departments — P&amp;L</div>
    <table style="width:100%;font-size:.76rem;border-collapse:collapse;color:#c7d2e5">
      <tr style="color:#7a86a0;text-align:left"><th style="font-weight:600">Dept</th><th>#</th><th>Coins</th><th>Earned</th><th>Jobs</th><th>Debt</th><th>Avg L</th></tr>
      ${deptRows || '<tr><td colspan="7" style="color:#54607a">No agents yet.</td></tr>'}
    </table>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;margin-top:14px">
      <div><div style="font-weight:600;color:#e8eefc;font-size:.8rem;margin-bottom:4px">💰 Richest</div>${lb(top('coins'), 'coins', '🪙')}</div>
      <div><div style="font-weight:600;color:#e8eefc;font-size:.8rem;margin-bottom:4px">🛠️ Hardest working</div>${lb(top('jobs_done'), 'jobs_done', '', ' jobs')}</div>
      <div><div style="font-weight:600;color:#e8eefc;font-size:.8rem;margin-bottom:4px">⭐ Top level</div>${lb(top('level'), 'level', 'L')}</div>
    </div>
    <div style="margin-top:14px;font-size:.72rem;color:#7a86a0;line-height:1.7;border-top:1px solid #1b2740;padding-top:8px">
      Total earned all-time: <b style="color:#6ee7a8">${totalEarned}🪙</b>${co.thriving !== undefined ? ` · Company is <b style="color:${co.thriving ? '#6ee7a8' : '#f59e0b'}">${co.thriving ? '🌱 thriving' : '⚠️ struggling'}</b>` : ''}
      ${co.upgrades != null ? ` · ${co.upgrades} upgrades owned` : ''}
    </div>`;
  _worldModal('📊 Company Finances', html);
}
window.worldFinances = worldFinances;
window._worldModal = _worldModal;
