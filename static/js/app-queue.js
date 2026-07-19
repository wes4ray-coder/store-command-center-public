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
    <div class="queue-pop" id="studio-queue-list" style="max-height:none;"></div>`;
  loadQueue();   // fills #studio-queue-list + sets the paused/running button state; 4s poller keeps it live
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
