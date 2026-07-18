/* Security → 🧿 DNS (Pi-hole): the legacy overview / logs / devices / findings / blocklist views. */
let _secLogBlocked = false;

const _SEC_VERDICT = { healthy: '✅ Healthy', needs_attention: '⚠️ Needs Attention', unknown: '❔ Unknown' };
const _FIND_BADGE = {
  pending: ['#f59e0b', 'Pending'], approved: ['#6c63ff', 'Approved'],
  remediated: ['#22c55e', 'Handled'], ignored: ['#9090b0', 'Ignored'],
};

/* ── Overview ─────────────────────────────────────────────────────────────── */
async function secOverview() {
  const el = _secBody();
  el.innerHTML = '<div class="empty">Loading…</div>';
  let o = {};
  try { o = await api('/api/security/overview'); } catch (e) { el.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  const score = o.score ?? '—';
  const sc = score >= 90 ? 'var(--green)' : score >= 60 ? 'var(--warn)' : 'var(--error)';
  const pi = o.pihole_ok ? `${(o.queries_total||0).toLocaleString()} queries · ${o.percent_blocked||0}% blocked`
    : (o.pihole_configured ? `<span style="color:var(--warn)">Pi-hole unreachable</span>` : `<span style="color:var(--warn)">Pi-hole password not set</span>`);
  el.innerHTML = `
    <div class="stats-row">
      <div class="stat-card"><div class="stat-label">Security Score</div><div class="stat-val" style="color:${sc}">${score}</div></div>
      <div class="stat-card"><div class="stat-label">Verdict</div><div class="stat-val" style="font-size:1.05rem">${esc(_SEC_VERDICT[o.verdict]||o.verdict)}</div></div>
      <div class="stat-card"><div class="stat-label">Devices</div><div class="stat-val">${o.clients||0}</div></div>
      <div class="stat-card"><div class="stat-label">Suspicious</div><div class="stat-val c-warn">${o.suspicious_clients||0}</div></div>
    </div>
    <div style="margin:10px 0 4px;color:var(--muted);font-size:.8rem;">Pi-hole: ${pi}${o.last_scan ? ' · last scan '+esc(new Date(o.last_scan).toLocaleString()) : ''}</div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin:14px 0;">
      <button class="btn-sm primary" id="sec-ai" onclick="secAnalyze()">&#129302; Hunt threats with AI</button>
      <button class="btn-sm" onclick="secMonitorTick()">&#128260; Refresh device profiles</button>
      <button class="btn-sm" id="sec-scan" onclick="secRunScan()">&#128269; Run config scan</button>
      <button class="btn-sm" onclick="secToggleReport()">&#128196; Config report</button>
    </div>
    <div id="sec-report"></div>
    <div style="margin-top:8px;color:var(--muted);font-size:.78rem;line-height:1.6;">
      <b>How it works:</b> “Refresh device profiles” snapshots recent DNS activity per device.
      “Hunt threats with AI” sends that activity to your local model, which flags ad/tracking/malware
      domains as Findings you can one-click <b>Ban</b>. Bans are pushed straight to Pi-hole.
    </div>`;
}
window.secOverview = secOverview;

async function secAnalyze() {
  const btn = document.getElementById('sec-ai');
  if (btn) { btn.disabled = true; btn.textContent = '🧠 Hunting (local model)…'; }
  try {
    const { task_id } = await api('/api/security/analyze', { method: 'POST' });
    const res = await pollTask(task_id, 60);
    toast(`AI hunt done — ${res.findings_added} new finding(s)`);
    secTab('findings');
  } catch (e) {
    toast('Analyze failed: ' + e.message, 'error');
    if (btn) { btn.disabled = false; btn.innerHTML = '&#129302; Hunt threats with AI'; }
  }
}
window.secAnalyze = secAnalyze;

async function secMonitorTick() {
  toast('Snapshotting DNS activity…');
  try { const r = await api('/api/security/monitor/tick', { method: 'POST' }); toast(`Profiled ${r.clients} devices from ${r.queries_scanned} queries`); if (_secDnsTab === 'devices' && _secTab === 'dns') secDevices(); else if (_secTab === 'dns') secOverview(); }
  catch (e) { toast('Error: ' + e.message, 'error'); }
}
window.secMonitorTick = secMonitorTick;

async function secRunScan() {
  const btn = document.getElementById('sec-scan');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Scanning…'; }
  try { const r = await api('/api/security/scan', { method: 'POST' }); toast(`Config scan: ${r.status} (${r.findings_parsed} findings)`); secOverview(); }
  catch (e) { toast('Scan failed: ' + e.message, 'error'); if (btn) { btn.disabled = false; btn.innerHTML = '&#128269; Run config scan'; } }
}
window.secRunScan = secRunScan;

let _secReportOpen = false;
async function secToggleReport() {
  const el = document.getElementById('sec-report'); if (!el) return;
  _secReportOpen = !_secReportOpen;
  if (!_secReportOpen) { el.innerHTML = ''; return; }
  el.innerHTML = '<div class="loading-state">Loading report…</div>';
  try { const r = await api('/api/security/report');
    el.innerHTML = `<pre style="white-space:pre-wrap;background:var(--bg);border:1px solid var(--border);border-radius:10px;padding:16px;font-size:.75rem;overflow-x:auto;max-height:460px;">${esc(r.report)}</pre>`;
  } catch (e) { el.innerHTML = `<div style="color:var(--warn);padding:10px;">${esc(e.message)}</div>`; }
}
window.secToggleReport = secToggleReport;

/* ── Live logs ────────────────────────────────────────────────────────────── */
async function secLogs() {
  const el = _secBody();
  el.innerHTML = `
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px;">
      <input id="sec-log-client" placeholder="filter by device…" onkeydown="if(event.key==='Enter')secLogsLoad()" style="padding:7px 10px;background:var(--surface2);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:.8rem;">
      <label style="font-size:.8rem;color:var(--muted);display:flex;gap:5px;align-items:center;cursor:pointer;"><input type="checkbox" id="sec-log-blocked" ${_secLogBlocked?'checked':''} onchange="secLogsLoad()"> blocked only</label>
      <label style="font-size:.8rem;color:var(--muted);display:flex;gap:5px;align-items:center;cursor:pointer;"><input type="checkbox" id="sec-log-live" onchange="secLogsLive(this.checked)"> live</label>
      <button class="btn-sm" onclick="secLogsLoad()">&#8635; Refresh</button>
    </div>
    <div id="sec-log-table"><div class="empty">Loading…</div></div>`;
  secLogsLoad();
}
window.secLogs = secLogs;

async function secLogsLoad() {
  const client = document.getElementById('sec-log-client')?.value.trim() || '';
  _secLogBlocked = document.getElementById('sec-log-blocked')?.checked || false;
  const t = document.getElementById('sec-log-table'); if (!t) return;
  let data;
  try { data = await api(`/api/security/logs?length=200&only_blocked=${_secLogBlocked}&client=${encodeURIComponent(client)}`); }
  catch (e) { t.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  const rows = data.queries || [];
  if (!rows.length) { t.innerHTML = '<div class="empty">No matching queries.</div>'; return; }
  t.innerHTML = `<div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;font-size:.76rem;">
    <thead><tr style="text-align:left;color:var(--muted);border-bottom:1px solid var(--border);">
      <th style="padding:6px 8px;">Time</th><th>Device</th><th>Domain</th><th>Status</th><th></th></tr></thead>
    <tbody>${rows.map(secLogRow).join('')}</tbody></table></div>`;
}
window.secLogsLoad = secLogsLoad;

function secLogRow(q) {
  const t = q.time ? new Date(q.time * 1000).toLocaleTimeString() : '';
  const badge = q.blocked
    ? `<span style="color:#f87171;">⛔ ${esc(q.status)}</span>`
    : `<span style="color:var(--muted);">${esc(q.status)}</span>`;
  const d = (q.domain || '').replace(/'/g, '');
  return `<tr style="border-bottom:1px solid var(--border);">
    <td style="padding:6px 8px;color:var(--muted);white-space:nowrap;">${t}</td>
    <td style="white-space:nowrap;">${esc(q.client || '')}</td>
    <td style="word-break:break-all;">${esc(q.domain || '')}</td>
    <td style="white-space:nowrap;">${badge}</td>
    <td style="white-space:nowrap;text-align:right;">
      ${q.blocked ? `<button class="btn-sm" title="Allow" onclick="secAllow('${d}')">✓</button>`
                  : `<button class="btn-sm" title="Ban" style="color:#f87171;" onclick="secBan('${d}')">⛔</button>`}
    </td></tr>`;
}

function secLogsLive(on) {
  _secStopTimers();
  if (on) _secLogTimer = setInterval(() => { if (_secTab === 'dns' && _secDnsTab === 'logs') secLogsLoad(); else _secStopTimers(); }, 4000);
}
window.secLogsLive = secLogsLive;

/* ── Devices ──────────────────────────────────────────────────────────────── */
async function secDevices() {
  const el = _secBody();
  el.innerHTML = '<div class="empty">Loading…</div>';
  let data;
  try { data = await api('/api/security/profile'); } catch (e) { el.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  const clients = data.clients || [];
  let h = `<div style="margin-bottom:12px;"><button class="btn-sm primary" onclick="secMonitorTick()">&#128260; Refresh profiles</button>
    <span style="color:var(--muted);font-size:.78rem;margin-left:8px;">Recent DNS activity per device.</span></div>`;
  if (!clients.length) { h += '<div class="empty"><div class="empty-icon">🖥️</div>No profiles yet — click “Refresh profiles”.</div>'; el.innerHTML = h; return; }
  h += '<div class="proposals-grid">';
  for (const c of clients) {
    const pct = c.total_queries ? Math.round(100 * c.blocked_queries / c.total_queries) : 0;
    h += `<div class="proposal-card" style="${c.suspicious ? 'border-color:#f87171;' : ''}">
      <div class="proposal-source" style="display:flex;justify-content:space-between;">
        <span>${c.suspicious ? '⚠️ ' : ''}${esc(c.name || c.ip)}</span>
        <span style="color:var(--muted);font-weight:400;">${esc(c.ip || '')}</span>
      </div>
      <div style="font-size:.78rem;color:var(--muted);margin:4px 0;">${c.total_queries} queries · ${c.blocked_queries} blocked (${pct}%)</div>
      <div style="display:flex;flex-wrap:wrap;gap:4px;margin:6px 0;">
        ${(c.top_domains||[]).slice(0,8).map(d => `<span title="${d[1]} hits" style="font-size:.68rem;background:var(--bg);border:1px solid var(--border);border-radius:4px;padding:1px 6px;cursor:pointer;" onclick="secBan('${(d[0]||'').replace(/'/g,'')}')">${esc(d[0])}</span>`).join('')}
      </div>
      <div class="proposal-actions">
        <button class="btn-sm" onclick="secFlag('${esc(c.ip)}',${c.suspicious?0:1})">${c.suspicious ? 'Clear flag' : 'Flag suspicious'}</button>
      </div></div>`;
  }
  h += '</div>';
  el.innerHTML = h;
}
window.secDevices = secDevices;

async function secFlag(ip, suspicious) {
  try { await api(`/api/security/clients/${encodeURIComponent(ip)}/flag`, { method: 'POST', body: JSON.stringify({ suspicious: !!suspicious }) }); secDevices(); }
  catch (e) { toast('Error: ' + e.message, 'error'); }
}
window.secFlag = secFlag;

/* ── Findings ─────────────────────────────────────────────────────────────── */
async function secFindings() {
  const el = _secBody();
  el.innerHTML = '<div class="empty">Loading…</div>';
  let list = [];
  try { list = await api('/api/security/findings'); } catch (e) { el.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  let h = `<div style="margin-bottom:12px;"><button class="btn-sm primary" onclick="secAnalyze()">&#129302; Hunt threats with AI</button></div>`;
  if (!list.length) { h += '<div class="empty"><div class="empty-icon">✅</div>No findings. Run “Hunt threats with AI” or a config scan.</div>'; el.innerHTML = h; return; }
  h += `<div class="proposals-grid">${list.map(secFindingCard).join('')}</div>`;
  el.innerHTML = h;
}
window.secFindings = secFindings;

function secFindingCard(f) {
  const [color, txt] = _FIND_BADGE[f.status] || ['#9090b0', f.status];
  const prio = f.priority ? `<span style="font-size:.66rem;padding:1px 6px;border-radius:4px;background:rgba(108,99,255,.15);color:var(--accent2);margin-left:6px;">${esc(f.priority)}</span>` : '';
  const domain = (f.domain || '').replace(/'/g, '');
  let actions = '';
  if (domain) actions += `<button class="btn-sm" style="color:#f87171;" onclick="secBan('${domain}')">⛔ Ban</button>`;
  if (f.status === 'pending') actions += `<button class="btn-sm primary" onclick="secReview(${f.id},'approved')">Approve</button><button class="btn-sm" onclick="secReview(${f.id},'ignored')">Ignore</button>`;
  else if (f.status === 'approved') actions += `<button class="btn-sm" style="color:var(--green)" onclick="secReview(${f.id},'remediated')">Mark handled</button><button class="btn-sm" onclick="secReview(${f.id},'pending')">Reset</button>`;
  else actions += `<button class="btn-sm" onclick="secReview(${f.id},'pending')">Reopen</button>`;
  return `<div class="proposal-card">
    <div class="proposal-source"><span style="color:${color}">● ${esc(txt)}</span>${prio}</div>
    <div class="proposal-title" style="font-size:.9rem;">${esc(f.issue)}</div>
    ${f.action ? `<div class="proposal-desc">Suggested: ${esc(f.action)}</div>` : ''}
    <div class="proposal-actions">${actions}</div></div>`;
}

async function secReview(id, status) {
  try { await api(`/api/security/findings/${id}/review`, { method: 'POST', body: JSON.stringify({ status }) }); secFindings(); }
  catch (e) { toast('Error: ' + e.message, 'error'); }
}
window.secReview = secReview;

/* ── Blocklist + audit ────────────────────────────────────────────────────── */
async function secBlocklist() {
  const el = _secBody();
  el.innerHTML = '<div class="empty">Loading…</div>';
  let deny = {}, actions = {};
  try { deny = await api('/api/security/blocklist'); actions = await api('/api/security/actions'); }
  catch (e) { el.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  const domains = deny.domains || [];
  let h = `<div class="section-header"><div class="section-title">⛔ Banned domains (${domains.length})</div></div>`;
  h += domains.length ? '<div style="display:flex;flex-direction:column;gap:4px;margin-bottom:20px;">' + domains.map(d => {
    const dn = (d.domain || '').replace(/'/g, '');
    return `<div class="stat-card" style="padding:8px 12px;display:flex;justify-content:space-between;align-items:center;">
      <span>${esc(d.domain)}</span><button class="btn-sm" onclick="secUnban('${dn}')">Remove</button></div>`;
  }).join('') + '</div>' : '<div class="empty" style="padding:16px;">No banned domains yet.</div>';
  h += `<div class="section-header"><div class="section-title">📋 Audit log</div></div>`;
  const acts = actions.actions || [];
  h += acts.length ? '<div style="display:flex;flex-direction:column;gap:3px;font-size:.78rem;">' + acts.map(a =>
    `<div style="display:flex;gap:10px;color:var(--muted);"><span style="width:130px;">${esc(new Date((a.created_at||'').replace(' ','T')).toLocaleString())}</span><b style="color:var(--text);">${esc(a.action)}</b><span>${esc(a.target)}</span></div>`).join('') + '</div>' : '<div class="empty" style="padding:12px;">No actions yet.</div>';
  el.innerHTML = h;
}
window.secBlocklist = secBlocklist;

/* ── Ban / allow / unban actions ──────────────────────────────────────────── */
async function secBan(domain) {
  if (!domain || !confirm('Ban ' + domain + ' via Pi-hole? It will be blocked network-wide.')) return;
  try { await api('/api/security/ban', { method: 'POST', body: JSON.stringify({ domain }) }); toast('Banned ' + domain); secTab(_secTab); }
  catch (e) { toast('Error: ' + e.message, 'error'); }
}
window.secBan = secBan;
async function secAllow(domain) {
  if (!domain || !confirm('Allow ' + domain + ' (whitelist) via Pi-hole?')) return;
  try { await api('/api/security/allow', { method: 'POST', body: JSON.stringify({ domain }) }); toast('Allowed ' + domain); secTab(_secTab); }
  catch (e) { toast('Error: ' + e.message, 'error'); }
}
window.secAllow = secAllow;
async function secUnban(domain) {
  try { await api('/api/security/unban', { method: 'POST', body: JSON.stringify({ domain }) }); toast('Removed ' + domain); secBlocklist(); }
  catch (e) { toast('Error: ' + e.message, 'error'); }
}
window.secUnban = secUnban;
