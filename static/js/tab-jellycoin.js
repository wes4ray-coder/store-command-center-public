/* ══ JELLYCOIN (JLY) — Crypto sub-tab ══
   The store's OWN GPU-mined token: chain stats, GPU rigs (old cards welcome, no
   CPU mining ever), Company skilling boosts (god-toggled), wallets & transfers,
   art NFTs, and agent push/sell missions (always behind god approval).
   Loaded by tab-crypto.js as pane 'jelly' → cryptoLoadJelly(). */

const _JLY = { st: null, tokenInfo: null };

function _jlyFmt(u) { return (u / 1e6).toLocaleString(undefined, { maximumFractionDigits: 2 }); }
function _jlyStat(label, val, hint) {
  return `<div style="flex:1;min-width:110px;background:var(--panel2,#0b1120);border:1px solid var(--border,#243049);border-radius:10px;padding:10px 12px;">
    <div style="font-size:.66rem;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;">${label}${hint ? ' ' + hlp(hint) : ''}</div>
    <div style="font-size:1.05rem;font-weight:700;margin-top:2px;">${val}</div></div>`;
}

async function cryptoLoadJelly() {
  const pane = document.getElementById('pane-crypto-jelly');
  let st, wal, tok, nfts, missions, blocks, ws;
  try {
    [st, wal, tok, nfts, missions, blocks, ws] = await Promise.all([
      api('/api/jelly/status'), api('/api/jelly/wallets'), api('/api/jelly/miner-token'),
      api('/api/jelly/nft/list'), api('/api/jelly/missions'), api('/api/jelly/blocks?limit=8'),
      api('/api/world/settings').catch(() => ({ settings: {} })),
    ]);
  } catch (e) {
    pane.innerHTML = `<div class="empty"><div class="empty-icon">&#10060;</div>${esc(e.message)}</div>`;
    return;
  }
  _JLY.st = st;
  const companyOn = String((ws.settings || {}).world_crypto_mining_enabled) === '1';
  const rigs = st.miners || [];

  pane.innerHTML = `
    <div class="section-header"><div><div class="section-title">🪼 JellyCoin (${esc(st.symbol)})</div>
      <div class="section-sub">Acme's own token. New JLY exists <b>only</b> when a real GPU solves a proof-of-work
      block — old cards get a second life, and there is deliberately no CPU mining. Community token, not an investment.</div></div>
      <button class="btn-sm" onclick="_cryptoLoaded.jelly=false;cryptoSub('jelly')">&#8635; Refresh</button>
    </div>

    <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px;">
      ${_jlyStat('Height', st.height)}
      ${_jlyStat('Supply', _jlyFmt(st.supply * 1e6) + ' JLY')}
      ${_jlyStat('Difficulty', st.difficulty, 'Relative to genesis (1.0). Auto-retargets toward one block per minute.')}
      ${_jlyStat('Block reward', st.block_reward + ' JLY')}
      ${_jlyStat('GPU rigs online', st.miners_online)}
      ${_jlyStat('Boosts pending', st.boosts_pending, 'Skilling tickets waiting to pay out inside the next mined blocks.')}
      ${_jlyStat('NFTs', st.nft_count)}
    </div>

    <div class="settings-group" style="margin-bottom:16px;">
      <div class="settings-group-title">⛏️ GPU rigs ${hlp('Any LAN box with an OpenCL GPU can mine — even cards far too old for AI. The miner refuses to run on CPU by design.')}</div>
      ${rigs.length ? `<table class="mini-table" style="width:100%;font-size:.78rem;">
        <tr><th style="text-align:left;">Rig</th><th style="text-align:left;">GPU</th><th>MH/s</th><th>Blocks</th><th></th></tr>
        ${rigs.map(m => `<tr><td>${esc(m.name)}</td><td style="color:var(--muted);">${esc(m.gpu || '?')}</td>
          <td style="text-align:center;">${(m.hashrate / 1e6).toFixed(1)}</td><td style="text-align:center;">${m.blocks}</td>
          <td style="text-align:center;color:${m.online ? 'var(--green)' : 'var(--muted)'};">${m.online ? '● online' : '○ offline'}</td></tr>`).join('')}
      </table>` : `<div style="font-size:.78rem;color:var(--muted);">No rigs yet. Dust off an old graphics card:</div>`}
      <div style="font-size:.76rem;color:var(--muted);line-height:1.8;margin-top:10px;">
        1&#41; On the GPU box: <code>pip install pyopencl numpy requests</code><br>
        2&#41; Download <a href="/api/jelly/mining/miner.py" style="color:var(--accent,#7aa2ff);">jellyminer.py</a> &nbsp;
        3&#41; Run: <code style="word-break:break-all;">${esc(tok.run)}</code>
        <button class="btn-sm" style="margin-left:6px;" onclick="navigator.clipboard.writeText(${JSON.stringify(tok.run)});toast?.('Copied ✓')">📋 Copy</button>
      </div>
    </div>

    <div class="settings-group" style="margin-bottom:16px;">
      <div class="settings-group-title">🏢 Company boosts
        <span style="font-size:.62rem;font-weight:700;background:${companyOn ? 'rgba(34,197,94,.16)' : 'rgba(148,163,184,.16)'};color:${companyOn ? 'var(--green)' : 'var(--muted)'};border-radius:10px;padding:2px 8px;margin-left:8px;text-transform:uppercase;">${companyOn ? 'on' : 'off'}</span>
      </div>
      <div style="font-size:.78rem;color:var(--muted);line-height:1.7;">
        When on, agents' woodcutting / mining / fishing queues boost tickets (${st.boosts_pending} pending,
        ${_jlyFmt(st.boosts_paid_jly * 1e6)} JLY paid so far). Tickets cash out <b>only inside a real GPU-mined
        block</b> — bonus JLY split between the agent and the company wallet. No rig online → nothing mines.
      </div>
      <button class="btn-sm" style="margin-top:8px;" onclick="jellyToggleCompany(${companyOn ? 0 : 1})">
        ${companyOn ? '⏸ Turn off' : '▶ Turn on'} skilling boosts</button>
      <span style="font-size:.7rem;color:var(--muted);margin-left:8px;">(same toggle lives in God Console → Company Settings)</span>
    </div>

    <div class="settings-group" style="margin-bottom:16px;">
      <div class="settings-group-title">👛 Wallets</div>
      <table class="mini-table" style="width:100%;font-size:.78rem;">
        <tr><th style="text-align:left;">Wallet</th><th style="text-align:left;">Kind</th><th style="text-align:right;">Balance</th></tr>
        ${(wal.wallets || []).slice(0, 14).map(w => `<tr><td>${esc(w.name)} ${w.name === 'assistant' ? '🤖' : ''}</td>
          <td style="color:var(--muted);">${esc(w.kind)}</td>
          <td style="text-align:right;font-weight:600;">${_jlyFmt(w.balance)} JLY</td></tr>`).join('')}
      </table>
      <div style="display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap;margin-top:12px;">
        <div class="field" style="margin:0;"><label>From</label><input id="jly-tx-from" placeholder="treasury" style="width:130px;"></div>
        <div class="field" style="margin:0;"><label>To</label><input id="jly-tx-to" placeholder="miner:rig1" style="width:130px;"></div>
        <div class="field" style="margin:0;"><label>JLY</label><input id="jly-tx-amt" type="number" step="0.01" style="width:80px;"></div>
        <div class="field" style="margin:0;flex:1;min-width:120px;"><label>Memo</label><input id="jly-tx-memo"></div>
        <button class="btn-sm" onclick="jellyTransfer()">💸 Send</button>
        <button class="btn-sm" onclick="jellyTip()" title="Send from the AI friend's 'assistant' wallet">🤖 Tip from AI friend</button>
      </div>
    </div>

    <div class="settings-group" style="margin-bottom:16px;">
      <div class="settings-group-title">🖼️ Art NFTs ${hlp('Mints a real art file: its sha256 becomes the on-chain content hash. Fee: 5 JLY to the treasury (treasury mints free).')}</div>
      <div style="display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap;margin-bottom:12px;">
        <div class="field" style="margin:0;flex:2;min-width:220px;"><label>Art file path</label>
          <input id="jly-nft-path" placeholder="designs/…png (from Studio / Library)"></div>
        <div class="field" style="margin:0;flex:1;"><label>Title</label><input id="jly-nft-title"></div>
        <div class="field" style="margin:0;"><label>Owner</label><input id="jly-nft-owner" placeholder="treasury" style="width:110px;"></div>
        <button class="btn-sm" onclick="jellyMintNft()">🪙 Mint</button>
      </div>
      ${(nfts.nfts || []).length ? `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;">
        ${(nfts.nfts || []).slice(0, 12).map(n => `<div style="background:var(--panel2,#0b1120);border:1px solid var(--border,#243049);border-radius:10px;padding:8px;">
          <img src="${thumbUrl(n.file_path)}" onerror="this.style.display='none'" style="width:100%;border-radius:6px;aspect-ratio:1;object-fit:cover;">
          <div style="font-size:.74rem;font-weight:600;margin-top:6px;">${esc(n.title)}</div>
          <div style="font-size:.66rem;color:var(--muted);">owner: ${esc(n.owner)} · #${n.minted_height}</div>
          <div style="font-size:.6rem;color:var(--muted);word-break:break-all;" title="content sha256: ${esc(n.sha256)}">${esc(n.token_id)}</div>
        </div>`).join('')}</div>` : `<div style="font-size:.76rem;color:var(--muted);">Nothing minted yet — pick a Studio artwork you love.</div>`}
    </div>

    <div class="settings-group" style="margin-bottom:16px;">
      <div class="settings-group-title">📣 Push &amp; sell missions ${hlp('The Company drafts JLY promo/perk/sell pitches with the LLM. Every draft waits for YOUR approval — agents never post or sell anything on their own. Approved pitches hit the town feed for agents to talk up.')}</div>
      <div style="display:flex;gap:8px;margin-bottom:10px;">
        <button class="btn-sm" onclick="jellyDraft('promo')">✍️ Draft promo</button>
        <button class="btn-sm" onclick="jellyDraft('perk')">🎁 Draft store perk</button>
        <button class="btn-sm" onclick="jellyDraft('sell')">🤝 Draft sell offer</button>
      </div>
      ${(missions.missions || []).slice(0, 8).map(m => `
        <div style="border:1px solid var(--border,#243049);border-radius:10px;padding:10px 12px;margin-bottom:8px;background:var(--panel2,#0b1120);">
          <div style="display:flex;justify-content:space-between;gap:8px;align-items:center;">
            <div style="font-weight:600;font-size:.82rem;">${esc(m.title)} <span style="color:var(--muted);font-weight:400;">· ${esc(m.kind)} · ${esc(m.agent)}</span></div>
            <div>${m.status === 'proposed'
              ? `<button class="btn-sm" onclick="jellyDecide(${m.id},1)">✅ Approve</button>
                 <button class="btn-sm" onclick="jellyDecide(${m.id},0)">🚫 Reject</button>`
              : `<span style="font-size:.66rem;font-weight:700;text-transform:uppercase;color:${m.status === 'approved' ? 'var(--green)' : 'var(--red)'};">${esc(m.status)}</span>`}</div>
          </div>
          <div style="font-size:.76rem;color:var(--muted);white-space:pre-wrap;margin-top:6px;">${esc(m.pitch)}</div>
        </div>`).join('') || `<div style="font-size:.76rem;color:var(--muted);">No missions yet.</div>`}
    </div>

    <div class="settings-group">
      <div class="settings-group-title">⛓️ Recent blocks</div>
      <table class="mini-table" style="width:100%;font-size:.74rem;">
        <tr><th>#</th><th style="text-align:left;">Hash</th><th style="text-align:left;">Miner</th><th>Reward</th><th>Boost</th></tr>
        ${(blocks.blocks || []).map(b => `<tr><td style="text-align:center;">${b.height}</td>
          <td style="font-family:monospace;color:var(--muted);">${esc(b.hash.slice(0, 20))}…</td>
          <td>${esc(b.miner)}</td><td style="text-align:center;">${_jlyFmt(b.reward)}</td>
          <td style="text-align:center;">${b.boost ? _jlyFmt(b.boost) : '—'}</td></tr>`).join('')}
      </table>
    </div>`;
}
window.cryptoLoadJelly = cryptoLoadJelly;

function _jlyReload() { _cryptoLoaded.jelly = false; cryptoSub('jelly'); }

async function jellyToggleCompany(on) {
  try {
    await api('/api/world/settings', { method: 'POST', body: JSON.stringify({ settings: { world_crypto_mining_enabled: String(on) } }) });
    toast?.(on ? 'Company skilling now boosts GPU mining ⛏️' : 'Skilling boosts off');
    _jlyReload();
  } catch (e) { toast?.(e.message); }
}
window.jellyToggleCompany = jellyToggleCompany;

async function jellyTransfer(fromOverride) {
  const from = fromOverride || document.getElementById('jly-tx-from').value.trim();
  const body = { from, to: document.getElementById('jly-tx-to').value.trim(),
    amount_jly: parseFloat(document.getElementById('jly-tx-amt').value || '0'),
    memo: document.getElementById('jly-tx-memo').value.trim() };
  try {
    await api('/api/jelly/transfer', { method: 'POST', body: JSON.stringify(body) });
    toast?.('Sent ✓'); _jlyReload();
  } catch (e) { toast?.(e.message); }
}
window.jellyTransfer = jellyTransfer;

async function jellyTip() {
  const body = { to: document.getElementById('jly-tx-to').value.trim(),
    amount_jly: parseFloat(document.getElementById('jly-tx-amt').value || '0'),
    memo: document.getElementById('jly-tx-memo').value.trim() || 'tip from your AI friend' };
  try {
    await api('/api/jelly/tip', { method: 'POST', body: JSON.stringify(body) });
    toast?.('AI friend tipped ✓ 🤖'); _jlyReload();
  } catch (e) { toast?.(e.message); }
}
window.jellyTip = jellyTip;

async function jellyMintNft() {
  const body = { file_path: document.getElementById('jly-nft-path').value.trim(),
    title: document.getElementById('jly-nft-title').value.trim(),
    owner: document.getElementById('jly-nft-owner').value.trim() || 'treasury' };
  if (!body.file_path) { toast?.('Give it an art file path'); return; }
  try {
    const r = await api('/api/jelly/nft/mint', { method: 'POST', body: JSON.stringify(body) });
    toast?.(`Minted ${r.token_id} ✓`); _jlyReload();
  } catch (e) { toast?.(e.message); }
}
window.jellyMintNft = jellyMintNft;

async function jellyDraft(kind) {
  try {
    toast?.('Drafting with the LLM…');
    await api('/api/jelly/missions/draft', { method: 'POST', body: JSON.stringify({ kind }) });
    _jlyReload();
  } catch (e) { toast?.(e.message); }
}
window.jellyDraft = jellyDraft;

async function jellyDecide(id, approve) {
  try {
    await api(`/api/jelly/missions/${id}/decide`, { method: 'POST', body: JSON.stringify({ approve: !!approve }) });
    toast?.(approve ? 'Mission approved — the town hears about it 📣' : 'Mission rejected');
    _jlyReload();
  } catch (e) { toast?.(e.message); }
}
window.jellyDecide = jellyDecide;
