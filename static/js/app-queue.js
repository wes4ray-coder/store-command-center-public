'use strict';

/* ── UNIVERSAL QUEUE ──
   One live view of every in-flight GPU/generation job (image, video, audio, 3D, LLM),
   fed by GET /api/queue. Rendered in three spots: the bottom-left strip, the header
   pill, and the Studio GPU sub-view (#studio-queue-list). Polled every few seconds. */
const QUEUE_ICON = { image:'\u{1F3A8}', video:'\u{1F3AC}', 'video chain':'\u{1F39E}\u{FE0F}',
                     audio:'\u{1F3B5}', '3d':'\u{1F9E9}', llm:'\u{1F9E0}',
                     // redacted NSFW jobs surface as a discreet generic "Private job"
                     private:'\u{1F512}' };

function queueJobsHtml(jobs) {
  if (!jobs || !jobs.length) return '<div class="q-empty">Nothing running — GPU idle.</div>';
  return jobs.map(j => {
    const pct = (j.progress != null && j.progress !== '') ? ` ${j.progress}%` : '';
    // show the model on LLM jobs as a chip (strip the provider prefix for brevity);
    // other kinds keep their normal detail line
    const mdlShort = j.model ? String(j.model).split('/').pop() : '';
    const chip = mdlShort ? ` <span title="model: ${esc(j.model)}" style="font-size:.62rem;padding:0 5px;border-radius:6px;background:rgba(120,150,205,.18);color:#9fb4d8;white-space:nowrap">${esc(mdlShort)}</span>` : '';
    const det = (!j.model && j.detail) ? ` · ${esc(j.detail)}` : '';
    const state = j.phase === 'running' ? ('run' + pct) : 'queued';
    return `<div class="q-row">
      <span class="q-ico">${QUEUE_ICON[j.kind] || '⚙️'}</span>
      <span class="q-label" title="${esc(j.label || '')}">${esc(j.label || '')}${det}${chip}</span>
      <span class="q-state ${j.phase}">${state}</span>
    </div>`;
  }).join('');
}

let _lastQueue = { jobs: [], counts: { running: 0, queued: 0, total: 0 }, busy: false };

async function loadQueue() {
  try {
    const q = await api('/api/queue');
    _lastQueue = q;
    const c = q.counts || { running: 0, queued: 0 };
    const base = (c.running || c.queued) ? `${c.running} running · ${c.queued} queued` : 'Idle';
    const label = q.paused ? `⏸ Paused · ${base}` : base;
    _renderQueueControls(!!q.paused);
    _setDot('gpu-dot', q.busy);
    const info = document.getElementById('gpu-strip-info'); if (info) info.textContent = label;
    const list = document.getElementById('gpu-strip-list'); if (list) list.innerHTML = queueJobsHtml(q.jobs);
    _setDot('topbar-gpu-dot', q.busy);
    const tinfo = document.getElementById('topbar-gpu'); if (tinfo) tinfo.textContent = 'GPU ' + label;
    const sv = document.getElementById('studio-queue-list'); if (sv) sv.innerHTML = queueJobsHtml(q.jobs);
    // Recent-completions section (persistent history) in the strip popover —
    // only when the popover is actually open; degrades quietly pre-restart.
    if (list && list.style.display !== 'none') _renderStripHistory(list);
  } catch {
    const info = document.getElementById('gpu-strip-info'); if (info) info.textContent = 'Status unavailable';
    const tinfo = document.getElementById('topbar-gpu');    if (tinfo) tinfo.textContent = 'GPU n/a';
  }
}
function _setDot(id, busy) {
  const d = document.getElementById(id);
  if (d) d.className = 'gpu-dot ' + (busy ? 'busy' : 'active');
}
function toggleQueuePanel() {
  const list = document.getElementById('gpu-strip-list');
  const caret = document.getElementById('gpu-strip-caret');
  if (!list) return;
  const show = list.style.display === 'none';
  list.style.display = show ? 'flex' : 'none';
  if (caret) caret.innerHTML = show ? '▴' : '▾';
  if (show) loadQueue();
}
let _queuePoller = null;
function startQueuePolling() {
  loadQueue();
  if (_queuePoller) clearInterval(_queuePoller);
  // Keep the interval running but no-op while the tab is hidden (mirrors world-tab gating).
  _queuePoller = setInterval(() => { if (!document.hidden) loadQueue(); }, 4000);
}
// Back-compat: older tabs call loadGpuStrip() after an action to refresh the strip.
function loadGpuStrip() { return loadQueue(); }

/* ── QUEUE HISTORY (persistent completions — GET /api/queue/history) ──
   Written by the orchestrator at every terminal transition, so it survives
   restarts. Pre-restart the endpoint 404s: flip _histSupported off and hide
   the section quietly. */
const HIST_MARK = { done: '✓', error: '✕', cancelled: '⊘' };
let _histSupported = true;
let _histCache = null, _histAt = 0;

async function loadQueueHistory(force = false) {
  if (!_histSupported) return null;
  if (!force && _histCache && Date.now() - _histAt < 15000) return _histCache;
  try {
    const h = await api('/api/queue/history?limit=12');
    _histCache = h; _histAt = Date.now();
    return h;
  } catch (e) {
    if (/404|not found/i.test(e.message || '')) _histSupported = false;  // backend not restarted yet
    return null;
  }
}

function _histAgo(iso) {
  if (!iso) return '';
  const t = Date.parse(iso.replace(' ', 'T') + 'Z');   // stored as UTC text
  if (isNaN(t)) return '';
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60)    return 'now';
  if (s < 3600)  return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}
function _histDur(d) {
  if (d == null || d === '') return '';
  if (d < 60) return `${Math.round(d)}s`;
  return `${Math.floor(d / 60)}m ${Math.round(d % 60)}s`;
}
function histRowHtml(r) {
  const mark = HIST_MARK[r.status] || '·';
  const srcChip = r.source ? ` <span style="font-size:.6rem;padding:0 5px;border-radius:6px;background:rgba(120,150,205,.18);color:#9fb4d8;white-space:nowrap">${esc(r.source)}</span>` : '';
  const dur = _histDur(r.duration_s);
  const tip = [r.label, r.model ? `model: ${r.model}` : '', r.error ? `error: ${r.error}` : '',
               dur ? `took ${dur}` : ''].filter(Boolean).join('\n');
  // reuse the .q-state pill: muted for done/cancelled, amber (running style) for errors
  const pillCls = r.status === 'error' ? 'running' : 'queued';
  return `<div class="q-row" title="${esc(tip)}">
    <span class="q-ico">${QUEUE_ICON[r.kind] || '⚙️'}</span>
    <span class="q-label">${esc(r.label || '')}${srcChip}</span>
    <span class="q-state ${pillCls}">${mark} ${_histAgo(r.finished_at)}</span>
  </div>`;
}

// Append/refresh the "Recent" section inside the strip popover (rebuilt every poll).
async function _renderStripHistory(list) {
  const h = await loadQueueHistory();
  if (!h || !_histSupported) return;                      // hide quietly (pre-restart)
  const rows = (h.items || []).slice(0, 8);
  if (!rows.length) return;                               // nothing finished yet — no section
  let sec = document.getElementById('q-hist-strip');
  if (!sec) {
    sec = document.createElement('div');
    sec.id = 'q-hist-strip';
    sec.style.cssText = 'display:flex;flex-direction:column;gap:6px;';
    list.appendChild(sec);
  }
  sec.innerHTML =
    '<div style="font-size:.6rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-top:4px;">Recent</div>'
    + rows.map(histRowHtml).join('');
}

function renderStudioQueue() {
  const root = viewRoot();
  root.innerHTML = `
    <div class="section-header">
      <div>
        <div class="section-title">&#9889; GPU Queue</div>
        <div class="section-sub">Everything generating right now &mdash; image, video, audio, 3D and LLM jobs.</div>
      </div>
      <div class="queue-controls" style="display:flex;gap:8px;align-items:center;">
        <span id="queue-state-badge" class="queue-status-badge idle" style="display:none;"></span>
        <button class="btn-sm" id="q-pause" onclick="queuePause()">&#9208;&#65039; Pause</button>
        <button class="btn-sm primary" id="q-start" onclick="queueResume()" style="display:none;">&#9654;&#65039; Start</button>
        <button class="btn-sm danger" id="q-clear" onclick="queueClear()">&#128465;&#65039; Clear</button>
      </div>
    </div>
    <div class="queue-pop" id="studio-queue-list" style="max-height:none;"></div>
    <div id="studio-hist-wrap" style="display:none;">
      <div class="section-header" style="margin-top:22px;">
        <div>
          <div class="section-title">&#128220; History</div>
          <div class="section-sub">What finished &mdash; persisted across restarts, with who/what asked for it.</div>
        </div>
        <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
          <select id="qh-kind" onchange="loadStudioHistory()">
            <option value="">all kinds</option>
            <option value="llm">&#129504; llm</option><option value="image">&#127912; image</option>
            <option value="video">&#127916; video</option><option value="video chain">&#127902;&#65039; video chain</option>
            <option value="audio">&#127925; audio</option>
          </select>
          <select id="qh-status" onchange="loadStudioHistory()">
            <option value="">all statuses</option>
            <option value="done">&#10003; done</option><option value="error">&#10007; error</option>
            <option value="cancelled">&#8856; cancelled</option>
          </select>
          <select id="qh-source" onchange="loadStudioHistory()"><option value="">all sources</option></select>
          <button class="btn-sm" onclick="loadStudioHistory(true)">&#8635; Refresh</button>
        </div>
      </div>
      <div id="studio-hist-summary" style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px;"></div>
      <div class="queue-pop" id="studio-hist-list" style="max-height:none;"></div>
    </div>`;
  loadQueue();   // fills #studio-queue-list + sets the paused/running button state; 4s poller keeps it live
  loadStudioHistory();
}

// Fuller, filterable history list in the Studio GPU view. Hidden entirely when
// the backend doesn't have the endpoint yet (pre-restart).
async function loadStudioHistory() {
  const wrap = document.getElementById('studio-hist-wrap');
  const box  = document.getElementById('studio-hist-list');
  if (!wrap || !box || !_histSupported) return;
  const qs = new URLSearchParams({ limit: 50 });
  for (const [id, key] of [['qh-kind', 'kind'], ['qh-status', 'status'], ['qh-source', 'source']]) {
    const v = (document.getElementById(id) || {}).value;
    if (v) qs.set(key, v);
  }
  try {
    const h = await api('/api/queue/history?' + qs.toString());
    wrap.style.display = '';
    const items = h.items || [];
    box.innerHTML = items.length ? items.map(histRowHtml).join('')
                                 : '<div class="q-empty">Nothing here yet.</div>';
    // summary chips: per-source counts over the last 24h
    const s = h.summary || {}, bySrc = s.by_source || {}, bySt = s.by_status || {};
    const chip = (t) => `<span style="font-size:.64rem;padding:2px 8px;border-radius:10px;background:var(--surface2);border:1px solid var(--border);color:var(--muted);">${t}</span>`;
    const sum = document.getElementById('studio-hist-summary');
    if (sum) sum.innerHTML =
      chip(`24h &mdash; &#10003; ${bySt.done || 0} &middot; &#10007; ${bySt.error || 0} &middot; &#8856; ${bySt.cancelled || 0}`)
      + Object.entries(bySrc).sort((a, b) => b[1] - a[1]).slice(0, 10)
              .map(([k, v]) => chip(`${esc(k)}: ${v}`)).join('');
    // fill the source filter from the summary (preserve the current pick)
    const sel = document.getElementById('qh-source');
    if (sel && sel.options.length <= 1) {
      const cur = sel.value;
      Object.keys(bySrc).sort().forEach(src => {
        const o = document.createElement('option'); o.value = src; o.textContent = src;
        sel.appendChild(o);
      });
      sel.value = cur;
    }
  } catch (e) {
    if (/404|not found/i.test(e.message || '')) { _histSupported = false; wrap.style.display = 'none'; }
  }
}

// Pause / Start / Clear for the unified queue. Each POSTs, toasts, and refreshes.
async function queuePause() {
  try { await api('/api/queue/pause', { method: 'POST' }); toast('Queue paused — running jobs will finish'); }
  catch (e) { toast('Error: ' + e.message, 'error'); }
  loadQueue();
}
async function queueResume() {
  try { await api('/api/queue/resume', { method: 'POST' }); toast('Queue started'); }
  catch (e) { toast('Error: ' + e.message, 'error'); }
  loadQueue();
}
async function queueClear() {
  if (!confirm('Clear the queue? Cancels every job that is waiting (not the ones already running).')) return;
  try {
    const r = await api('/api/queue/clear', { method: 'POST' });
    const c = r.cleared || {};
    const n = (c.llm || 0) + (c.videos || 0) + (c.video_chains || 0) + (c.audio_clips || 0);
    toast(`Cleared ${n} queued job(s)`);
  } catch (e) { toast('Error: ' + e.message, 'error'); }
  loadQueue();
}
// Reflect paused/running across the Pause/Start buttons + a badge (called from loadQueue).
function _renderQueueControls(paused) {
  const pauseBtn = document.getElementById('q-pause');
  const startBtn = document.getElementById('q-start');
  const badge = document.getElementById('queue-state-badge');
  if (pauseBtn) pauseBtn.style.display = paused ? 'none' : '';
  if (startBtn) startBtn.style.display = paused ? '' : 'none';
  if (badge) {
    badge.style.display = paused ? '' : 'none';
    badge.textContent = paused ? '⏸️ Paused' : '';
    badge.className = 'queue-status-badge ' + (paused ? 'running' : 'idle');
  }
}
