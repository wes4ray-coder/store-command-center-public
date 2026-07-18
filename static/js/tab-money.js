/* ══ MONEY TAB ══
   Real-dollar mission control. Demand signals (shop searches) flow in via
   /api/money/signals; "Run Company Review" has the LLM compare them to the
   current catalog and propose money missions (product gaps, online income,
   carpentry leads). Missions follow an approve/reject/done queue, and an
   approved mission is announced into The Company world. */

let _moSignals = [];
let _moMissions = [];
let _moFilter = 'all';

const MO_KINDS = {
  product_gap:    { icon: '&#128161;', label: 'Product gap',    color: 'var(--accent)' },
  online_income:  { icon: '&#127760;', label: 'Online income',  color: 'var(--accent2)' },
  carpentry_lead: { icon: '&#128296;', label: 'Carpentry lead', color: 'var(--warn)' },
  other:          { icon: '&#10024;',  label: 'Other',          color: 'var(--muted)' },
};
function _moKind(k) { return MO_KINDS[k] || MO_KINDS.other; }
function _moUsd(cents) { return '$' + ((cents || 0) / 100).toLocaleString(undefined, { maximumFractionDigits: 0 }); }

async function renderMoney() {
  document.getElementById('main-content').innerHTML = `
    <div class="view-header">
      <div class="view-title">&#128176; Money</div>
      <div class="view-sub">Real-dollar mission control &mdash; shop demand signals reviewed by the company
        into product gaps, online income ideas &amp; carpentry leads. Approve the ones worth chasing.</div>
    </div>
    <div class="stats-row" id="money-stats"></div>
    <div id="money-signals" style="margin-bottom:18px;"></div>
    <div id="money-add" style="margin-bottom:18px;"></div>
    <div id="money-missions"></div>`;
  await loadMoStats();
  await loadMoSignals();
  renderMoAdd();
  await loadMoMissions();
}
window.renderMoney = renderMoney;

/* ── stats strip ──────────────────────────────────────────────────────────── */
async function loadMoStats() {
  const el = document.getElementById('money-stats');
  if (!el) return;
  let s = {};
  try { s = await api('/api/money/stats'); } catch { el.innerHTML = ''; return; }
  const m = s.missions || {};
  el.innerHTML = `
    <div class="stat-card"><div class="stat-label">Proposed missions</div>
      <div class="stat-val c-warn">${m.proposed || 0}</div></div>
    <div class="stat-card"><div class="stat-label">Approved</div>
      <div class="stat-val c-green">${m.approved || 0}</div></div>
    <div class="stat-card"><div class="stat-label">Est. pipeline</div>
      <div class="stat-val c-accent">${_moUsd(s.pipeline_value_cents)}</div></div>
    <div class="stat-card"><div class="stat-label">New signals</div>
      <div class="stat-val c-accent2">${(s.signals || {}).new || 0}</div></div>`;
}

/* ── demand signals ───────────────────────────────────────────────────────── */
async function loadMoSignals() {
  const el = document.getElementById('money-signals');
  if (!el) return;
  let data;
  try { data = await api('/api/money/signals?limit=50'); }
  catch (e) { el.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  _moSignals = data.signals || [];
  const newCount = (data.counts || {}).new || 0;
  el.innerHTML = `
    <div class="card" style="padding:16px 18px;">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;flex-wrap:wrap;gap:8px;">
        <div style="font-weight:700;font-size:1rem;">&#128269; Demand Signals
          <span style="font-size:.72rem;color:var(--muted);font-weight:400;">(${newCount} new)</span>
          ${hlp('Shop search queries reported by the storefront (POST /api/money/signals with the X-Money-Token header). The company review compares NEW signals against the current catalog to find products we should carry but do not.')}</div>
        <button class="btn-sm primary" id="mo-review-btn" onclick="moRunReview()" ${newCount ? '' : 'disabled'}
          title="Send all NEW signals + the current catalog to the LLM once; it proposes money missions (demand gaps and other leads) and marks the signals reviewed.">&#9654; Run Company Review</button>
        <button class="btn-sm" id="mo-hunt-btn" onclick="moHuntLeads()"
          title="Sweep the local searxng meta-search for local carpentry work leads, screen them with the LLM, and propose carpentry_lead missions. Queries customizable via setting money_lead_queries.">&#128296; Hunt Carpentry Leads</button>
      </div>
      ${_moSignals.length ? `
      <div style="overflow-x:auto"><table style="width:100%;font-size:.78rem;border-collapse:collapse;">
        <thead><tr style="text-align:left;color:var(--muted);font-size:.68rem;text-transform:uppercase;letter-spacing:.04em;">
          <th style="padding:6px 8px;">Query</th><th style="padding:6px 8px;">Source</th>
          <th style="padding:6px 8px;">Results</th><th style="padding:6px 8px;">Status</th>
          <th style="padding:6px 8px;">When</th></tr></thead>
        <tbody>${_moSignals.map(s => `
          <tr style="border-top:1px solid var(--border,#3333);">
            <td style="padding:6px 8px;">${esc(s.query || '')}</td>
            <td style="padding:6px 8px;color:var(--muted);">${esc(s.source || '')}</td>
            <td style="padding:6px 8px;${(s.results_count || 0) === 0 ? 'color:var(--warn);font-weight:600;' : ''}">${s.results_count || 0}</td>
            <td style="padding:6px 8px;">${s.status === 'new'
              ? '<span style="color:var(--accent2);">new</span>'
              : `<span style="color:var(--muted);">${esc(s.status)}</span>`}</td>
            <td style="padding:6px 8px;color:var(--muted);white-space:nowrap;">${esc((s.created_at || '').slice(0, 16))}</td>
          </tr>`).join('')}
        </tbody></table></div>`
      : `<div style="color:var(--muted);font-size:.8rem;">No signals yet &mdash; the storefront reports searches here as shoppers look for things.</div>`}
    </div>`;
}

async function moRunReview() {
  const btn = document.getElementById('mo-review-btn');
  const orig = btn.innerHTML;
  btn.disabled = true; btn.innerHTML = '⏳ Reviewing…';
  try {
    const { task_id } = await api('/api/money/review', { method: 'POST', body: JSON.stringify({}) });
    const r = await pollTask(task_id, 120);
    toast(`💰 Review done — ${r && r.proposed != null ? r.proposed : '?'} mission(s) proposed`);
  } catch (e) { toast('Review failed: ' + e.message, 'error'); }
  btn.disabled = false; btn.innerHTML = orig;
  await loadMoStats(); await loadMoSignals(); await loadMoMissions();
}

async function moHuntLeads() {
  const btn = document.getElementById('mo-hunt-btn');
  const orig = btn.innerHTML;
  btn.disabled = true; btn.innerHTML = '⏳ Hunting…';
  try {
    const r0 = await api('/api/money/leads/hunt', { method: 'POST', body: JSON.stringify({}) });
    if (r0.task_id == null) {
      toast(`🔨 ${r0.note || 'No fresh leads found'} (${r0.results || 0} results)`);
    } else {
      const r = await pollTask(r0.task_id, 180);
      toast(`🔨 Lead hunt done — ${r && r.proposed != null ? r.proposed : '?'} lead(s) proposed from ${r0.fresh} fresh results`);
    }
  } catch (e) { toast('Lead hunt failed: ' + e.message, 'error'); }
  btn.disabled = false; btn.innerHTML = orig;
  await loadMoStats(); await loadMoMissions();
}

/* ── add mission (manual, e.g. a carpentry lead idea) ─────────────────────── */
function renderMoAdd() {
  const el = document.getElementById('money-add');
  if (!el) return;
  el.innerHTML = `
    <details class="settings-group">
      <summary style="cursor:pointer;font-weight:600;font-size:.9rem;">&#10133; Add mission</summary>
      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;margin-top:12px;">
        <div class="field" style="margin:0;">
          <label style="font-size:.72rem;">Kind ${hlp('What kind of money-maker this is. carpentry_lead is for local Acme Carpentry work (your local area).')}</label>
          <select id="mo-add-kind">
            <option value="product_gap">&#128161; Product gap</option>
            <option value="online_income">&#127760; Online income</option>
            <option value="carpentry_lead">&#128296; Carpentry lead</option>
            <option value="other" selected>&#10024; Other</option>
          </select>
        </div>
        <div class="field" style="margin:0;flex:1;min-width:200px;">
          <label style="font-size:.72rem;">Title</label>
          <input type="text" id="mo-add-title" placeholder="e.g. Deck repair leads — post in your town FB groups">
        </div>
        <div class="field" style="margin:0;flex:2;min-width:240px;">
          <label style="font-size:.72rem;">Detail</label>
          <input type="text" id="mo-add-detail" placeholder="What to do &amp; why it will earn">
        </div>
        <div class="field" style="margin:0;width:110px;">
          <label style="font-size:.72rem;">Est. $ ${hlp('Rough dollar value of this mission if it lands. Feeds the pipeline total in the stats strip.')}</label>
          <input type="number" id="mo-add-value" min="0" step="1" placeholder="0">
        </div>
        <button class="btn-sm primary" onclick="moAddMission()">&#128190; Add</button>
      </div>
    </details>`;
}

async function moAddMission() {
  const title = document.getElementById('mo-add-title').value.trim();
  if (!title) { toast('Give the mission a title', 'error'); return; }
  const payload = {
    kind: document.getElementById('mo-add-kind').value,
    title,
    detail: document.getElementById('mo-add-detail').value.trim(),
    est_value_cents: Math.round((parseFloat(document.getElementById('mo-add-value').value) || 0) * 100),
  };
  try {
    await api('/api/money/missions', { method: 'POST', body: JSON.stringify(payload) });
    toast('✅ Mission added');
    ['mo-add-title', 'mo-add-detail', 'mo-add-value'].forEach(id => { const e = document.getElementById(id); if (e) e.value = ''; });
    await loadMoStats(); await loadMoMissions();
  } catch (e) { toast('Add failed: ' + e.message, 'error'); }
}

/* ── missions queue ───────────────────────────────────────────────────────── */
async function loadMoMissions() {
  const el = document.getElementById('money-missions');
  if (!el) return;
  let data;
  try { data = await api('/api/money/missions'); }
  catch (e) { el.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  _moMissions = data.missions || [];
  const c = data.counts || {};
  const tabs = [['all', 'All', _moMissions.length], ['proposed', 'Proposed', c.proposed || 0],
                ['approved', 'Approved', c.approved || 0], ['done', 'Done', c.done || 0],
                ['rejected', 'Rejected', c.rejected || 0]];
  const shown = _moFilter === 'all' ? _moMissions : _moMissions.filter(m => m.status === _moFilter);
  el.innerHTML = `
    <div style="font-weight:700;font-size:1rem;margin-bottom:10px;">&#128176; Money Missions
      ${hlp('The queue of real-dollar leads. Approve a mission to greenlight it (a Company agent is assigned and it is announced in the town), mark it Done when it earned (record the result), or Reject it.')}</div>
    <div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;">
      ${tabs.map(([k, l, n]) => `<button class="btn-sm ${k === _moFilter ? 'primary' : ''}" onclick="moSetFilter('${k}')">${l} (${n})</button>`).join('')}
    </div>
    ${shown.length ? `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px;">${shown.map(moCardHtml).join('')}</div>`
      : `<div class="empty"><div class="empty-icon">&#128176;</div>No ${_moFilter === 'all' ? '' : _moFilter} missions yet &mdash; run a company review or add one above.</div>`}`;
}
function moSetFilter(f) { _moFilter = f; loadMoMissions(); }

function moCardHtml(m) {
  const k = _moKind(m.kind);
  const statusChip = {
    proposed: '<span style="color:var(--warn);">&#9203; proposed</span>',
    approved: '<span style="color:var(--green,#22c55e);">&#9989; approved</span>',
    rejected: '<span style="color:var(--red,#ef4444);">&#10060; rejected</span>',
    done:     '<span style="color:var(--accent);">&#127942; done</span>',
  }[m.status] || `<span style="color:var(--muted);">${esc(m.status)}</span>`;
  const btns =
    m.status === 'proposed' ? `
      <button class="btn-sm success" onclick="moApprove(${m.id})" title="Greenlight this mission — a Company agent is assigned and the town is told.">&#10003; Approve</button>
      <button class="btn-sm danger" onclick="moReject(${m.id})">&#10005; Reject</button>`
    : m.status === 'approved' ? `
      <button class="btn-sm success" onclick="moDone(${m.id})" title="Mark this mission complete and record what it earned / what happened.">&#127942; Done</button>
      <button class="btn-sm danger" onclick="moReject(${m.id})">&#10005; Reject</button>`
    : '';
  return `
    <div class="card" style="padding:12px 14px;display:flex;flex-direction:column;gap:8px;">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">
        <span style="font-size:.68rem;font-weight:700;color:${k.color};border:1px solid ${k.color};
          border-radius:12px;padding:2px 9px;white-space:nowrap;">${k.icon} ${k.label}</span>
        <span style="font-size:.72rem;">${statusChip}</span>
      </div>
      <div style="font-weight:600;font-size:.9rem;line-height:1.35;">${esc(m.title || '')}</div>
      ${m.detail ? `<div style="font-size:.78rem;color:var(--muted);line-height:1.45;">${esc(m.detail)}</div>` : ''}
      <div style="display:flex;justify-content:space-between;align-items:center;font-size:.72rem;color:var(--muted);">
        <span>${m.est_value_cents ? `est. <b style="color:var(--accent);">${_moUsd(m.est_value_cents)}</b>` : ''}</span>
        <span>${m.agent ? `&#128100; ${esc(m.agent)}` : ''}</span>
      </div>
      ${m.result ? `<div style="font-size:.74rem;color:var(--accent2);">&#128221; ${esc(m.result)}</div>` : ''}
      ${btns ? `<div style="display:flex;gap:6px;flex-wrap:wrap;border-top:1px solid var(--border,#3333);padding-top:8px;">${btns}</div>` : ''}
    </div>`;
}

async function moApprove(id) {
  try { await api(`/api/money/missions/${id}/approve`, { method: 'POST', body: JSON.stringify({}) });
    toast('✅ Mission approved'); await loadMoStats(); await loadMoMissions(); }
  catch (e) { toast('Approve failed: ' + e.message, 'error'); }
}
async function moReject(id) {
  if (!confirm('Reject this mission?')) return;
  try { await api(`/api/money/missions/${id}/reject`, { method: 'POST', body: JSON.stringify({}) });
    toast('Rejected'); await loadMoStats(); await loadMoMissions(); }
  catch (e) { toast('Reject failed: ' + e.message, 'error'); }
}
async function moDone(id) {
  const result = prompt('What happened / what did it earn?') || '';
  try { await api(`/api/money/missions/${id}/done`, { method: 'POST', body: JSON.stringify({ result }) });
    toast('🏆 Marked done'); await loadMoStats(); await loadMoMissions(); }
  catch (e) { toast('Failed: ' + e.message, 'error'); }
}

window.moRunReview = moRunReview;
window.moAddMission = moAddMission;
window.moSetFilter = moSetFilter;
window.moApprove = moApprove;
window.moReject = moReject;
window.moDone = moDone;
