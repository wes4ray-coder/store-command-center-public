/* Restored from pre_unification_backup (Jul 9) — real tab implementation.
   Part of the modular frontend: one file per tab. */
// Shared helpers used by multiple tab modules.
async function pollTask(taskId, maxTries = 30) {
  for (let i = 0; i < maxTries; i++) {
    await new Promise(r => setTimeout(r, 2000));
    const t = await api(`/api/task/${taskId}`);
    if (t.status === 'done')  return t.result;
    if (t.status === 'error') throw new Error(t.error || 'Task failed');
  }
  throw new Error('Timeout');
}

/* ── PERSISTENT PROMPT ENHANCEMENT ──
   Enhance runs server-side as an orchestrator task (a task_id, pollable via
   /api/task/{id} even after it finishes and kept ~last-50). We remember the pending
   task_id per target field in localStorage, so you can switch tabs — or reload — and
   come back: the tab re-attaches, shows "enhancing…", and drops the result into the
   field (or restores an already-finished one). Used by image / audio / 3D enhancers.

   setBusy(on) must look the button/status element up by id at call time (not capture
   it), so it keeps working after the tab re-renders. */
const _ENHANCE_KEY = 'store_pending_enhance';
const _enhanceActive = {};   // fieldId -> true while a poll loop owns it

const _ENHANCE_MAX_AGE = 6 * 3600 * 1000;   // forget a stash older than 6h
function _enhMap()   { try { return JSON.parse(localStorage.getItem(_ENHANCE_KEY) || '{}'); } catch { return {}; } }
function _enhSave(m) { try { localStorage.setItem(_ENHANCE_KEY, JSON.stringify(m)); } catch {} }
function _enhRemember(fieldId, rec) {
  const m = _enhMap();
  if (rec) m[fieldId] = rec; else delete m[fieldId];
  _enhSave(m);
}
function _enhText(res) {
  return (typeof res === 'string') ? res
       : (res && (res.enhanced || res.prompt || res.enhanced_prompt || res.text)) || '';
}
// Drop the result into the field if it's on screen; returns whether it applied.
function _enhApply(fieldId, text) {
  const el = document.getElementById(fieldId);
  if (el && text) { el.value = text; el.dispatchEvent(new Event('input', { bubbles: true })); return true; }
  return false;
}

async function _enhPoll(fieldId, taskId, setBusy, maxTries = 120) {
  if (_enhanceActive[fieldId]) { if (setBusy) setBusy(true); return; }  // already polling; just refresh UI
  _enhanceActive[fieldId] = true;
  if (setBusy) setBusy(true);
  try {
    for (let i = 0; i < maxTries; i++) {
      await new Promise(r => setTimeout(r, 2000));
      let t;
      try { t = await api(`/api/task/${taskId}`); } catch { continue; }
      if (t.status === 'done') {
        const text = _enhText(t.result);
        if (_enhApply(fieldId, text)) {
          _enhRemember(fieldId, null);
          if (setBusy) setBusy(false);
          if (text) toast('✨ Prompt enhanced!');
        } else {
          // finished while we're away — STASH the result so enhanceResume() applies it on return
          _enhRemember(fieldId, { taskId, ts: Date.now(), done: true, result: text });
          if (setBusy) setBusy(false);
        }
        return;
      }
      if (t.status === 'error') throw new Error(t.error || 'Enhancement failed');
      if (t.status === 'not_found' || t.status === 'cancelled') { _enhRemember(fieldId, null); if (setBusy) setBusy(false); return; }
    }
    throw new Error('Enhancement timed out');
  } catch (e) {
    _enhRemember(fieldId, null);
    if (setBusy) setBusy(false);
    if (document.getElementById(fieldId)) toast('Enhance failed: ' + e.message, 'error');
  } finally {
    _enhanceActive[fieldId] = false;
  }
}

// Start a new enhancement. submitFn: async () => task_id. Fire-and-forget: survives nav.
async function enhanceStart(fieldId, submitFn, setBusy) {
  if (_enhanceActive[fieldId]) { toast('Already enhancing…'); return; }
  if (setBusy) setBusy(true);
  let taskId;
  try { taskId = await submitFn(); }
  catch (e) { if (setBusy) setBusy(false); toast('Enhance failed: ' + e.message, 'error'); return; }
  if (taskId == null) { if (setBusy) setBusy(false); toast('Enhance failed: no task', 'error'); return; }
  _enhRemember(fieldId, { taskId, ts: Date.now() });
  _enhPoll(fieldId, taskId, setBusy);
}

// Call on tab render: re-attach to a pending enhancement, or apply one that finished
// while this tab was closed.
function enhanceResume(fieldId, setBusy) {
  const rec = _enhMap()[fieldId];
  if (!rec) return;
  if (rec.ts && (Date.now() - rec.ts) > _ENHANCE_MAX_AGE) { _enhRemember(fieldId, null); return; }
  if (rec.done) {                              // finished while away → apply now
    if (_enhApply(fieldId, rec.result) && rec.result) toast('✨ Prompt enhanced!');
    _enhRemember(fieldId, null);
    if (setBusy) setBusy(false);
    return;
  }
  if (rec.taskId != null) _enhPoll(fieldId, rec.taskId, setBusy);   // still running → keep polling
}

// Restart the backend server, then wait for it to come back and reload the page.
async function systemRestart() {
  let busy = { busy: false, total: 0, jobs: [] };
  try { busy = await api('/api/system/gpu-status'); } catch {}
  let force = false;
  if (busy.busy) {
    const detail = (busy.jobs || []).map(j => `${j.count} ${j.kind}`).join(', ') || `${busy.total} job(s)`;
    if (!confirm(`⚠️ ${busy.total} GPU job(s) in flight (${detail}).\n\nRestarting will KILL them (they'll be marked failed). Restart anyway?`)) return;
    force = true;
  } else if (!confirm('Restart the Store server? The app will be unavailable for a few seconds.')) {
    return;
  }
  try {
    await api('/api/system/restart', { method: 'POST', body: JSON.stringify({ force }) });
  } catch (e) { /* connection may drop as the server exits — that's expected */ }
  toast('Restarting server…');
  // Poll until the server answers again, then reload.
  let tries = 0;
  const wait = setInterval(async () => {
    tries++;
    try {
      await api('/api/status');
      clearInterval(wait);
      toast('Server is back — reloading');
      setTimeout(() => location.reload(), 600);
    } catch {
      if (tries > 30) { clearInterval(wait); toast('Server did not come back — check logs', 'error'); }
    }
  }, 1000);
}
window.systemRestart = systemRestart;
