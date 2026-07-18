/* Security → 🔐 System & LLM access (moved here from Settings). */
let _secSysTimer = null;
async function secSystem() {
  const el = document.getElementById('sec-body');
  el.innerHTML = `
    <div class="stat-card" style="padding:16px;margin-bottom:14px;">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <h3 style="margin:0;">&#129504; LLM access — who's using LM Studio</h3>
        <button class="btn-sm" onclick="secLoadLlmAccess()">&#128260; Refresh</button>
      </div>
      <div style="font-size:.76rem;color:var(--muted);margin-top:4px;">The node's LM Studio (:1234). Unexpected callers here = the store, OpenClaw… or something else.</div>
      <div id="sec-llm" style="margin-top:10px;font-size:.8rem;">Checking…</div>
    </div>
    <div class="stat-card" style="padding:16px;">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px;">
        <h3 style="margin:0;">&#128220; Store logs</h3>
        <div style="display:flex;gap:6px;align-items:center;">
          <select id="sec-log-level" onchange="secLoadLogs()" style="padding:4px 6px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px;font-size:.76rem;"><option value="">All</option><option value="ERROR">Errors</option><option value="WARNING">Warn+</option></select>
          <input id="sec-log-q" placeholder="filter…" onkeydown="if(event.key==='Enter')secLoadLogs()" style="width:110px;padding:4px 6px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px;font-size:.76rem;">
          <button class="btn-sm" onclick="secLoadLogs()">&#128260;</button>
          <span id="sec-log-tally" style="font-size:.72rem;color:var(--muted);"></span>
        </div>
      </div>
      <pre id="sec-logs" style="max-height:320px;overflow:auto;background:#0b0b0f;border:1px solid var(--border);border-radius:8px;padding:10px;font-size:.7rem;line-height:1.35;white-space:pre-wrap;color:#cbd5e1;margin:10px 0 0;">Loading…</pre>
    </div>`;
  secLoadLlmAccess();
  secLoadLogs();
}

async function secLoadLlmAccess() {
  const el = document.getElementById('sec-llm');
  if (!el) return;
  el.innerHTML = 'Checking…';
  let d;
  try { d = await api('/api/security/llm-access'); }
  catch (e) { el.innerHTML = `<span style="color:var(--warn)">${esc(e.message)}</span>`; return; }
  if (d.error) { el.innerHTML = `<span style="color:var(--warn)">${esc(d.error)}</span>`; return; }
  let exposed;
  if (d.api_key_required) {
    exposed = `<div style="color:var(--green);margin-bottom:8px;">&#128273; <b>Protected by an API key</b> — LM Studio requires a key (bound to <code>${esc(d.bind)}</code>, but unauthorized callers get 401). Set the store's key in Settings → Compute Nodes.</div>`;
  } else if (d.exposed) {
    exposed = `<div style="background:#2a1005;border:1px solid #f59e0b80;border-radius:8px;padding:8px 10px;color:#fcd34d;margin-bottom:8px;">&#9888;&#65039; <b>Exposed to the LAN, no auth</b> — bound to <code>${esc(d.bind)}</code> and <b>no API key required</b>. Any device on your network can use this LLM. Fix: enable "Require API Key" in LM Studio (Developer settings), or firewall it: <code>sudo ufw allow 22 &amp;&amp; sudo ufw allow from &lt;store-host&gt; to any port 1234 &amp;&amp; sudo ufw deny 1234 &amp;&amp; sudo ufw enable</code>.</div>`;
  } else {
    exposed = `<div style="color:var(--green);margin-bottom:8px;">&#10003; Bound to <code>${esc(d.bind)}</code>.</div>`;
  }
  const unknown = (d.unknown_connections || []);
  const conns = (d.connections || []).length
    ? `Live connections: ${d.connections.map(ip => unknown.includes(ip) ? `<b style="color:#f87171">${esc(ip)} ⚠️</b>` : `<span style="color:var(--green)">${esc(ip)}</span>`).join(', ')}`
    : 'No active connections right now.';
  const warn = unknown.length ? `<div style="color:#f87171;margin-top:4px;">&#9888;&#65039; ${unknown.length} unrecognized caller(s) — investigate if that's not your store/OpenClaw.</div>` : '';
  const recent = (d.recent || []).length
    ? `<details style="margin-top:8px;"><summary style="cursor:pointer;color:var(--muted);font-size:.75rem;">Recent LM Studio requests (${d.recent.length})</summary><pre style="max-height:180px;overflow:auto;background:#0b0b0f;border:1px solid var(--border);border-radius:6px;padding:8px;font-size:.68rem;white-space:pre-wrap;color:#cbd5e1;margin-top:6px;">${d.recent.map(esc).join('\n')}</pre></details>`
    : '';
  el.innerHTML = exposed + `<div>${conns}</div>` + warn + recent;
}
window.secLoadLlmAccess = secLoadLlmAccess;

async function secLoadLogs() {
  const pre = document.getElementById('sec-logs'); if (!pre) return;
  const level = document.getElementById('sec-log-level')?.value || '';
  const q = document.getElementById('sec-log-q')?.value.trim() || '';
  try {
    const r = await api(`/api/system/logs?lines=300&level=${encodeURIComponent(level)}&q=${encodeURIComponent(q)}`);
    if (r.note) { pre.textContent = r.note; return; }
    const lines = r.lines || [];
    pre.innerHTML = lines.length ? lines.map(l => {
      const c = / ERROR | CRITICAL /.test(l) ? '#f87171' : / WARNING /.test(l) ? '#fbbf24' : '';
      const d = document.createElement('div'); d.textContent = l; if (c) d.style.color = c; return d.outerHTML;
    }).join('') : '<span style="color:var(--muted)">(no matching lines)</span>';
    pre.scrollTop = pre.scrollHeight;
    const t = document.getElementById('sec-log-tally');
    if (t) t.innerHTML = `<span style="color:#f87171">${r.errors||0} err</span> · <span style="color:#fbbf24">${r.warnings||0} warn</span>`;
  } catch (e) { pre.textContent = 'Error: ' + e.message; }
}
window.secLoadLogs = secLoadLogs;
