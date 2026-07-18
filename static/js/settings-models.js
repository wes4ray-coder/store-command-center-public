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
    }).join('') + (llm.error ? `<div style="font-size:.7rem;color:#e0a05a;margin-top:6px">⚠️ LLM list: ${esc(llm.error)} — saved values still apply.</div>` : '')
      + await _storageCard()
      + await _perModelTuning();
  } catch (e) {
    root.innerHTML = `<div style="color:#e07a7a;font-size:.8rem">Couldn't load the model registry: ${esc(e.message || e)}</div>`;
  }
}
/* ── 📁 STORAGE LOCATIONS — where each model kind lives / downloads on the node.
   Settings win over the .env fallbacks; first line = the active path (downloads +
   HF_HOME), extra lines = additional locations for other layouts. */
async function _storageCard() {
  try {
    const r = await api('/api/models/storage');
    const rows = (r.kinds || []).map(k => `
      <div style="display:grid;grid-template-columns:210px 1fr auto;gap:8px;align-items:start;margin:7px 0">
        <div><b style="font-size:.76rem">${esc(k.label)}</b>
          <div style="font-size:.62rem;color:var(--muted)">setting <code>${esc(k.setting)}</code> · env <code>${esc(k.env)}</code></div></div>
        <div>
          <textarea id="mstore-${k.kind}" rows="1" placeholder="${esc(k.default || '(node default cache)')}"
            title="${esc(k.note)} One path per line — the FIRST is where downloads land; extra lines are additional locations."
            style="width:100%;resize:vertical;padding:5px 8px;background:var(--card);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:.74rem;font-family:ui-monospace,monospace">${esc(k.value)}</textarea>
          <div style="font-size:.64rem;color:var(--muted);margin-top:2px">active: <code>${esc(k.effective || '(node default cache)')}</code>${k.extra.length ? ` · +${k.extra.length} more` : ''} ${k.value ? '' : '· from .env default'}</div>
        </div>
        <button class="btn-sm" onclick="saveModelStorage('${k.kind}')">Save</button>
      </div>`).join('');
    return `<div style="border:1px solid var(--border);border-radius:9px;padding:11px 13px;margin:12px 0;background:rgba(120,150,205,.07)">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px"><b style="font-size:.84rem">📁 Storage locations</b>
        <span id="mstore-status" style="font-size:.68rem;color:var(--muted)"></span></div>
      <div style="font-size:.72rem;color:var(--muted);line-height:1.45;margin-bottom:8px">
        Where each model type lives on the GPU node. Blank = the <code>.env</code>/built-in default shown as the placeholder.
        One path per line: the <b>first</b> is where new downloads land (and what <code>HF_HOME</code> points at); extra lines are
        additional locations for layouts that spread models across drives. Applies to the <i>next</i> download/generation — nothing is moved.
        LLM is informational: LM Studio owns its folder (change it on the node, record it here).</div>
      ${rows}</div>`;
  } catch (e) { return `<div style="font-size:.7rem;color:#e0a05a">storage: ${esc(e.message || e)}</div>`; }
}
async function saveModelStorage(kind) {
  const el = document.getElementById('mstore-' + kind), st = document.getElementById('mstore-status');
  if (!el) return;
  try {
    await api('/api/settings', { method: 'PATCH', body: JSON.stringify({ ['models_dir_' + kind]: el.value.trim() }) });
    if (st) st.textContent = `✓ ${kind} saved — used on the next download/run`;
    loadModelRegistry();
  } catch (e) { if (st) st.textContent = '⚠️ ' + (e.message || e); }
}
window.saveModelStorage = saveModelStorage;

/* ── PER-MODEL TUNING — overrides applied at the LLM proxy, so every consumer
   (world, swarm, oracles, OpenClaw) inherits them. Explicit request params
   always beat these; blank = model default. ── */
async function _perModelTuning() {
  let cfg = {};
  try { cfg = (await api('/api/llm/models/config')).config || {}; } catch { }
  const models = [...new Set([...(_modelOpts.llm || []), ...Object.keys(cfg)])];
  if (!models.length) return '';
  const rows = models.map(m => {
    const c = cfg[m] || {}, id = btoa(m).replace(/=/g, '');
    const num = (k, ph, step) => `<label style="font-size:.66rem;color:var(--muted)">${k}
      <input type="number" step="${step}" id="pmt-${id}-${k}" value="${c[k] ?? ''}" placeholder="${ph}"
        style="width:76px;padding:3px 6px;background:var(--card);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:.72rem"></label>`;
    return `<div style="border:1px solid var(--border);border-radius:8px;padding:8px 11px;margin-bottom:6px;background:var(--card)">
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:5px">
        <b style="font-size:.76rem">${esc(m)}</b>
        ${Object.keys(c).length ? '<span style="font-size:.6rem;color:#8fd0a0">● tuned</span>' : ''}
        <button class="btn" style="margin-left:auto;padding:2px 10px;font-size:.68rem" onclick="savePmt('${esc(m)}','${id}')">💾 Save</button>
        <button class="btn" style="padding:2px 8px;font-size:.68rem" title="How much GPU memory this model wants" onclick="pmtEstimate('${esc(m)}','${id}')">📐</button>
        <button class="btn" style="padding:2px 8px;font-size:.68rem" title="Retune truth-check: load with the saved config and verify it REALLY lands on the GPU (catches silent CPU fallback). Takes 1-4 min." onclick="pmtTest('${esc(m)}','${id}')">🧪 Test</button>
        <span id="pmt-st-${id}" style="font-size:.66rem;color:var(--muted)"></span>
      </div>
      <div style="display:flex;gap:9px;flex-wrap:wrap;align-items:flex-end">
        ${num('temperature', '0.7', '0.05')}${num('top_p', '0.95', '0.05')}${num('max_tokens', 'auto', '64')}
        ${num('repeat_penalty', '1.1', '0.05')}${num('presence_penalty', '0', '0.1')}${num('seed', 'random', '1')}
        ${num('context_length', 'model dflt', '1024')}${num('ttl', 'global', '300')}${num('parallel', '4', '1')}
        <label style="font-size:.66rem;color:var(--muted)" title="Pinned models are never evicted by other loads — pair a pinned GPU model with @cpu side-models for a true multi-model setup.">pin
          <input type="checkbox" id="pmt-${id}-pin" ${c.pin ? 'checked' : ''} style="width:16px;height:16px;vertical-align:middle"></label>
        <label style="font-size:.66rem;color:var(--muted)" title="GPU offload: max = all layers on GPU, off = CPU only, 0–1 = fraction of layers. Load-time — applies at the model's NEXT load.">gpu
          <input type="text" id="pmt-${id}-gpu" value="${esc(c.gpu ?? '')}" placeholder="max / 0.6 / off"
            style="width:76px;padding:3px 6px;background:var(--card);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:.72rem"></label>
        <label style="font-size:.66rem;color:var(--muted);flex:1;min-width:220px">system_prepend
          <input type="text" id="pmt-${id}-system_prepend" value="${esc(c.system_prepend || '')}" placeholder="prefixed to every system prompt for this model"
            style="width:100%;padding:3px 6px;background:var(--card);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:.72rem"></label>
      </div>
    </div>`;
  }).join('');
  const dl = `<div style="border:1px solid var(--border);border-radius:9px;padding:11px 13px;margin:12px 0;background:rgba(120,150,205,.07)">
    <div style="font-weight:700;font-size:.84rem;margin-bottom:3px">⬇️ Download an LLM</div>
    <div style="font-size:.7rem;color:var(--muted);margin-bottom:8px">Pulls onto the GPU node via <code>lms get</code> — lands in the storage location configured above. Use LM Studio / Hugging Face ids, e.g. <code>qwen/qwen3.5-9b</code>.</div>
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <input id="llm-dl-id" placeholder="publisher/model-id" style="flex:1;min-width:240px;padding:6px 9px;background:var(--card);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:.78rem" onkeydown="if(event.key==='Enter')llmDownload()">
      <button class="btn-sm" onclick="llmDownload()">⬇️ Download</button>
      <span id="llm-dl-status" style="font-size:.68rem;color:var(--muted)"></span>
    </div></div>`;
  const addAlias = `<div style="display:flex;gap:8px;align-items:center;margin:0 0 8px">
    <input id="pmt-new-id" placeholder="add a model or CPU alias, e.g. google/gemma-4-12b-qat@cpu"
      style="flex:1;min-width:260px;padding:5px 8px;background:var(--card);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:.74rem"
      onkeydown="if(event.key==='Enter'){savePmt(this.value.trim(), btoa(this.value.trim()).replace(/=/g,'')); setTimeout(loadModelRegistry, 600);}">
    <span style="font-size:.64rem;color:var(--muted)">an <code>@cpu</code> id loads the SAME model as a second CPU-placed instance — GPU + CPU side-by-side (replaces the copy-and-rename trick)</span>
  </div>`;
  return `${dl}<div style="margin-top:16px">
    <div style="font-weight:700;font-size:.84rem;margin-bottom:3px">🎛️ Per-model tuning</div>${addAlias}
    <div style="font-size:.7rem;color:var(--muted);margin-bottom:8px">Applied at the LLM proxy for EVERY caller (world · swarm · oracles · OpenClaw). Requests that set a param explicitly keep their own value; blank fields fall back to the model's default.</div>
    ${rows}</div>`;
}
async function savePmt(model, id) {
  const st = document.getElementById('pmt-st-' + id);
  const keys = ['temperature', 'top_p', 'max_tokens', 'repeat_penalty', 'presence_penalty', 'seed',
                'context_length', 'ttl', 'parallel', 'gpu', 'system_prepend'];
  const config = {};
  for (const k of keys) {
    const el = document.getElementById(`pmt-${id}-${k}`);
    if (el && el.value !== '') config[k] = (k === 'system_prepend' || k === 'gpu') ? el.value : parseFloat(el.value);
  }
  const pinEl = document.getElementById(`pmt-${id}-pin`);
  if (pinEl && pinEl.checked) config.pin = true;
  if (st) { st.textContent = 'saving…'; st.style.color = 'var(--muted)'; }
  try {
    await api('/api/llm/models/config', { method: 'POST', body: JSON.stringify({ model, config }) });
    if (st) { st.textContent = '✓ applies to all callers'; st.style.color = '#8fd0a0'; }
  } catch (e) { if (st) { st.textContent = '✗ ' + (e.message || e); st.style.color = '#e07a7a'; } }
}
window.savePmt = savePmt;
async function pmtEstimate(model, id) {
  const st = document.getElementById('pmt-st-' + id);
  if (st) { st.textContent = 'estimating…'; st.style.color = 'var(--muted)'; }
  try {
    const r = await api('/api/llm/models/estimate', { method: 'POST', body: JSON.stringify({ model }) });
    if (st) { st.textContent = r.estimate_gib ? `wants ~${r.estimate_gib} GiB (12 GiB card)` : 'no estimate'; st.style.color = r.estimate_gib > 11.5 ? '#e0a05a' : '#8fd0a0'; }
  } catch (e) { if (st) { st.textContent = '✗ ' + (e.message || e); st.style.color = '#e07a7a'; } }
}
async function pmtTest(model, id) {
  const st = document.getElementById('pmt-st-' + id);
  if (st) { st.textContent = '🧪 loading + verifying (1-4 min)…'; st.style.color = 'var(--muted)'; }
  try {
    const r = await api('/api/llm/models/testload', { method: 'POST', body: JSON.stringify({ model }) });
    if (st) { st.textContent = `${r.verdict} · ${Math.round((r.vram_mb || 0) / 102.4) / 10} GiB VRAM`; st.style.color = r.gpu_real ? '#8fd0a0' : '#e0a05a'; }
  } catch (e) { if (st) { st.textContent = '✗ ' + (e.message || e); st.style.color = '#e07a7a'; } }
}
window.pmtEstimate = pmtEstimate; window.pmtTest = pmtTest;
async function llmDownload() {
  const el = document.getElementById('llm-dl-id'), st = document.getElementById('llm-dl-status');
  const m = (el && el.value || '').trim();
  if (!m) return;
  if (st) { st.textContent = 'starting…'; st.style.color = 'var(--muted)'; }
  try {
    const r = await api('/api/llm/models/download', { method: 'POST', body: JSON.stringify({ model: m }) });
    if (st) { st.textContent = '⬇️ ' + (r.note || 'downloading'); st.style.color = '#8fd0a0'; }
  } catch (e) { if (st) { st.textContent = '✗ ' + (e.message || e); st.style.color = '#e07a7a'; } }
}
window.llmDownload = llmDownload;

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
