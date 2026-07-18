// ── Model registry (Settings → 🧠 Models) ──
let _modelOpts = { llm: [], image: [] };
async function loadModelRegistry() {
  const root = document.getElementById('model-registry-slot');
  if (!root) return;
  root.innerHTML = '<div style="color:var(--muted);font-size:.8rem;">Loading models&#8230;</div>';
  try {
    const [reg, llm, img] = await Promise.all([
      api('/api/models/registry'),
      api('/api/settings/llm-models').catch(() => ({ models: [] })),
      api('/api/models').catch(() => ({ installed: [] })),
    ]);
    _modelOpts.llm = llm.models || [];
    _modelOpts.image = (img.installed || []).map(m => (typeof m === 'string' ? m : m.name)).filter(Boolean);
    const kindTag = { llm: '💬 text', vision: '👁️ vision', image: '🖼️ image', lora: '🎨 lora' };
    const ttl = reg.idle_ttl != null ? reg.idle_ttl : 1800;
    const ttlBlock = `<div style="border:1px solid var(--border);border-radius:9px;padding:11px 13px;margin-bottom:12px;background:rgba(120,150,205,.07)">
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:4px">
        <b style="font-size:.84rem">⏱️ Idle auto-unload (TTL)</b>
        <span style="font-size:.66rem;color:#8fd0a0">${ttl > 0 ? 'unloads after ' + Math.round(ttl / 60) + ' min idle' : 'off — models stay resident'}</span>
      </div>
      <div style="font-size:.72rem;color:var(--muted);line-height:1.45;margin-bottom:8px">
        Every model the queue loads is loaded with <code>lms load --ttl</code>, so the node frees its VRAM
        when the model sits unused this long. 0 = never auto-unload. Applies to the next load.</div>
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
        <input type="number" id="mdl-idle-ttl" min="0" step="60" value="${ttl}" style="width:110px;padding:6px 9px;background:var(--card);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:.78rem">
        <span style="font-size:.7rem;color:var(--muted)">seconds</span>
        <button class="btn-sm" onclick="setIdleTtl()">Save</button>
        <span style="font-size:.68rem;color:var(--muted)">presets:
          <a href="#" onclick="document.getElementById('mdl-idle-ttl').value=600;setIdleTtl();return false">10m</a> ·
          <a href="#" onclick="document.getElementById('mdl-idle-ttl').value=1800;setIdleTtl();return false">30m</a> ·
          <a href="#" onclick="document.getElementById('mdl-idle-ttl').value=0;setIdleTtl();return false">never</a></span>
        <span id="mdl-idle-status" style="font-size:.68rem;color:var(--muted)"></span>
      </div></div>`;
    root.innerHTML = ttlBlock + (reg.slots || []).map(s => {
      const optsFor = (s.kind === 'image') ? _modelOpts.image : _modelOpts.llm;
      let control;
      if (s.kind === 'lora') {
        control = `<input type="text" id="mdl-${s.key}" value="${esc(s.raw)}" placeholder="${esc(s.default || 'file.safetensors:0.9')}"
                     style="flex:1;min-width:220px;padding:6px 9px;background:var(--card);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:.78rem"
                     onchange="setModelSlot('${s.key}', this.value)">`;
      } else {
        const _fbName = { enhance_model: 'global Text LLM', default_model: 'default image checkpoint' };
        const blankLabel = s.fallback ? `— use ${esc(_fbName[s.fallback] || s.fallback)} —` : '— default —';
        const opts = [`<option value="">${blankLabel}</option>`]
          .concat(optsFor.map(m => `<option value="${esc(m)}" ${m === s.raw ? 'selected' : ''}>${esc(m)}</option>`));
        // if the saved value isn't in the list (e.g. node offline), keep it selectable
        if (s.raw && !optsFor.includes(s.raw)) opts.splice(1, 0, `<option value="${esc(s.raw)}" selected>${esc(s.raw)} (saved)</option>`);
        control = `<select id="mdl-${s.key}" onchange="setModelSlot('${s.key}', this.value)"
                     style="flex:1;min-width:220px;max-width:420px;padding:6px 9px;background:var(--card);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:.78rem">${opts.join('')}</select>`;
      }
      const eff = s.value ? `<span style="font-size:.66rem;color:#8fd0a0">▶ ${esc(s.value.split('/').pop())}</span>` : '<span style="font-size:.66rem;color:#e0a05a">not set</span>';
      return `<div style="border:1px solid var(--border);border-radius:9px;padding:11px 13px;margin-bottom:9px;background:var(--card)">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:5px">
          <b style="font-size:.84rem">${esc(s.name)}</b>
          <span style="font-size:.6rem;padding:1px 6px;border-radius:8px;background:rgba(120,150,205,.15);color:#9fb4d8">${kindTag[s.kind] || s.kind}</span>
          ${eff}
        </div>
        <div style="font-size:.72rem;color:var(--muted);line-height:1.45;margin-bottom:8px">${esc(s.desc)}</div>
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">${control}
          <span id="mdl-status-${s.key}" style="font-size:.68rem;color:var(--muted)"></span></div>
      </div>`;
    }).join('') + (llm.error ? `<div style="font-size:.7rem;color:#e0a05a;margin-top:6px">⚠️ LLM list: ${esc(llm.error)} — saved values still apply.</div>` : '');
  } catch (e) {
    root.innerHTML = `<div style="color:#e07a7a;font-size:.8rem">Couldn't load the model registry: ${esc(e.message || e)}</div>`;
  }
}
async function setIdleTtl() {
  const el = document.getElementById('mdl-idle-ttl'), st = document.getElementById('mdl-idle-status');
  const seconds = Math.max(0, parseInt(el && el.value, 10) || 0);
  if (st) { st.textContent = 'saving…'; st.style.color = 'var(--muted)'; }
  try {
    await api('/api/models/idle-ttl', { method: 'POST', body: JSON.stringify({ seconds }) });
    if (st) { st.textContent = '✓ saved'; st.style.color = '#8fd0a0'; }
    setTimeout(() => loadModelRegistry(), 700);
  } catch (e) {
    if (st) { st.textContent = '✗ ' + (e.message || 'failed'); st.style.color = '#e07a7a'; }
  }
}
async function setModelSlot(key, value) {
  const st = document.getElementById('mdl-status-' + key);
  if (st) { st.textContent = 'saving…'; st.style.color = 'var(--muted)'; }
  try {
    const r = await api('/api/models/registry', { method: 'POST', body: JSON.stringify({ key, value }) });
    if (st) { st.textContent = '✓ saved' + (r.effective ? ' → ' + r.effective.split('/').pop() : ''); st.style.color = '#8fd0a0'; }
    setTimeout(() => loadModelRegistry(), 700);   // refresh effective/fallback badges
  } catch (e) {
    if (st) { st.textContent = '✗ ' + (e.message || 'failed'); st.style.color = '#e07a7a'; }
  }
}
