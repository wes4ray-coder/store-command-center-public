/* Models tab — recommended image/video/audio/3D model catalog + install/download.
   Split from app-main.js; loaded after it. */
/* ══ MODELS ══ */
async function renderModels() {
  // Fetch everything in PARALLEL (the video/audio/3D lists SSH to the node and are slow
  // — serial awaits made the tab sit on "Loading" for ~9s, feeling like it needed 2 clicks).
  const [dataR, stR, settingsR, vmR, amR, gmR, loraR] = await Promise.allSettled([
    api('/api/models'), api('/api/status'), api('/api/settings'),
    api('/api/video-models'), api('/api/audio-models'), api('/api/models3d/gen-models'),
    api('/api/loras'),
  ]);
  const data = dataR.value || {}, st = stR.value || {}, settings = settingsR.value || {};
  const _videoModels = vmR.value || [], _audioModels = amR.value || [], _genModels = gmR.value || [];
  const _loras = (loraR.value && loraR.value.recommended) || [];
  const installed   = data.installed || [];
  const recommended = data.recommended || [];

  let h = `
    <div class="view-header">
      <div class="view-title">&#127981; Models</div>
      <div class="view-sub">Manage ComfyUI checkpoint models on the GPU box &middot; ${esc(data.source || '')} source</div>
    </div>
    <div style="display:grid;gap:12px;max-width:820px;">`;

  for (const m of recommended) {
    const isInst = m.installed || installed.includes(m.filename);
    const safeId = m.filename.replace(/[^a-zA-Z0-9_-]/g, '_');
    h += `<div class="queue-card" id="mc-${safeId}">
      <div style="display:flex;align-items:flex-start;gap:12px;">
        <div style="flex:1;">
          <div style="font-size:.95rem;font-weight:700;">${esc(m.label || m.filename)}</div>
          <div style="font-size:.75rem;color:var(--muted);margin-top:3px;">${esc(m.style||'')} &middot; ${esc(m.vram||'')} &middot; ${esc(m.source||'')}</div>
          ${m.note ? `<div style="font-size:.72rem;color:var(--warn);margin-top:3px;">&#9432; ${esc(m.note)}</div>` : ''}
          <div style="font-size:.7rem;color:var(--border);margin-top:3px;word-break:break-all;">${esc(m.filename)}</div>
        </div>
        <div style="flex-shrink:0;text-align:right;">
          ${isInst
            ? `<span style="color:var(--green);font-weight:700;font-size:.82rem;">&#10003; Installed</span>`
            : `<button class="btn-sm primary" data-action="dl-model" data-filename="${esc(m.filename)}" id="dl-btn-${safeId}" title="Download this checkpoint to the GPU box (several GB, one time). Once installed it can be picked as the image model for generation.">&#11015; Download</button>`}
        </div>
      </div>
      <div class="dl-progress" id="dl-prog-${safeId}" style="display:none;margin-top:10px;">
        <div style="font-size:.75rem;color:var(--muted);margin-bottom:5px;" id="dl-status-${safeId}">Starting download&#8230;</div>
        <div style="background:var(--border);border-radius:4px;height:6px;overflow:hidden;">
          <div style="background:var(--accent);height:100%;width:0%;transition:width .5s;" id="dl-bar-${safeId}"></div>
        </div>
        <div style="margin-top:8px;display:flex;gap:8px;">
          <button class="btn-sm danger" data-action="cancel-dl" data-filename="${esc(m.filename)}" data-safeid="${safeId}" style="font-size:.7rem;">&#10005; Cancel</button>
        </div>
      </div>
    </div>`;
  }

  if (!recommended.length) {
    h += `<div class="empty"><div class="empty-icon">&#127981;</div>No models listed. Check ComfyUI connection on the box.</div>`;
  }
  h += `</div>`;

  // ── LoRAs section (e.g. the pixel-art sprite generator) ──────────────────────────
  h += `
    <div style="margin-top:28px;">
      <div class="section-header">
        <div class="section-title">&#127912; LoRAs</div>
        <div class="section-sub">Style add-ons for image gen (downloaded to ComfyUI's loras/ dir) &middot; e.g. the pixel-art sprite generator</div>
      </div>
      <div style="display:grid;gap:12px;max-width:820px;">`;
  for (const m of _loras) {
    const isInst = m.installed;
    const safeId = 'lora_' + m.filename.replace(/[^a-zA-Z0-9_-]/g, '_');
    h += `<div class="queue-card" id="mc-${safeId}">
      <div style="display:flex;align-items:flex-start;gap:12px;">
        <div style="flex:1;">
          <div style="font-size:.95rem;font-weight:700;">${esc(m.label || m.filename)}</div>
          <div style="font-size:.75rem;color:var(--muted);margin-top:3px;">${esc(m.style||'')} &middot; ${esc(m.vram||'')} &middot; ${esc(m.source||'')}</div>
          ${m.note ? `<div style="font-size:.72rem;color:var(--warn);margin-top:3px;">&#9432; ${esc(m.note)}</div>` : ''}
          <div style="font-size:.7rem;color:var(--border);margin-top:3px;word-break:break-all;">${esc(m.filename)}</div>
        </div>
        <div style="flex-shrink:0;text-align:right;">
          ${isInst
            ? `<span style="color:var(--green);font-weight:700;font-size:.82rem;">&#10003; Installed</span>`
            : (m.auto_download
              ? `<button class="btn-sm primary" data-action="dl-model" data-filename="${esc(m.filename)}" data-safeid="${safeId}" id="dl-btn-${safeId}" title="Download this LoRA to the GPU box's loras/ folder (one time). Then pick it in Settings → 🧠 Models.">&#11015; Download</button>`
              : `<span style="font-size:.72rem;color:var(--muted)">manual install</span>`)}
        </div>
      </div>
      <div class="dl-progress" id="dl-prog-${safeId}" style="display:none;margin-top:10px;">
        <div style="font-size:.75rem;color:var(--muted);margin-bottom:5px;" id="dl-status-${safeId}">Starting download&#8230;</div>
        <div style="background:var(--border);border-radius:4px;height:6px;overflow:hidden;">
          <div style="background:var(--accent);height:100%;width:0%;transition:width .5s;" id="dl-bar-${safeId}"></div>
        </div>
        <div style="margin-top:8px;display:flex;gap:8px;">
          <button class="btn-sm danger" data-action="cancel-dl" data-filename="${esc(m.filename)}" data-safeid="${safeId}" style="font-size:.7rem;">&#10005; Cancel</button>
        </div>
      </div>
    </div>`;
  }
  if (!_loras.length) {
    h += `<div class="empty"><div class="empty-icon">&#127912;</div>No LoRAs listed. Check ComfyUI connection on the box.</div>`;
  }
  h += `</div></div>`;

  // ── Video Models section ────────────────────────────────────────────────────────
  const videoModels = _videoModels;
  h += `
    <div style="margin-top:28px;">
      <div class="section-header">
        <div class="section-title">&#127916; Video Models</div>
        <div class="section-sub">HuggingFace diffusers models for text-to-video &middot; cached on RTX 3060</div>
      </div>
      <div style="display:grid;gap:12px;max-width:820px;">`;
  for (const vm of videoModels) {
    const safeVid = vm.key.replace(/[^a-zA-Z0-9_-]/g, '_');
    const isInst  = vm.installed;
    const dlSt    = vm.dl_status || null;
    h += `<div class="queue-card" id="vmc-${safeVid}">
      <div style="display:flex;align-items:flex-start;gap:12px;">
        <div style="flex:1;">
          <div style="font-size:.95rem;font-weight:700;">${esc(vm.label)}</div>
          <div style="font-size:.75rem;color:var(--muted);margin-top:3px;">${esc(vm.style)} &middot; VRAM ${esc(vm.vram)} &middot; ${esc(vm.size)} &middot; ${esc(vm.source)}</div>
          ${vm.note ? `<div style="font-size:.72rem;color:var(--warn);margin-top:3px;">&#9432; ${esc(vm.note)}</div>` : ''}
          <div style="font-size:.7rem;color:var(--border);margin-top:3px;">${esc(vm.model_id)}</div>
        </div>
        <div style="flex-shrink:0;text-align:right;">
          ${isInst
            ? `<span style="color:var(--green);font-weight:700;font-size:.82rem;">&#10003; Installed</span>`
            : dlSt === 'downloading'
              ? `<button class="btn-sm" disabled>&#11015; Downloading&hellip;</button>`
              : `<button class="btn-sm primary" data-action="dl-video-model" data-key="${esc(vm.key)}" id="vdl-btn-${safeVid}" title="Download this text-to-video model to the GPU box (several GB, one time). Needed before it can be selected in Video generation.">&#11015; Download</button>`}
        </div>
      </div>
      <div class="dl-progress" id="vdl-prog-${safeVid}" style="display:${dlSt==='downloading'?'block':'none'};margin-top:10px;">
        <div style="font-size:.75rem;color:var(--muted);margin-bottom:5px;" id="vdl-status-${safeVid}">Downloading&hellip;</div>
        <div style="background:var(--border);border-radius:4px;height:6px;overflow:hidden;">
          <div style="background:var(--accent);height:100%;width:0%;transition:width .5s;" id="vdl-bar-${safeVid}"></div>
        </div>
        <div style="margin-top:8px;">
          <button class="btn-sm danger" data-action="cancel-vdl" data-key="${esc(vm.key)}" data-safeid="${safeVid}" style="font-size:.7rem;">&#10005; Cancel</button>
        </div>
      </div>
    </div>`;
  }
  if (!videoModels.length) {
    h += `<div class="empty"><div class="empty-icon">&#127916;</div>Could not fetch video models. Check box connection.</div>`;
  }
  h += `</div></div>`;

  // ── Audio Models section ─────────────────────────────────────────────────────────
  const audioModels = _audioModels;
  h += `
    <div style="margin-top:28px;">
      <div class="section-header">
        <div class="section-title">&#127925; Audio Models</div>
        <div class="section-sub">Music (MusicGen, ACE-Step, Stable Audio) &amp; voice (MMS-TTS) &middot; used by the Music/Audio tab &amp; video sound</div>
      </div>
      <div style="display:grid;gap:12px;max-width:820px;">`;
  for (const am of audioModels) {
    const safe = am.key.replace(/[^a-zA-Z0-9_-]/g, '_');
    const dlSt = am.dl_status || null;
    h += `<div class="queue-card" id="amc-${safe}">
      <div style="display:flex;align-items:flex-start;gap:12px;">
        <div style="flex:1;">
          <div style="font-size:.95rem;font-weight:700;">${esc(am.label)}</div>
          <div style="font-size:.75rem;color:var(--muted);margin-top:3px;">${esc(am.kind)} &middot; VRAM ${esc(am.vram)} &middot; ${esc(am.size)}</div>
          ${am.note ? `<div style="font-size:.72rem;color:var(--warn);margin-top:3px;">&#9432; ${esc(am.note)}</div>` : ''}
          ${am.dl_error ? `<div style="font-size:.68rem;color:var(--warn);margin-top:3px;white-space:pre-wrap;">${esc(am.dl_error)}</div>` : ''}
          <div style="font-size:.7rem;color:var(--border);margin-top:3px;">${esc(am.repo)}</div>
        </div>
        <div style="flex-shrink:0;text-align:right;" id="am-btn-${safe}">
          ${am.installed
            ? `<span style="color:var(--green);font-weight:700;font-size:.82rem;">&#10003; Installed</span>`
            : dlSt === 'downloading'
              ? `<button class="btn-sm" disabled>&#11015; ${am.install ? 'Installing' : 'Downloading'}&hellip;</button>`
              : `<button class="btn-sm primary" data-action="dl-audio-model" data-key="${esc(am.key)}" data-install="${am.install?1:0}" id="adl-btn-${safe}" title="Download/install this audio model on the GPU box (one time). Used by the Audio tab and for adding music/voice to videos.">&#11015; ${am.install ? 'Install' : 'Download'}</button>`}
        </div>
      </div>
      <div class="dl-progress" id="adl-prog-${safe}" style="display:${dlSt==='downloading'?'block':'none'};margin-top:10px;">
        <div style="font-size:.75rem;color:var(--muted);margin-bottom:5px;" id="adl-status-${safe}">Working&hellip;</div>
        <div style="background:var(--border);border-radius:4px;height:6px;overflow:hidden;">
          <div style="background:var(--accent);height:100%;width:40%;transition:width .5s;" id="adl-bar-${safe}"></div>
        </div>
        <div style="margin-top:8px;">
          <button class="btn-sm danger" data-action="cancel-adl" data-key="${esc(am.key)}" data-safeid="${safe}" style="font-size:.7rem;">&#10005; Cancel</button>
        </div>
      </div>
    </div>`;
  }
  if (!audioModels.length) {
    h += `<div class="empty"><div class="empty-icon">&#127925;</div>Could not fetch audio models. Check node connection.</div>`;
  }
  h += `</div></div>`;

  // ── 3D Models section ───────────────────────────────────────────────────────────
  const genModels = _genModels;
  h += `
    <div style="margin-top:28px;">
      <div class="section-header">
        <div class="section-title">&#129513; 3D Generation Models</div>
        <div class="section-sub">Image&rarr;3D model makers &middot; installed on the GPU box &middot; used by 3D Studio &rarr; Generate</div>
      </div>
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
  if (!genModels.length) {
    h += `<div class="empty"><div class="empty-icon">&#129513;</div>Could not fetch 3D models. Check box connection.</div>`;
  }
  h += `</div></div>`;

  // GPU queue + active generations now live in the Studio "Queue" sub-tab
  // (the universal queue). Keep a lightweight pointer here instead of duplicating it.
  h += `
    <div style="margin-top:24px;font-size:.8rem;color:var(--muted);">
      &#9889; Live generation status moved to the <a href="#" onclick="studioSub('gpu');return false;"
      style="color:var(--accent);text-decoration:none;font-weight:600;">Queue tab</a>.
    </div>`;

  // ── AI Generation + AI Prompts ───────────────────────────────────────────
  h += `
    <div style="margin-top:24px;display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px;">
      <div class="settings-group">
        <div class="settings-group-title">&#127912; AI Generation</div>
        <div class="field"><label>Default Steps</label><input type="number" id="s-steps" value="${settings.default_steps||20}" min="1" max="150"></div>
        <div class="field"><label>Default Width</label><input type="number" id="s-width" value="${settings.default_width||1024}" step="64"></div>
        <div class="field"><label>Default Height</label><input type="number" id="s-height" value="${settings.default_height||1024}" step="64"></div>
        <div class="field"><label>Default Variations</label><input type="number" id="s-vars" value="${settings.default_variations||3}" min="1" max="10"></div>
        <div class="field">
          <label>Default Image Model</label>
          <select id="s-default-model"><option value="">Loading&hellip;</option></select>
          <div style="font-size:.7rem;color:var(--muted);margin-top:3px;">Used for Proposals &amp; Regeneration. Quick Generate uses the sidebar selector.</div>
        </div>
        <button class="btn-sm primary" id="s-save-3" style="margin-top:10px;">&#128190; Save</button>
      </div>
      <div class="settings-group" style="grid-column:1/-1;">
        <div class="settings-group-title">&#129302; AI Prompts</div>
        <div class="field">
          <label>Image Enhancement Prompt</label>
          <div style="font-size:.72rem;color:var(--muted);margin-bottom:6px;">System prompt sent to the LLM when enhancing rough concepts into detailed image generation prompts. Used for Proposals (Approve), Quick Generate Enhance, and the Enhance button in the proposal modal.</div>
          <textarea id="s-enhance-prompt" rows="9" style="font-family:monospace;font-size:.73rem;">${esc(settings.enhance_system_prompt||'')}</textarea>
        </div>
        <div style="display:flex;gap:8px;margin-top:10px;">
          <button class="btn-sm primary" id="s-save-enhance">&#128190; Save Prompt</button>
          <button class="btn-sm" id="s-reset-enhance">&#8635; Reset to Default</button>
        </div>
      </div>
    </div>`;

  viewRoot().innerHTML = h;

  // Populate model dropdown
  const modelSel = document.getElementById('s-default-model');
  if (modelSel) {
    try {
      const mdata = await api('/api/models');
      const minst = mdata.installed || [];
      const mrec  = mdata.recommended || [];
      const lmap  = {};
      for (const m of mrec) lmap[m.filename] = m.label || m.filename;
      const curModel = settings.default_model || '';
      modelSel.innerHTML = minst.length
        ? minst.map(f => `<option value="${esc(f)}"${f===curModel?' selected':''}>${esc(lmap[f]||f)}</option>`).join('')
        : '<option value="">No models found</option>';
    } catch { modelSel.innerHTML = '<option value="">Error loading</option>'; }
  }

  // Save AI gen settings
  const save3btn = document.getElementById('s-save-3');
  if (save3btn) save3btn.addEventListener('click', async () => {
    const modEl = document.getElementById('s-default-model');
    try {
      await api('/api/settings', { method: 'PATCH', body: JSON.stringify({
        default_steps:      parseInt(document.getElementById('s-steps').value)||20,
        default_width:      parseInt(document.getElementById('s-width').value)||1024,
        default_height:     parseInt(document.getElementById('s-height').value)||1024,
        default_variations: parseInt(document.getElementById('s-vars').value)||3,
        default_model:      modEl ? modEl.value : '',
      }) });
      try { _settings = await api('/api/settings'); } catch {}
      toast('AI settings saved \u2713');
    } catch(e) { toast('Save failed: ' + e.message, 'error'); }
  });

  // Save enhance prompt
  const saveEnhBtn = document.getElementById('s-save-enhance');
  if (saveEnhBtn) saveEnhBtn.addEventListener('click', async () => {
    const val = document.getElementById('s-enhance-prompt').value.trim();
    try {
      await api('/api/settings', { method: 'PATCH', body: JSON.stringify({ enhance_system_prompt: val }) });
      try { _settings = await api('/api/settings'); } catch {}
      toast('Enhance prompt saved \u2713');
    } catch(e) { toast('Save failed: ' + e.message, 'error'); }
  });

  const resetEnhBtn = document.getElementById('s-reset-enhance');
  if (resetEnhBtn) resetEnhBtn.addEventListener('click', async () => {
    if (!confirm('Reset enhance prompt to default?')) return;
    try {
      await api('/api/settings', { method: 'PATCH', body: JSON.stringify({ enhance_system_prompt: '' }) });
      try { _settings = await api('/api/settings'); } catch {}
      renderModels();
      toast('Reset to default \u2713');
    } catch(e) { toast('Reset failed: ' + e.message, 'error'); }
  });

  // (download/cancel actions are handled by the global bindCards delegated listener)

  // Check for in-progress downloads
  for (const m of recommended) {
    if (!m.installed) {
      const safeId2 = m.filename.replace(/[^a-zA-Z0-9_-]/g, '_');
      try {
        const s = await api(`/api/models/${encodeURIComponent(m.filename)}/download-status`);
        if (s.status === 'downloading') {
          const dlBtn = document.getElementById(`dl-btn-${safeId2}`);
          if (dlBtn) dlBtn.style.display = 'none';
          const prog = document.getElementById(`dl-prog-${safeId2}`);
          if (prog) prog.style.removeProperty('display');
          pollDownload(m.filename, safeId2);
        }
      } catch {}
    }
  }
}

const MODEL_SIZES = {
  'sdxl_base_1.0.safetensors': 6938144924,
  'dreamshaperXL_lightningDPMSDE.safetensors': 6938144924,
  'realvisxlV50_v50LightningBakedvae.safetensors': 6938144924,
  'sd_xl_turbo_1.0_fp16.safetensors': 3440912520,
};

const VIDEO_MODEL_SIZES = {
  'Wan-AI--Wan2.1-T2V-1.3B-Diffusers':  5905580032,  // ~5.5 GB
  'Lightricks--LTX-Video':              9663676416,  // ~9 GB
  'THUDM--CogVideoX-2b':               9663676416,  // ~9 GB
};

/* \u2550\u2550 STUDIO MODEL SECTIONS \u2550\u2550
   The old standalone Models tab was split: each engine's model catalog now renders
   inside its Studio sub-tab (Image / Video / Audio / 3D) via appendStudioModels(sub),
   appended under #studio-content by renderStudio(). refreshStudioModels() re-renders
   the current one after a download finishes. renderModels() above is superseded and
   no longer routed to. Download/cancel buttons still work via the global bindCards()
   delegated handler; the pollDownload/pollVideoDownload helpers above are reused. */

function _extraModelsHTML(extra) {
  const groups = (extra && extra.groups) || [];
  let h = '';
  for (const g of groups) {
    h += `<div class="section-header" style="margin-top:26px;"><div><div class="section-title">${esc(g.label)}</div>
      <div class="section-sub">${esc(g.sub)}</div></div></div>
      <div style="display:grid;gap:12px;max-width:820px;">`;
    for (const m of (g.models || [])) {
      const isInst = m.installed;
      const safeId = 'x_' + m.filename.replace(/[^a-zA-Z0-9_-]/g, '_');
      h += `<div class="queue-card" id="mc-${safeId}">
        <div style="display:flex;align-items:flex-start;gap:12px;">
          <div style="flex:1;">
            <div style="font-size:.95rem;font-weight:700;">${esc(m.label || m.filename)}</div>
            <div style="font-size:.75rem;color:var(--muted);margin-top:3px;">${esc(m.style||'')} &middot; ${esc(m.vram||'')} &middot; ${esc(m.source||'')}</div>
            ${m.note ? `<div style="font-size:.72rem;color:var(--warn);margin-top:3px;">&#9432; ${esc(m.note)}</div>` : ''}
            <div style="font-size:.7rem;color:var(--border);margin-top:3px;word-break:break-all;">${esc(m.filename)}</div>
          </div>
          <div style="flex-shrink:0;text-align:right;">
            ${isInst
              ? `<span style="color:var(--green);font-weight:700;font-size:.82rem;">&#10003; Installed</span>`
              : (m.auto_download
                ? `<button class="btn-sm primary" data-action="dl-model" data-filename="${esc(m.filename)}" data-safeid="${safeId}" id="dl-btn-${safeId}" title="Download to the GPU box (one time).">&#11015; Download</button>`
                : `<span style="font-size:.72rem;color:var(--muted)">manual install</span>`)}
          </div>
        </div>
        <div class="dl-progress" id="dl-prog-${safeId}" style="display:none;margin-top:10px;">
          <div style="font-size:.75rem;color:var(--muted);margin-bottom:5px;" id="dl-status-${safeId}">Starting download&#8230;</div>
          <div style="background:var(--border);border-radius:4px;height:6px;overflow:hidden;">
            <div style="background:var(--accent);height:100%;width:0%;transition:width .5s;" id="dl-bar-${safeId}"></div>
          </div>
          <div style="margin-top:8px;display:flex;gap:8px;">
            <button class="btn-sm danger" data-action="cancel-dl" data-filename="${esc(m.filename)}" data-safeid="${safeId}" style="font-size:.7rem;">&#10005; Cancel</button>
          </div>
        </div>
      </div>`;
    }
    h += `</div>`;
  }
  return h;
}

async function appendStudioModels(sub) {
  const root = document.getElementById('studio-content');
  if (!root) return;
  const existing = document.getElementById('studio-models-extra');
  if (existing) existing.remove();
  const box = document.createElement('div');
  box.id = 'studio-models-extra';
  box.style.cssText = 'margin-top:32px;border-top:1px solid var(--border);padding-top:20px;';
  box.innerHTML = '<div style="color:var(--muted);font-size:.8rem;">Loading models&#8230;</div>';
  root.appendChild(box);
  try {
    if (sub === 'image') {
      const [data, settings, loras, extra] = await Promise.all([
        api('/api/models'), api('/api/settings'),
        api('/api/loras').catch(() => ({ recommended: [] })),
        api('/api/extra-models').catch(() => ({ groups: [] })),
      ]);
      box.innerHTML = _imageModelsHTML(data) + _lorasHTML(loras) + _extraModelsHTML(extra) + _imageAiSettingsHTML(settings);
      _wireImageAiSettings(settings);
      _resumeImageDownloads(data.recommended || []);
    } else if (sub === 'video') {
      box.innerHTML = _videoModelsHTML(await api('/api/video-models'));
    } else if (sub === 'audio') {
      box.innerHTML = _audioModelsHTML(await api('/api/audio-models'));
    } else if (sub === '3d') {
      box.innerHTML = _gen3dHTML(await api('/api/models3d/gen-models'));
    } else {
      box.remove();
      return;
    }
    if (typeof bindCards === 'function') bindCards();
  } catch (e) {
    box.innerHTML = `<div style="color:var(--muted);font-size:.8rem;">Models unavailable: ${esc(e.message)}</div>`;
  }
}

// Re-render the current engine's model section (after a download completes).
function refreshStudioModels() {
  const sub = (typeof _studioSub !== 'undefined') ? _studioSub : null;
  if (sub && ['image', 'video', 'audio', '3d'].includes(sub) && document.getElementById('studio-content')) {
    appendStudioModels(sub);
  }
}
