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

/* ── 🔮 OPEN CALLS — grouped by asset, rung chips + resolve countdowns ────── */
async function oracleLoadOpen() {
  const pane = document.getElementById('pane-oracle-open');
  let d;
  const q = '/api/oracle/predictions?status=open&limit=300' + (_oracleHistoryFilter ? '&agent_id=' + encodeURIComponent(_oracleHistoryFilter) : '');
  try { d = await api(q); }
  catch (e) { pane.innerHTML = `<div class="empty"><div class="empty-icon">&#10060;</div>${esc(e.message)}</div>`; return; }
  const preds = d.predictions || [];

  // group by asset; inside an asset keep each analyst's ladder together, short rungs first
  const byAsset = {};
  preds.forEach(p => (byAsset[p.asset] = byAsset[p.asset] || []).push(p));
  const assetKeys = Object.keys(byAsset).sort((a, b) => {
    const soon = k => Math.min(...byAsset[k].map(p => new Date(String(p.resolve_at || '9999').replace(' ', 'T')).getTime() || Infinity));
    return soon(a) - soon(b);
  });

  const cards = assetKeys.map(asset => {
    const ps = byAsset[asset].slice().sort((a, b) =>
      (a.agent_name || '').localeCompare(b.agent_name || '')
      || String(b.batch_id || '').localeCompare(String(a.batch_id || ''))
      || (a.horizon_days || 0) - (b.horizon_days || 0));
    const rows = ps.map((p, i) => {
      const newLadder = i === 0 || ps[i - 1].agent_name !== p.agent_name || ps[i - 1].batch_id !== p.batch_id;
      return `
      <tr style="border-top:1px ${newLadder ? 'solid' : 'dashed'} var(--border);vertical-align:top;${newLadder ? '' : 'opacity:.92;'}">
        <td style="padding:6px 10px;font-weight:600;">${newLadder ? esc(p.agent_name || '') : ''}</td>
        <td style="padding:6px 10px;white-space:nowrap;">${_orRungChip(p.horizon_days)}</td>
        <td style="padding:6px 10px;">${_orDir(p.direction)}</td>
        <td style="padding:6px 10px;white-space:nowrap;">${_orUsd(p.current_value)} <span style="color:var(--muted);">&rarr;</span> <b>${_orUsd(p.target_value)}</b></td>
        <td style="padding:6px 10px;white-space:nowrap;">${_orCountdown(p.resolve_at)} <span style="color:var(--muted);font-size:.66rem;">${_orDate(p.resolve_at)}</span></td>
        <td style="padding:6px 10px;min-width:110px;">${_orConfBar(p.confidence)}</td>
        <td style="padding:6px 10px;max-width:280px;">${newLadder ? _orThesis(p) : ''}</td>
      </tr>`;
    }).join('');
    const chips = [...new Set(ps.map(p => p.horizon_days))].sort((a, b) => a - b).map(_orRungChip).join(' ');
    return `
    <div class="settings-group" style="max-width:1000px;overflow-x:auto;margin-bottom:14px;">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">
        ${_orAssetBadge(asset, ps[0].market)}
        <span style="font-size:.72rem;color:var(--muted);">${ps.length} open call(s)</span>
        <span style="display:flex;gap:4px;">${chips}</span>
      </div>
      <table style="width:100%;border-collapse:collapse;font-size:.8rem;">
        <thead><tr style="text-align:left;color:var(--muted);font-size:.66rem;text-transform:uppercase;letter-spacing:.04em;">
          <th style="padding:5px 10px;">Analyst</th><th style="padding:5px 10px;">Rung</th>
          <th style="padding:5px 10px;">Call</th><th style="padding:5px 10px;">Target</th>
          <th style="padding:5px 10px;">Resolves</th><th style="padding:5px 10px;">Confidence</th>
          <th style="padding:5px 10px;">Thesis</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
  }).join('');

  pane.innerHTML = `
    <div class="section-header">
      <div><div class="section-title">&#128302; Open calls</div>
        <div class="section-sub">Live forecast ladders grouped by asset &mdash; each rung (1d/3d/5d/1w/2w) resolves
          independently; soonest-resolving asset first.</div></div>
      <button class="btn-sm" onclick="_oracleLoaded.open=false;oracleSub('open')">&#8635; Refresh</button>
    </div>
    ${_orFilterBanner()}
    ${preds.length ? cards
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
      <td style="padding:7px 10px;white-space:nowrap;">${_orRungChip(p.horizon_days)}</td>
      <td style="padding:7px 10px;white-space:nowrap;">${_orDir(p.direction)} ${_orUsd(p.target_value)}</td>
      <td style="padding:7px 10px;white-space:nowrap;"><b>${_orUsd(p.actual_value)}</b></td>
      <td style="padding:7px 10px;text-align:center;color:${cCol};font-weight:700;">${correct ? '&#10003;' : '&#10007;'}</td>
      <td style="padding:7px 10px;text-align:right;color:var(--muted);">${p.rel_error != null ? _orPct(p.rel_error * 100, 1) : '—'}</td>
      <td style="padding:7px 10px;text-align:right;font-weight:700;color:${sCol};">${score > 0 ? '+' : ''}${score.toFixed(1)}</td>
      <td style="padding:7px 10px;color:var(--muted);white-space:nowrap;">${_orDate(p.resolved_at)}</td>
      <td style="padding:7px 10px;max-width:280px;">${_orThesis(p)}</td>
    </tr>`;
  }).join('');

  // per-rung accuracy strip across whatever is loaded (respects the analyst filter)
  const rungAgg = {};
  preds.forEach(p => {
    const k = p.horizon_days;
    rungAgg[k] = rungAgg[k] || { n: 0, c: 0 };
    rungAgg[k].n++; if (p.correct) rungAgg[k].c++;
  });
  const rungStrip = Object.keys(rungAgg).map(Number).sort((a, b) => a - b).map(h => {
    const r = rungAgg[h], pct = Math.round(100 * r.c / r.n);
    const col = pct >= 50 ? 'var(--green)' : 'var(--red)';
    return `<span style="font-size:.72rem;color:var(--muted);" title="${r.c}/${r.n} correct at ${_orRungLabel(h)}">
      ${_orRungChip(h)} <b style="color:${col};">${pct}%</b> <span style="font-size:.62rem;">(${r.n})</span></span>`;
  }).join(' ');

  pane.innerHTML = `
    <div class="section-header">
      <div><div class="section-title">&#128202; Results</div>
        <div class="section-sub">Resolved calls, scored per rung on direction + horizon-scaled closeness.</div></div>
      <button class="btn-sm" onclick="_oracleLoaded.results=false;oracleSub('results')">&#8635; Refresh</button>
    </div>
    ${_orFilterBanner()}
    ${rungStrip ? `<div style="display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin-bottom:12px;">
      <span style="font-size:.7rem;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;">Accuracy by rung</span>
      ${rungStrip}</div>` : ''}
    ${preds.length ? `
    <div class="settings-group" style="max-width:1000px;overflow-x:auto;">
      <table style="width:100%;border-collapse:collapse;font-size:.8rem;">
        <thead><tr style="text-align:left;color:var(--muted);font-size:.66rem;text-transform:uppercase;letter-spacing:.04em;">
          <th style="padding:6px 10px;">Analyst</th><th style="padding:6px 10px;">Asset</th>
          <th style="padding:6px 10px;">Rung</th>
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
