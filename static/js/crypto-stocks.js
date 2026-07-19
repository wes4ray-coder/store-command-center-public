/* ══ CRYPTO TAB — Stocks + Key Backups panes (split from tab-crypto.js) ══ */

/* ── 📈 STOCKS ────────────────────────────────────────────────────────────── */
async function cryptoLoadStocks() {
  const pane = document.getElementById('pane-crypto-stocks');
  let cfg = { settings: {} }, port = { configured: false }, watch = { quotes: [] };
  try { cfg = await api('/api/crypto/settings'); } catch {}
  try { port = await api('/api/crypto/stocks'); } catch (e) { port = { configured: false, error: e.message }; }
  try { watch = await api('/api/crypto/stocks/watch'); } catch {}
  const st = cfg.settings || {};

  const holdRows = port.configured
    ? Object.entries(port.holdings || {}).map(([sym, h]) => `
        <tr style="border-bottom:1px solid var(--border);">
          <td style="padding:6px 10px;font-weight:600;">${esc(sym)}</td>
          <td style="padding:6px 10px;text-align:right;">${esc(h.quantity || '')}</td>
          <td style="padding:6px 10px;text-align:right;">${h.price != null ? _cyUsd(parseFloat(h.price)) : '—'}</td>
          <td style="padding:6px 10px;text-align:right;">${h.equity != null ? _cyUsd(parseFloat(h.equity)) : '—'}</td>
          <td style="padding:6px 10px;text-align:right;">${_cyPct(parseFloat(h.percent_change))}</td>
        </tr>`).join('')
    : '';

  const portCard = port.configured ? `
    <div class="settings-group" style="max-width:680px;margin-bottom:16px;">
      <div class="settings-group-title">&#129412; Robinhood portfolio
        <span style="font-size:.72rem;color:var(--muted);font-weight:400;margin-left:8px;">equity: <b style="color:var(--text);">${port.equity != null ? _cyUsd(parseFloat(port.equity)) : '—'}</b></span></div>
      <div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;font-size:.78rem;">
        <thead><tr style="color:var(--muted);text-align:left;border-bottom:1px solid var(--border);">
          <th style="padding:6px 10px;">Symbol</th><th style="padding:6px 10px;text-align:right;">Qty</th>
          <th style="padding:6px 10px;text-align:right;">Price</th><th style="padding:6px 10px;text-align:right;">Equity</th>
          <th style="padding:6px 10px;text-align:right;">Change</th></tr></thead>
        <tbody>${holdRows || '<tr><td colspan="5" style="padding:12px;color:var(--muted);">No holdings.</td></tr>'}</tbody>
      </table></div>
    </div>` : `
    <div class="settings-group" style="max-width:680px;margin-bottom:16px;">
      <div class="settings-group-title">&#129412; Robinhood</div>
      <div style="font-size:.76rem;color:var(--muted);margin-bottom:10px;">
        Not connected${port.error ? ` — <span style="color:var(--warn);">${esc(port.error)}</span>` : ''}.
        Enter credentials to see your portfolio (read-only here; this tab never places orders).
      </div>
      <div class="settings-grid" style="max-width:640px;">
        <div class="field"><label>Username ${hlp('Your Robinhood login email. Used only by robin_stocks on this server to read your portfolio — nothing is traded from here.')}</label>
          <input type="text" id="cy-rh-user" value="${esc(st.rh_username || '')}" placeholder="you@example.com"></div>
        <div class="field"><label>Password ${hlp('Your Robinhood password. Stored in this app’s local settings DB on your own server. Leave blank to keep the currently saved one.')}</label>
          <input type="password" id="cy-rh-pass" value="" placeholder="${st.rh_password ? 'saved — leave blank to keep' : 'password'}"></div>
        <div class="field"><label>MFA TOTP secret (optional) ${hlp('The BASE32 secret from Robinhood’s authenticator-app setup (not a 6-digit code). With it, logins auto-answer the 2FA prompt via pyotp. Leave blank to keep the saved one.')}</label>
          <input type="password" id="cy-rh-mfa" value="" placeholder="${st.rh_mfa_secret ? 'saved — leave blank to keep' : 'BASE32SECRET'}"></div>
      </div>
      <button class="btn-sm primary" onclick="cryptoSaveStocksCreds()">&#128190; Save credentials</button>
    </div>`;

  const quoteRows = (watch.quotes || []).map(q => `
    <tr style="border-bottom:1px solid var(--border);vertical-align:top;">
      <td style="padding:6px 10px;font-weight:600;">${esc(q.symbol)}</td>
      <td style="padding:6px 10px;text-align:right;">${q.price != null ? _cyUsd(q.price) : `<span style="color:var(--warn);">${esc(q.error || '—')}</span>`}</td>
      <td style="padding:6px 10px;font-size:.72rem;">${(q.news || []).map(n =>
        n.link ? `<a href="${esc(n.link)}" target="_blank" rel="noopener" style="color:var(--accent);text-decoration:none;display:block;margin-bottom:2px;">${esc(n.title)}</a>`
               : `<div style="color:var(--muted);margin-bottom:2px;">${esc(n.title)}</div>`).join('') || '<span style="color:var(--muted);">—</span>'}</td>
    </tr>`).join('');

  pane.innerHTML = `
    <div class="section-header">
      <div><div class="section-title">&#128200; Stocks</div>
        <div class="section-sub">Portfolio, watchlist quotes &amp; an LLM daily brief. <b>Not financial advice.</b></div></div>
      <button class="btn-sm" onclick="_cryptoLoaded.stocks=false;cryptoSub('stocks')">&#8635; Refresh</button>
    </div>
    ${portCard}
    <div class="settings-group" style="max-width:680px;margin-bottom:16px;">
      <div class="settings-group-title">&#128064; Watchlist</div>
      <div style="display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap;margin-bottom:12px;">
        <div class="field" style="flex:1;min-width:260px;margin:0;">
          <label>Symbols (comma-separated) ${hlp('Ticker symbols to track with free yfinance data — quotes cached 5 min, top-3 news headlines each. Also feeds the Daily Brief below (together with your holdings).')}</label>
          <input type="text" id="cy-watchlist" value="${esc(st.stocks_watchlist || '')}" placeholder="AAPL, MSFT, NVDA, SPY">
        </div>
        <button class="btn-sm primary" onclick="cryptoSaveWatchlist()">&#128190; Save</button>
      </div>
      ${watch.error ? `<div style="color:var(--warn);font-size:.76rem;margin-bottom:8px;">${esc(watch.error)}</div>` : ''}
      <div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;font-size:.78rem;">
        <thead><tr style="color:var(--muted);text-align:left;border-bottom:1px solid var(--border);">
          <th style="padding:6px 10px;">Symbol</th><th style="padding:6px 10px;text-align:right;">Price</th>
          <th style="padding:6px 10px;">Latest news</th></tr></thead>
        <tbody>${quoteRows || `<tr><td colspan="3" style="padding:12px;color:var(--muted);">${esc(watch.note || 'No watchlist symbols yet.')}</td></tr>`}</tbody>
      </table></div>
    </div>
    <div class="settings-group" style="max-width:820px;">
      <div class="settings-group-title">&#128221; Daily Brief</div>
      <div style="font-size:.74rem;color:var(--muted);margin-bottom:10px;">
        SMA20 vs SMA50 + 14-day RSI per symbol (watchlist + holdings), summarized by the local LLM.
        <b style="color:var(--warn);">Automated technical commentary — NOT financial advice.</b>
      </div>
      <button class="btn-sm primary" id="cy-brief-btn" onclick="cryptoDailyBrief()">&#128221; Generate today's brief</button>
      <div id="cy-brief-out" style="margin-top:12px;"></div>
    </div>`;
}
window.cryptoLoadStocks = cryptoLoadStocks;

async function cryptoSaveStocksCreds() {
  const body = { rh_username: document.getElementById('cy-rh-user').value.trim() };
  const pass = document.getElementById('cy-rh-pass').value;
  const mfa  = document.getElementById('cy-rh-mfa').value.trim();
  if (pass) body.rh_password = pass;      // blank = keep saved value
  if (mfa)  body.rh_mfa_secret = mfa;
  try {
    await api('/api/crypto/settings', { method: 'POST', body: JSON.stringify(body) });
    toast('Credentials saved ✓');
    _cryptoLoaded.stocks = false;
    cryptoSub('stocks');
  } catch (e) { toast('Save failed: ' + e.message, 'error'); }
}
window.cryptoSaveStocksCreds = cryptoSaveStocksCreds;

async function cryptoSaveWatchlist() {
  try {
    await api('/api/crypto/settings', { method: 'POST',
      body: JSON.stringify({ stocks_watchlist: document.getElementById('cy-watchlist').value.trim() }) });
    toast('Watchlist saved ✓');
    _cryptoLoaded.stocks = false;
    cryptoSub('stocks');
  } catch (e) { toast('Save failed: ' + e.message, 'error'); }
}
window.cryptoSaveWatchlist = cryptoSaveWatchlist;

async function cryptoDailyBrief() {
  const btn = document.getElementById('cy-brief-btn');
  const out = document.getElementById('cy-brief-out');
  btn.disabled = true; btn.innerHTML = '&#9203; Crunching signals + writing…';
  out.innerHTML = '<div style="color:var(--muted);font-size:.78rem;">Fetching 3 months of history per symbol, then one LLM pass — this can take a minute.</div>';
  try {
    const { task_id } = await api('/api/crypto/stocks/brief');
    const r = await pollTask(task_id, 150);
    const sigRows = (r.signals || []).map(s => `
      <tr style="border-bottom:1px solid var(--border);">
        <td style="padding:5px 10px;font-weight:600;">${esc(s.symbol)}</td>
        <td style="padding:5px 10px;text-align:right;">${_cyUsd(s.price)}</td>
        <td style="padding:5px 10px;text-align:right;">${s.sma20 ?? '—'}</td>
        <td style="padding:5px 10px;text-align:right;">${s.sma50 ?? '—'}</td>
        <td style="padding:5px 10px;text-align:right;">${s.rsi ?? '—'}</td>
        <td style="padding:5px 10px;">${esc(s.stance)}</td>
      </tr>`).join('');
    out.innerHTML = `
      <div style="overflow-x:auto;margin-bottom:12px;"><table style="width:100%;border-collapse:collapse;font-size:.76rem;">
        <thead><tr style="color:var(--muted);text-align:left;border-bottom:1px solid var(--border);">
          <th style="padding:5px 10px;">Symbol</th><th style="padding:5px 10px;text-align:right;">Price</th>
          <th style="padding:5px 10px;text-align:right;">SMA20</th><th style="padding:5px 10px;text-align:right;">SMA50</th>
          <th style="padding:5px 10px;text-align:right;">RSI14</th><th style="padding:5px 10px;">Stance</th></tr></thead>
        <tbody>${sigRows || '<tr><td colspan="6" style="padding:10px;color:var(--muted);">No signals.</td></tr>'}</tbody>
      </table></div>
      <div class="prompt-test-out" style="display:block;">${esc(r.brief || '(empty brief)')}</div>`;
  } catch (e) {
    out.innerHTML = `<div style="color:var(--red);font-size:.8rem;">${esc(e.message)}</div>`;
  }
  btn.disabled = false; btn.innerHTML = "&#128221; Generate today's brief";
}
window.cryptoDailyBrief = cryptoDailyBrief;

/* ── 🔑 BACKUPS ───────────────────────────────────────────────────────────── */
// Secret export is now GATED: request files a `secret_export` prayer, a human
// blesses it in the God Console, then the single-use zip downloads with ?prayer_id.
let _cryptoBackupPrayerId = null;

async function cryptoLoadBackups() {
  const pane = document.getElementById('pane-crypto-backups');
  const pending = _cryptoBackupPrayerId != null;
  pane.innerHTML = `
    <div class="section-header"><div><div class="section-title">&#128273; Key backup</div>
      <div class="section-sub">One zip with everything needed to reconstruct this crypto setup.</div></div></div>
    <div class="settings-group" style="max-width:640px;border-color:var(--red);">
      <div class="settings-group-title" style="color:var(--red);">&#9888;&#65039; THIS FILE CONTAINS PRIVATE KEYS</div>
      <div style="font-size:.78rem;color:var(--muted);line-height:1.8;margin-bottom:14px;">
        Anyone holding this zip controls the wallets and accounts inside it. Download it,
        move it to offline storage (USB stick, printed, password-managed vault), and never
        share or commit it anywhere.
        <br><br><b style="color:var(--text);">Included:</b>
        <ul style="margin:6px 0 0 18px;line-height:1.8;">
          <li>&#8383; Bitcoin wallet descriptors <b>with private keys</b> (<code>listdescriptors private=true</code>)</li>
          <li>&#128273; All <code>btc_ / ft_ / xmr_ / rh_ / money_</code> settings (RPC + API + broker credentials) as <code>settings.json</code></li>
          <li>&#129302; Every FreqTrade strategy file (<code>strategies/</code> + <code>strategies_drafts/</code>)</li>
        </ul>
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;">
        <button class="btn-sm" style="font-size:.88rem;padding:10px 20px;" onclick="cryptoRequestBackup()">&#128229; Request encrypted backup</button>
        <button class="btn-sm danger" style="font-size:.88rem;padding:10px 20px;" onclick="cryptoDownloadBackup()" ${pending ? '' : 'disabled'}>&#11015;&#65039; Download backup (.zip)</button>
      </div>
      <div style="font-size:.75rem;color:var(--muted);margin-top:10px;line-height:1.7;">
        ${pending
          ? `&#9989; Backup requested (prayer #${_cryptoBackupPrayerId}). Approve the <b>'secret_export'</b> request in the God Console (World &#8594; God Console &#8594; prayers), then click <b>Download backup</b>. Single-use.`
          : `Two-step, gated export: request an encrypted backup, approve the <b>'secret_export'</b> request in the God Console (World &#8594; God Console &#8594; prayers), then download. Named <code>crypto-backup-&lt;date&gt;.zip</code>.`}
      </div>
    </div>`;
}
window.cryptoLoadBackups = cryptoLoadBackups;

// Step 1 — file the gated secret_export prayer; remember its id for the download.
async function cryptoRequestBackup() {
  try {
    const j = await api('/api/crypto/backup/request', { method: 'POST' });
    _cryptoBackupPrayerId = j.prayer && j.prayer.id;
    if (!_cryptoBackupPrayerId) { toast('Request failed — no prayer id returned.', 'error'); return; }
    toast(`Backup requested (prayer #${_cryptoBackupPrayerId}). Approve it in the God Console, then Download.`);
    cryptoLoadBackups();
  } catch (e) {
    toast('Request failed: ' + e.message, 'error');
  }
}
window.cryptoRequestBackup = cryptoRequestBackup;

// Step 2 — only after the prayer is blessed, pull the single-use zip as a blob.
async function cryptoDownloadBackup() {
  if (!_cryptoBackupPrayerId) { toast('Request an encrypted backup first.', 'error'); return; }
  // Check the prayer status before spending the single-use blessing.
  let blessed = false;
  try {
    const j = await api('/api/world/ops/prayers?limit=100');
    const p = (j.prayers || []).find(x => x.id === _cryptoBackupPrayerId);
    blessed = !!p && (p.status === 'approved' || p.status === 'done');
  } catch (e) {
    toast('Could not check approval: ' + e.message, 'error');
    return;
  }
  if (!blessed) { toast('Not approved yet — approve it in the God Console first.', 'error'); return; }
  // Blessed: fetch as a blob so a 403 (race / already-consumed) stays graceful.
  try {
    const res = await fetch(API + '/api/crypto/backup?prayer_id=' + _cryptoBackupPrayerId);
    if (!res.ok) {
      toast(res.status === 403
        ? 'Backup no longer available — request a new one.'
        : `Download failed (HTTP ${res.status}).`, 'error');
    } else {
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'crypto-backup-' + new Date().toISOString().slice(0, 10) + '.zip';
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
      toast('Backup downloaded — this request is now used up.');
    }
  } catch (e) {
    toast('Download failed: ' + e.message, 'error');
  }
  // Single-use blessing: reset back to the request state either way.
  _cryptoBackupPrayerId = null;
  cryptoLoadBackups();
}
window.cryptoDownloadBackup = cryptoDownloadBackup;
window.cryptoDownloadBackup = cryptoDownloadBackup;
