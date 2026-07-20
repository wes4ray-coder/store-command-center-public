/* ══ CRYPTO & MARKETS TAB ══
   Sub-tabs (same pane-toggle mechanism as Settings — everything stays in the DOM,
   we only switch which pane is visible, and each pane lazy-loads once):
     📊 Stats   — top-20 coins + trending (CoinGecko)
     ⛓️ Nodes   — local Bitcoin Core regtest container + honest catalog of others
     ⛏️ Mining  — regtest block miner + Monero/xmrig placeholder + reality check
     🤖 Trading — FreqTrade (DRY-RUN) status + LLM strategy drafts w/ approve flow
     📈 Stocks  — Robinhood portfolio, yfinance watchlist, LLM daily brief
     🔑 Backups — private-key backup zip download */

const _CRYPTO_PANES = ['stats', 'jelly', 'pearl', 'nodes', 'mining', 'trading', 'stocks', 'backups'];
let _cryptoLoaded = {};       // pane -> true once its data has been fetched
let _cryptoDrafts = [];       // strategy drafts cache (for code preview)

async function renderCrypto() {
  // Lives inside the 💰 Finance tab (fin-pane-crypto). If the pane is gone the
  // user switched views — bail instead of clobbering whatever is on screen now.
  const _cyRoot = document.getElementById('fin-pane-crypto');
  if (!_cyRoot) return;
  _cryptoLoaded = {};
  _cyRoot.innerHTML = `
    <div class="view-header">
      <div class="view-title">&#8383; Crypto &amp; Markets</div>
      <div class="view-sub">Market data, paper-trading bot, real Monero mining &amp; your stock watchlist.
        Your real spendable coins live in the &#128092; Wallets tab. Nothing here auto-trades real money.</div>
    </div>
    <div class="subtab-bar" id="crypto-subtabs">
      <div class="subtab active" onclick="cryptoSub('stats')">&#128202; Stats</div>
      <div class="subtab" onclick="cryptoSub('jelly')">&#129724; JellyCoin</div>
      <div class="subtab" onclick="cryptoSub('pearl')">&#129714; Pearl</div>
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
    ({ stats: cryptoLoadStats, jelly: cryptoLoadJelly, pearl: cryptoLoadPearl, nodes: cryptoLoadNodes, mining: cryptoLoadMining,
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

/* shared status dot — used by Mining + Trading panes */
function _cyDot(running) {
  const col = running ? 'var(--green)' : 'var(--red)';
  return `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${col};box-shadow:0 0 6px ${col};margin-right:7px;"></span>`;
}
