/* ══ CRYPTO TAB — Trading pane: FreqTrade + Kraken + strategy hunt (split from tab-crypto.js) ══ */

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
