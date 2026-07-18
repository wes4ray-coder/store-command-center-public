/* Models — image family (checkpoints, LoRAs, AI-gen settings + download polling). Split from tab-models.js. */
async function pollDownload(filename, safeId) {
  const totalBytes = MODEL_SIZES[filename] || 0;
  const statusEl = document.getElementById(`dl-status-${safeId}`);
  const barEl = document.getElementById(`dl-bar-${safeId}`);
  for (let i = 0; i < 600; i++) {
    await new Promise(r => setTimeout(r, 4000));
    try {
      const s = await api(`/api/models/${encodeURIComponent(filename)}/download-status`);
      if (s.status === 'done') {
        if (statusEl) statusEl.textContent = '&#10003; Download complete!';
        if (barEl) { barEl.style.width = '100%'; barEl.style.background = 'var(--green)'; }
        toast(`${filename.split('.')[0]} installed!`);
        setTimeout(() => refreshStudioModels(), 2000);
        return;
      }
      if (s.status === 'error') {
        if (statusEl) statusEl.textContent = '&#10060; ' + (s.error || 'Download failed');
        if (barEl) barEl.style.background = 'var(--red)';
        toast('Download failed: ' + (s.error || 'unknown'), 'error');
        return;
      }
      if (s.status === 'cancelled') return;
      if (s.bytes_downloaded) {
        const mb = (s.bytes_downloaded / 1048576).toFixed(0);
        if (totalBytes) {
          const pct = Math.min(99, (s.bytes_downloaded / totalBytes) * 100);
          if (barEl) barEl.style.width = pct.toFixed(1) + '%';
          const gbTotal = (totalBytes / 1073741824).toFixed(1);
          if (statusEl) statusEl.textContent = `Downloading&#8230; ${mb} MB / ${gbTotal} GB`;
        } else {
          if (statusEl) statusEl.textContent = `Downloading&#8230; ${mb} MB`;
        }
      }
    } catch {}
  }
}

function _imageModelsHTML(data) {
  const installed = data.installed || [], recommended = data.recommended || [];
  let h = `<div class="section-header"><div><div class="section-title">&#128444;&#65039; Image Models</div>
      <div class="section-sub">ComfyUI checkpoints on the GPU box &middot; ${esc(data.source || '')} source</div></div></div>
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
  if (!recommended.length) h += `<div class="empty"><div class="empty-icon">&#127981;</div>No models listed. Check ComfyUI connection on the box.</div>`;
  h += `</div>`;
  return h;
}

function _imageAiSettingsHTML(settings) {
  settings = settings || {};
  return `<div style="margin-top:24px;max-width:400px;">
      <div class="settings-group">
        <div class="settings-group-title">&#127912; AI Generation Defaults</div>
        <div class="field"><label>Default Steps ${hlp('How many denoising steps the image model runs. More = more detail/coherence but slower. Lightning/Turbo models want ~4–8; standard SDXL ~20–30. Affects every new generation unless overridden.')}</label><input type="number" id="s-steps" value="${settings.default_steps||20}" min="1" max="150"></div>
        <div class="field"><label>Default Width ${hlp('Output image width in pixels. SDXL is trained on 1024. Larger = slower and more VRAM; non-standard sizes can distort. Affects new generations.')}</label><input type="number" id="s-width" value="${settings.default_width||1024}" step="64"></div>
        <div class="field"><label>Default Height ${hlp('Output image height in pixels (see Width). 1024×1024 is the safe SDXL default; use taller/wider for posters vs. square merch.')}</label><input type="number" id="s-height" value="${settings.default_height||1024}" step="64"></div>
        <div class="field"><label>Default Variations ${hlp('How many images to generate per prompt by default, so you can pick the best. More = more GPU time. Affects the count pre-filled in the generator.')}</label><input type="number" id="s-vars" value="${settings.default_variations||3}" min="1" max="10"></div>
        <div class="field">
          <label>Default Image Model ${hlp('The ComfyUI checkpoint used when the app generates on your behalf — Proposals and Regeneration. (Quick Generate in the sidebar uses its own model picker.) Only installed models appear here.')}</label>
          <select id="s-default-model"><option value="">Loading&hellip;</option></select>
          <div style="font-size:.7rem;color:var(--muted);margin-top:3px;">Used for Proposals &amp; Regeneration. Quick Generate uses the sidebar selector.</div>
        </div>
        <button class="btn-sm primary" id="s-save-3" style="margin-top:10px;">&#128190; Save</button>
        <div style="font-size:.72rem;color:var(--muted);margin-top:12px;">
          &#129302; The image <b>enhancement prompt</b> now lives in
          <a href="#" onclick="switchView('settings');setTimeout(()=>settingsSub('prompts'),50);return false;" style="color:var(--accent);text-decoration:none;">Settings &rarr; Prompts</a>.
        </div>
      </div>
    </div>`;
}

async function _wireImageAiSettings(settings) {
  const modelSel = document.getElementById('s-default-model');
  if (modelSel) {
    try {
      const mdata = await api('/api/models');
      const minst = mdata.installed || [], mrec = mdata.recommended || [];
      const lmap = {};
      for (const m of mrec) lmap[m.filename] = m.label || m.filename;
      const curModel = settings.default_model || '';
      modelSel.innerHTML = minst.length
        ? minst.map(f => `<option value="${esc(f)}"${f===curModel?' selected':''}>${esc(lmap[f]||f)}</option>`).join('')
        : '<option value="">No models found</option>';
    } catch { modelSel.innerHTML = '<option value="">Error loading</option>'; }
  }
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
}

async function _resumeImageDownloads(recommended) {
  for (const m of (recommended || [])) {
    if (m.installed) continue;
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

// Inject the current engine's model catalog under #studio-content (called by renderStudio).
function _lorasHTML(loras) {
  const rec = (loras && loras.recommended) || [];
  let h = `<div class="section-header" style="margin-top:26px;"><div><div class="section-title">&#127912; LoRAs</div>
      <div class="section-sub">Style add-ons for image gen (ComfyUI loras/ dir) &middot; e.g. the pixel-art sprite generator</div></div></div>
    <div style="display:grid;gap:12px;max-width:820px;">`;
  for (const m of rec) {
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
              ? `<button class="btn-sm primary" data-action="dl-model" data-filename="${esc(m.filename)}" data-safeid="${safeId}" id="dl-btn-${safeId}" title="Download this LoRA to the GPU box's loras/ folder (one time). Then pick it in Settings &rarr; \u{1F9E0} Models.">&#11015; Download</button>`
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
  if (!rec.length) h += `<div class="empty"><div class="empty-icon">&#127912;</div>No LoRAs listed. Check ComfyUI connection on the box.</div>`;
  h += `</div>`;
  return h;
}
