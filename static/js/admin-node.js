/* ══ ADMIN — GPU node deploy / health panel (split from admin.js; runs on the Settings panel) ══ */

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
