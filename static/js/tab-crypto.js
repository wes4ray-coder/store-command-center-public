/* ══ CRYPTO & MARKETS TAB ══
   Sub-tabs (same pane-toggle mechanism as Settings — everything stays in the DOM,
   we only switch which pane is visible, and each pane lazy-loads once):
     📊 Stats   — top-20 coins + trending (CoinGecko)
     ⛓️ Nodes   — local Bitcoin Core regtest container + honest catalog of others
     ⛏️ Mining  — regtest block miner + Monero/xmrig placeholder + reality check
     🤖 Trading — FreqTrade (DRY-RUN) status + LLM strategy drafts w/ approve flow
     📈 Stocks  — Robinhood portfolio, yfinance watchlist, LLM daily brief
     🔑 Backups — private-key backup zip download */

const _CRYPTO_PANES = ['stats', 'jelly', 'nodes', 'mining', 'trading', 'stocks', 'backups'];
let _cryptoLoaded = {};       // pane -> true once its data has been fetched
let _cryptoDrafts = [];       // strategy drafts cache (for code preview)

async function renderCrypto() {
  _cryptoLoaded = {};
  document.getElementById('main-content').innerHTML = `
    <div class="view-header">
      <div class="view-title">&#8383; Crypto &amp; Markets</div>
      <div class="view-sub">Market data, paper-trading bot, real Monero mining &amp; your stock watchlist.
        Your real spendable coins live in the &#128092; Wallets tab. Nothing here auto-trades real money.</div>
    </div>
    <div class="subtab-bar" id="crypto-subtabs">
      <div class="subtab active" onclick="cryptoSub('stats')">&#128202; Stats</div>
      <div class="subtab" onclick="cryptoSub('jelly')">&#129724; JellyCoin</div>
      <div class="subtab" onclick="cryptoSub('nodes')">&#9939;&#65039; Nodes</div>
      <div class="subtab" onclick="cryptoSub('mining')">&#9935;&#65039; Mining</div>
      <div class="subtab" onclick="cryptoSub('trading')">&#129302; Trading</div>
      <div class="subtab" onclick="cryptoSub('stocks')">&#128200; Stocks</div>
      <div class="subtab" onclick="cryptoSub('backups')">&#128273; Backups</div>
    </div>
    ${_CRYPTO_PANES.map(k => `<div class="settings-tabpane" id="pane-crypto-${k}"${k === 'stats' ? '' : ' style="display:none;"'}>
      <div class="empty"><div class="empty-icon">&#9203;</div>Loading&#8230;</div>
    </div>`).join('')}`;
  cryptoSub('stats');
}
window.renderCrypto = renderCrypto;

function cryptoSub(k) {
  _CRYPTO_PANES.forEach(name => {
    const pane = document.getElementById('pane-crypto-' + name);
    if (pane) pane.style.display = (name === k) ? '' : 'none';
  });
  document.querySelectorAll('#crypto-subtabs .subtab').forEach((el, i) => {
    el.classList.toggle('active', _CRYPTO_PANES[i] === k);
  });
  if (!_cryptoLoaded[k]) {
    _cryptoLoaded[k] = true;
    ({ stats: cryptoLoadStats, jelly: cryptoLoadJelly, nodes: cryptoLoadNodes, mining: cryptoLoadMining,
       trading: cryptoLoadTrading, stocks: cryptoLoadStocks, backups: cryptoLoadBackups }[k])();
  }
}
window.cryptoSub = cryptoSub;

function _cyPct(v) {
  if (v == null || isNaN(v)) return '<span style="color:var(--muted)">—</span>';
  const col = v >= 0 ? 'var(--green)' : 'var(--red)';
  return `<span style="color:${col}">${v >= 0 ? '+' : ''}${Number(v).toFixed(2)}%</span>`;
}
function _cyUsd(v, dec) {
  if (v == null || isNaN(v)) return '—';
  return '$' + Number(v).toLocaleString(undefined, { maximumFractionDigits: dec != null ? dec : (v < 1 ? 6 : 2) });
}
function _cyMcap(v) {
  if (v == null) return '—';
  if (v >= 1e12) return '$' + (v / 1e12).toFixed(2) + 'T';
  if (v >= 1e9)  return '$' + (v / 1e9).toFixed(1) + 'B';
  if (v >= 1e6)  return '$' + (v / 1e6).toFixed(1) + 'M';
  return _cyUsd(v, 0);
}

/* ── 📊 STATS ─────────────────────────────────────────────────────────────── */
async function cryptoLoadStats() {
  const pane = document.getElementById('pane-crypto-stats');
  let d;
  try { d = await api('/api/crypto/stats'); }
  catch (e) { pane.innerHTML = `<div class="empty"><div class="empty-icon">&#10060;</div>${esc(e.message)}</div>`; return; }
  if (d.error && !(d.coins || []).length) {
    pane.innerHTML = `<div class="empty"><div class="empty-icon">&#128268;</div>${esc(d.error)}</div>`;
    return;
  }
  const trending = (d.trending || []).length ? `
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px;align-items:center;">
      <span style="font-size:.72rem;color:var(--muted);font-weight:700;text-transform:uppercase;letter-spacing:.05em;">&#128293; Trending</span>
      ${d.trending.map(t => `<span style="display:inline-flex;align-items:center;gap:5px;background:var(--surface2);border:1px solid var(--border);border-radius:20px;padding:4px 10px;font-size:.75rem;">
        ${t.thumb ? `<img src="${esc(t.thumb)}" style="width:16px;height:16px;border-radius:50%;" loading="lazy">` : ''}${esc(t.symbol || t.name)}${t.rank ? ` <span style="color:var(--muted);">#${t.rank}</span>` : ''}</span>`).join('')}
    </div>` : '';
  const rows = (d.coins || []).map(c => `
    <tr style="border-bottom:1px solid var(--border);">
      <td style="padding:7px 10px;color:var(--muted);">${c.rank ?? ''}</td>
      <td style="padding:7px 10px;font-weight:600;white-space:nowrap;">
        ${c.image ? `<img src="${esc(c.image)}" style="width:18px;height:18px;border-radius:50%;vertical-align:-4px;margin-right:7px;" loading="lazy">` : ''}${esc(c.name)}
        <span style="color:var(--muted);font-weight:400;">${esc(c.symbol)}</span></td>
      <td style="padding:7px 10px;text-align:right;">${_cyUsd(c.price)}</td>
      <td style="padding:7px 10px;text-align:right;">${_cyPct(c.chg24h)}</td>
      <td style="padding:7px 10px;text-align:right;">${_cyPct(c.chg7d)}</td>
      <td style="padding:7px 10px;text-align:right;color:var(--muted);">${_cyMcap(c.mcap)}</td>
    </tr>`).join('');
  pane.innerHTML = `
    <div class="section-header">
      <div><div class="section-title">&#128202; Top 20 by market cap</div>
        <div class="section-sub">CoinGecko free API · cached 2 min${d.fetched_at ? ' · as of ' + esc(d.fetched_at) : ''}</div></div>
      <button class="btn-sm" onclick="_cryptoLoaded.stats=false;cryptoSub('stats')">&#8635; Refresh</button>
    </div>
    ${trending}
    <div style="overflow-x:auto;">
      <table style="width:100%;border-collapse:collapse;font-size:.8rem;">
        <thead><tr style="color:var(--muted);text-align:left;border-bottom:1px solid var(--border);">
          <th style="padding:6px 10px;">#</th><th style="padding:6px 10px;">Coin</th>
          <th style="padding:6px 10px;text-align:right;">Price</th>
          <th style="padding:6px 10px;text-align:right;">24h</th>
          <th style="padding:6px 10px;text-align:right;">7d</th>
          <th style="padding:6px 10px;text-align:right;">Market cap</th>
        </tr></thead>
        <tbody>${rows || '<tr><td colspan="6" style="padding:14px;color:var(--muted);">No data.</td></tr>'}</tbody>
      </table>
    </div>`;
}
window.cryptoLoadStats = cryptoLoadStats;

/* ── ⛓️ NODES ─────────────────────────────────────────────────────────────── */
function _cyDot(running) {
  const col = running ? 'var(--green)' : 'var(--red)';
  return `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${col};box-shadow:0 0 6px ${col};margin-right:7px;"></span>`;
}

async function cryptoLoadNodes() {
  const pane = document.getElementById('pane-crypto-nodes');
  let d;
  try { d = await api('/api/crypto/nodes'); }
  catch (e) { pane.innerHTML = `<div class="empty"><div class="empty-icon">&#10060;</div>${esc(e.message)}</div>`; return; }
  pane.innerHTML = `
    <div class="section-header">
      <div><div class="section-title">&#9939;&#65039; Nodes</div>
        <div class="section-sub">Your spendable coins are real mainnet wallets in the <b>&#128092; Wallets</b> tab — no node, no download. Running your own full node is optional and only about self-sovereignty.</div></div>
    </div>
    <div class="settings-group" style="max-width:640px;margin-bottom:16px;border-color:var(--accent);">
      <div style="font-size:.8rem;color:var(--text);line-height:1.7;">&#128161; ${esc(d.note || '')}
        <br><a onclick="document.querySelector('.nav-item[data-view=wallets]').click()" style="color:var(--accent);cursor:pointer;font-weight:600;">Open Wallets &#8594;</a></div>
    </div>
    <div class="section-header"><div><div class="section-title">Full nodes you could run</div>
      <div class="section-sub">Honest notes on what each one really gets you at home (none are needed for the wallets to work).</div></div></div>
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px;">
      ${(d.catalog || []).map(n => `
        <div class="settings-group" style="padding:14px 16px;">
          <div style="font-weight:700;font-size:.88rem;margin-bottom:6px;">${esc(n.name)}
            <span style="font-size:.6rem;font-weight:700;background:var(--surface);border:1px solid var(--border);color:var(--muted);border-radius:10px;padding:2px 8px;margin-left:6px;text-transform:uppercase;">full node not installed</span></div>
          <div style="font-size:.74rem;color:var(--muted);line-height:1.6;">${esc(n.note)}</div>
        </div>`).join('')}
    </div>`;
}
window.cryptoLoadNodes = cryptoLoadNodes;

/* ── ⛏️ MINING (real Monero CPU mining via official xmrig) ─────────────────── */
async function cryptoLoadMining() {
  const pane = document.getElementById('pane-crypto-mining');
  let m = {};
  try { m = await api('/api/crypto/mining'); }
  catch (e) { pane.innerHTML = `<div class="empty"><div class="empty-icon">&#10060;</div>${esc(e.message)}</div>`; return; }
  const running = !!m.running;
  pane.innerHTML = `
    <div class="section-header"><div><div class="section-title">&#9935;&#65039; Mining</div>
      <div class="section-sub">Real Monero CPU mining via official xmrig ${esc(m.installed ? '(installed)' : '(NOT installed)')}. Off by default — this mines to your real XMR address.</div></div>
      <button class="btn-sm" onclick="_cryptoLoaded.mining=false;cryptoSub('mining')">&#8635; Refresh</button>
    </div>
    <div class="settings-group" style="max-width:600px;margin-bottom:16px;">
      <div class="settings-group-title">${_cyDot(running)}xmrig — Monero (RandomX, CPU)
        <span style="font-size:.62rem;font-weight:700;background:${running ? 'rgba(34,197,94,.16)' : 'rgba(148,163,184,.16)'};color:${running ? 'var(--green)' : 'var(--muted)'};border-radius:10px;padding:2px 8px;margin-left:8px;text-transform:uppercase;">${running ? 'mining' : 'stopped'}</span></div>
      <div style="font-size:.76rem;color:var(--muted);line-height:1.7;margin-bottom:12px;">
        Mines to <code style="word-break:break-all;">${esc(m.wallet || '(no XMR address yet — open Wallets)')}</code><br>
        Pool: <code>${esc(m.pool || '')}</code>
      </div>
      <div style="display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap;margin-bottom:12px;">
        <div class="field" style="margin:0;flex:1;min-width:220px;">
          <label>Pool ${hlp('Monero mining pool host:port. Default MoneroOcean auto-switches to the most profitable algorithm.')}</label>
          <input id="cy-xmr-pool" value="${esc(m.pool || '')}" style="width:100%;">
        </div>
        <div class="field" style="margin:0;">
          <label>Threads ${hlp('0 = auto (xmrig picks). Lower it to leave CPU for the live sites — this box also serves WordPress + the Store.')}</label>
          <input type="number" id="cy-xmr-threads" min="0" max="8" value="${m.threads ?? 0}" style="width:90px;">
        </div>
        <button class="btn-sm" onclick="cryptoMiningConfig()">&#128190; Save</button>
      </div>
      <div style="display:flex;gap:8px;">
        <button class="btn-sm success" onclick="cryptoMiningAction('start')" ${running || !m.installed ? 'disabled' : ''}>&#9654; Start mining</button>
        <button class="btn-sm danger" onclick="cryptoMiningAction('stop')" ${running ? '' : 'disabled'}>&#9209; Stop</button>
      </div>
    </div>
    <div class="settings-group" style="max-width:600px;border-color:var(--warn);">
      <div class="settings-group-title" style="color:var(--warn);">&#9888;&#65039; Profitability reality check</div>
      <div style="font-size:.76rem;color:var(--muted);line-height:1.7;">
        Home CPU mining earns <b>pennies per day</b> — usually less than the electricity it
        burns, and it heats/loads this box while it serves your live sites. BTC / LTC / DOGE
        are ASIC-only; Ethereum has no mining at all. The realistic money paths here are the
        <b>&#129302; Trading</b> flow (paper-tested first) and the store's missions/products.
        Mining pays to your real XMR wallet, so anything earned is genuinely yours.
      </div>
    </div>`;
}
window.cryptoLoadMining = cryptoLoadMining;

async function cryptoMiningConfig() {
  const pool = document.getElementById('cy-xmr-pool').value;
  const threads = parseInt(document.getElementById('cy-xmr-threads').value, 10) || 0;
  try {
    await api('/api/crypto/mining/config', { method: 'POST', body: JSON.stringify({ pool, threads }) });
    toast('Mining config saved');
  } catch (e) { toast('Error: ' + e.message, 'error'); }
  _cryptoLoaded.mining = false; cryptoSub('mining');
}
window.cryptoMiningConfig = cryptoMiningConfig;

async function cryptoMiningAction(action) {
  try {
    await api(`/api/crypto/mining/${action}`, { method: 'POST' });
    toast(`xmrig ${action}`);
  } catch (e) { toast('Error: ' + e.message, 'error'); }
  _cryptoLoaded.mining = false; cryptoSub('mining');
}
window.cryptoMiningAction = cryptoMiningAction;

/* ── 🤖 TRADING ───────────────────────────────────────────────────────────── */
async function cryptoLoadTrading() {
  const pane = document.getElementById('pane-crypto-trading');
  let t = {}, s = {}, k = { configured: false };
  try { t = await api('/api/crypto/trading'); } catch (e) { t = { configured: false, error: e.message }; }
  try { s = await api('/api/crypto/trading/strategies'); } catch { s = { drafts: [], active: [] }; }
  try { k = await api('/api/crypto/kraken'); } catch (e) { k = { configured: false, error: e.message }; }
  _cryptoDrafts = s.drafts || [];

  // ── your real Kraken account ──
  let krakenCard;
  if (!k.configured) {
    krakenCard = `<div class="settings-group" style="max-width:640px;margin-bottom:16px;">
      <div class="settings-group-title">&#128025; Kraken account</div>
      <div style="font-size:.76rem;color:var(--muted);line-height:1.6;margin-bottom:10px;">
        Connect your real Kraken account (read-only balances here; the bot only trades it if you
        explicitly go live). Create an API key at Kraken → Settings → API with <b>Query Funds</b>
        permission (add <b>Create/Modify Orders</b> only when you want the bot to trade).
      </div>
      <div style="display:grid;gap:8px;max-width:520px;">
        <div class="field" style="margin:0;"><label>API key ${hlp('From Kraken → Settings → API. Query Funds is enough to just view balances.')}</label>
          <input id="cy-kraken-key" placeholder="Kraken API key" style="width:100%;"></div>
        <div class="field" style="margin:0;"><label>Private key (secret) ${hlp('The base64 private key Kraken shows when you create the API key. Stored encrypted at rest.')}</label>
          <input id="cy-kraken-secret" type="password" placeholder="Kraken private key" style="width:100%;"></div>
        <div><button class="btn-sm primary" onclick="cryptoKrakenSave()">&#128190; Connect Kraken</button></div>
      </div></div>`;
  } else if (k.error) {
    krakenCard = `<div class="settings-group" style="max-width:640px;margin-bottom:16px;border-color:var(--red);">
      <div class="settings-group-title">&#128025; Kraken account</div>
      <div style="font-size:.78rem;color:var(--red);">${esc(k.error)}</div>
      <div style="margin-top:8px;"><button class="btn-sm" onclick="cryptoKrakenForget()">Re-enter keys</button></div></div>`;
  } else {
    krakenCard = `<div class="settings-group" style="max-width:640px;margin-bottom:16px;">
      <div class="settings-group-title">${_cyDot(true)}Kraken account
        <span style="font-size:.72rem;color:var(--muted);font-weight:400;margin-left:8px;">total &asymp; <b style="color:var(--green);">$${Number(k.total_usd || 0).toLocaleString()}</b></span></div>
      ${(k.balances || []).length ? `<div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;font-size:.78rem;">
        <thead><tr style="text-align:left;color:var(--muted);font-size:.66rem;text-transform:uppercase;">
          <th style="padding:4px 8px;">Asset</th><th style="padding:4px 8px;">Amount</th><th style="padding:4px 8px;">USD</th></tr></thead>
        <tbody>${k.balances.map(b => `<tr style="border-top:1px solid var(--border);">
          <td style="padding:4px 8px;font-weight:600;">${esc(b.asset)}</td>
          <td style="padding:4px 8px;">${b.amount}</td>
          <td style="padding:4px 8px;color:var(--muted);">$${Number(b.usd).toLocaleString()}</td></tr>`).join('')}</tbody></table></div>`
        : '<div style="font-size:.76rem;color:var(--muted);">No non-zero balances.</div>'}
      <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;">
        <button class="btn-sm" onclick="cryptoKrakenSyncFt()" title="Copy your Kraken keys into FreqTrade so the bot can use your real account — stays paper (dry-run) until you flip it yourself.">&#128260; Use in FreqTrade (stays paper)</button>
        <button class="btn-sm" onclick="cryptoKrakenForget()">Re-enter keys</button>
      </div></div>`;
  }

  const dryBadge = `<span style="font-size:.68rem;font-weight:800;background:rgba(245,158,11,.18);color:var(--warn);border:1px solid var(--warn);border-radius:10px;padding:3px 10px;text-transform:uppercase;letter-spacing:.05em;">DRY-RUN · paper money</span>`;
  let statusCard;
  if (!t.configured) {
    statusCard = `<div class="settings-group" style="max-width:640px;margin-bottom:16px;">
      <div class="settings-group-title">&#129302; FreqTrade ${dryBadge}</div>
      <div style="font-size:.78rem;color:var(--muted);line-height:1.7;">
        Container <code>crypto-freqtrade</code>: <b>${esc(t.container || 'unknown')}</b>.
        Not reachable — ${esc(t.error || 'is the container running and are ft_api_user / ft_api_pass set?')}
      </div></div>`;
  } else {
    const p = t.profit || {};
    statusCard = `<div class="settings-group" style="max-width:640px;margin-bottom:16px;">
      <div class="settings-group-title">${_cyDot(t.running)}FreqTrade ${t.dry_run ? dryBadge
        : '<span style="font-size:.68rem;font-weight:800;background:rgba(239,68,68,.18);color:var(--red);border:1px solid var(--red);border-radius:10px;padding:3px 10px;">&#9888; LIVE MONEY</span>'}</div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-bottom:10px;">
        ${statCard('Strategy', esc(t.strategy || '—'))}
        ${statCard('Open trades', t.open_trade_count ?? '—')}
        ${statCard('Closed trades', p.closed_trade_count ?? p.trade_count ?? '—')}
        ${statCard('Closed profit', p.profit_closed_coin != null ? `${Number(p.profit_closed_coin).toFixed(4)} ${esc(t.stake_currency || '')}` : '—')}
        ${statCard('Win / loss', (p.winning_trades != null) ? `${p.winning_trades} / ${p.losing_trades}` : '—')}
        ${statCard('Balance', t.balance_total != null ? `${Number(t.balance_total).toFixed(2)} ${esc(t.stake_currency || '')}` : '—')}
      </div>
      <div style="font-size:.74rem;color:var(--muted);">Pairs: ${(t.whitelist || []).slice(0, 12).map(w => `<code style="margin-right:6px;">${esc(w)}</code>`).join('') || '—'}</div>
    </div>`;
  }

  const draftCard = (d) => {
    const stCol = { proposed: 'var(--warn)', approved: 'var(--green)', rejected: 'var(--red)' }[d.status] || 'var(--muted)';
    const bt = d.backtest;
    let btHtml = '<span style="font-size:.68rem;color:var(--muted);">not backtested</span>';
    if (bt) {
      const good = bt.passed;
      const col = good ? 'var(--green)' : 'var(--red)';
      btHtml = `<span title="180-day Coinbase backtest" style="font-size:.68rem;color:${col};font-weight:700;">
        ${good ? '✓ PASSED' : '✗ FAILED'} · ${bt.profit_pct > 0 ? '+' : ''}${bt.profit_pct}% · PF ${bt.profit_factor} · ${bt.trades} trades · ${bt.win_pct}% win · Sharpe ${bt.sharpe}</span>`;
    }
    return `<details class="settings-group prompt-item" style="max-width:820px;">
      <summary><span class="prompt-title">${esc(d.name)}</span>
        <span class="prompt-badge" style="background:rgba(108,99,255,.14);color:${stCol};">${esc(d.status)}</span>
        <span style="font-size:.7rem;color:var(--muted);margin-left:6px;">${esc(d.created_at || '')}</span></summary>
      <div class="prompt-help">Goal: ${esc(d.goal || '')}</div>
      <div style="margin:6px 0 2px;">${btHtml}</div>
      <div id="cy-draft-code-${d.id}" style="display:none;"></div>
      <div class="prompt-actions">
        <button class="btn-sm" onclick="cryptoDraftCode(${d.id})">&#128065; Code preview</button>
        ${d.status !== 'rejected' ? `<button class="btn-sm" id="cy-bt-${d.id}" onclick="cryptoBacktest(${d.id})">&#129514; Backtest</button>` : ''}
        ${d.status === 'proposed' ? `
          <button class="btn-sm success" onclick="cryptoStratAction(${d.id},'approve')" title="Requires a passing backtest">&#10003; Approve &rarr; strategies/</button>
          <button class="btn-sm danger" onclick="cryptoStratAction(${d.id},'reject')">&#10005; Reject</button>` : ''}
      </div>
    </details>`;
  };

  pane.innerHTML = `
    <div class="section-header">
      <div><div class="section-title">&#129302; Trading — FreqTrade</div>
        <div class="section-sub">A real trading bot in paper mode. <b>Live trading stays off until you flip it in the freqtrade config yourself</b> — nothing in this tab can enable real money.</div></div>
      <button class="btn-sm" onclick="_cryptoLoaded.trading=false;cryptoSub('trading')">&#8635; Refresh</button>
    </div>
    ${krakenCard}
    ${statusCard}
    <div class="settings-group" style="max-width:820px;margin-bottom:16px;">
      <div class="settings-group-title">&#129504; Agent strategy writer</div>
      <div style="font-size:.76rem;color:var(--muted);margin-bottom:10px;">
        Describe a goal; the local LLM drafts a complete freqtrade IStrategy into
        <code>strategies_drafts/</code>. Drafts NEVER run — you review the code and Approve
        to move it into <code>strategies/</code> (still dry-run until freqtrade's own config says otherwise).
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
        <input type="text" id="cy-strat-goal" placeholder="e.g. slow-and-steady BTC/USDT swing strategy using RSI dips" style="flex:1;min-width:260px;"
          title="Plain-English goal for the strategy. Fed to the local LLM which writes a complete IStrategy draft for human review.">
        <button class="btn-sm primary" id="cy-strat-btn" onclick="cryptoProposeStrategy()">&#129504; Agent: write strategy</button>
      </div>
    </div>
    <div class="settings-group" style="max-width:820px;margin-bottom:16px;border-color:var(--accent);">
      <div class="settings-group-title">&#127937; Autonomous strategy hunt</div>
      <div style="font-size:.76rem;color:var(--muted);margin-bottom:10px;">
        The agent writes a batch of diverse strategies, <b>backtests each on ~180 days of real history</b>,
        and ranks them below. Only proven winners rise to the top — you approve the best. No money moves.
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
        <label style="font-size:.76rem;color:var(--muted);">How many:
          <input type="number" id="cy-hunt-n" min="1" max="12" value="5" style="width:64px;margin-left:4px;"></label>
        <button class="btn-sm primary" id="cy-hunt-btn" onclick="cryptoStartHunt()">&#127937; Start hunt</button>
        <span style="font-size:.7rem;color:var(--muted);">~30–60s per strategy (generate + backtest)</span>
      </div>
      <div id="cy-hunt-status" style="margin-top:10px;"></div>
    </div>
    <div id="cy-leaderboard"></div>
    <div class="section-header"><div><div class="section-title">Strategy drafts</div>
      <div class="section-sub">${(s.drafts || []).length} drafts · active in strategies/: ${(s.active || []).map(a => `<code style="margin-right:5px;">${esc(a)}</code>`).join('') || 'none'}</div></div></div>
    <div id="cy-drafts">${(s.drafts || []).map(draftCard).join('') || '<div class="empty" style="padding:24px;"><div class="empty-icon">&#129504;</div>No drafts yet — ask the agent to write one above.</div>'}</div>`;
  cryptoLoadLeaderboard();
  if (_cyHuntPoll) cryptoPollHunt();   // resume the live progress view if a hunt is running
}
window.cryptoLoadTrading = cryptoLoadTrading;

let _cyHuntPoll = null;

async function cryptoStartHunt() {
  const n = parseInt(document.getElementById('cy-hunt-n').value, 10) || 5;
  const btn = document.getElementById('cy-hunt-btn');
  try {
    await api('/api/crypto/trading/hunt', { method: 'POST', body: JSON.stringify({ count: n }) });
    toast(`Hunt started — generating & backtesting ${n} strategies`);
  } catch (e) { toast(e.message, 'error'); return; }
  if (btn) btn.disabled = true;
  cryptoPollHunt();
}
window.cryptoStartHunt = cryptoStartHunt;

async function cryptoPollHunt() {
  let st;
  try { st = await api('/api/crypto/trading/hunt/status'); } catch { return; }
  const box = document.getElementById('cy-hunt-status');
  const btn = document.getElementById('cy-hunt-btn');
  if (box) {
    const pct = st.target ? Math.round((st.done / st.target) * 100) : 0;
    box.innerHTML = `
      <div style="font-size:.78rem;margin-bottom:6px;">
        ${st.running ? '⏳' : '✅'} ${st.done}/${st.target} done · <b style="color:var(--green);">${st.passers} passed</b>
        <div style="height:6px;background:var(--surface);border-radius:4px;margin-top:5px;overflow:hidden;">
          <div style="height:100%;width:${pct}%;background:linear-gradient(90deg,var(--accent),var(--accent2));"></div></div>
      </div>
      <pre style="font-size:.68rem;color:var(--muted);background:var(--surface);border-radius:6px;padding:8px 10px;max-height:150px;overflow:auto;white-space:pre-wrap;margin:0;">${esc((st.log || []).slice(-12).join('\n'))}</pre>`;
  }
  if (st.running) {
    if (btn) btn.disabled = true;
    _cyHuntPoll = setTimeout(cryptoPollHunt, 3000);
  } else {
    _cyHuntPoll = null;
    if (btn) btn.disabled = false;
    cryptoLoadLeaderboard();
    _cryptoLoaded.trading = false;   // drafts list is stale
  }
}
window.cryptoPollHunt = cryptoPollHunt;

async function cryptoLoadLeaderboard() {
  const el = document.getElementById('cy-leaderboard');
  if (!el) return;
  let d;
  try { d = await api('/api/crypto/trading/leaderboard'); } catch { el.innerHTML = ''; return; }
  const lb = d.leaderboard || [];
  if (!lb.length) { el.innerHTML = ''; return; }
  const medal = (i) => ['🥇', '🥈', '🥉'][i] || `#${i + 1}`;
  el.innerHTML = `
    <div class="section-header"><div><div class="section-title">&#127942; Leaderboard</div>
      <div class="section-sub">Backtested strategies, best first. Green = passed the profitability gate.</div></div></div>
    <div class="settings-group" style="max-width:820px;margin-bottom:16px;overflow-x:auto;">
      <table style="width:100%;border-collapse:collapse;font-size:.76rem;">
        <thead><tr style="text-align:left;color:var(--muted);font-size:.66rem;text-transform:uppercase;">
          <th style="padding:5px 8px;">#</th><th style="padding:5px 8px;">Strategy</th>
          <th style="padding:5px 8px;">Profit</th><th style="padding:5px 8px;">PF</th>
          <th style="padding:5px 8px;">Win%</th><th style="padding:5px 8px;">Sharpe</th>
          <th style="padding:5px 8px;">Trades</th><th style="padding:5px 8px;"></th></tr></thead>
        <tbody>${lb.map((x, i) => {
          const m = x.metrics || {};
          const col = x.passed ? 'var(--green)' : 'var(--red)';
          return `<tr style="border-top:1px solid var(--border);">
            <td style="padding:5px 8px;">${medal(i)}</td>
            <td style="padding:5px 8px;font-weight:600;">${esc(x.name)}
              ${x.status === 'approved' ? '<span style="font-size:.6rem;color:var(--green);">✓ live</span>' : ''}</td>
            <td style="padding:5px 8px;color:${col};font-weight:700;">${(x.profit_pct > 0 ? '+' : '')}${x.profit_pct}%</td>
            <td style="padding:5px 8px;">${x.profit_factor}</td>
            <td style="padding:5px 8px;color:var(--muted);">${m.win_pct != null ? m.win_pct + '%' : '—'}</td>
            <td style="padding:5px 8px;color:var(--muted);">${x.sharpe}</td>
            <td style="padding:5px 8px;color:var(--muted);">${m.trades ?? '—'}</td>
            <td style="padding:5px 8px;">${x.passed && x.status === 'proposed'
              ? `<button class="btn-sm success" onclick="cryptoStratAction(${x.id},'approve')">✓ Approve</button>` : ''}</td>
          </tr>`;
        }).join('')}</tbody></table></div>`;
}
window.cryptoLoadLeaderboard = cryptoLoadLeaderboard;

async function cryptoDraftCode(id) {
  const box = document.getElementById('cy-draft-code-' + id);
  if (!box) return;
  if (box.style.display === 'block') { box.style.display = 'none'; return; }
  box.style.display = 'block';
  box.innerHTML = '<div style="color:var(--muted);font-size:.78rem;">Loading code…</div>';
  try {
    const d = await api('/api/crypto/trading/strategy/' + id);
    box.innerHTML = `<pre style="background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:12px;font-size:.72rem;line-height:1.5;overflow-x:auto;max-height:420px;overflow-y:auto;white-space:pre;">${esc(d.code || '(no code stored)')}</pre>`;
  } catch (e) { box.innerHTML = `<div style="color:var(--red);font-size:.78rem;">${esc(e.message)}</div>`; }
}
window.cryptoDraftCode = cryptoDraftCode;

async function cryptoProposeStrategy() {
  const goal = document.getElementById('cy-strat-goal').value.trim();
  if (!goal) { toast('Describe the strategy goal first', 'error'); return; }
  const btn = document.getElementById('cy-strat-btn'); const orig = btn.innerHTML;
  btn.disabled = true; btn.innerHTML = '&#9203; Writing… (local LLM, can take a while)';
  try {
    const { task_id } = await api('/api/crypto/trading/strategy/propose', {
      method: 'POST', body: JSON.stringify({ goal }) });
    const r = await pollTask(task_id, 150);
    toast(`Draft "${r.name}" saved to strategies_drafts/ — review & approve`);
    _cryptoLoaded.trading = false;
    cryptoSub('trading');
    return;
  } catch (e) { toast('Strategy draft failed: ' + e.message, 'error'); }
  btn.disabled = false; btn.innerHTML = orig;
}
window.cryptoProposeStrategy = cryptoProposeStrategy;

async function cryptoKrakenSave() {
  const key = document.getElementById('cy-kraken-key').value.trim();
  const secret = document.getElementById('cy-kraken-secret').value.trim();
  if (!key || !secret) { toast('Enter both the API key and private key', 'error'); return; }
  try {
    await api('/api/crypto/settings', { method: 'POST', body: JSON.stringify({ kraken_api_key: key, kraken_api_secret: secret }) });
    toast('Kraken connected — loading balances…');
  } catch (e) { toast('Error: ' + e.message, 'error'); return; }
  _cryptoLoaded.trading = false; cryptoSub('trading');
}
window.cryptoKrakenSave = cryptoKrakenSave;

async function cryptoKrakenForget() {
  try { await api('/api/crypto/settings', { method: 'POST', body: JSON.stringify({ kraken_api_key: '', kraken_api_secret: '' }) }); }
  catch (e) { toast('Error: ' + e.message, 'error'); return; }
  _cryptoLoaded.trading = false; cryptoSub('trading');
}
window.cryptoKrakenForget = cryptoKrakenForget;

async function cryptoKrakenSyncFt() {
  if (!confirm('Copy your Kraken API keys into the FreqTrade bot?\n\nThe bot STAYS in paper mode (dry-run) — this just lets it read your real account. Going live is a separate manual step.')) return;
  try {
    const r = await api('/api/crypto/kraken/sync-freqtrade', { method: 'POST', body: JSON.stringify({}) });
    toast(r.restarted ? 'Synced to FreqTrade (still paper) ✓' : 'Config updated', 'success');
  } catch (e) { toast('Error: ' + e.message, 'error'); }
  _cryptoLoaded.trading = false; cryptoSub('trading');
}
window.cryptoKrakenSyncFt = cryptoKrakenSyncFt;

async function cryptoBacktest(id) {
  const btn = document.getElementById('cy-bt-' + id);
  if (btn) { btn.disabled = true; btn.innerHTML = '⏳ Backtesting…'; }
  try {
    const r = await api(`/api/crypto/trading/strategy/${id}/backtest`, { method: 'POST', body: JSON.stringify({}) });
    const m = r.metrics;
    toast(`${r.passed ? '✓ PASSED' : '✗ FAILED'} — ${m.profit_pct > 0 ? '+' : ''}${m.profit_pct}% over 180d, PF ${m.profit_factor}`,
          r.passed ? 'success' : 'error');
  } catch (e) { toast('Backtest failed: ' + e.message, 'error'); }
  _cryptoLoaded.trading = false;
  cryptoSub('trading');
}
window.cryptoBacktest = cryptoBacktest;

async function cryptoStratAction(id, action) {
  if (action === 'approve' && !confirm('Move this draft into the LIVE strategies/ folder? (FreqTrade still only uses it if selected in its config, and stays dry-run.)')) return;
  try {
    await api(`/api/crypto/trading/strategy/${id}/${action}`, { method: 'POST', body: JSON.stringify({}) });
    toast(action === 'approve' ? '✅ Approved → strategies/' : 'Rejected');
  } catch (e) {
    // approve gate: offer force-override on a failing/absent backtest
    if (action === 'approve' && /backtest/i.test(e.message)) {
      if (confirm(e.message + '\n\nApprove anyway (override the backtest gate)?')) {
        try {
          await api(`/api/crypto/trading/strategy/${id}/approve`, { method: 'POST', body: JSON.stringify({ force: true }) });
          toast('✅ Approved (gate overridden) → strategies/');
        } catch (e2) { toast('Error: ' + e2.message, 'error'); }
      }
    } else { toast('Error: ' + e.message, 'error'); }
  }
  _cryptoLoaded.trading = false;
  cryptoSub('trading');
}
window.cryptoStratAction = cryptoStratAction;

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
