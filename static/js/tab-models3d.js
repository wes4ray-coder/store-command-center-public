/* ══ 3D STUDIO TAB (Cults3D pipeline) ══
   Backlog → Review → Approved → Published, plus local text/image→3D generation.
   Pairs with routers/models3d.py. */

let _m3dTab = 'review';

async function renderModels3D() {
  const main = viewRoot();
  let counts = {}, cfg = {};
  try { counts = await api('/api/models3d/counts'); } catch {}
  try { cfg = await api('/api/models3d/config'); } catch {}
  const n = s => counts[s] || 0;

  main.innerHTML = `
    <div class="view-header">
      <div class="view-title">&#127981; 3D Studio</div>
      <div class="view-sub">Review your backlog of 3D files, let AI draft the listing, generate product images, and publish to Cults3D.</div>
    </div>

    <div class="settings-group" style="margin-bottom:12px;">
      <div class="settings-group-title">&#128193; Backlog folder</div>
      <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
        <input type="text" id="m3d-backlog-path" value="${esc(cfg.backlog||'')}" placeholder="/media/user/Backup/Nextdata/#CAD/#My3D" style="flex:1;min-width:280px;">
        <button class="btn-sm primary" onclick="m3dSaveBacklog()">&#128190; Save</button>
      </div>
      <div id="m3d-backlog-status" style="font-size:.74rem;margin-top:6px;color:${cfg.exists?'var(--green)':'var(--warn)'};">
        ${cfg.backlog ? (cfg.exists?`✅ Folder found. Recognizes: ${(cfg.extensions||[]).join(' ')}`:'⚠️ Folder not found — check the path / mount the drive.') : ''}
      </div>
    </div>

    <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:14px;">
      <button class="btn-sm primary" onclick="m3dScan()" title="Look through your backlog folder for new 3D files and import them into Review. Files stay where they are on disk — only their location is recorded.">&#128194; Scan backlog</button>
      <button class="btn-sm" onclick="m3dToggleGen()" title="Open the panel to create a brand-new 3D model from a text description, generated on your GPU box.">&#10024; Generate 3D</button>
      <button class="btn-sm" onclick="renderModels3D()">&#8635; Refresh</button>
      <span id="m3d-scan-status" style="font-size:.78rem;color:var(--muted);"></span>
    </div>

    <div id="m3d-genpanel" style="display:none;" class="settings-group">
      <div class="settings-group-title">&#10024; Generate a 3D model (local, on your GPU box)</div>
      <div style="font-size:.75rem;color:var(--muted);margin-bottom:8px;line-height:1.6;">
        Describe an object &mdash; SDXL renders a clean product image, then an image&rarr;3D model turns it into a
        printable mesh (.glb). It lands under <b>Generated</b>, auto-rendered and ready to review. Takes ~2&ndash;3 min.
      </div>
      <div class="field"><label>Mesh model ${hlp('The image→3D model that builds the printable mesh. TripoSR is MIT-licensed = safe to sell. Others may carry license restrictions (watch the warning below). Install more in the 3D Generation Models section.')}</label>
        <select id="m3d-gen-model" onchange="m3dOnGenModelChange()"><option value="triposr">TripoSR (MIT — safe to sell)</option></select>
        <div id="m3d-gen-model-warn" style="font-size:.72rem;margin-top:4px;"></div></div>
      <div class="field"><label>Prompt ${hlp('Describe the single object to create. SDXL first renders a clean product image from this, then the image→3D model turns that into a printable mesh. Be concrete about shape, style, and material; skip scenes/backgrounds.')}</label>
        <div style="display:flex;gap:6px;">
          <textarea id="m3d-gen-prompt" placeholder="e.g. a cute low-poly fox figurine, smooth, printable" style="flex:1;min-height:56px;font-family:inherit;resize:vertical;"></textarea>
          <button class="btn-sm" onclick="m3dEnhance()" title="Let AI expand your idea into a strong 3D prompt">&#10024; Enhance</button>
        </div></div>
      <div class="field"><label>Title (optional) ${hlp('A name for the generated model — used in your 3D library and as the default title when you publish to Cults3D. Leave blank to auto-name it.')}</label>
        <input type="text" id="m3d-gen-title" placeholder="Low-Poly Fox Figurine"></div>
      <button class="btn-sm primary" onclick="m3dGenerate()">&#10024; Generate</button>
      <span id="m3d-gen-status" style="font-size:.78rem;color:var(--muted);margin-left:8px;"></span>
      <div id="m3d-genmodels" style="margin-top:14px;border-top:1px solid var(--border);padding-top:10px;">
        <div style="font-size:.8rem;font-weight:600;margin-bottom:6px;">&#129513; 3D generation models</div>
        <div id="m3d-genmodels-list" style="font-size:.76rem;color:var(--muted);">Loading…</div>
      </div>
    </div>

    <div id="m3d-active"></div>

    <div class="tabs" style="display:flex;gap:6px;margin:14px 0;flex-wrap:wrap;">
      ${['backlog','review','approved','published','rejected'].map(s => `
        <button class="btn-sm ${_m3dTab===s?'primary':''}" onclick="m3dSetTab('${s}')">
          ${m3dTabLabel(s)} <span style="opacity:.6;">${n(s)}</span></button>`).join('')}
    </div>

    <div id="m3d-list"><div class="empty">Loading…</div></div>`;

  await m3dLoadList();
  m3dLoadActive();
  resumeM3dEnhance();   // re-attach if an enhance was started here and we wandered off
  if (document.getElementById('m3d-genpanel').style.display !== 'none') m3dLoadGenModels();
}
window.renderModels3D = renderModels3D;

function m3dTabLabel(s){return {backlog:'📥 Backlog',review:'🔍 Review',approved:'✅ Approved',published:'🚀 Published',rejected:'🗑 Rejected'}[s]||s;}
function m3dSetTab(s){ _m3dTab=s; renderModels3D(); }
window.m3dSetTab = m3dSetTab;
function m3dToggleGen(){ const p=document.getElementById('m3d-genpanel'); const show=p.style.display==='none'; p.style.display = show?'block':'none'; if(show) m3dLoadGenModels(); }
window.m3dToggleGen = m3dToggleGen;

/* ── live "active" strip: anything generating or errored ── */
let _m3dActiveTimer = null;
async function m3dLoadActive(){
  const box = document.getElementById('m3d-active');
  if (!box) { if(_m3dActiveTimer){clearInterval(_m3dActiveTimer);_m3dActiveTimer=null;} return; }
  let gen=[], err=[];
  try { gen = await api('/api/models3d?status=generating'); } catch {}
  try { err = await api('/api/models3d?status=error'); } catch {}
  const items = [...gen, ...err];
  if (!items.length){ box.innerHTML=''; if(_m3dActiveTimer){clearInterval(_m3dActiveTimer);_m3dActiveTimer=null;} return; }
  box.innerHTML = `<div class="settings-group" style="margin-bottom:12px;">
    <div class="settings-group-title">${gen.length?'⏳ Working…':'⚠️ Needs attention'}</div>
    ${items.map(m=>{
      const isErr = m.status==='error';
      return `<div style="display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid var(--border);">
        <div style="font-size:1.3rem;">${isErr?'❌':'⏳'}</div>
        <div style="flex:1;">
          <div style="font-weight:600;font-size:.82rem;">${esc(m.title||m.gen_prompt||('Model #'+m.id))}</div>
          <div style="font-size:.72rem;color:${isErr?'var(--warn)':'var(--muted)'};">${esc(m.progress_msg||m.publish_error||(isErr?'Failed':'Working…'))}</div>
        </div>
        ${isErr?`<button class="btn-sm" onclick="m3dRetryGen(${m.id})">↻ Retry</button><button class="btn-sm" onclick="m3dDelete(${m.id})">🗑</button>`:''}
      </div>`;}).join('')}
  </div>`;
  // keep polling while anything is still generating
  if (gen.length && !_m3dActiveTimer){
    _m3dActiveTimer = setInterval(()=>{ if(_currentView==='models3d') m3dLoadActive(); else {clearInterval(_m3dActiveTimer);_m3dActiveTimer=null;} }, 4000);
  }
}
window.m3dLoadActive = m3dLoadActive;

async function m3dRetryGen(id){
  try{ const m=await api(`/api/models3d/${id}`);
    if(m.gen_prompt){ await api('/api/models3d/generate',{method:'POST',body:JSON.stringify({prompt:m.gen_prompt,title:m.title})});
      await api(`/api/models3d/${id}`,{method:'DELETE'}); toast('Re-queued'); renderModels3D(); }
    else toast('No prompt to retry from','error');
  }catch(e){toast(e.message,'error');}
}
window.m3dRetryGen=m3dRetryGen;

async function m3dSaveBacklog(){
  const path=document.getElementById('m3d-backlog-path').value.trim();
  const st=document.getElementById('m3d-backlog-status');
  if(!path){ st.style.color='var(--warn)'; st.textContent='Enter a folder path'; return; }
  st.style.color='var(--muted)'; st.textContent='Checking…';
  try{
    const r=await api('/api/models3d/config',{method:'POST',body:JSON.stringify({backlog:path})});
    st.style.color='var(--green)'; st.textContent=`✅ Saved. Found ${r.found} 3D file(s) here — click Scan backlog to import.`;
  }catch(e){ st.style.color='var(--warn)'; st.textContent='❌ '+e.message; }
}
window.m3dSaveBacklog=m3dSaveBacklog;

async function m3dScan(){
  const st=document.getElementById('m3d-scan-status');
  st.textContent='Scanning…';
  try{
    const r=await api('/api/models3d/scan',{method:'POST'});
    const bf = r.backfilled ? `, 📁 filled folders on ${r.backfilled}` : '';
    st.textContent = (r.added||r.backfilled) ? `✅ Added ${r.added} new` + (r.skipped?`, ${r.skipped} already known`:'') + bf : (r.note || `No new files. Drop them in: ${r.backlog}`);
    setTimeout(renderModels3D, 900);
  }catch(e){ st.style.color='var(--warn)'; st.textContent='❌ '+e.message; }
}
window.m3dScan = m3dScan;

async function m3dGenerate(){
  const prompt=document.getElementById('m3d-gen-prompt').value.trim();
  const title=document.getElementById('m3d-gen-title').value.trim();
  const generator=(document.getElementById('m3d-gen-model')||{}).value||'triposr';
  const st=document.getElementById('m3d-gen-status');
  if(!prompt){ st.textContent='Enter a prompt first'; return; }
  const gm=m3dSelectedGen();
  if(gm && gm.commercial===false && !confirm(`${gm.label} is ${gm.license} — do NOT sell the output.\n\nGenerate anyway (personal / non-commercial use)?`)) return;
  st.style.color='var(--muted)'; st.textContent='⏳ Starting…';
  let mid;
  try{
    const r=await api('/api/models3d/generate',{method:'POST',body:JSON.stringify({prompt,title,generator})});
    mid=r.model_id;
    toast('3D generation started — progress shows below');
  }catch(e){ st.style.color='var(--warn)'; st.textContent='❌ '+e.message; return; }
  m3dLoadActive();   // show the live strip immediately
  // Poll this model until it leaves 'generating', updating the inline status.
  const started=Date.now();
  const poll=setInterval(async ()=>{
    if(_currentView!=='models3d'){ clearInterval(poll); return; }
    let m; try{ m=await api(`/api/models3d/${mid}`); }catch{ return; }
    const secs=Math.round((Date.now()-started)/1000);
    if(m.status==='generating'){ st.style.color='var(--muted)'; st.textContent=`${m.progress_msg||'Working…'} (${secs}s)`; m3dLoadActive(); return; }
    clearInterval(poll);
    if(m.status==='error'){ st.style.color='var(--warn)'; st.textContent='❌ '+(m.publish_error||'Generation failed'); m3dLoadActive(); }
    else { st.style.color='var(--green)'; st.textContent=`✅ Done in ${secs}s — now in Review`; toast('3D model ready — in Review'); _m3dTab='review'; renderModels3D(); }
  }, 4000);
}
window.m3dGenerate = m3dGenerate;

const _m3dBusy = (on) => { const st=document.getElementById('m3d-gen-status'); if(st){ st.style.color='var(--muted)'; st.textContent = on ? '✨ Enhancing…' : ''; } };
// Runs server-side; persists across tab switches / reload (see enhanceStart).
async function m3dEnhance(){
  const inp=document.getElementById('m3d-gen-prompt');
  const idea=inp ? inp.value.trim() : '';
  const st=document.getElementById('m3d-gen-status');
  if(!idea){ if(st) st.textContent='Type an idea first'; return; }
  enhanceStart('m3d-gen-prompt',
    async () => (await api('/api/models3d/enhance',{method:'POST',body:JSON.stringify({prompt:idea})})).task_id,
    _m3dBusy);
}
window.m3dEnhance=m3dEnhance;
// re-attach a pending enhance when the 3D tab (re)renders
function resumeM3dEnhance(){ enhanceResume('m3d-gen-prompt', _m3dBusy); }

let _m3dGenModels=[];
async function m3dLoadGenModels(){
  const box=document.getElementById('m3d-genmodels-list');
  if(!box) return;
  let models=[];
  try{ models=await api('/api/models3d/gen-models'); }catch(e){ box.innerHTML=esc(e.message); return; }
  _m3dGenModels=models;
  // Populate the generator dropdown — only INSTALLED models are selectable.
  const sel=document.getElementById('m3d-gen-model');
  if(sel){
    const prev=sel.value;
    const opts=models.filter(m=>m.installed);
    sel.innerHTML = (opts.length?opts:models.filter(m=>m.key==='triposr')).map(m=>
      `<option value="${esc(m.key)}">${esc(m.label)}${m.commercial===false?' ⚠️':''}</option>`).join('')
      || '<option value="triposr">TripoSR</option>';
    if([...sel.options].some(o=>o.value===prev)) sel.value=prev;
    m3dOnGenModelChange();
  }
  box.innerHTML = models.map(m=>{
    // badge = install state + verified-by-real-test verdict (not just 'venv exists')
    let badge='';
    if(m.dl_status==='installing') badge='<span style="color:var(--accent2);">⏳ installing…</span>';
    else if(m.dl_status==='error') badge='<span style="color:var(--warn);">❌ install failed</span>';
    else if(m.installed){
      if(m.test_status==='pass')      badge=`<span style="color:var(--green);">✅ tested & working${m.test_detail&&m.test_detail.secs?` (${m.test_detail.secs}s)`:''}</span>`;
      else if(m.test_status==='fail') badge='<span style="color:var(--warn);">❌ test failed</span>';
      else if(m.test_status==='running') badge='<span style="color:var(--accent2);">🧪 testing…</span>';
      else badge='<span style="color:var(--muted);">✅ installed (untested)</span>';
    }
    let btn='';
    if(!m.installed && m.dl_status!=='installing') btn=`<button class="btn-sm" onclick="m3dInstallModel('${m.key}')" title="Download and set up this image→3D model on the GPU box (one time, a few minutes).">⬇ Install</button>`;
    else if(m.installed && m.test_status!=='running') btn=`<button class="btn-sm" onclick="m3dTestModel('${m.key}')" title="Run a real generation to confirm it actually works">🧪 Test</button>`;
    const testErr = (m.test_status==='fail' && m.test_detail && m.test_detail.error) ? `<div style="font-size:.66rem;color:var(--warn);">test: ${esc(String(m.test_detail.error))}</div>` : '';
    return `<div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--border);">
      <div style="flex:1;">
        <div style="font-weight:600;color:var(--text);">${esc(m.label)} ${badge}</div>
        <div style="font-size:.72rem;">${esc(m.style)} · VRAM ${esc(m.vram||'?')}</div>
        <div style="font-size:.68rem;opacity:.8;">${esc(m.note||'')}</div>
        ${m.dl_error?`<div style="font-size:.66rem;color:var(--warn);">${esc(m.dl_error)}</div>`:''}
        ${testErr}
      </div>${btn}</div>`;
  }).join('');
}

async function m3dTestModel(key){
  toast('Running a real test generation on the GPU box — ~1-3 min…');
  try{ await api(`/api/models3d/gen-models/${key}/test`,{method:'POST'}); }catch(e){ toast(e.message,'error'); return; }
  m3dLoadGenModels();
  const poll=setInterval(async ()=>{
    if(_currentView!=='models3d'){ clearInterval(poll); return; }
    let s; try{ s=await api(`/api/models3d/gen-models/${key}/test-status`); }catch{ return; }
    if(s.status==='pass'||s.status==='fail'){ clearInterval(poll); m3dLoadGenModels();
      toast(s.status==='pass'?'✅ Test passed — it really works':'❌ Test failed: '+((s.detail&&s.detail.error)||'').slice(0,80), s.status==='fail'?'error':'success'); }
  }, 6000);
}
window.m3dTestModel=m3dTestModel;
window.m3dLoadGenModels=m3dLoadGenModels;

function m3dSelectedGen(){ return _m3dGenModels.find(m=>m.key===(document.getElementById('m3d-gen-model')||{}).value); }
function m3dOnGenModelChange(){
  const w=document.getElementById('m3d-gen-model-warn'); if(!w) return;
  const m=m3dSelectedGen();
  if(m && m.commercial===false){
    w.style.color='var(--warn)';
    w.innerHTML=`⚠️ <b>${esc(m.license||'Non-commercial')}</b> license — do NOT sell models made with this. Use TripoSR for anything you publish for sale.`;
  } else if(m){
    w.style.color='var(--green)'; w.innerHTML=`✅ ${esc(m.license||'')} — safe to sell the output.`;
  } else w.innerHTML='';
}
window.m3dOnGenModelChange=m3dOnGenModelChange;

async function m3dInstallModel(key){
  toast('Installing on the GPU box — this can take a few minutes…');
  try{ await api(`/api/models3d/gen-models/${key}/install`,{method:'POST'}); }catch(e){ toast(e.message,'error'); return; }
  m3dLoadGenModels();
  const poll=setInterval(async ()=>{
    if(_currentView!=='models3d'){ clearInterval(poll); return; }
    let s; try{ s=await api(`/api/models3d/gen-models/${key}/install-status`); }catch{ return; }
    if(s.status==='done'||s.status==='error'){ clearInterval(poll); m3dLoadGenModels(); toast(s.status==='done'?'Model installed ✅':'Install failed', s.status==='error'?'error':'success'); }
  }, 5000);
}
window.m3dInstallModel=m3dInstallModel;

async function m3dLoadList(){
  const box=document.getElementById('m3d-list');
  let items=[];
  try{ items=await api('/api/models3d?status='+encodeURIComponent(_m3dTab)); }
  catch(e){ box.innerHTML=`<div style="color:var(--warn)">${esc(e.message)}</div>`; return; }
  if(!items.length){
    box.innerHTML=`<div class="empty" style="padding:24px;"><div class="empty-icon">${_m3dTab==='backlog'?'📥':'📭'}</div>
      ${_m3dTab==='backlog'?'No files in the backlog. Click <b>Scan backlog</b> after dropping 3D files into your backlog folder, or <b>Generate 3D</b>.':'Nothing here yet.'}</div>`;
    return;
  }
  box.innerHTML = `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px;">
    ${items.map(m3dCard).join('')}</div>`;
}

function m3dCard(m){
  const img = m.primary_url ? `<img src="${esc(window.thumbM3d(m.primary_url,400))}" data-full="${esc(m.primary_url)}" loading="lazy" decoding="async" style="width:100%;height:180px;object-fit:contain;background:var(--surface2);" onerror="if(!this.dataset.fb){this.dataset.fb=1;this.src=this.dataset.full;}">`
    : `<div style="height:180px;display:flex;align-items:center;justify-content:center;background:var(--surface2);color:var(--muted);font-size:2.4rem;">${m.status==='generating'?'⏳':'🧊'}</div>`;
  const price = m.price_cents ? '$'+(m.price_cents/100).toFixed(2) : 'Free';
  const err = m.publish_error ? `<div style="font-size:.7rem;color:var(--warn);margin-top:4px;">${esc(m.publish_error)}</div>` : '';
  return `<div class="stat-card" style="padding:0;overflow:hidden;display:flex;flex-direction:column;">
    ${img}
    <div style="padding:10px 12px;flex:1;display:flex;flex-direction:column;gap:6px;">
      <div style="font-weight:600;font-size:.86rem;">${esc(m.title||m.file_name||'Untitled')}</div>
      ${m.rel_dir?`<div style="font-size:.68rem;color:var(--accent2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="${esc(m.rel_dir)}">📁 ${esc(m.rel_dir)}</div>`:''}
      <div style="font-size:.7rem;color:var(--muted);">${esc((m.file_ext||'').toUpperCase())} · ${((m.file_size||0)/1024/1024).toFixed(2)} MB · ${price}</div>
      ${m.tags?`<div style="font-size:.68rem;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">🏷 ${esc(m.tags)}</div>`:''}
      ${err}
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:auto;">${m3dActions(m)}</div>
    </div></div>`;
}

function m3dActions(m){
  const b=(label,fn,cls='',title='')=>`<button class="btn-sm ${cls}" onclick="${fn}"${title?` title="${title}"`:''}>${label}</button>`;
  if(m.status==='published')
    return `<a class="btn-sm primary" href="${esc(m.cults3d_url||'#')}" target="_blank" rel="noopener">↗ View on Cults3D</a>`;
  if(m.status==='rejected')
    return b('↩ Restore',`m3dPatch(${m.id},{status:'review'})`) + b('🗑 Delete',`m3dDelete(${m.id})`);
  let a = b('🔍 Open',`m3dOpen(${m.id})`,'primary');
  a += b('🖼 Render',`m3dRender(${m.id})`,'','Render turntable preview images of the mesh on the GPU box. At least one image is required before you can publish.');
  if(m.status==='backlog') a += b('🤖 Propose',`m3dPropose(${m.id})`,'','Have the AI draft a title, description, tags, and price from the file and folder, then move this into Review.');
  if(m.status==='review')  a += b('✅ Approve',`m3dPatch(${m.id},{status:'approved'})`,'','Mark this listing ready to publish (moves it to Approved).');
  if(m.status==='approved') a += b('🚀 Publish',`m3dPublish(${m.id})`,'primary','Push this model live to your Cults3D store: uploads the 3D file plus its images via the Cults3D API.');
  a += b('✕ Reject',`m3dPatch(${m.id},{status:'rejected'})`);
  return a;
}

async function m3dRender(id){
  toast('Rendering turntable views…');
  try{ await api(`/api/models3d/${id}/render`,{method:'POST'}); setTimeout(renderModels3D,3500);}catch(e){toast(e.message,'error');}
}
window.m3dRender=m3dRender;

async function m3dPropose(id){
  toast('AI drafting the listing…');
  try{
    const r=await api(`/api/models3d/${id}/propose`,{method:'POST'});
    if(r.task_id){ try{ await pollTask(r.task_id); }catch{} }
    toast('Listing drafted'); renderModels3D();
  }catch(e){toast(e.message,'error');}
}
window.m3dPropose=m3dPropose;

async function m3dPatch(id,patch){
  try{ await api(`/api/models3d/${id}`,{method:'PATCH',body:JSON.stringify(patch)}); renderModels3D(); }
  catch(e){toast(e.message,'error');}
}
window.m3dPatch=m3dPatch;

async function m3dDelete(id){
  if(!confirm('Delete this entry? (the source file on disk is kept)')) return;
  try{ await api(`/api/models3d/${id}`,{method:'DELETE'}); renderModels3D(); }catch(e){toast(e.message,'error');}
}
window.m3dDelete=m3dDelete;

async function m3dPublish(id){
  if(!confirm('Publish this model to Cults3D now?')) return;
  toast('Publishing to Cults3D…');
  try{ await api(`/api/models3d/${id}/publish`,{method:'POST'}); setTimeout(renderModels3D,4000);}catch(e){toast(e.message,'error');}
}
window.m3dPublish=m3dPublish;

/* ── detail / edit modal ── */
async function m3dOpen(id){
  let m; try{ m=await api(`/api/models3d/${id}`);}catch(e){toast(e.message,'error');return;}
  const mesh = m.mesh && !m.mesh.error ? `${m.mesh.faces} faces · ${(m.mesh.dims_mm||[]).join(' × ')} mm · ${m.mesh.watertight?'watertight ✅':'not watertight ⚠️'}` : '';
  const gallery = [...(m.render_urls||[]),...(m.hero_urls||[])];
  const wrap=document.createElement('div');
  wrap.className='modal-overlay'; wrap.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;z-index:1000;padding:20px;';
  wrap.innerHTML=`<div class="settings-group" style="max-width:640px;width:100%;max-height:90vh;overflow:auto;background:var(--surface);">
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <div class="settings-group-title">🧊 Edit listing</div>
      <button class="btn-sm" onclick="this.closest('.modal-overlay').remove()">✕</button></div>
    <div style="font-size:.7rem;color:var(--muted);margin-bottom:8px;">${esc(m.file_name||'')} · ${mesh}</div>
    ${m.rel_dir?`<div style="font-size:.72rem;color:var(--accent2);margin-bottom:8px;">📁 ${esc(m.rel_dir)}${m.category?` &nbsp;·&nbsp; category: <b>${esc(m.category)}</b>`:''}</div>`:''}
    ${gallery.length?`<div style="font-size:.68rem;color:var(--muted);margin-bottom:4px;">Click a thumbnail to make it the cover image.</div><div style="display:flex;gap:6px;overflow-x:auto;margin-bottom:10px;">${gallery.map(u=>{const fn=u.split('/img/')[1]; const cur=(m.primary_image||'').split('/').pop()===fn; return `<img src="${esc(window.thumbM3d(u,200))}" data-full="${esc(u)}" loading="lazy" decoding="async" title="Set as cover" onclick="m3dSetPrimary(${id},'${esc(fn)}')" onerror="if(!this.dataset.fb){this.dataset.fb=1;this.src=this.dataset.full;}" style="height:90px;border-radius:6px;cursor:pointer;background:var(--surface2);object-fit:contain;outline:${cur?'2px solid var(--accent)':'none'};">`;}).join('')}</div>`:'<div style="font-size:.72rem;color:var(--muted);margin-bottom:10px;">No images yet — click Render.</div>'}
    <div class="field"><label>Title</label><input id="m3d-e-title" value="${esc(m.title||'')}"></div>
    <div class="field"><label>Description</label><textarea id="m3d-e-desc" rows="4">${esc(m.description||'')}</textarea></div>
    <div class="field"><label>Tags (comma separated)</label><input id="m3d-e-tags" value="${esc(m.tags||'')}"></div>
    <div style="display:flex;gap:8px;">
      <div class="field" style="flex:1;"><label>Price (USD, 0=free) ${hlp('What buyers pay for this model on Cults3D. 0 = free download. Set when you publish; you can edit it later on Cults3D too.')}</label><input id="m3d-e-price" type="number" step="0.01" value="${((m.price_cents||0)/100).toFixed(2)}"></div>
      <div class="field" style="flex:1;"><label>License ${hlp('The usage license attached on Cults3D (e.g. “standard”). Governs how buyers may use/redistribute the model. Use Cults3D’s license codes.')}</label><input id="m3d-e-lic" value="${esc(m.license_code||'standard')}"></div>
    </div>
    <label style="font-size:.75rem;display:flex;gap:6px;align-items:center;margin-bottom:10px;"><input type="checkbox" id="m3d-e-ai" ${m.made_with_ai?'checked':''}> Made with AI ${hlp('Flags the listing as AI-generated on Cults3D. Some marketplaces require this disclosure — leave it on for image→3D models.')}</label>
    <div class="field"><label>🖼 Add AI hero image (prompt)</label>
      <div style="display:flex;gap:6px;"><input id="m3d-e-hero" placeholder="studio product shot of ${esc((m.title||'the object').slice(0,30))} on a pedestal">
      <button class="btn-sm" onclick="m3dHero(${id})">Generate</button></div></div>
    <div style="display:flex;gap:8px;margin-top:12px;">
      <button class="btn-sm primary" onclick="m3dSaveEdit(${id})">💾 Save</button>
      <button class="btn-sm" onclick="m3dRender(${id});this.closest('.modal-overlay').remove()">🖼 Render mesh</button>
      <button class="btn-sm" onclick="m3dPropose(${id});this.closest('.modal-overlay').remove()">🤖 Re-propose</button>
    </div></div>`;
  wrap.addEventListener('click',e=>{if(e.target===wrap)wrap.remove();});
  document.body.appendChild(wrap);
}
window.m3dOpen=m3dOpen;

async function m3dSaveEdit(id){
  const patch={
    title:document.getElementById('m3d-e-title').value.trim(),
    description:document.getElementById('m3d-e-desc').value.trim(),
    tags:document.getElementById('m3d-e-tags').value.trim(),
    price_cents:Math.round(parseFloat(document.getElementById('m3d-e-price').value||'0')*100),
    license_code:document.getElementById('m3d-e-lic').value.trim()||'standard',
    made_with_ai:document.getElementById('m3d-e-ai').checked,
  };
  try{ await api(`/api/models3d/${id}`,{method:'PATCH',body:JSON.stringify(patch)});
    toast('Saved'); document.querySelector('.modal-overlay')?.remove(); renderModels3D();
  }catch(e){toast(e.message,'error');}
}
window.m3dSaveEdit=m3dSaveEdit;

async function m3dHero(id){
  const prompt=document.getElementById('m3d-e-hero').value.trim();
  if(!prompt){toast('Enter a hero prompt');return;}
  toast('Generating hero image on the GPU box…');
  try{ await api(`/api/models3d/${id}/hero`,{method:'POST',body:JSON.stringify({prompt})});
    setTimeout(()=>{document.querySelector('.modal-overlay')?.remove(); m3dOpen(id);}, 6000);
  }catch(e){toast(e.message,'error');}
}
window.m3dHero=m3dHero;

async function m3dSetPrimary(id, filename){
  try{ await api(`/api/models3d/${id}`,{method:'PATCH',body:JSON.stringify({primary_image:filename})});
    document.querySelector('.modal-overlay')?.remove(); m3dOpen(id);
  }catch(e){toast(e.message,'error');}
}
window.m3dSetPrimary=m3dSetPrimary;
