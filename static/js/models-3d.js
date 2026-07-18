/* Models — 3D generation family (install/test + catalog HTML). Split from tab-models.js. */
async function install3dModel(key, safe){
  const cell = document.getElementById('gm-btn-'+safe);
  if (cell) cell.innerHTML = '<button class="btn-sm" disabled>⏳ Installing…</button>';
  try { await api('/api/models3d/gen-models/'+key+'/install', { method:'POST' }); }
  catch(e){ toast(e.message,'error'); if(cell) cell.innerHTML='<button class="btn-sm primary" onclick="install3dModel(\''+key+'\',\''+safe+'\')">⬇ Install</button>'; return; }
  toast('Installing on the GPU box — a few minutes…');
  const poll = setInterval(async () => {
    if (_currentView !== 'models3d') { clearInterval(poll); return; }
    let s; try { s = await api('/api/models3d/gen-models/'+key+'/install-status'); } catch { return; }
    if (s.status === 'done') { clearInterval(poll); if(cell) cell.innerHTML='<span style="color:var(--green);font-weight:700;font-size:.82rem;">✓ Installed</span>'; toast('3D model installed ✅'); }
    else if (s.status === 'error') { clearInterval(poll); if(cell) cell.innerHTML='<button class="btn-sm primary" onclick="install3dModel(\''+key+'\',\''+safe+'\')">↻ Retry</button>'; toast('Install failed: '+(s.error||'').slice(0,120),'error'); }
  }, 5000);
}
window.install3dModel = install3dModel;

async function test3dModel(key, safe){
  const cell = document.getElementById('gm-btn-'+safe);
  if (cell) cell.innerHTML = '<span style="color:var(--accent2);font-size:.82rem;">🧪 Testing…</span>';
  toast('Running a real test generation on the GPU box — ~1-3 min…');
  try { await api('/api/models3d/gen-models/'+key+'/test', { method:'POST' }); }
  catch(e){ toast(e.message,'error'); return; }
  const poll = setInterval(async () => {
    if (_currentView !== 'models3d') { clearInterval(poll); return; }
    let s; try { s = await api('/api/models3d/gen-models/'+key+'/test-status'); } catch { return; }
    if (s.status === 'pass' || s.status === 'fail') {
      clearInterval(poll);
      if (cell) cell.innerHTML = (s.status==='pass'
        ? '<span style="color:var(--green);font-weight:700;font-size:.82rem;">✓ Tested &amp; working</span>'
        : '<span style="color:#f87171;font-weight:700;font-size:.82rem;">✗ Test failed</span>')
        + '<br><button class="btn-sm" onclick="test3dModel(\''+key+'\',\''+safe+'\')" style="margin-top:5px;">🧪 Re-test</button>';
      toast(s.status==='pass' ? '✅ Test passed — it really works' : '❌ Test failed: '+((s.detail&&s.detail.error)||'').slice(0,100), s.status==='fail'?'error':'success');
    }
  }, 6000);
}
window.test3dModel = test3dModel;

function _gen3dHTML(genModels) {
  genModels = genModels || [];
  let h = `<div class="section-header"><div><div class="section-title">&#129513; 3D Generation Models</div>
      <div class="section-sub">Image&rarr;3D model makers &middot; installed on the GPU box &middot; used by 3D &rarr; Generate</div></div></div>
    <div style="display:grid;gap:12px;max-width:820px;">`;
  for (const gm of genModels) {
    const safe = gm.key.replace(/[^a-zA-Z0-9_-]/g, '_');
    const dlSt = gm.dl_status || null;
    h += `<div class="queue-card" id="gmc-${safe}">
      <div style="display:flex;align-items:flex-start;gap:12px;">
        <div style="flex:1;">
          <div style="font-size:.95rem;font-weight:700;">${esc(gm.label)}</div>
          <div style="font-size:.75rem;color:var(--muted);margin-top:3px;">${esc(gm.style||'')} &middot; VRAM ${esc(gm.vram||'?')}</div>
          ${gm.note ? `<div style="font-size:.72rem;color:var(--warn);margin-top:3px;">&#9432; ${esc(gm.note)}</div>` : ''}
          ${gm.dl_error ? `<div style="font-size:.68rem;color:var(--warn);margin-top:3px;">${esc(gm.dl_error)}</div>` : ''}
        </div>
        <div style="flex-shrink:0;text-align:right;" id="gm-btn-${safe}">
          ${gm.installed
            ? `${gm.test_status==='pass' ? '<span style="color:var(--green);font-weight:700;font-size:.82rem;">&#10003; Tested &amp; working</span>' : gm.test_status==='fail' ? '<span style="color:#f87171;font-weight:700;font-size:.82rem;">&#10007; Test failed</span>' : gm.test_status==='running' ? '<span style="color:var(--accent2);font-size:.82rem;">&#129514; Testing&hellip;</span>' : '<span style="color:var(--muted);font-size:.82rem;">&#10003; Installed (untested)</span>'}${gm.test_status==='running' ? '' : `<br><button class="btn-sm" onclick="test3dModel('${esc(gm.key)}','${safe}')" title="Run a real generation to confirm the model actually works, not just that it installed." style="margin-top:5px;">&#129514; Test</button>`}`
            : dlSt === 'installing'
              ? `<button class="btn-sm" disabled>&#11015; Installing&hellip;</button>`
              : `<button class="btn-sm primary" onclick="install3dModel('${esc(gm.key)}','${safe}')" title="Download and set up this image→3D model on the GPU box (one time, a few minutes). Used by 3D Studio → Generate.">&#11015; Install</button>`}
        </div>
      </div>
    </div>`;
  }
  if (!genModels.length) h += `<div class="empty"><div class="empty-icon">&#129513;</div>Could not fetch 3D models. Check box connection.</div>`;
  h += `</div>`;
  return h;
}
