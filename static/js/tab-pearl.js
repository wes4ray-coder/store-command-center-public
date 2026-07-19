/* ══ CRYPTO → 🦪 PEARL (PRL) PANE ══
   The user asked about "Purl" — research identified it as Pearl (PRL), the
   proof-of-useful-work L1 by Pearl Research Labs. This pane follows the same
   flow as the other coins: status/balance/address + config, a HARD-GATED miner
   start/stop (toggle, never auto-starts), and the honest research card with
   the red flags. Backend: app/routers/pearl.py + app/pearl.py. */

async function cryptoLoadPearl() {
  const pane = document.getElementById('pane-crypto-pearl');
  let st = {}, cfg = { settings: {} }, research = null;
  try { st = await api('/api/crypto/pearl/status'); }
  catch (e) { pane.innerHTML = `<div class="empty"><div class="empty-icon">&#10060;</div>${esc(e.message)}</div>`; return; }
  try { cfg = await api('/api/crypto/pearl/settings'); } catch {}
  try { research = await api('/api/crypto/pearl/research'); } catch {}
  const s = cfg.settings || {};
  const node = st.node || {}, wal = st.wallet || {}, mn = st.miner || {};
  const enabled = !!st.mining_enabled;
  const agentAccess = !!st.agent_access;
  const minerActive = mn.state === 'active' || mn.state === 'activating';

  // ── verdict banner ──
  const banner = `
    <div class="settings-group" style="max-width:820px;margin-bottom:16px;border-color:var(--warn);">
      <div class="settings-group-title" style="color:var(--warn);">&#129714; "Purl" = Pearl (PRL) — real, but young &amp; thin</div>
      <div style="font-size:.78rem;color:var(--muted);line-height:1.7;">
        ${esc((research && research.verdict) || 'Real project by Pearl Research Labs; verify everything against the official repo only.')}
        <br>Not related to our JellyCoin — Pearl is a public NVIDIA-mined (CUDA, not OpenCL) proof-of-useful-work chain.
        Nothing here spends money or starts mining by itself; the miner is behind the toggle below.
      </div>
    </div>`;

  // ── research / red-flags card ──
  const li = (arr) => (arr || []).map(x => `<li>${esc(x)}</li>`).join('');
  const researchCard = research ? `
    <details class="settings-group" style="max-width:820px;margin-bottom:16px;">
      <summary style="cursor:pointer;font-weight:700;font-size:.85rem;">&#128270; What Pearl actually is (verified 2026-07-18) + red flags</summary>
      <div style="font-size:.76rem;color:var(--muted);line-height:1.7;margin-top:10px;">
        <b style="color:var(--text);">The project:</b><ul style="margin:4px 0 10px 18px;">${li(research.what_it_is)}</ul>
        <b style="color:var(--text);">Mining:</b><ul style="margin:4px 0 10px 18px;">${li(research.mining)}</ul>
        <b style="color:var(--red);">&#9888;&#65039; Red flags:</b><ul style="margin:4px 0 10px 18px;">${li(research.red_flags)}</ul>
        <b style="color:var(--text);">Sources:</b>
        <div style="margin:4px 0 0;">${(research.sources || []).map(u =>
          `<a href="${esc(u)}" target="_blank" rel="noopener" style="color:var(--accent);display:block;word-break:break-all;margin-bottom:2px;">${esc(u)}</a>`).join('')}</div>
      </div>
    </details>` : '';

  // ── node + wallet card ──
  const dot = (ok) => `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${ok ? 'var(--green)' : 'var(--red)'};box-shadow:0 0 6px ${ok ? 'var(--green)' : 'var(--red)'};margin-right:7px;"></span>`;
  const nodeLine = !node.configured
    ? '<span style="color:var(--muted);">pearld not configured — set the RPC URL below once installed.</span>'
    : node.reachable
      ? `${dot(true)}pearld reachable · height <b>${node.height ?? '—'}</b>${node.chain ? ` · chain <code>${esc(node.chain)}</code>` : ''}`
      : `${dot(false)}pearld unreachable — <span style="color:var(--warn);">${esc(node.error || 'check the URL/credentials')}</span>`;
  const walLine = !wal.configured
    ? '<span style="color:var(--muted);">oyster wallet not configured.</span>'
    : wal.reachable
      ? `${dot(true)}oyster wallet · balance <b style="color:var(--green);">${wal.balance ?? '—'} PRL</b>
         ${(wal.addresses || []).length ? `<br>Receive: <code style="word-break:break-all;">${esc(wal.addresses[0])}</code>` : ''}`
      : `${dot(false)}oyster wallet unreachable — <span style="color:var(--warn);">${esc(wal.error || 'check the URL/credentials')}</span>`;
  const nodeCard = `
    <div class="settings-group" style="max-width:820px;margin-bottom:16px;">
      <div class="settings-group-title">&#9939;&#65039; Your Pearl node &amp; wallet (self-hosted)</div>
      <div style="font-size:.78rem;line-height:1.9;margin-bottom:12px;">${nodeLine}<br>${walLine}</div>
      <div class="settings-grid" style="max-width:760px;">
        <div class="field"><label>pearld RPC URL ${hlp('JSON-RPC of YOUR pearld node (btcd fork), e.g. http://127.0.0.1:8334 — or http://127.0.0.1:PORT if it runs on the GPU node. You install pearld yourself from the official repo.')}</label>
          <input id="prl-node-url" value="${esc(s.pearl_node_url || '')}" placeholder="http://127.0.0.1:8334"></div>
        <div class="field"><label>oyster wallet RPC URL ${hlp('JSON-RPC of the oyster HD-wallet daemon that ships with the official release. Balance/addresses come from here.')}</label>
          <input id="prl-wallet-url" value="${esc(s.pearl_wallet_url || '')}" placeholder="http://127.0.0.1:8332"></div>
        <div class="field"><label>RPC user ${hlp('The rpcuser you configured for pearld/oyster.')}</label>
          <input id="prl-rpc-user" value="${esc(s.pearl_rpc_user || '')}"></div>
        <div class="field"><label>RPC password ${hlp('Stored Fernet-encrypted at rest, and included in the gated crypto key-backup zip. Leave blank to keep the saved one.')}</label>
          <input type="password" id="prl-rpc-pass" value="" placeholder="${s.pearl_rpc_pass ? 'saved — leave blank to keep' : 'rpc password'}"></div>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;">
        <button class="btn-sm primary" onclick="pearlSaveSettings()">&#128190; Save</button>
        <button class="btn-sm" onclick="pearlNewAddress()" ${wal.reachable ? '' : 'disabled'}>&#127381; New receive address</button>
        <button class="btn-sm" onclick="_cryptoLoaded.pearl=false;cryptoSub('pearl')">&#8635; Refresh</button>
      </div>
      <div style="font-size:.72rem;color:var(--muted);margin-top:10px;line-height:1.6;">
        &#128273; The oyster wallet's SEED PHRASE is created on the node and never touches this app —
        write it down offline when oystercli shows it. The pearl_* settings here (incl. the RPC password)
        ride the existing gated key-backup zip in &#128273; Backups.
      </div>
    </div>`;

  // ── mining card (toggle-gated) ──
  const stateBadge = `<span style="font-size:.62rem;font-weight:700;background:${minerActive ? 'rgba(34,197,94,.16)' : 'rgba(148,163,184,.16)'};color:${minerActive ? 'var(--green)' : 'var(--muted)'};border-radius:10px;padding:2px 8px;margin-left:8px;text-transform:uppercase;">${esc(mn.state || 'unknown')}</span>`;
  const miningCard = `
    <div class="settings-group" style="max-width:820px;margin-bottom:16px;">
      <div class="settings-group-title">${dot(minerActive)}GPU mining — NVIDIA vLLM miner ${stateBadge}</div>
      <div style="font-size:.76rem;color:var(--muted);line-height:1.7;margin-bottom:12px;">
        Pearl mines with its own <b>CUDA/vLLM</b> miner (pearl-gateway + vllm-miner) — NVIDIA RTX 30-series+.
        The GPU node's <b>RTX 3060 12GB</b> qualifies (low-end; expect small returns, and it will compete with
        LM Studio/ComfyUI for the GPU). This app only starts/stops a systemd unit <b>you</b> install — it never
        downloads miner binaries, and never starts anything while the toggle is off.
        ${mn.installed_hint ? `<br><span style="color:var(--warn);">${esc(mn.installed_hint)}</span>` : ''}
        ${mn.error ? `<br><span style="color:var(--red);">${esc(mn.error)}</span>` : ''}
      </div>
      <label style="display:flex;align-items:center;gap:10px;font-size:.82rem;font-weight:600;margin-bottom:8px;cursor:pointer;">
        <input type="checkbox" id="prl-mining-enabled" ${enabled ? 'checked' : ''} onchange="pearlToggleMining(this.checked)">
        Allow Pearl mining ${hlp('Master gate. While OFF, the Start button is refused by the server (403) and the miner state isn’t even probed. Turning it ON does not start anything — it only unlocks the Start button.')}
      </label>
      <label style="display:flex;align-items:center;gap:10px;font-size:.82rem;font-weight:600;margin-bottom:12px;cursor:pointer;">
        <input type="checkbox" id="prl-agent-access" ${agentAccess ? 'checked' : ''} onchange="pearlToggleAgent(this.checked)">
        Allow agents to control mining ${hlp('Agent-access gate (default OFF). While OFF, only YOU (an authenticated browser session) can start/stop — the MCP tool / OpenClaw / any automation is refused with 403. Turn ON to let agents drive the miner (they still need the master toggle above too). Nothing auto-starts either way.')}
        <span style="font-size:.62rem;font-weight:700;background:${agentAccess ? 'rgba(245,158,11,.16)' : 'rgba(148,163,184,.16)'};color:${agentAccess ? 'var(--warn)' : 'var(--muted)'};border-radius:10px;padding:2px 8px;text-transform:uppercase;">${agentAccess ? 'agents allowed' : 'human-only'}</span>
      </label>
      <div class="settings-grid" style="max-width:760px;">
        <div class="field"><label>Miner host ${hlp('The box running the miner unit over SSH. Default: the GPU node (127.0.0.1).')}</label>
          <input id="prl-miner-host" value="${esc(s.pearl_miner_host || '')}" placeholder="127.0.0.1 (default)"></div>
        <div class="field"><label>systemd --user unit ${hlp('Name of the systemd user unit YOU created wrapping the official miner (like jellyminer.service). Start/Stop drive this unit.')}</label>
          <input id="prl-miner-unit" value="${esc(s.pearl_miner_unit || '')}" placeholder="pearl-miner (default)"></div>
        <div class="field"><label>Pool ${hlp('Community pools that support consumer GPUs: pool.kryptex.com/prl or pearl.luckypool.io. The official pool is H100/H200-only and takes 20%. Configured inside your miner unit; recorded here for reference.')}</label>
          <input id="prl-pool" value="${esc(s.pearl_pool_url || '')}" placeholder="pearl.luckypool.io"></div>
        <div class="field"><label>Payout PRL address ${hlp('Your own oyster wallet receive address — pool payouts and solo rewards land here. Use New receive address above.')}</label>
          <input id="prl-payout" value="${esc(s.pearl_payout_address || '')}" placeholder="prl1..."></div>
      </div>
      <div style="display:flex;gap:8px;">
        <button class="btn-sm success" onclick="pearlMiner('start')" ${(!enabled || minerActive) ? 'disabled' : ''} title="${enabled ? 'systemctl --user start on the miner host' : 'Enable the toggle first'}">&#9654; Start mining</button>
        <button class="btn-sm danger" onclick="pearlMiner('stop')" ${minerActive ? '' : 'disabled'}>&#9209; Stop</button>
      </div>
    </div>`;

  // ── setup steps ──
  const setupCard = research && (research.setup || []).length ? `
    <div class="settings-group" style="max-width:820px;border-color:var(--accent);">
      <div class="settings-group-title">&#128736;&#65039; What you'd install to hold / mine PRL for real</div>
      <ol style="font-size:.76rem;color:var(--muted);line-height:1.8;margin:6px 0 0 18px;">
        ${(research.setup || []).map(x => `<li style="margin-bottom:6px;">${esc(x.replace(/^\d+\.\s*/, ''))}</li>`).join('')}
      </ol>
    </div>` : '';

  pane.innerHTML = `
    <div class="section-header">
      <div><div class="section-title">&#129714; Pearl (PRL)</div>
        <div class="section-sub">Proof-of-useful-work L1 — GPU mining that does AI math. Self-hosted node/wallet; miner behind a toggle; nothing auto-starts.</div></div>
      <button class="btn-sm" onclick="_cryptoLoaded.pearl=false;cryptoSub('pearl')">&#8635; Refresh</button>
    </div>
    ${banner}${researchCard}${nodeCard}${miningCard}${setupCard}`;
}
window.cryptoLoadPearl = cryptoLoadPearl;

async function pearlSaveSettings() {
  const val = (id) => { const el = document.getElementById(id); return el ? el.value.trim() : null; };
  const body = {
    pearl_node_url: val('prl-node-url'), pearl_wallet_url: val('prl-wallet-url'),
    pearl_rpc_user: val('prl-rpc-user'),
    pearl_miner_host: val('prl-miner-host'), pearl_miner_unit: val('prl-miner-unit'),
    pearl_pool_url: val('prl-pool'), pearl_payout_address: val('prl-payout'),
  };
  const pass = val('prl-rpc-pass');
  if (pass) body.pearl_rpc_pass = pass;      // blank = keep the saved secret
  try {
    await api('/api/crypto/pearl/settings', { method: 'POST', body: JSON.stringify(body) });
    toast('Pearl settings saved');
  } catch (e) { toast('Save failed: ' + e.message, 'error'); return; }
  _cryptoLoaded.pearl = false; cryptoSub('pearl');
}
window.pearlSaveSettings = pearlSaveSettings;

async function pearlToggleMining(on) {
  try {
    await api('/api/crypto/pearl/settings', { method: 'POST',
      body: JSON.stringify({ pearl_mining_enabled: on ? '1' : '0' }) });
    toast(on ? 'Pearl mining UNLOCKED — nothing started; use the Start button.'
             : 'Pearl mining locked off.');
  } catch (e) { toast('Error: ' + e.message, 'error'); }
  _cryptoLoaded.pearl = false; cryptoSub('pearl');
}
window.pearlToggleMining = pearlToggleMining;

async function pearlToggleAgent(on) {
  try {
    await api('/api/crypto/pearl/settings', { method: 'POST',
      body: JSON.stringify({ pearl_agent_access: on ? '1' : '0' }) });
    toast(on ? 'Agents may now start/stop Pearl mining (master toggle still required).'
             : 'Agent access locked off — only you can control Pearl mining.');
  } catch (e) { toast('Error: ' + e.message, 'error'); }
  _cryptoLoaded.pearl = false; cryptoSub('pearl');
}
window.pearlToggleAgent = pearlToggleAgent;

async function pearlMiner(action) {
  if (action === 'start' &&
      !confirm('Start the Pearl miner unit on the GPU node?\n\nThe RTX 3060 will run CUDA mining and compete with LM Studio / ComfyUI until you stop it. Returns on a 3060 are small.')) return;
  try {
    const r = await api(`/api/crypto/pearl/miner/${action}`, { method: 'POST' });
    toast(`Miner ${action}: ${r.state || 'ok'}`);
  } catch (e) { toast('Error: ' + e.message, 'error'); }
  _cryptoLoaded.pearl = false; cryptoSub('pearl');
}
window.pearlMiner = pearlMiner;

async function pearlNewAddress() {
  try {
    const r = await api('/api/crypto/pearl/address/new', { method: 'POST' });
    const payout = document.getElementById('prl-payout');
    if (payout && !payout.value) payout.value = r.address;
    prompt('New PRL receive address (copy it):', r.address);
  } catch (e) { toast('Error: ' + e.message, 'error'); }
}
window.pearlNewAddress = pearlNewAddress;
