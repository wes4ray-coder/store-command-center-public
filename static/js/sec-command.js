/* Security → 🛡️ Command: posture + every background defense in one view. */
const _DEF_DOT = { on: ['#6ee7a8', 'active'], off: ['#7a86a0', 'off'], warn: ['#f59e0b', 'attention'], unknown: ['#9090b0', 'unknown'] };

async function secCommand() {
  const el = document.getElementById('sec-body');
  el.innerHTML = `
    <div style="display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap">
      <div id="cmd-head" style="flex:1;min-width:320px"><div class="empty">Reading posture…</div></div>
      <div id="cmd-stats" style="display:flex;gap:10px;flex-wrap:wrap"><div id="cmd-stat-def"></div><div id="cmd-stat-threats"></div></div>
    </div>
    <div id="cmd-fixes"></div>
    <div class="section-header" style="margin-top:14px"><div class="section-title">⚙️ Store automations — background jobs keeping watch</div></div>
    <div id="cmd-app"><div class="empty">Checking defenses…</div></div>
    <div class="section-header" style="margin-top:14px"><div class="section-title">🧱 System &amp; network shields</div></div>
    <div id="cmd-host"></div>
    <div class="section-header" style="margin-top:14px"><div class="section-title">🗞️ Recent security alerts</div></div>
    <div id="cmd-events"></div>`;
  secCmdPosture();
  secCmdDefenses();
}
window.secCommand = secCommand;

async function secCmdPosture() {
  let p;
  try { p = await api('/api/security/posture'); } catch (e) { return; }
  const head = document.getElementById('cmd-head'); if (!head) return;
  const gc = p.grade === 'A' ? '#6ee7a8' : p.grade === 'B' ? '#a3e635' : p.grade === 'C' ? '#fbbf24' : p.grade === 'D' ? '#fb923c' : '#f87171';
  const hist = (p.history || []).slice(0, 10).reverse();
  const trend = hist.length > 1 ? `<div style="font-size:.7rem;color:#7a86a0;margin-top:4px">trend: ${hist.map(h => h.grade).join(' → ')}</div>` : '';
  head.innerHTML = `
    <div style="display:flex;gap:14px;align-items:center;flex-wrap:wrap">
      <div style="width:96px;height:96px;border-radius:16px;background:${gc}22;border:2px solid ${gc};display:flex;flex-direction:column;align-items:center;justify-content:center">
        <div style="font-size:2.3rem;font-weight:900;color:${gc};line-height:1">${p.grade ?? '—'}</div>
        <div style="font-size:.7rem;color:${gc}">${p.score ?? '—'}/100</div>
      </div>
      <div style="flex:1;min-width:220px">
        <div style="font-size:.95rem;font-weight:700;color:#e2e8f0">Security posture ${window.hlp ? hlp('Letter grade from the last hardening-audit snapshot (patches, SSH, exposure, containers, AI systems). The nightly audit keeps it fresh and alerts on regressions.') : ''}</div>
        <div style="font-size:.74rem;color:#8a97ad">last audit snapshot ${p.snapshot_at ? esc(p.snapshot_at.replace('T',' ')) + ' UTC' : 'never'}</div>
        ${trend}
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">
          <button class="btn-sm primary" onclick="secCmdAudit()">▶ Run audit now</button>
          <button class="btn-sm" onclick="secCmdBackup()">💾 Backup DB now</button>
          <button class="btn-sm" onclick="secAnalyze()">🤖 AI threat hunt</button>
          <button class="btn-sm" onclick="secCommand()">↻ Refresh</button>
        </div>
      </div>
    </div>`;
  const ev = document.getElementById('cmd-events');
  if (ev) ev.innerHTML = (p.events || []).length ? p.events.map(e => `<div style="font-size:.76rem;padding:3px 0;display:flex;gap:8px">
      <span style="color:${_SEV[e.severity]||'#7a86a0'};font-weight:700;text-transform:uppercase;font-size:.62rem;width:58px">${esc(e.severity)}</span>
      <span style="color:#c7d2e5">${esc(e.text)}</span>
      <span style="color:#54607a;margin-left:auto;white-space:nowrap">${(e.created_at||'').slice(5,16)}</span></div>`).join('')
    : '<div style="color:#54607a;font-size:.78rem">No alerts — the nightly audit reports regressions here and to the God Console.</div>';
  // threats count fills in when the (slower) scan finishes
  try {
    const t = await api('/api/security/threats');
    const st = document.getElementById('cmd-stat-threats');
    if (st) st.innerHTML = `<div style="background:var(--surface,#161a22);border:1px solid var(--border,#2a2f3d);border-radius:10px;padding:10px 14px;text-align:center">
      <div style="font-size:1.4rem;font-weight:800;color:${t.count?'#f87171':'#6ee7a8'}">${t.count||0}</div>
      <div style="font-size:.64rem;color:#7a86a0;text-transform:uppercase">active threats</div></div>`;
  } catch (e) { /* threats view has the detail */ }
}

async function secCmdDefenses() {
  let d;
  try { d = await api('/api/security/defenses'); }
  catch (e) { const a = document.getElementById('cmd-app'); if (a) a.innerHTML = '<div class="empty">Defense status unavailable.</div>'; return; }
  const defs = d.defenses || [];
  const st = document.getElementById('cmd-stat-def');
  if (st) st.innerHTML = `<div style="background:var(--surface,#161a22);border:1px solid var(--border,#2a2f3d);border-radius:10px;padding:10px 14px;text-align:center">
      <div style="font-size:1.4rem;font-weight:800;color:${d.counts.warn?'#f59e0b':'#6ee7a8'}">${d.counts.on}/${defs.length}</div>
      <div style="font-size:.64rem;color:#7a86a0;text-transform:uppercase">defenses active</div></div>`;

  const card = v => {
    const [col, word] = _DEF_DOT[v.status] || _DEF_DOT.unknown;
    const lr = v.last_run ? `<span title="${esc(v.last_run.note||'')}">last ran ${_ago(v.last_run.ago_s)}${v.last_run.note?` · ${esc(v.last_run.note.slice(0,60))}`:''}</span>` : (v.kind==='app' ? 'never ran yet' : '');
    const toggle = v.toggle ? `
      <label style="display:flex;gap:6px;align-items:center;cursor:pointer;font-size:.72rem;color:#aeb9cc;white-space:nowrap">
        <input type="checkbox" ${v.enabled?'checked':''} onchange="secDefToggle('${v.id}',this.checked)"> on
      </label>
      <span style="font-size:.7rem;color:#7a86a0;white-space:nowrap">every <input type="number" id="def-iv-${v.id}" value="${v.interval_min}" min="1"
        style="width:56px;padding:2px 5px;background:var(--surface2,#0b1120);border:1px solid var(--border,#26324a);border-radius:5px;color:var(--text,#e8eefc)"
        onchange="secDefToggle('${v.id}',${v.enabled})"> min</span>` : '';
    return `<div style="display:flex;gap:10px;align-items:flex-start;padding:9px 12px;margin-bottom:6px;background:var(--surface,#161a22);border:1px solid var(--border,#2a2f3d);border-left:3px solid ${col};border-radius:8px">
      <span style="font-size:1.05rem">${v.icon}</span>
      <div style="flex:1;min-width:0">
        <div style="font-size:.84rem;color:#e2e8f0;font-weight:600">${esc(v.name)}
          <span style="font-size:.6rem;color:${col};font-weight:700;text-transform:uppercase;margin-left:6px">● ${word}</span></div>
        <div style="font-size:.74rem;color:#aeb9cc">${esc(v.detail)}</div>
        <div style="font-size:.68rem;color:#54607a;margin-top:2px">${lr}</div>
        ${v.fix ? `<div style="font-size:.72rem;color:#7dd3fc;margin-top:3px">🔧 <code style="background:#0b1120;padding:1px 6px;border-radius:4px">${esc(v.fix)}</code></div>` : ''}
      </div>
      <div style="display:flex;gap:10px;align-items:center">${toggle}</div>
    </div>`;
  };
  const app = defs.filter(v => v.kind === 'app'), host = defs.filter(v => v.kind !== 'app');
  const a = document.getElementById('cmd-app'); if (a) a.innerHTML = app.map(card).join('');
  const h = document.getElementById('cmd-host'); if (h) h.innerHTML = host.map(card).join('');

  const needs = defs.filter(v => v.status === 'warn' && v.fix);
  const fx = document.getElementById('cmd-fixes');
  if (fx) fx.innerHTML = needs.length ? `
    <div style="background:#2a1e12;border:1px solid #7c5a1a;border-radius:10px;padding:10px 14px;margin-top:12px">
      <div style="font-size:.8rem;font-weight:700;color:#f6c76b;margin-bottom:4px">⚔️ Needs you — root-only fixes the app can't run itself:</div>
      ${needs.map(v => `<div style="font-size:.76rem;color:#e8d9b5;padding:2px 0">• ${esc(v.name)}: <code style="background:#0b1120;padding:1px 6px;border-radius:4px;color:#a9c7e8">${esc(v.fix)}</code></div>`).join('')}
    </div>` : '';
}

async function secDefToggle(id, on) {
  const iv = parseInt(document.getElementById('def-iv-' + id)?.value) || undefined;
  try {
    await api('/api/security/defenses/toggle', { method: 'POST', body: JSON.stringify({ id, on, interval_min: iv }) });
    toast?.(on ? '✓ Enabled — applies within 30s' : 'Disabled');
    secCmdDefenses();
  } catch (e) { toast?.('Toggle failed: ' + e.message); }
}
async function secCmdAudit() {
  toast?.('Running audit snapshot…');
  try { const r = await api('/api/security/audit/run', { method: 'POST', body: JSON.stringify({}) }); toast?.(`Audit ${r.grade} (${r.score}) · ${r.alerts} alert(s)`); secCommand(); }
  catch (e) { toast?.('Audit failed'); }
}
async function secCmdBackup() {
  toast?.('Snapshotting DB…');
  try { const r = await api('/api/system/db-backup', { method: 'POST', body: JSON.stringify({}) }); toast?.(`💾 ${((r.copies)||[]).length || 'backup'} copies written`); secCmdDefenses(); }
  catch (e) { toast?.('Backup failed: ' + e.message); }
}
window.secCmdPosture = secCmdPosture; window.secCmdDefenses = secCmdDefenses;
window.secDefToggle = secDefToggle; window.secCmdAudit = secCmdAudit; window.secCmdBackup = secCmdBackup;
