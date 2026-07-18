/* Library management: auto-populate (import + AI generate), audit (health + AI gaps),
   and per-doc detail triggers (metadata, enrich, summarize). */

/* ── Manage panel ─────────────────────────────────────────────────────────── */
function libManage() {
  const el = document.getElementById('lib-content');
  const bread = document.getElementById('lib-breadcrumbs');
  if (bread) bread.innerHTML = '<span style="color:var(--muted);">Library</span> &gt; Manage';
  el.innerHTML = `
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:16px;">
      <button class="btn-sm" onclick="libShowSections()">&larr; Back</button>
      <span style="font-weight:600;font-size:1.1rem;">&#9881;&#65039; Manage Library</span>
    </div>
    <div class="settings-grid">
      <div class="settings-group">
        <div class="settings-group-title">&#128229; Auto-populate</div>
        <p style="color:var(--muted);font-size:.8rem;margin-bottom:10px;">Import loose markdown from the store folder into the library.</p>
        <button class="btn-sm primary" id="lm-import" onclick="libImport()">Import from folder</button>
        <div id="lm-import-msg" style="font-size:.78rem;margin-top:8px;color:var(--muted);"></div>
        <div style="border-top:1px solid var(--border);margin:14px 0;"></div>
        <p style="color:var(--muted);font-size:.8rem;margin-bottom:8px;">Or generate guides with the local model (one topic per line):</p>
        <textarea id="lm-topics" placeholder="e.g.\nHardening Pi-hole DHCP\nBackup & restore the store" style="width:100%;min-height:70px;padding:8px;background:var(--surface2);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:.82rem;"></textarea>
        <button class="btn-sm" id="lm-gen" onclick="libGenerateBatch()" style="margin-top:8px;">&#129302; Generate guides</button>
        <div id="lm-gen-msg" style="font-size:.78rem;margin-top:8px;color:var(--muted);"></div>
      </div>
      <div class="settings-group">
        <div class="settings-group-title">&#128269; Audit</div>
        <div id="lm-audit"><div class="loading-state">Loading health report…</div></div>
        <button class="btn-sm" id="lm-audit-ai" onclick="libAuditAI()" style="margin-top:10px;">&#129302; AI gap analysis</button>
        <div id="lm-audit-ai-msg" style="font-size:.78rem;margin-top:8px;color:var(--muted);"></div>
      </div>
    </div>`;
  libLoadAudit();
}
window.libManage = libManage;

async function libImport() {
  const msg = document.getElementById('lm-import-msg');
  const btn = document.getElementById('lm-import');
  btn.disabled = true; btn.textContent = '⏳ Importing…';
  try {
    const r = await api('/api/library/import', { method: 'POST', body: JSON.stringify({}) });
    msg.style.color = 'var(--green)';
    msg.innerHTML = `&#10003; Imported ${r.count} doc(s)${r.skipped ? ', ' + r.skipped + ' unchanged' : ''}. Under the <b>imported</b> category.`;
    toast(`Imported ${r.count} docs`);
    libLoadAudit();
  } catch (e) { msg.style.color = 'var(--warn)'; msg.textContent = 'Error: ' + e.message; }
  finally { btn.disabled = false; btn.textContent = 'Import from folder'; }
}
window.libImport = libImport;

async function libGenerateBatch() {
  const topics = document.getElementById('lm-topics').value.split('\n').map(t => t.trim()).filter(Boolean);
  const msg = document.getElementById('lm-gen-msg');
  const btn = document.getElementById('lm-gen');
  if (!topics.length) { msg.textContent = 'Enter at least one topic.'; return; }
  btn.disabled = true;
  let done = 0;
  for (const topic of topics) {
    msg.style.color = 'var(--muted)';
    msg.textContent = `Generating ${done + 1}/${topics.length}: ${topic}…`;
    try {
      await api('/api/library/guide', { method: 'POST', body: JSON.stringify({ topic, category: 'guides' }) });
      done++;
    } catch (e) { msg.style.color = 'var(--warn)'; msg.textContent = `Failed on "${topic}": ${e.message}`; break; }
  }
  if (done === topics.length) { msg.style.color = 'var(--green)'; msg.textContent = `✓ Generated ${done} guide(s).`; toast(`Generated ${done} guides`); }
  btn.disabled = false;
}
window.libGenerateBatch = libGenerateBatch;

async function libLoadAudit() {
  const el = document.getElementById('lm-audit');
  if (!el) return;
  try {
    const a = await api('/api/library/audit');
    const cats = Object.entries(a.categories || {}).map(([c, n]) =>
      `<div style="display:flex;justify-content:space-between;"><span>${esc(c)}</span><span style="color:var(--muted)">${n}</span></div>`).join('');
    el.innerHTML = `
      <div style="font-size:.82rem;">
        <div style="margin-bottom:8px;"><b>${a.total}</b> documents across <b>${Object.keys(a.categories||{}).length}</b> categories</div>
        <div style="display:flex;flex-direction:column;gap:2px;margin-bottom:10px;">${cats}</div>
        <div style="color:var(--muted);font-size:.76rem;line-height:1.6;">
          ${a.empty_categories.length ? '⚠️ Empty: ' + a.empty_categories.map(esc).join(', ') + '<br>' : ''}
          ${a.tiny_docs.length ? '📄 ' + a.tiny_docs.length + ' very small doc(s)<br>' : ''}
          ${a.duplicates.length ? '👯 ' + a.duplicates.length + ' duplicate(s)<br>' : ''}
          ${a.duplicates.length || a.tiny_docs.length || a.empty_categories.length ? '' : '✅ No issues found'}
        </div>
      </div>`;
  } catch (e) { el.innerHTML = `<div style="color:var(--warn);">${esc(e.message)}</div>`; }
}
window.libLoadAudit = libLoadAudit;

async function libAuditAI() {
  const btn = document.getElementById('lm-audit-ai');
  const msg = document.getElementById('lm-audit-ai-msg');
  btn.disabled = true; btn.textContent = '🧠 Analyzing…';
  msg.style.color = 'var(--muted)'; msg.textContent = 'The local model is reviewing the library…';
  try {
    const { task_id } = await api('/api/library/audit/ai', { method: 'POST' });
    const res = await pollTask(task_id, 60);
    toast('Gap analysis saved to library › audits');
    libReadDoc('audits', 'library-gap-analysis.md');
  } catch (e) { msg.style.color = 'var(--warn)'; msg.textContent = 'Error: ' + e.message; }
  finally { btn.disabled = false; btn.innerHTML = '&#129302; AI gap analysis'; }
}
window.libAuditAI = libAuditAI;

/* ── Per-doc detail triggers ──────────────────────────────────────────────── */
async function libDocDetails() {
  if (!_libCurDoc) return;
  let m;
  try { m = await api(`/api/library/meta?category=${encodeURIComponent(_libCurDoc.category)}&path=${encodeURIComponent(_libCurDoc.path)}`); }
  catch (e) { toast('Error: ' + e.message, 'error'); return; }
  const outline = (m.headings || []).map(h => `<div style="padding-left:${(h.level - 1) * 14}px;color:var(--muted);">${esc(h.text)}</div>`).join('');
  const links = (m.links || []).map(l => `<div style="color:var(--muted);">${esc(l.text)} → <span style="color:var(--accent2)">${esc(l.url)}</span></div>`).join('');
  _libModal(`ℹ️ Details`, `
    <div style="font-size:.82rem;line-height:1.7;">
      <div><b>${m.words}</b> words · <b>${m.lines}</b> lines · ${(m.size/1024).toFixed(1)} KB</div>
      <div style="color:var(--muted);">Modified ${esc(new Date(m.modified).toLocaleString())}</div>
      <div style="margin-top:12px;font-weight:600;">Outline (${(m.headings||[]).length})</div>
      <div style="max-height:200px;overflow:auto;font-size:.78rem;">${outline || '<span style="color:var(--muted)">none</span>'}</div>
      ${m.links && m.links.length ? `<div style="margin-top:12px;font-weight:600;">Links (${m.links.length})</div><div style="max-height:160px;overflow:auto;font-size:.75rem;">${links}</div>` : ''}
    </div>`);
}
window.libDocDetails = libDocDetails;

async function libDocEnrich() { _libDocLLM('enrich', '/api/library/enrich', 'Enriching (local model)…'); }
window.libDocEnrich = libDocEnrich;
async function libDocSummarize() { _libDocLLM('summarize', '/api/library/summarize', 'Summarizing (local model)…'); }
window.libDocSummarize = libDocSummarize;

async function _libDocLLM(kind, endpoint, working) {
  if (!_libCurDoc) return;
  if (!confirm(`${kind === 'enrich' ? 'Enrich' : 'Summarize'} this document with the local model? It will be updated in place.`)) return;
  toast(working);
  try {
    const { task_id } = await api(endpoint, { method: 'POST', body: JSON.stringify(_libCurDoc) });
    await pollTask(task_id, 60);
    toast('Done — reloading doc');
    libReadDoc(_libCurDoc.category, _libCurDoc.path);
  } catch (e) { toast('Error: ' + e.message, 'error'); }
}

/* ── tiny modal helper ────────────────────────────────────────────────────── */
function _libModal(title, bodyHtml) {
  document.getElementById('lib-modal')?.remove();
  const o = document.createElement('div');
  o.id = 'lib-modal';
  o.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9999;display:flex;align-items:center;justify-content:center;padding:5vh 3vw;';
  o.onclick = (e) => { if (e.target === o) o.remove(); };
  o.innerHTML = `<div style="background:var(--surface);border:1px solid var(--border);border-radius:12px;max-width:640px;width:100%;max-height:80vh;overflow:auto;padding:20px;box-shadow:0 20px 60px rgba(0,0,0,.5);">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
      <div style="font-weight:600;font-size:1.05rem;">${title}</div>
      <button class="btn-sm" onclick="document.getElementById('lib-modal').remove()">✕</button>
    </div>${bodyHtml}</div>`;
  document.body.appendChild(o);
}
