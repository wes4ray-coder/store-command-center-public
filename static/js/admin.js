/* Admin / System settings panel: server config, backups, restart, sign out.
   Mounted into #admin-panel-slot by renderSettings(). */

function _fmtBytes(n) {
  if (n < 1024) return n + ' B';
  if (n < 1048576) return (n / 1024).toFixed(0) + ' KB';
  if (n < 1073741824) return (n / 1048576).toFixed(1) + ' MB';
  return (n / 1073741824).toFixed(2) + ' GB';
}
function _fmtTime(sec) {
  try { return new Date(sec * 1000).toLocaleString(); } catch { return ''; }
}

async function mountAdminPanel() {
  const slot = document.getElementById('admin-panel-slot');
  if (!slot) return;
  let sv = {}, nodes = {}, settings = {};
  try { sv = await api('/api/settings/server'); } catch {}
  try { nodes = await api('/api/settings/nodes'); } catch {}
  try { settings = await api('/api/settings'); } catch {}

  slot.innerHTML = `
    <div class="settings-group-title">&#128421;&#65039; Server</div>
    <div style="font-size:.75rem;color:var(--muted);margin-bottom:10px;">Identity &amp; location. Saved to <code>.env</code>; a restart applies them.</div>
    <div class="field"><label>App Name ${hlp('The name shown in the app’s title/header. Cosmetic branding for this instance. Written to .env; takes effect after a restart.')}</label><input type="text" id="sv-name" value="${esc(sv.app_name||'')}"></div>
    <div class="field"><label>Port ${hlp('The TCP port uvicorn serves on (default 8787). Must match your nginx/reverse-proxy config or the site won’t load. Change only if the port conflicts. Needs a restart.')}</label><input type="text" id="sv-port" value="${esc(String(sv.port||''))}"></div>
    <div class="field"><label>URL Base Path <span style="color:var(--muted)">(reverse-proxy prefix, "" = root)</span> ${hlp('The path prefix the app is served under (here: /store). It must match the reverse-proxy route. Getting it wrong breaks all JS/CSS/API links. Leave “/store” unless you re-map the proxy. Needs a restart.')}</label><input type="text" id="sv-base" value="${esc(sv.base_path||'')}" placeholder="/store"></div>
    <div class="field"><label>Data Directory <span style="color:var(--muted)">(db, designs, videos, backups)</span> ${hlp('Absolute folder where the SQLite DB, generated designs/videos, and backups live. Move it to a bigger disk if you’re low on space. Point it at an EXISTING copy to migrate. Needs a restart.')}</label><input type="text" id="sv-data" value="${esc(sv.data_dir||'')}"></div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:6px;">
      <button class="btn-sm primary" onclick="saveServerSettings()">&#128190; Save (needs restart)</button>
      <button class="btn-sm" onclick="systemRestart()">&#128260; Restart Server</button>
      <button class="btn-sm" onclick="browserReset()" title="Fix a stuck automation browser (stale Chrome lock)">&#128295; Fix Browser Lock</button>
      <a class="btn-sm" href="${API}/logout" style="text-decoration:none;color:#f87171;border-color:rgba(239,68,68,.4);">&#128275; Sign Out</a>
    </div>
    <div id="sv-msg" style="font-size:.75rem;margin-top:8px;"></div>
    <div id="gpu-busy-banner" style="margin-top:8px;"></div>

    <div class="settings-group-title" style="margin-top:22px;">&#129513; Compute Nodes / Model Hosts</div>
    <div style="font-size:.75rem;color:var(--muted);margin-bottom:10px;">Where each kind of model runs. Point these at any machine on your network. Saved to <code>.env</code>; a restart applies them. Image &amp; Video share the ComfyUI host.</div>
    <div class="field"><label>&#129504; LLM &mdash; LM Studio URL <span style="color:var(--muted)">(text / prompts / listings)</span> ${hlp('The OpenAI-compatible endpoint of LM Studio on your GPU box. Every text task — prompt enhance, listing copy, research, haggling, the assistant — calls this. If it’s wrong/unreachable, all those features fail. Include the /v1 suffix. Needs a restart.')}</label>
      <input type="text" id="nd-llm" value="${esc(nodes.llm_url||'')}" placeholder="http://127.0.0.1:1234/v1"></div>
    <div class="field"><label>&#129504; LLM model <span style="color:var(--muted)">(used for prompts, listings, haggling, enhance)</span> ${hlp('Which model (already loaded in LM Studio on the GPU box) every text task uses — prompt enhance, listing copy, haggling, the assistant. The list is read live from that node; pick one and click Use. Applies on the next task, no restart. For adult content pick an uncensored model.')}</label>
      <div style="display:flex;gap:6px;align-items:center;">
        <select id="llm-model-select" style="flex:1;padding:7px 8px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px;"><option>Loading&hellip;</option></select>
        <button class="btn-sm primary" onclick="saveLlmModel()" title="Set the selected model as the app's LLM. Takes effect on the next text task; no restart.">&#128190; Use</button>
        <button class="btn-sm" onclick="loadLlmModels()" title="Refresh model list from LM Studio">&#128260;</button>
      </div>
      <div id="llm-model-msg" style="font-size:.72rem;color:var(--muted);margin-top:3px;"></div></div>
    <div class="field"><label>&#128273; LM Studio API key <span style="color:var(--muted)">(if the node requires one — locks the LLM to authorized callers)</span> ${hlp('Only needed if LM Studio on the GPU box is set to require a key. Sent as a Bearer token on every LLM call. Leave blank for an open LAN node. Stored locally; applies on the next call, no restart.')}</label>
      <div style="display:flex;gap:6px;">
        <input type="password" id="llm-api-key" value="${esc(settings.lmstudio_api_key||'')}" placeholder="sk-lm-xxxx:yyyy" style="flex:1;padding:7px 8px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px;">
        <button class="btn-sm primary" onclick="saveLlmKey()">&#128190; Save</button>
      </div>
      <div id="llm-key-msg" style="font-size:.72rem;color:var(--muted);margin-top:3px;"></div></div>
    <div class="field"><label>&#127912; Image &amp; &#127916; Video &mdash; ComfyUI URL ${hlp('The ComfyUI server on your GPU box (default port 8188). Drives ALL image and video generation. If unreachable, generating and the GPU queue break. Image and video share this one host.')}</label>
      <input type="text" id="nd-comfy" value="${esc(nodes.comfyui_url||'')}" placeholder="http://127.0.0.1:8188"></div>
    <div style="display:flex;gap:8px;">
      <div class="field" style="flex:2;"><label>&#129513; 3D node &mdash; host / IP <span style="color:var(--muted)">(SSH: 3D gen, installs)</span> ${hlp('IP/hostname the app SSHes into to run image→3D generation and to install models on the box. Used for 3D Studio → Generate and the model Install/Test buttons. Requires key-based SSH as the user below.')}</label>
        <input type="text" id="nd-host" value="${esc(nodes.gpu_host||'')}" placeholder="127.0.0.1"></div>
      <div class="field" style="flex:1;"><label>SSH user ${hlp('The Linux username the app logs in as over SSH on the 3D node. Must have passwordless (key) SSH set up and permission to run the model tooling.')}</label>
        <input type="text" id="nd-user" value="${esc(nodes.ssh_user||'')}" placeholder="user"></div>
    </div>
    <div class="field"><label>&#127925; Audio / Music URL <span style="color:var(--muted)">(optional / future)</span> ${hlp('Optional endpoint for a dedicated audio/music service. The audio engines currently run via the GPU node, so this is usually left blank / for future use.')}</label>
      <input type="text" id="nd-audio" value="${esc(nodes.audio_url||'')}" placeholder="http://127.0.0.1:XXXX"></div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:6px;">
      <button class="btn-sm primary" onclick="saveNodeSettings()">&#128190; Save (needs restart)</button>
      <button class="btn-sm" onclick="systemRestart()">&#128260; Restart Server</button>
    </div>
    <div id="nd-msg" style="font-size:.75rem;margin-top:8px;"></div>

    <div class="field" style="margin-top:14px;"><label>&#129303; HuggingFace token <span style="color:var(--muted)">(for gated models e.g. Stable Fast 3D)</span> ${hlp('A HuggingFace read token so the GPU box can download license-gated models (accept the model license on huggingface.co first). Used during node Deploy and 3D installs. Applies immediately, no restart.')}</label>
      <div style="display:flex;gap:6px;">
        <input type="password" id="hf-token" value="${esc(settings.hf_token||'')}" placeholder="hf_xxx (accept the model license on huggingface.co first)" style="flex:1;">
        <button class="btn-sm primary" onclick="saveHfToken()">&#128190; Save</button>
      </div></div>
    <div id="hf-msg" style="font-size:.75rem;margin-top:4px;"></div>

    <div class="settings-group-title" style="margin-top:22px;">&#127859; Content</div>
    <label style="display:flex;gap:10px;align-items:flex-start;cursor:pointer;padding:10px;border:1px solid var(--border);border-radius:8px;">
      <input type="checkbox" id="nsfw-toggle" ${(settings.nsfw_enabled||'').toString().toLowerCase().match(/^(1|true|on|yes)$/)?'checked':''} onchange="saveNsfw()" style="margin-top:3px;">
      <span><b>&#128286; Allow NSFW / adult content</b><br><span style="color:var(--muted);font-size:.78rem;">Un-censors the local LLM (no refusals/disclaimers) for prompts, descriptions &amp; listings across image, video, audio &amp; 3D. Off by default. Image/video/audio models aren't filtered — this mainly frees the text model. Pick an uncensored model above for best results.</span></span>
    </label>
    <div id="nsfw-msg" style="font-size:.72rem;color:var(--muted);margin-top:4px;"></div>

    <div class="settings-group-title" style="margin-top:22px;">&#128421;&#65039; GPU Node</div>
    <div style="font-size:.75rem;color:var(--muted);margin-bottom:10px;">Provision &amp; health-check the GPU box — image (ComfyUI), video, 3D, audio/music, LM Studio, and the autostart services. Deploy downloads any missing dependencies.</div>
    <div id="node-panel" style="font-size:.8rem;color:var(--muted);">Checking node&hellip;</div>

    <div class="settings-group-title" style="margin-top:22px;">&#128190; Backups</div>
    <div style="font-size:.75rem;color:var(--muted);margin-bottom:10px;">Stored in the store's data folder. Restore is destructive (a safety backup is taken first).</div>
    <div style="margin-bottom:10px;"><button class="btn-sm primary" onclick="createBackup()" id="bk-create">&#10133; Create Backup</button></div>
    <div id="backups-list" style="font-size:.78rem;color:var(--muted);">Loading&hellip;</div>

    <div class="settings-group-title" style="margin-top:22px;">&#128220; Store Logs</div>
    <div style="font-size:.75rem;color:var(--muted);margin-bottom:8px;">Everything the server logs — errors, warnings, background jobs. Rotating file in the data folder.</div>
    <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-bottom:8px;">
      <select id="log-level" onchange="loadStoreLogs()" style="padding:5px 8px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px;font-size:.78rem;">
        <option value="">All</option><option value="ERROR">Errors</option><option value="WARNING">Warnings+</option></select>
      <input id="log-search" placeholder="filter text…" onkeydown="if(event.key==='Enter')loadStoreLogs()" style="flex:1;min-width:120px;padding:5px 8px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px;font-size:.78rem;">
      <button class="btn-sm" onclick="loadStoreLogs()">&#128260; Refresh</button>
      <label style="font-size:.72rem;color:var(--muted);display:flex;align-items:center;gap:3px;cursor:pointer;"><input type="checkbox" id="log-auto" onchange="toggleLogAuto()"> auto</label>
      <span id="log-tally" style="font-size:.72rem;color:var(--muted);"></span>
    </div>
    <pre id="store-logs" style="max-height:360px;overflow:auto;background:#0b0b0f;border:1px solid var(--border);border-radius:8px;padding:10px;font-size:.7rem;line-height:1.35;white-space:pre-wrap;color:#cbd5e1;margin:0;">Loading&hellip;</pre>
  `;
  loadBackups();
  loadNodePanel();
  refreshGpuBusy();
  loadLlmModels();
  loadStoreLogs();
}

let _logAutoTimer = null;
function _colorLogLine(l) {
  const e = document.createElement('div');
  e.textContent = l;
  if (/ ERROR | CRITICAL /.test(l)) e.style.color = '#f87171';
  else if (/ WARNING /.test(l)) e.style.color = '#fbbf24';
  else if (/ DEBUG /.test(l)) e.style.color = '#6b7280';
  return e.outerHTML;
}
async function loadStoreLogs() {
  const pre = document.getElementById('store-logs');
  const tally = document.getElementById('log-tally');
  if (!pre) return;
  const level = document.getElementById('log-level')?.value || '';
  const q = document.getElementById('log-search')?.value.trim() || '';
  try {
    const r = await api(`/api/system/logs?lines=400&level=${encodeURIComponent(level)}&q=${encodeURIComponent(q)}`);
    if (r.note) { pre.textContent = r.note; if (tally) tally.textContent = ''; return; }
    const lines = r.lines || [];
    pre.innerHTML = lines.length ? lines.map(_colorLogLine).join('') : '<span style="color:var(--muted)">(no matching lines)</span>';
    pre.scrollTop = pre.scrollHeight;
    if (tally) tally.innerHTML = `<span style="color:#f87171">${r.errors||0} err</span> · <span style="color:#fbbf24">${r.warnings||0} warn</span>`;
  } catch (e) { pre.textContent = 'Error loading logs: ' + e.message; }
}
window.loadStoreLogs = loadStoreLogs;

function toggleLogAuto() {
  const on = document.getElementById('log-auto')?.checked;
  if (_logAutoTimer) { clearInterval(_logAutoTimer); _logAutoTimer = null; }
  if (on) _logAutoTimer = setInterval(loadStoreLogs, 3000);
}
window.toggleLogAuto = toggleLogAuto;

async function loadLlmModels() {
  const sel = document.getElementById('llm-model-select');
  const msg = document.getElementById('llm-model-msg');
  if (!sel) return;
  sel.innerHTML = '<option>Loading…</option>';
  try {
    const d = await api('/api/settings/llm-models');
    if (!d.models || !d.models.length) {
      sel.innerHTML = `<option value="${esc(d.current || '')}">${esc(d.current || '(none)')}</option>`;
      if (msg) { msg.style.color = 'var(--warn)'; msg.textContent = d.error || 'No models found on LM Studio.'; }
      return;
    }
    sel.innerHTML = d.models.map(m => `<option value="${esc(m)}"${m === d.current ? ' selected' : ''}>${esc(m)}</option>`).join('');
    if (msg) { msg.style.color = 'var(--muted)'; msg.textContent = `In use: ${d.current}`; }
  } catch (e) { if (msg) { msg.style.color = 'var(--warn)'; msg.textContent = 'Error: ' + e.message; } }
}
window.loadLlmModels = loadLlmModels;

async function saveNsfw() {
  const on = document.getElementById('nsfw-toggle')?.checked;
  const msg = document.getElementById('nsfw-msg');
  try {
    await api('/api/settings', { method: 'PATCH', body: JSON.stringify({ nsfw_enabled: on ? 'true' : '' }) });
    if (msg) { msg.style.color = on ? '#f59e0b' : 'var(--green)'; msg.textContent = on ? '🔞 NSFW allowed — applies to the next LLM call.' : '✓ NSFW off (default safety).'; }
    toast(on ? 'NSFW content allowed' : 'NSFW disabled');
  } catch (e) { if (msg) { msg.style.color = 'var(--warn)'; msg.textContent = 'Error: ' + e.message; } }
}
window.saveNsfw = saveNsfw;

async function saveLlmKey() {
  const k = document.getElementById('llm-api-key')?.value.trim() || '';
  const msg = document.getElementById('llm-key-msg');
  try {
    await api('/api/settings', { method: 'PATCH', body: JSON.stringify({ lmstudio_api_key: k }) });
    if (msg) { msg.style.color = 'var(--green)'; msg.textContent = k ? '✓ Saved — sent as Bearer token on the next LLM call.' : '✓ Cleared (no auth header).'; }
    toast('LM Studio API key saved');
  } catch (e) { if (msg) { msg.style.color = 'var(--warn)'; msg.textContent = 'Error: ' + e.message; } }
}
window.saveLlmKey = saveLlmKey;

async function saveLlmModel() {
  const sel = document.getElementById('llm-model-select');
  const msg = document.getElementById('llm-model-msg');
  const m = sel && sel.value;
  if (!m) return;
  try {
    await api('/api/settings', { method: 'PATCH', body: JSON.stringify({ enhance_model: m }) });
    if (msg) { msg.style.color = 'var(--green)'; msg.textContent = `✓ LLM model set to ${m} — applies to the next task.`; }
    toast('LLM model set: ' + m);
  } catch (e) { if (msg) { msg.style.color = 'var(--warn)'; msg.textContent = 'Error: ' + e.message; } }
}
window.saveLlmModel = saveLlmModel;

// Live "GPU busy" indicator — polls while the Settings panel is open so both people/
// agents can see when it's safe to restart (a restart kills in-flight generations).
let _gpuBusyTimer = null;
async function refreshGpuBusy() {
  const el = document.getElementById('gpu-busy-banner');
  if (!el) { if (_gpuBusyTimer) { clearTimeout(_gpuBusyTimer); _gpuBusyTimer = null; } return; }
  let s = { busy: false, total: 0, jobs: [] };
  try { s = await api('/api/system/gpu-status'); } catch {}
  const restartBtns = document.querySelectorAll('button[onclick="systemRestart()"]');
  if (s.busy) {
    const detail = (s.jobs || []).map(j => `${j.count} ${j.kind}`).join(', ');
    el.innerHTML = `<div style="background:#2a1005;border:1px solid #f59e0b80;border-radius:8px;padding:8px 10px;font-size:.78rem;color:#fcd34d">
      &#9203; <b>GPU busy — ${s.total} job(s) running/queued</b>${detail ? ' ('+esc(detail)+')' : ''}.
      Restarting now will kill them — wait for them to finish.</div>`;
    restartBtns.forEach(b => { b.style.opacity = '.55'; b.title = `${s.total} GPU job(s) in flight — restart will kill them`; });
  } else {
    el.innerHTML = `<div style="font-size:.74rem;color:var(--green)">&#10003; GPU idle — safe to restart.</div>`;
    restartBtns.forEach(b => { b.style.opacity = ''; b.title = ''; });
  }
  if (_gpuBusyTimer) clearTimeout(_gpuBusyTimer);
  _gpuBusyTimer = setTimeout(refreshGpuBusy, 4000);
}
window.refreshGpuBusy = refreshGpuBusy;

const _NODE_COMPONENTS = [
  ['gpu', '&#127918; GPU / driver'], ['comfyui', '&#127912; Image (ComfyUI)'],
  ['video', '&#127916; Video (diffusers)'], ['model3d', '&#128230; 3D (TripoSR)'],
  ['audio', '&#127925; Audio / music'], ['lmstudio', '&#129504; LM Studio (LLM)'],
  ['services', '&#9881;&#65039; Autostart services'],
];
function _nodeDot(v) {
  const m = { ok: ['#22c55e', '&#10003;'], up: ['#22c55e', '&#10003;'],
    missing: ['#f59e0b', '&#9679;'], skipped: ['#f59e0b', '&#9679;'],
    down: ['#f59e0b', '&#9679;'], failed: ['#ef4444', '&#10007;'], na: ['#6b7280', '&#8211;'] };
  const [c, ic] = m[v] || ['#6b7280', '?'];
  return `<span style="color:${c};font-weight:700">${ic}</span> <span style="color:var(--muted)">${v || 'unknown'}</span>`;
}

async function loadNodePanel() {
  const el = document.getElementById('node-panel');
  if (!el) return;
  el.innerHTML = 'Checking node&hellip;';
  let s;
  try { s = await api('/api/node/status'); }
  catch (e) { el.innerHTML = `<span style="color:var(--warn)">Node check failed: ${esc(e.message)}</span> <button class="btn-sm" onclick="loadNodePanel()">&#128260; Retry</button>`; return; }

  if (!s.reachable) {
    el.innerHTML = `<div style="background:#1a0f0f;border:1px solid #ef444450;border-radius:8px;padding:12px;color:#fca5a5">
      &#9888;&#65039; <b>GPU node unreachable</b> at ${esc(s.gpu_host || '')}.<br>${esc(s.error || '')}
      <div style="margin-top:8px"><button class="btn-sm" onclick="loadNodePanel()">&#128260; Retry</button></div></div>`;
    return;
  }
  if (!s.os_ok) {
    // The "you need Ubuntu" gate.
    el.innerHTML = `<div style="background:#2a1005;border:1px solid #f59e0b80;border-radius:8px;padding:14px;color:#fcd34d">
      &#9888;&#65039; <b>Your GPU node must run Ubuntu.</b><br>
      <div style="margin:6px 0;color:#fde68a">Detected: <b>${esc(s.os || 'not Linux')}</b></div>
      <div style="font-size:.78rem;color:#fbbf24">${esc(s.note || 'Windows/macOS can’t autostart the CUDA services (ComfyUI, diffusers, LM Studio headless) the node needs. Install Ubuntu 24.04 on the GPU machine, then re-check.')}</div>
      <div style="margin-top:10px"><button class="btn-sm" onclick="loadNodePanel()">&#128260; Re-check</button></div></div>`;
    return;
  }
  const grid = _NODE_COMPONENTS.map(([k, label]) =>
    `<div style="display:flex;justify-content:space-between;gap:10px;padding:4px 0;border-bottom:1px solid var(--border)">
      <span>${label}</span>${_nodeDot(s[k])}</div>`).join('');
  const servers = `<div style="display:flex;gap:14px;margin:8px 0;font-size:.75rem">
      <span>LLM server: ${_nodeDot(s.llm_server)}</span>
      <span>ComfyUI server: ${_nodeDot(s.comfy_server)}</span></div>`;
  el.innerHTML = `
    <div style="font-size:.75rem;color:var(--green);margin-bottom:6px">&#10003; ${esc(s.os)} &middot; ${esc(s.gpu_host)}</div>
    ${grid}
    ${servers}
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:10px">
      <button class="btn-sm primary" id="node-deploy-btn" onclick="deployNode()" title="SSH into the GPU box and install/update everything it needs — ComfyUI (image/video), TripoSR (3D), LM Studio, and autostart services. Installs only what is missing; safe to re-run. Node must be Ubuntu.">&#128640; Deploy / Update Node</button>
      <label style="font-size:.76rem;color:var(--muted);display:flex;align-items:center;gap:4px;cursor:pointer">
        <input type="checkbox" id="node-audio"> include audio/music (MusicGen, large)</label>
      <button class="btn-sm" onclick="loadNodePanel()" title="Re-run the health check — SSH into the GPU box and report which components (GPU, ComfyUI, 3D, audio, LM Studio, services) are installed and running.">&#128260; Re-check</button>
    </div>
    <div style="font-size:.72rem;color:var(--muted);margin-top:4px">Deploy is safe to re-run — it installs only what's missing and logs every step below.</div>
    <pre id="node-log" style="display:none;margin-top:10px;max-height:280px;overflow:auto;background:#0b0b0f;border:1px solid var(--border);border-radius:8px;padding:10px;font-size:.72rem;line-height:1.4;white-space:pre-wrap;color:#cbd5e1"></pre>`;
}
window.loadNodePanel = loadNodePanel;

async function deployNode() {
  const btn = document.getElementById('node-deploy-btn');
  const logEl = document.getElementById('node-log');
  const withAudio = document.getElementById('node-audio')?.checked || false;
  if (withAudio && !confirm('Audio/music (MusicGen) pulls large models and heavy dependencies. Continue?')) return;
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Deploying…'; }
  if (logEl) { logEl.style.display = 'block'; logEl.textContent = 'Starting node deploy…\n'; }
  try {
    const r = await api('/api/node/deploy', { method: 'POST', body: JSON.stringify({ with_audio: withAudio }) });
    if (r.needs_ubuntu) {
      if (logEl) logEl.textContent = '⚠️ ' + (r.note || 'Node must be Ubuntu.');
      if (btn) { btn.disabled = false; btn.innerHTML = '&#128640; Deploy / Update Node'; }
      loadNodePanel();
      return;
    }
    toast('Node deploy started — streaming log');
    _pollNodeLog();
  } catch (e) {
    if (logEl) logEl.textContent += '\n❌ ' + e.message;
    if (btn) { btn.disabled = false; btn.innerHTML = '&#128640; Deploy / Update Node'; }
  }
}
window.deployNode = deployNode;

async function _pollNodeLog() {
  const logEl = document.getElementById('node-log');
  const btn = document.getElementById('node-deploy-btn');
  try {
    const r = await api('/api/node/deploy-log');
    if (logEl && r.log) { logEl.textContent = r.log; logEl.scrollTop = logEl.scrollHeight; }
    if (r.running) { setTimeout(_pollNodeLog, 2500); return; }
    // finished
    if (btn) { btn.disabled = false; btn.innerHTML = '&#128640; Deploy / Update Node'; }
    const okDeploy = r.result?.ok;
    toast(okDeploy ? '✅ Node deploy complete' : '⚠️ Node deploy finished with issues — check the log', okDeploy ? 'success' : 'error');
    loadNodePanel();
  } catch (e) {
    if (logEl) logEl.textContent += '\n(log poll error: ' + e.message + ')';
    if (btn) { btn.disabled = false; btn.innerHTML = '&#128640; Deploy / Update Node'; }
  }
}
window.mountAdminPanel = mountAdminPanel;

async function saveServerSettings() {
  const msg = document.getElementById('sv-msg');
  const body = {
    app_name:  document.getElementById('sv-name').value.trim(),
    port:      document.getElementById('sv-port').value.trim(),
    base_path: document.getElementById('sv-base').value.trim(),
    data_dir:  document.getElementById('sv-data').value.trim(),
  };
  try {
    await api('/api/settings/server', { method: 'POST', body: JSON.stringify(body) });
    msg.style.color = 'var(--green)';
    msg.innerHTML = '&#10003; Saved to .env. Click <b>Restart Server</b> to apply.';
    toast('Server settings saved — restart to apply');
  } catch (e) {
    msg.style.color = 'var(--warn)';
    msg.textContent = 'Error: ' + e.message;
  }
}
window.saveServerSettings = saveServerSettings;

async function saveNodeSettings() {
  const msg = document.getElementById('nd-msg');
  const body = {
    llm_url:     document.getElementById('nd-llm').value.trim(),
    comfyui_url: document.getElementById('nd-comfy').value.trim(),
    gpu_host:    document.getElementById('nd-host').value.trim(),
    ssh_user:    document.getElementById('nd-user').value.trim(),
    audio_url:   document.getElementById('nd-audio').value.trim(),
  };
  try {
    await api('/api/settings/nodes', { method: 'POST', body: JSON.stringify(body) });
    msg.style.color = 'var(--green)';
    msg.innerHTML = '&#10003; Saved to .env. Click <b>Restart Server</b> to apply.';
    toast('Node settings saved — restart to apply');
  } catch (e) {
    msg.style.color = 'var(--warn)';
    msg.textContent = 'Error: ' + e.message;
  }
}
window.saveNodeSettings = saveNodeSettings;

async function saveHfToken() {
  const msg = document.getElementById('hf-msg');
  try {
    await api('/api/settings', { method: 'PATCH', body: JSON.stringify({ hf_token: document.getElementById('hf-token').value.trim() }) });
    msg.style.color = 'var(--green)'; msg.innerHTML = '&#10003; Saved — applies immediately (no restart).';
    toast('HuggingFace token saved');
  } catch (e) { msg.style.color = 'var(--warn)'; msg.textContent = 'Error: ' + e.message; }
}
window.saveHfToken = saveHfToken;

async function loadBackups() {
  const el = document.getElementById('backups-list');
  if (!el) return;
  try {
    const data = await api('/api/system/backups');
    const list = data.backups || [];
    if (!list.length) { el.innerHTML = '<div class="empty" style="padding:12px;">No backups yet.</div>'; return; }
    el.innerHTML = list.map(b => `
      <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;padding:8px 10px;border:1px solid var(--border);border-radius:8px;margin-bottom:6px;">
        <div>
          <div style="color:var(--text);font-weight:600;">${esc(b.name)}</div>
          <div style="font-size:.7rem;">${_fmtBytes(b.size)} &middot; ${_fmtTime(b.mtime)}</div>
        </div>
        <div style="display:flex;gap:6px;flex-shrink:0;">
          <a class="btn-sm" href="${API}/api/system/backups/${encodeURIComponent(b.name)}/download" title="Download">&#11015;</a>
          <button class="btn-sm" onclick="restoreBackup('${esc(b.name)}')" title="Restore">&#8635;</button>
          <button class="btn-sm" onclick="deleteBackup('${esc(b.name)}')" title="Delete" style="color:#f87171;">&#128465;</button>
        </div>
      </div>`).join('');
  } catch (e) {
    el.innerHTML = `<div style="color:var(--warn);">Error loading backups: ${esc(e.message)}</div>`;
  }
}
window.loadBackups = loadBackups;

async function createBackup() {
  const btn = document.getElementById('bk-create');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Creating…'; }
  try {
    const r = await api('/api/system/backup', { method: 'POST' });
    toast('Backup created: ' + r.name);
    await loadBackups();
  } catch (e) {
    toast('Backup failed: ' + e.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '&#10133; Create Backup'; }
  }
}
window.createBackup = createBackup;

async function deleteBackup(name) {
  if (!confirm('Delete backup ' + name + '?')) return;
  try {
    await api('/api/system/backups/' + encodeURIComponent(name), { method: 'DELETE' });
    toast('Deleted');
    await loadBackups();
  } catch (e) { toast('Error: ' + e.message, 'error'); }
}
window.deleteBackup = deleteBackup;

async function restoreBackup(name) {
  if (!confirm('Restore from ' + name + '?\n\nThis overwrites the current app and data, then restarts. A safety backup of the current state is taken first.')) return;
  try {
    await api('/api/system/restore', { method: 'POST', body: JSON.stringify({ name }) });
  } catch (e) { /* connection may drop during restart */ }
  toast('Restoring & restarting…');
  let tries = 0;
  const wait = setInterval(async () => {
    tries++;
    try { await api('/api/status'); clearInterval(wait); toast('Restored — reloading'); setTimeout(() => location.reload(), 800); }
    catch { if (tries > 40) { clearInterval(wait); toast('Server did not come back — check logs', 'error'); } }
  }, 1000);
}
window.restoreBackup = restoreBackup;

async function browserReset() {
  const msg = document.getElementById('sv-msg');
  if (msg) { msg.style.color = 'var(--muted)'; msg.textContent = 'Cleaning up the automation browser…'; }
  try {
    const r = await api('/api/system/browser-reset', { method: 'POST' });
    if (msg) { msg.style.color = 'var(--green)'; msg.textContent = `✓ Browser reset — cleared ${(r.removed_locks||[]).length} lock file(s).`; }
    toast('Browser lock cleared');
  } catch (e) { if (msg) { msg.style.color = 'var(--warn)'; msg.textContent = '❌ ' + e.message; } }
}
window.browserReset = browserReset;
