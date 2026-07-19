/* Split from tab-oracle.js — the Open-calls & Results history sub-views plus the
   shared filter-banner / thesis helpers they use. Classic non-module script: same
   global scope as tab-oracle.js (oracleSub() dispatches here via bare globals;
   _oracleHistoryFilter / formatting helpers live in the core file). */

/* ── shared filter banner for Open/Results panes ──────────────────────────── */
function _orFilterBanner() {
  if (!_oracleHistoryFilter) return '';
  return `<div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;font-size:.76rem;color:var(--muted);">
    &#128269; Filtered to one analyst.
    <button class="btn-sm" onclick="oracleClearFilter()">&#10005; Clear filter</button></div>`;
}
function oracleClearFilter() {
  _oracleHistoryFilter = '';
  _oracleLoaded.open = false;
  _oracleLoaded.results = false;
  const active = document.querySelector('#oracle-subtabs .subtab.active');
  oracleSub(active && active.textContent.includes('Results') ? 'results' : 'open');
}
window.oracleClearFilter = oracleClearFilter;

// expandable thesis + sources block, shared by Open/Results
function _orThesis(p) {
  const sources = (p.sources || []).map(s =>
    s.url
      ? `<a href="${esc(s.url)}" target="_blank" rel="noopener" style="color:var(--accent);text-decoration:none;display:block;margin-bottom:3px;">&#128279; ${esc(s.title || s.url)}</a>${s.snippet ? `<div style="color:var(--muted);font-size:.7rem;margin:0 0 6px 16px;">${esc(s.snippet)}</div>` : ''}`
      : `<div style="color:var(--muted);margin-bottom:3px;">${esc(s.title || '')}</div>`).join('');
  if (!p.thesis && !sources) return '<span style="color:var(--muted);font-size:.72rem;">—</span>';
  return `<details>
    <summary style="cursor:pointer;color:var(--accent);font-size:.72rem;">thesis${(p.sources || []).length ? ` · ${p.sources.length} source(s)` : ''}</summary>
    ${p.thesis ? `<div style="font-size:.76rem;color:var(--text);line-height:1.6;margin:6px 0;">${esc(p.thesis)}</div>` : ''}
    ${sources ? `<div style="font-size:.74rem;margin-top:4px;">${sources}</div>` : ''}
  </details>`;
}

/* ── 🔮 OPEN CALLS ────────────────────────────────────────────────────────── */
async function oracleLoadOpen() {
  const pane = document.getElementById('pane-oracle-open');
  let d;
  const q = '/api/oracle/predictions?status=open&limit=200' + (_oracleHistoryFilter ? '&agent_id=' + encodeURIComponent(_oracleHistoryFilter) : '');
  try { d = await api(q); }
  catch (e) { pane.innerHTML = `<div class="empty"><div class="empty-icon">&#10060;</div>${esc(e.message)}</div>`; return; }
  const preds = (d.predictions || []).slice().sort((a, b) =>
    String(a.resolve_at || '').localeCompare(String(b.resolve_at || '')));

  const rows = preds.map(p => `
    <tr style="border-top:1px solid var(--border);vertical-align:top;">
      <td style="padding:7px 10px;font-weight:600;">${esc(p.agent_name || '')}</td>
      <td style="padding:7px 10px;">${_orAssetBadge(p.asset, p.market)}</td>
      <td style="padding:7px 10px;">${_orDir(p.direction)}</td>
      <td style="padding:7px 10px;white-space:nowrap;">${_orUsd(p.current_value)} <span style="color:var(--muted);">&rarr;</span> <b>${_orUsd(p.target_value)}</b></td>
      <td style="padding:7px 10px;text-align:center;color:var(--muted);white-space:nowrap;">${p.horizon_days != null ? p.horizon_days + 'd' : '—'}</td>
      <td style="padding:7px 10px;color:var(--muted);white-space:nowrap;">${_orDate(p.resolve_at)}</td>
      <td style="padding:7px 10px;min-width:120px;">${_orConfBar(p.confidence)}</td>
      <td style="padding:7px 10px;max-width:280px;">${_orThesis(p)}</td>
    </tr>`).join('');

  pane.innerHTML = `
    <div class="section-header">
      <div><div class="section-title">&#128302; Open calls</div>
        <div class="section-sub">Live forecasts still awaiting their horizon, soonest to resolve first.</div></div>
      <button class="btn-sm" onclick="_oracleLoaded.open=false;oracleSub('open')">&#8635; Refresh</button>
    </div>
    ${_orFilterBanner()}
    ${preds.length ? `
    <div class="settings-group" style="max-width:1000px;overflow-x:auto;">
      <table style="width:100%;border-collapse:collapse;font-size:.8rem;">
        <thead><tr style="text-align:left;color:var(--muted);font-size:.66rem;text-transform:uppercase;letter-spacing:.04em;">
          <th style="padding:6px 10px;">Analyst</th><th style="padding:6px 10px;">Asset</th>
          <th style="padding:6px 10px;">Call</th><th style="padding:6px 10px;">Target</th>
          <th style="padding:6px 10px;text-align:center;">Horizon</th><th style="padding:6px 10px;">Resolves</th>
          <th style="padding:6px 10px;">Confidence</th><th style="padding:6px 10px;">Thesis</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`
    : `<div class="empty"><div class="empty-icon">&#128302;</div>${_oracleHistoryFilter ? 'No open calls for this analyst.' : 'No open calls yet — run a tournament round to see analysts compete.'}</div>`}`;
}
window.oracleLoadOpen = oracleLoadOpen;

/* ── 📊 RESULTS ───────────────────────────────────────────────────────────── */
async function oracleLoadResults() {
  const pane = document.getElementById('pane-oracle-results');
  let d;
  const q = '/api/oracle/predictions?status=resolved&limit=200' + (_oracleHistoryFilter ? '&agent_id=' + encodeURIComponent(_oracleHistoryFilter) : '');
  try { d = await api(q); }
  catch (e) { pane.innerHTML = `<div class="empty"><div class="empty-icon">&#10060;</div>${esc(e.message)}</div>`; return; }
  const preds = d.predictions || [];

  const rows = preds.map(p => {
    const correct = !!p.correct;
    const cCol = correct ? 'var(--green)' : 'var(--red)';
    const score = Number(p.score || 0);
    const sCol = score > 0 ? 'var(--green)' : (score < 0 ? 'var(--red)' : 'var(--muted)');
    return `
    <tr style="border-top:1px solid var(--border);vertical-align:top;">
      <td style="padding:7px 10px;font-weight:600;">${esc(p.agent_name || '')}</td>
      <td style="padding:7px 10px;">${_orAssetBadge(p.asset, p.market)}</td>
      <td style="padding:7px 10px;white-space:nowrap;">${_orDir(p.direction)} ${_orUsd(p.target_value)}</td>
      <td style="padding:7px 10px;white-space:nowrap;"><b>${_orUsd(p.actual_value)}</b></td>
      <td style="padding:7px 10px;text-align:center;color:${cCol};font-weight:700;">${correct ? '&#10003;' : '&#10007;'}</td>
      <td style="padding:7px 10px;text-align:right;color:var(--muted);">${p.rel_error != null ? _orPct(p.rel_error * 100, 1) : '—'}</td>
      <td style="padding:7px 10px;text-align:right;font-weight:700;color:${sCol};">${score > 0 ? '+' : ''}${score.toFixed(1)}</td>
      <td style="padding:7px 10px;color:var(--muted);white-space:nowrap;">${_orDate(p.resolved_at)}</td>
      <td style="padding:7px 10px;max-width:280px;">${_orThesis(p)}</td>
    </tr>`;
  }).join('');

  pane.innerHTML = `
    <div class="section-header">
      <div><div class="section-title">&#128202; Results</div>
        <div class="section-sub">Resolved calls, scored on direction, how close the target was, and how far out it was called.</div></div>
      <button class="btn-sm" onclick="_oracleLoaded.results=false;oracleSub('results')">&#8635; Refresh</button>
    </div>
    ${_orFilterBanner()}
    ${preds.length ? `
    <div class="settings-group" style="max-width:1000px;overflow-x:auto;">
      <table style="width:100%;border-collapse:collapse;font-size:.8rem;">
        <thead><tr style="text-align:left;color:var(--muted);font-size:.66rem;text-transform:uppercase;letter-spacing:.04em;">
          <th style="padding:6px 10px;">Analyst</th><th style="padding:6px 10px;">Asset</th>
          <th style="padding:6px 10px;">Called</th><th style="padding:6px 10px;">Actual</th>
          <th style="padding:6px 10px;text-align:center;">Correct</th><th style="padding:6px 10px;text-align:right;">% off</th>
          <th style="padding:6px 10px;text-align:right;">Score</th><th style="padding:6px 10px;">Resolved</th>
          <th style="padding:6px 10px;">Thesis</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`
    : `<div class="empty"><div class="empty-icon">&#128202;</div>${_oracleHistoryFilter ? 'No resolved calls for this analyst yet.' : 'No resolved calls yet — run a round, then Resolve due now once horizons arrive.'}</div>`}`;
}
window.oracleLoadResults = oracleLoadResults;
