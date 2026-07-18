/* Library: web archive (snapshots + time machine), drop-link with destination,
   and AI-guide research. Snapshots open in an in-store modal (never a redirect). */

function _fmtTs(s) { try { return new Date((s || '').replace(' ', 'T')).toLocaleString(); } catch { return s || ''; } }

/* ── Drop a link → choose destination ─────────────────────────────────────── */
function libDropLink() {
  const el = document.getElementById('lib-content');
  el.innerHTML = `
    <div class="stat-card" style="padding:24px;max-width:640px;">
      <h3 style="margin-bottom:6px;">&#128229; Drop a Link</h3>
      <p style="color:var(--muted);font-size:.85rem;margin-bottom:16px;">Save a page as an offline snapshot, or have the local model rip it into the AI library for recall.</p>
      <input type="text" id="dl-url" placeholder="https://..." style="width:100%;padding:10px;background:var(--surface2);border:1px solid var(--border);border-radius:8px;color:var(--text);margin-bottom:14px;" />
      <div style="display:flex;flex-direction:column;gap:8px;margin-bottom:14px;">
        <label style="display:flex;gap:10px;align-items:flex-start;cursor:pointer;padding:10px;border:1px solid var(--border);border-radius:8px;">
          <input type="radio" name="dl-dest" value="archive" checked style="margin-top:3px;">
          <span><b>&#128452;&#65039; Archive (snapshot)</b><br><span style="color:var(--muted);font-size:.78rem;">Paste a URL — the store saves it automatically (fast fetch → <b>wget</b> → your logged-in browser), viewable offline. Re-saving builds a version history.</span>
          <label style="display:flex;gap:6px;align-items:center;margin-top:6px;font-size:.74rem;color:var(--muted);cursor:pointer;"><input type="checkbox" id="dl-deep"> Use the logged-in Store browser directly (beats Cloudflare; slower)</label></span>
        </label>
        <label style="display:flex;gap:10px;align-items:flex-start;cursor:pointer;padding:10px;border:1px solid var(--border);border-radius:8px;">
          <input type="radio" name="dl-dest" value="ai" style="margin-top:3px;">
          <span><b>&#129504; AI Library (memory &amp; recall)</b><br><span style="color:var(--muted);font-size:.78rem;">Local model converts the page to a clean Markdown doc, searchable in the library.</span></span>
        </label>
        <label style="display:flex;gap:10px;align-items:flex-start;cursor:pointer;padding:10px;border:1px solid var(--border);border-radius:8px;">
          <input type="radio" name="dl-dest" value="upload" style="margin-top:3px;">
          <span><b>&#128196; Upload saved page (.html)</b><br><span style="color:var(--muted);font-size:.78rem;">In your browser: <b>File → Save Page As → “Web Page, HTML only”</b>, then choose the file here. Bypasses Cloudflare/bot-blocks since <i>your</i> browser did the saving. The URL above is optional (used to load images + group versions).</span>
          <input type="file" id="dl-file" accept=".html,.htm,.mhtml" style="margin-top:6px;display:block;font-size:.75rem;color:var(--muted);"></span>
        </label>
      </div>
      <input type="text" id="dl-cat" placeholder="AI library category (optional, default: saved)" style="width:100%;padding:8px 10px;background:var(--surface2);border:1px solid var(--border);border-radius:8px;color:var(--text);margin-bottom:14px;font-size:.82rem;" />
      <div style="display:flex;gap:10px;">
        <button class="btn" id="dl-go" onclick="libDropLinkGo()">Save</button>
        <button class="btn-sm" onclick="libShowSections()">Cancel</button>
      </div>
      <div id="dl-msg" style="font-size:.8rem;margin-top:12px;"></div>
    </div>`;
}
window.libDropLink = libDropLink;

async function libDropLinkGo() {
  const url = document.getElementById('dl-url').value.trim();
  const dest = document.querySelector('input[name="dl-dest"]:checked').value;
  const cat = document.getElementById('dl-cat').value.trim();
  const msg = document.getElementById('dl-msg');
  const btn = document.getElementById('dl-go');
  // URL is required for archive/AI, optional for an uploaded page.
  if (dest !== 'upload' && !/^https?:\/\//.test(url)) { msg.style.color = 'var(--warn)'; msg.textContent = 'Enter a valid http(s) URL.'; return; }
  btn.disabled = true; btn.textContent = dest === 'ai' ? '⏳ Ripping (local model)…' : dest === 'upload' ? '⏳ Uploading…' : '⏳ Capturing…';
  msg.style.color = 'var(--muted)'; msg.textContent = 'Working…';
  try {
    if (dest === 'upload') {
      const f = document.getElementById('dl-file')?.files?.[0];
      if (!f) { throw new Error('Choose the .html file you saved from your browser.'); }
      const fd = new FormData();
      fd.append('file', f);
      if (url) fd.append('url', url);
      const r = await fetch(API + '/api/library/archive/upload', { method: 'POST', body: fd });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || await r.text());
      const j = await r.json();
      toast('Page uploaded: ' + (j.title || f.name));
      libArchiveView();
    } else if (dest === 'archive') {
      const deep = document.getElementById('dl-deep')?.checked || false;
      if (deep) { btn.textContent = '⏳ Rendering in browser…'; }
      const r = await api('/api/library/archive', { method: 'POST', body: JSON.stringify({ url, deep }) });
      toast('Snapshot saved: ' + (r.title || url));
      libArchiveView();
    } else {
      const { task_id } = await api('/api/library/rip', { method: 'POST', body: JSON.stringify({ url, category: cat || 'saved' }) });
      msg.textContent = 'Local model is writing the doc…';
      const res = await pollTask(task_id, 60);   // orchestrator loads model + runs
      const doc = (res && res.doc) || {};
      toast('Ripped to library: ' + (doc.title || url));
      libBrowse(doc.category || 'saved');
    }
  } catch (e) {
    msg.style.color = 'var(--warn)'; msg.textContent = 'Error: ' + e.message;
    btn.disabled = false; btn.textContent = 'Save';
  }
}
window.libDropLinkGo = libDropLinkGo;

/* ── Archive index ────────────────────────────────────────────────────────── */
async function libArchiveView() {
  const el = document.getElementById('lib-content');
  el.innerHTML = '<div class="empty">Loading archive…</div>';
  const bread = document.getElementById('lib-breadcrumbs');
  if (bread) bread.innerHTML = '<span style="color:var(--muted);">Library</span> &gt; Archive';
  let sites = [];
  try { sites = (await api('/api/library/archive')).sites || []; } catch (e) {
    el.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return;
  }
  let h = `<div style="margin-bottom:14px;display:flex;align-items:center;gap:8px;">
      <button class="btn-sm" onclick="libShowSections()">&larr; Back</button>
      <span style="font-weight:600;font-size:1.1rem;">&#128452;&#65039; Web Archive</span>
      <button class="btn-sm" style="margin-left:auto;" onclick="libDropLink()">&#128229; Save a page</button></div>`;
  if (!sites.length) {
    h += `<div class="empty"><div class="empty-icon">&#128452;&#65039;</div>No saved pages yet. Use “Drop Link → Archive”.</div>`;
    el.innerHTML = h; return;
  }
  h += '<div style="display:flex;flex-direction:column;gap:8px;">';
  for (const s of sites) {
    const vtxt = s.versions > 1 ? `${s.versions} versions` : '1 version';
    h += `<div class="stat-card" style="padding:12px 14px;display:flex;align-items:center;gap:12px;">
        <div style="flex:1;min-width:0;cursor:pointer;" onclick="libOpenSnapshot(${JSON.stringify(s.url).replace(/"/g,'&quot;')}, ${s.latest_id})">
          <div style="font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(s.title || s.url)}</div>
          <div style="color:var(--muted);font-size:.72rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(s.url)}</div>
          <div style="color:var(--muted);font-size:.7rem;">${vtxt} &middot; latest ${_fmtTs(s.latest)}</div>
        </div>
        <button class="btn-sm" title="Save new version" onclick='libRecapture(${JSON.stringify(s.url)})'>&#8635;</button>
        <button class="btn-sm" title="View" onclick='libOpenSnapshot(${JSON.stringify(s.url)}, ${s.latest_id})'>&#128065;&#65039;</button>
      </div>`;
  }
  h += '</div>';
  el.innerHTML = h;
}
window.libArchiveView = libArchiveView;

async function libRecapture(url) {
  toast('Capturing new version…');
  try { await api('/api/library/archive', { method: 'POST', body: JSON.stringify({ url }) }); toast('New version saved'); libArchiveView(); }
  catch (e) { toast('Error: ' + e.message, 'error'); }
}
window.libRecapture = libRecapture;

/* ── In-store snapshot viewer + time machine ──────────────────────────────── */
let _snapVersions = [];
let _snapIndex = 0;
let _snapUrl = '';

async function libOpenSnapshot(url, snapshotId) {
  _snapUrl = url;
  try {
    _snapVersions = (await api('/api/library/archive/versions?url=' + encodeURIComponent(url))).versions || [];
  } catch { _snapVersions = []; }
  _snapIndex = Math.max(0, _snapVersions.findIndex(v => v.id === snapshotId));
  if (_snapIndex < 0) _snapIndex = 0;
  _renderSnapModal();
}
window.libOpenSnapshot = libOpenSnapshot;

function _renderSnapModal() {
  document.getElementById('snap-modal')?.remove();
  const v = _snapVersions[_snapIndex];
  if (!v) return;
  const overlay = document.createElement('div');
  overlay.id = 'snap-modal';
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9999;display:flex;align-items:center;justify-content:center;padding:3vh 2vw;';
  overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
  const opts = _snapVersions.map((s, i) =>
    `<option value="${i}" ${i === _snapIndex ? 'selected' : ''}>${_fmtTs(s.captured_at)}</option>`).join('');
  overlay.innerHTML = `
    <div style="background:var(--surface);border:1px solid var(--border);border-radius:12px;width:100%;max-width:1100px;height:100%;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,.5);">
      <div style="display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid var(--border);">
        <div style="flex:1;min-width:0;">
          <div style="font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(v.title || _snapUrl)}</div>
          <div style="color:var(--muted);font-size:.7rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(_snapUrl)}</div>
        </div>
        <button class="btn-sm" title="Older" onclick="libSnapStep(1)" ${_snapIndex >= _snapVersions.length - 1 ? 'disabled' : ''}>&#8592;</button>
        <select onchange="libSnapPick(this.value)" title="Time machine — versions" style="background:var(--surface2);border:1px solid var(--border);border-radius:6px;color:var(--text);padding:5px 8px;font-size:.78rem;">${opts}</select>
        <button class="btn-sm" title="Newer" onclick="libSnapStep(-1)" ${_snapIndex <= 0 ? 'disabled' : ''}>&#8594;</button>
        <span style="font-size:.7rem;color:var(--muted);">${_snapIndex + 1}/${_snapVersions.length}</span>
        <button class="btn-sm" title="Save new version" onclick="libSnapRecapture()">&#8635;</button>
        <button class="btn-sm" style="color:#f87171;" title="Delete this version" onclick="libSnapDelete()">&#128465;&#65039;</button>
        <button class="btn-sm" onclick="document.getElementById('snap-modal').remove()">&#10005;</button>
      </div>
      <iframe src="${API}/api/library/archive/${v.id}/view" title="snapshot" sandbox="allow-same-origin allow-popups"
              style="flex:1;border:0;width:100%;background:#fff;"></iframe>
    </div>`;
  document.body.appendChild(overlay);
}

function libSnapStep(delta) {
  const n = _snapIndex + delta;
  if (n < 0 || n >= _snapVersions.length) return;
  _snapIndex = n; _renderSnapModal();
}
window.libSnapStep = libSnapStep;
function libSnapPick(i) { _snapIndex = parseInt(i, 10) || 0; _renderSnapModal(); }
window.libSnapPick = libSnapPick;

async function libSnapRecapture() {
  toast('Capturing new version…');
  try {
    await api('/api/library/archive', { method: 'POST', body: JSON.stringify({ url: _snapUrl }) });
    _snapVersions = (await api('/api/library/archive/versions?url=' + encodeURIComponent(_snapUrl))).versions || [];
    _snapIndex = 0; _renderSnapModal(); toast('New version saved');
  } catch (e) { toast('Error: ' + e.message, 'error'); }
}
window.libSnapRecapture = libSnapRecapture;

async function libSnapDelete() {
  const v = _snapVersions[_snapIndex];
  if (!v || !confirm('Delete this snapshot version?')) return;
  try {
    await api('/api/library/archive/' + v.id, { method: 'DELETE' });
    _snapVersions.splice(_snapIndex, 1);
    if (!_snapVersions.length) { document.getElementById('snap-modal')?.remove(); libArchiveView(); return; }
    if (_snapIndex >= _snapVersions.length) _snapIndex = _snapVersions.length - 1;
    _renderSnapModal();
  } catch (e) { toast('Error: ' + e.message, 'error'); }
}
window.libSnapDelete = libSnapDelete;

/* ── AI guide research ────────────────────────────────────────────────────── */
function libAgentGuide() {
  const el = document.getElementById('lib-content');
  el.innerHTML = `
    <div class="stat-card" style="padding:24px;max-width:640px;">
      <h3 style="margin-bottom:6px;">&#129302; AI Guide</h3>
      <p style="color:var(--muted);font-size:.85rem;margin-bottom:16px;">The local OpenClaw agent researches a topic (with web search) and saves a Markdown guide to your library.</p>
      <input type="text" id="ag-topic" placeholder="e.g. How to harden a Pi-hole install" style="width:100%;padding:10px;background:var(--surface2);border:1px solid var(--border);border-radius:8px;color:var(--text);margin-bottom:12px;" />
      <input type="text" id="ag-cat" placeholder="category (optional, default: guides)" style="width:100%;padding:8px 10px;background:var(--surface2);border:1px solid var(--border);border-radius:8px;color:var(--text);margin-bottom:14px;font-size:.82rem;" />
      <div style="display:flex;gap:10px;">
        <button class="btn" id="ag-go" onclick="libAgentGuideGo()">Research &amp; Save</button>
        <button class="btn-sm" onclick="libShowSections()">Cancel</button>
      </div>
      <div id="ag-msg" style="font-size:.8rem;margin-top:12px;color:var(--muted);"></div>
    </div>`;
}
window.libAgentGuide = libAgentGuide;

async function libAgentGuideGo() {
  const topic = document.getElementById('ag-topic').value.trim();
  const cat = document.getElementById('ag-cat').value.trim();
  const msg = document.getElementById('ag-msg');
  const btn = document.getElementById('ag-go');
  if (!topic) { msg.style.color = 'var(--warn)'; msg.textContent = 'Enter a topic.'; return; }
  btn.disabled = true; btn.textContent = '⏳ Researching (may take a minute)…';
  msg.style.color = 'var(--muted)'; msg.textContent = 'The agent is searching and writing…';
  try {
    const r = await api('/api/library/guide', { method: 'POST', body: JSON.stringify({ topic, category: cat || 'guides' }) });
    toast('Guide saved: ' + r.doc.title);
    libBrowse(r.doc.category);
  } catch (e) {
    msg.style.color = 'var(--warn)'; msg.textContent = 'Error: ' + e.message;
    btn.disabled = false; btn.textContent = 'Research & Save';
  }
}
window.libAgentGuideGo = libAgentGuideGo;
