/* ══ WALLETS TAB ══
   REAL mainnet light-wallets: one BIP39 seed → deterministic receive addresses for
   BTC / LTC / DOGE / ETH / KAS (+ a Monero primary address), live balances via
   public explorers. No node, no blockchain download. SENDING IS REVIEW-GATED —
   /api/wallets/send only queues a proposal; nothing is signed or broadcast yet. */

let _waData = null;   // last /api/wallets payload

function _waBal(c) {
  if (c.balance == null) {
    return c.error
      ? `<span style="color:var(--warn);font-size:.72rem;" title="${esc(c.error)}">${esc(c.error.length > 46 ? c.error.slice(0, 46) + '…' : c.error)}</span>`
      : '<span style="color:var(--muted);">—</span>';
  }
  const dec = Math.min(c.decimals != null ? c.decimals : 8, 8);
  return `<b style="color:${c.balance > 0 ? 'var(--green)' : 'var(--text)'};">${Number(c.balance).toLocaleString(undefined, { maximumFractionDigits: dec })}</b> <span style="color:var(--muted);">${esc(c.sym)}</span>`;
}

async function renderWallets() {
  document.getElementById('main-content').innerHTML = `
    <div class="view-header">
      <div class="view-title">&#128092; Wallets
        <span id="wa-xmr-status" title="Monero wallet daemon status" style="font-size:.6rem;font-weight:700;vertical-align:middle;margin-left:10px;padding:3px 9px;border-radius:10px;background:var(--surface2);color:var(--muted);text-transform:uppercase;letter-spacing:.04em;">&#9679; Monero daemon &hellip;</span></div>
      <div class="view-sub">Real mainnet light-wallets &mdash; receive &amp; monitor real crypto.
        No node, no blockchain download. Backed by public explorers.</div>
    </div>
    <div id="wa-seed-banner"></div>
    <div id="wa-coins"><div class="empty"><div class="empty-icon">&#9203;</div>Loading wallets&#8230;</div></div>
    <div id="wa-advanced" style="margin-top:18px;"></div>`;
  await waLoad();
}
window.renderWallets = renderWallets;

async function waLoad() {
  const el = document.getElementById('wa-coins');
  let d;
  try { d = await api('/api/wallets'); }
  catch (e) { el.innerHTML = `<div class="empty"><div class="empty-icon">&#10060;</div>${esc(e.message)}</div>`; return; }
  _waData = d;
  waRenderBanner();
  waRenderCoins();
  waRenderAdvanced();
  await waLoadSends();
  waLoadXmr();   // upgrades the XMR card if the daemon is up (no await — cosmetic)
}

/* ── seed backup banner ───────────────────────────────────────────────────── */
function waRenderBanner() {
  const el = document.getElementById('wa-seed-banner');
  if (!el) return;
  if (_waData && _waData.seed_backed_up) { el.innerHTML = ''; return; }
  el.innerHTML = `
    <div class="settings-group" style="border-color:var(--red);background:rgba(239,68,68,.06);margin-bottom:18px;">
      <div class="settings-group-title" style="color:var(--red);">&#9888;&#65039; Back up your recovery phrase</div>
      <div style="font-size:.8rem;color:var(--muted);line-height:1.7;margin-bottom:12px;">
        These wallets hold <b style="color:var(--text);">real money</b>. The 24-word recovery phrase is the
        <b style="color:var(--text);">only</b> way to restore them &mdash; if this machine dies and you never
        wrote it down, every coin sent here is gone forever. Reveal it once, write it on paper, store it offline.
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;">
        <button class="btn-sm danger" onclick="waRevealSeed()">&#128273; Reveal seed phrase (once)</button>
      </div>
      <div id="wa-seed-reveal" style="margin-top:12px;"></div>
    </div>`;
}

async function waRevealSeed() {
  const out = document.getElementById('wa-seed-reveal');
  let d;
  try { d = await api('/api/wallets/seed'); }
  catch (e) { toast('Error: ' + e.message, 'error'); return; }
  const addrs = d.addresses || {};
  out.innerHTML = `
    <div style="background:var(--surface);border:1px solid var(--red);border-radius:8px;padding:14px 16px;">
      <div style="font-size:.72rem;color:var(--red);font-weight:700;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px;">
        &#128683; Never screenshot, photograph or paste this anywhere</div>
      <div style="font-family:monospace;font-size:.92rem;line-height:2;letter-spacing:.02em;word-spacing:.5em;
        background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:12px 14px;margin-bottom:12px;user-select:all;">
        ${esc(d.mnemonic || '')}</div>
      <div style="font-size:.74rem;color:var(--muted);line-height:1.7;margin-bottom:10px;">${esc(d.warning || '')}</div>
      <div style="font-size:.72rem;color:var(--muted);margin-bottom:4px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;">Addresses this phrase controls</div>
      ${Object.keys(addrs).map(sym => `
        <div style="font-size:.72rem;margin-bottom:3px;"><b style="width:44px;display:inline-block;">${esc(sym)}</b>
          <span style="font-family:monospace;color:var(--muted);word-break:break-all;">${esc(addrs[sym] || '—')}</span></div>`).join('')}
      <button class="btn-sm success" style="margin-top:12px;" onclick="waAckSeed()">&#10003; I've saved it safely</button>
    </div>`;
}
window.waRevealSeed = waRevealSeed;

async function waAckSeed() {
  try {
    await api('/api/wallets/seed/ack', { method: 'POST', body: JSON.stringify({}) });
    toast('Recovery phrase marked as backed up');
  } catch (e) { toast('Error: ' + e.message, 'error'); return; }
  if (_waData) _waData.seed_backed_up = true;
  waRenderBanner();
}
window.waAckSeed = waAckSeed;

/* ── coin cards ───────────────────────────────────────────────────────────── */
function waRenderCoins() {
  const el = document.getElementById('wa-coins');
  if (!el) return;
  const coins = (_waData && _waData.coins) || [];
  el.innerHTML = `
    <div class="section-header">
      <div><div class="section-title">&#128176; Coins</div>
        <div class="section-sub">Send coins TO these addresses from anywhere &mdash; they appear here automatically. Balances cached ~60s.</div></div>
      <button class="btn-sm" onclick="waLoad()">&#8635; Refresh</button>
    </div>
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:12px;">
      ${coins.map(c => `
        <div class="settings-group" style="padding:14px 16px;margin:0;" id="wa-card-${esc(c.sym)}">
          <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px;">
            <div style="font-weight:700;font-size:.9rem;">${esc(c.name)}
              <span style="color:var(--muted);font-weight:400;font-size:.74rem;">${esc(c.sym)}</span></div>
            <div style="font-size:.84rem;" id="wa-bal-${esc(c.sym)}">${_waBal(c)}</div>
          </div>
          <div title="Click to copy" onclick="waCopy('${esc(c.address)}')"
            style="font-family:monospace;font-size:.68rem;word-break:break-all;cursor:pointer;
              background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:8px 10px;margin-bottom:8px;">
            ${esc(c.address || '(no address)')}</div>
          <div style="display:flex;justify-content:space-between;align-items:center;font-size:.7rem;color:var(--muted);">
            <span>&#128229; Receive: send ${esc(c.sym)} to this address ${hlp('This address is derived from your recovery phrase — it is yours on the real ' + c.name + ' network. Anything sent to it lands in this wallet. Click the address to copy it.')}</span>
            ${c.explorer ? `<a href="${esc(c.explorer)}" target="_blank" rel="noopener" style="color:var(--accent);white-space:nowrap;">explorer &#8599;</a>` : ''}
          </div>
          ${c.sym === 'XMR' ? `<div id="wa-xmr-note" style="font-size:.7rem;color:var(--warn);margin-top:8px;line-height:1.5;"></div>` : ''}
        </div>`).join('')}
    </div>`;
}

async function waLoadXmr() {
  let d;
  try { d = await api('/api/wallets/xmr'); } catch { d = { configured: false, note: 'status check failed' }; }
  const note = document.getElementById('wa-xmr-note');
  const bal = document.getElementById('wa-bal-XMR');
  const pill = document.getElementById('wa-xmr-status');
  if (!d.configured) {
    if (pill) { pill.style.background = 'rgba(239,68,68,.16)'; pill.style.color = 'var(--red)';
                pill.innerHTML = '&#9679; Monero daemon down'; }
    if (note) note.innerHTML = `&#9432; ${esc(d.note || 'Monero wallet daemon not reachable.')}
      <div style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap;">
        <button class="btn-sm" onclick="waXmrRestart()">&#8635; Start daemon</button>
        <button class="btn-sm" onclick="waXmrSetup()">&#128268; Reopen wallet</button></div>`;
    return;
  }
  if (pill) { pill.style.background = 'rgba(34,197,94,.16)'; pill.style.color = 'var(--green)';
              pill.innerHTML = '&#9679; Monero daemon up'; }
  if (note) note.innerHTML = `<span style="color:var(--green);">&#10003; wallet daemon connected</span>`;
  if (bal && d.balance != null) {
    bal.innerHTML = `<b style="color:${d.balance > 0 ? 'var(--green)' : 'var(--text)'};">${Number(d.balance).toLocaleString(undefined, { maximumFractionDigits: 8 })}</b> <span style="color:var(--muted);">XMR</span>`;
  }
}

async function waXmrRestart() {
  toast('Starting the Monero daemon…');
  try {
    await api('/api/wallets/xmr/daemon/start', { method: 'POST', body: JSON.stringify({}) });
  } catch (e) { toast('Start failed: ' + e.message, 'error'); return; }
  // give it a few seconds to open the wallet, then refresh status
  setTimeout(waLoadXmr, 6000);
  toast('Daemon starting — balance will appear shortly');
}
window.waXmrRestart = waXmrRestart;

async function waXmrSetup() {
  toast('Bringing the Monero wallet online…');
  try {
    const r = await api('/api/wallets/xmr/setup', { method: 'POST', body: JSON.stringify({}) });
    toast(r.matches_derived ? 'XMR wallet online ✓' : 'XMR online (address mismatch!)', r.matches_derived ? 'success' : 'error');
  } catch (e) { toast('XMR setup failed: ' + e.message, 'error'); }
  waLoadXmr();
}
window.waXmrSetup = waXmrSetup;

function waCopy(addr) {
  if (!addr) return;
  navigator.clipboard.writeText(addr)
    .then(() => toast('Address copied'))
    .catch(() => toast('Copy failed — select & copy manually', 'error'));
}
window.waCopy = waCopy;

/* ── advanced: import seed + gated send queue ─────────────────────────────── */
function waRenderAdvanced() {
  const el = document.getElementById('wa-advanced');
  if (!el) return;
  const coins = (_waData && _waData.coins) || [];
  el.innerHTML = `
    <details class="settings-group">
      <summary style="cursor:pointer;font-weight:600;font-size:.9rem;">&#9881;&#65039; Advanced &mdash; import seed &amp; sends</summary>

      <div class="settings-group" style="margin-top:14px;border-color:var(--warn);">
        <div class="settings-group-title" style="color:var(--warn);">&#128260; Import your own seed</div>
        <div style="font-size:.74rem;color:var(--muted);line-height:1.7;margin-bottom:10px;">
          Restores a wallet from an existing BIP39 recovery phrase.
          <b style="color:var(--warn);">This REPLACES the current wallet</b> &mdash; back up the current
          phrase first or any funds on its addresses become unreachable from here.
        </div>
        <div class="field">
          <label>Recovery phrase ${hlp('12–24 BIP39 words separated by spaces. Validated before anything is replaced. The phrase is stored encrypted in the Store settings and never logged.')}</label>
          <textarea id="wa-import-mnemonic" rows="2" placeholder="word1 word2 word3 &hellip;"
            style="width:100%;font-family:monospace;font-size:.8rem;"></textarea>
        </div>
        <button class="btn-sm danger" onclick="waImportSeed()">&#128260; Replace wallet with this seed</button>
      </div>

      <div class="settings-group" style="margin-top:14px;">
        <div class="settings-group-title">&#128228; Send (review-gated)</div>
        <div style="font-size:.74rem;color:var(--warn);line-height:1.6;margin-bottom:10px;">
          &#9888;&#65039; Sending is review-gated; broadcast is <b>not enabled yet</b>.
          Submitting here only queues a proposal &mdash; nothing is signed or transmitted.
        </div>
        <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;">
          <div class="field" style="margin:0;">
            <label style="font-size:.72rem;">Coin</label>
            <select id="wa-send-sym">${coins.map(c => `<option value="${esc(c.sym)}">${esc(c.sym)} — ${esc(c.name)}</option>`).join('')}</select>
          </div>
          <div class="field" style="margin:0;flex:2;min-width:240px;">
            <label style="font-size:.72rem;">To address ${hlp('Destination address on the real network of the chosen coin. Double-check it — crypto transactions cannot be reversed once broadcasting is eventually enabled.')}</label>
            <input type="text" id="wa-send-to" placeholder="destination address" style="font-family:monospace;">
          </div>
          <div class="field" style="margin:0;width:130px;">
            <label style="font-size:.72rem;">Amount</label>
            <input type="number" id="wa-send-amount" min="0" step="any" placeholder="0.0">
          </div>
          <div class="field" style="margin:0;flex:1;min-width:160px;">
            <label style="font-size:.72rem;">Note</label>
            <input type="text" id="wa-send-note" placeholder="why / to whom">
          </div>
          <button class="btn-sm primary" onclick="waQueueSend()">&#128228; Queue for review</button>
        </div>
        <div id="wa-sends" style="margin-top:14px;"></div>
      </div>
    </details>`;
}

async function waImportSeed() {
  const m = (document.getElementById('wa-import-mnemonic').value || '').trim();
  if (!m) { toast('Paste a recovery phrase first', 'error'); return; }
  if (!confirm('Replace the current wallet with this seed?\n\nThe current addresses (and any funds on them) will no longer be shown here unless you re-import the old phrase. Continue?')) return;
  try {
    await api('/api/wallets/seed/import', { method: 'POST', body: JSON.stringify({ mnemonic: m }) });
    toast('Seed imported — wallet replaced');
  } catch (e) { toast('Import failed: ' + e.message, 'error'); return; }
  await renderWallets();
}
window.waImportSeed = waImportSeed;

async function waQueueSend() {
  const sym = document.getElementById('wa-send-sym').value;
  const to = (document.getElementById('wa-send-to').value || '').trim();
  const amount = parseFloat(document.getElementById('wa-send-amount').value);
  const note = (document.getElementById('wa-send-note').value || '').trim();
  if (!to) { toast('Destination address is required', 'error'); return; }
  if (!amount || amount <= 0) { toast('Amount must be > 0', 'error'); return; }
  try {
    const r = await api('/api/wallets/send', {
      method: 'POST', body: JSON.stringify({ sym, to, amount, note }) });
    toast(r.note || 'Queued for review — broadcast not enabled yet');
    document.getElementById('wa-send-to').value = '';
    document.getElementById('wa-send-amount').value = '';
    document.getElementById('wa-send-note').value = '';
  } catch (e) { toast('Error: ' + e.message, 'error'); return; }
  await waLoadSends();
}
window.waQueueSend = waQueueSend;

async function waLoadSends() {
  const el = document.getElementById('wa-sends');
  if (!el) return;
  let d;
  try { d = await api('/api/wallets/sends'); }
  catch (e) { el.innerHTML = `<div style="color:var(--red);font-size:.76rem;">${esc(e.message)}</div>`; return; }
  const sends = d.sends || [];
  if (!sends.length) {
    el.innerHTML = `<div style="color:var(--muted);font-size:.76rem;">No queued sends.</div>`;
    return;
  }
  el.innerHTML = `
    <div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;font-size:.74rem;">
      <thead><tr style="text-align:left;color:var(--muted);font-size:.66rem;text-transform:uppercase;letter-spacing:.04em;">
        <th style="padding:5px 8px;">#</th><th style="padding:5px 8px;">Coin</th>
        <th style="padding:5px 8px;">To</th><th style="padding:5px 8px;">Amount</th>
        <th style="padding:5px 8px;">Status</th><th style="padding:5px 8px;">Note</th>
        <th style="padding:5px 8px;">When</th><th style="padding:5px 8px;"></th></tr></thead>
      <tbody>${sends.map(s => `
        <tr style="border-top:1px solid var(--border);">
          <td style="padding:5px 8px;color:var(--muted);">${s.id}</td>
          <td style="padding:5px 8px;font-weight:600;">${esc(s.sym)}</td>
          <td style="padding:5px 8px;font-family:monospace;word-break:break-all;max-width:260px;">${esc(s.to_addr || '')}</td>
          <td style="padding:5px 8px;">${s.amount}</td>
          <td style="padding:5px 8px;">${
            s.status === 'proposed' ? '<span style="color:var(--warn);">proposed</span>'
            : s.status === 'prepared' ? '<span style="color:var(--accent2);">prepared</span>'
            : s.status === 'sent' ? '<span style="color:var(--green);">sent</span>'
            : `<span style="color:var(--muted);">${esc(s.status)}</span>`}</td>
          <td style="padding:5px 8px;color:var(--muted);">${s.txid
            ? `<span title="${esc(s.txid)}" style="font-family:monospace;">${esc(s.txid.slice(0,10))}…</span>`
            : esc(s.note || '')}</td>
          <td style="padding:5px 8px;color:var(--muted);white-space:nowrap;">${esc((s.created_at || '').slice(0, 16))}</td>
          <td style="padding:5px 8px;white-space:nowrap;">${
            s.status === 'proposed'
              ? `<button class="btn-sm" onclick="waPrepareSend(${s.id})">&#128200; Prepare</button>
                 <button class="btn-sm danger" onclick="waCancelSend(${s.id})">&#10005;</button>`
            : s.status === 'prepared'
              ? `<button class="btn-sm success" onclick="waBroadcastSend(${s.id}, '${esc(s.sym)}', ${s.amount}, '${esc(s.to_addr)}')">&#9889; Broadcast</button>
                 <button class="btn-sm danger" onclick="waCancelSend(${s.id})">&#10005;</button>`
            : ''}</td>
        </tr>`).join('')}
      </tbody></table></div>
    <div style="font-size:.68rem;color:var(--muted);margin-top:8px;line-height:1.5;">
      &#128200; <b>Prepare</b> builds &amp; signs the transaction and shows the network fee — nothing is sent.
      &#9889; <b>Broadcast</b> pushes it to the network for real (you'll confirm first). Broadcasts are <b>irreversible</b>.
      ETH &amp; XMR are reliable; BTC/LTC/DOGE are new — do a tiny test amount first.
    </div>`;
}

async function waPrepareSend(id) {
  toast('Building transaction & estimating fee…');
  try {
    const r = await api(`/api/wallets/sends/${id}/prepare`, { method: 'POST', body: JSON.stringify({}) });
    toast(`Prepared — network fee ≈ ${r.fee} (review, then Broadcast)`);
  } catch (e) { toast(e.message, 'error'); }
  await waLoadSends();
}
window.waPrepareSend = waPrepareSend;

async function waBroadcastSend(id, sym, amount, to) {
  if (!confirm(`Broadcast ${amount} ${sym} to\n${to}\n\nThis sends REAL funds and CANNOT be undone. Continue?`)) return;
  toast('Broadcasting…');
  try {
    const r = await api(`/api/wallets/sends/${id}/broadcast`, { method: 'POST', body: JSON.stringify({ confirm: true }) });
    toast(`Sent! txid ${String(r.txid).slice(0, 12)}…`);
  } catch (e) { toast(e.message, 'error'); }
  await waLoadSends();
  await waLoad();
}
window.waBroadcastSend = waBroadcastSend;

async function waCancelSend(id) {
  try {
    await api(`/api/wallets/sends/${id}/cancel`, { method: 'POST', body: JSON.stringify({}) });
    toast('Send cancelled');
  } catch (e) { toast('Error: ' + e.message, 'error'); }
  await waLoadSends();
}
window.waCancelSend = waCancelSend;
