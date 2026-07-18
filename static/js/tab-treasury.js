'use strict';
/* ══ THE COMPANY — Treasury (the national reserve) ══
   The seat of the economy: the company's "gold" (real $ via the world_ops
   ledger), PayPal management, the full transaction history, spend cap, and
   survival health. This is where all the money lives — the God Console just
   shows a slice of it. Classic global-scope script; renders into #main-content. */

function fmtUSD(c) { return '$' + ((c || 0) / 100).toFixed(2); }

function _health(s) {
  const bal = s.balance_cents || 0, cap = s.cap_cents || 0;
  if (bal >= cap && cap > 0) return { t: '🟢 Thriving', c: '#6ee7a8', d: 'The reserve is strong. Invest in growth.' };
  if (bal >= 0) return { t: '🟢 Stable', c: '#6ee7a8', d: 'The nation holds. Keep earning.' };
  if (-bal < cap) return { t: '🟡 Strained', c: '#f59e0b', d: 'Running a deficit — settle the bill or earn more.' };
  return { t: '🔴 Crisis', c: '#f87171', d: 'The treasury is breached. Collapse looms if the debt grows.' };
}

const _LED_ICON = { fund: '💵', revenue: '📈', spend: '🛍️', payment: '✅', payout: '💸' };

async function renderTreasury() {
  const el = document.getElementById('main-content');
  el.innerHTML = '<div style="padding:24px;color:#64748b">Loading the treasury…</div>';
  let s, led;
  try {
    [s, led] = await Promise.all([
      api('/api/world/ops/summary'),
      api('/api/world/ops/ledger?limit=200'),
    ]);
  } catch (e) { el.innerHTML = '<div style="padding:24px;color:#f87171">Treasury failed to load.</div>'; return; }

  const h = _health(s);
  const owed = s.owed_cents || 0;
  const tot = led.totals || {};
  const earned = (tot.revenue || 0) + (tot.fund || 0);
  const spent = -(tot.spend || 0);
  const paidOut = -(tot.payout || 0);
  const pp = s.paypal || {};

  const stat = (label, val, color, sub) => `
    <div style="background:var(--surface,#161a22);border:1px solid var(--border,#2a2f3d);border-radius:12px;padding:14px 16px">
      <div style="font-size:.68rem;color:#7a86a0;text-transform:uppercase;letter-spacing:.05em">${label}</div>
      <div style="font-size:1.5rem;font-weight:800;color:${color || '#e8eefc'};margin-top:2px">${val}</div>
      ${sub ? `<div style="font-size:.68rem;color:#54607a;margin-top:2px">${sub}</div>` : ''}</div>`;

  const rows = (led.ledger || []).map(r => {
    const cr = r.amount_cents >= 0;
    return `<tr style="border-top:1px solid #1b2740">
      <td style="padding:5px 8px;color:#7a86a0;white-space:nowrap">${(r.created_at || '').slice(0, 16)}</td>
      <td style="padding:5px 8px">${_LED_ICON[r.kind] || '·'} ${esc(r.kind)}</td>
      <td style="padding:5px 8px;color:#8a97ad">${esc(r.source || '')}</td>
      <td style="padding:5px 8px;color:#aeb9cc">${esc(r.note || '')}</td>
      <td style="padding:5px 8px;text-align:right;font-weight:700;color:${cr ? '#6ee7a8' : '#f87171'}">${cr ? '+' : '−'}${fmtUSD(Math.abs(r.amount_cents))}</td></tr>`;
  }).join('') || '<tr><td colspan="5" style="padding:12px;color:#54607a">No transactions yet.</td></tr>';

  el.innerHTML = `
  <div class="section-header">
    <div><div class="section-title">🏦 National Treasury</div>
      <div class="section-sub">The company's gold reserve — every real dollar in, out, and owed.</div></div>
    <button class="btn-sm" onclick="renderTreasury()">↻ Refresh</button>
    <button class="btn-sm" onclick="treasurySyncRevenue()" title="Pull real Etsy sales into the Treasury as revenue right now (also runs automatically every ~15 min). Deduped — safe to click repeatedly.">💰 Sync sales</button>
  </div>

  <div style="display:flex;gap:16px;flex-wrap:wrap;align-items:stretch;margin-bottom:20px">
    <div style="flex:1 1 300px;background:linear-gradient(135deg,#1a1f2e,#0f1626);border:1px solid #2a3752;border-radius:14px;padding:20px">
      <div style="font-size:.72rem;color:#7a86a0;text-transform:uppercase;letter-spacing:.06em">Gold reserve</div>
      <div style="font-size:2.6rem;font-weight:900;color:${(s.balance_cents||0)>=0?'#fcd34d':'#f87171'};line-height:1.1">${fmtUSD(s.balance_cents)}</div>
      <div style="display:inline-block;margin-top:8px;padding:3px 12px;border-radius:20px;background:#0e1626;border:1px solid ${h.c}55;color:${h.c};font-weight:700;font-size:.82rem">${h.t}</div>
      <div style="font-size:.74rem;color:#8a97ad;margin-top:6px">${h.d}</div>
    </div>
    <div style="flex:2 1 380px;display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px">
      ${stat('Bill owed', owed ? fmtUSD(owed) : '$0.00', owed ? '#f87171' : '#6ee7a8', owed ? 'settle via PayPal' : 'nothing due')}
      ${stat('Spent this month', fmtUSD(s.cycle_spend_cents), '#e8eefc', `of ${fmtUSD(s.cap_cents)} cap`)}
      ${stat('All-time earned', fmtUSD(earned), '#6ee7a8', 'revenue + funding')}
      ${stat('All-time spent', fmtUSD(spent), '#fbbf24', 'Etsy/Printify fees')}
      ${stat('Paid out to you', fmtUSD(paidOut), '#7dd3fc', 'PayPal withdrawals')}
      ${stat('Automation', s.mode === 'budget' ? '💸 Auto' : '🙏 Review', '#c4b5fd', s.pending_prayers ? `${s.pending_prayers} prayers pending` : 'up to date')}
    </div>
  </div>

  <div style="display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start">
    <div style="flex:1 1 420px;min-width:320px">
      <div style="background:var(--surface,#161a22);border:1px solid var(--border,#2a2f3d);border-radius:12px;padding:16px;margin-bottom:16px">
        <div style="font-weight:700;margin-bottom:10px">💰 Move money</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
          <input id="tr-amt" type="number" step="0.01" placeholder="$ amount" title="Dollar amount for the money buttons on this row. Type it first, then click an action." style="width:120px;padding:7px 10px;background:#0b1120;border:1px solid #26324a;border-radius:8px;color:#e8eefc">
          <button class="btn-sm" onclick="treasuryMoney('revenue','cults3d')" title="Record Cults3D sales income into the Treasury as revenue (raises the gold reserve). Type the amount first.">+ Cults3D earnings</button>
          <button class="btn-sm" onclick="treasuryMoney('revenue','store')" title="Record a store sale into the Treasury as revenue (raises the gold reserve). Type the amount first.">+ Store sale</button>
          <button class="btn-sm" onclick="treasuryMoney('fund','manual')" title="Manually add cash to the Treasury (seed funding). Raises the gold reserve. Type the amount first.">+ Add funds</button>
          ${owed ? `<button class="btn-sm" onclick="treasuryMoney('payment','paypal')" title="Settle the outstanding Etsy/Printify bill from your PayPal. Clears the amount owed.">✅ Pay Etsy bill (${fmtUSD(owed)})</button>` : ''}
          ${(s.balance_cents||0) > 0 ? `<button class="btn-sm primary" onclick="treasuryWithdraw(${s.balance_cents})" title="Send Treasury cash to your PayPal payout email. Files a payout prayer that only sends after you approve it in the God Console.">💸 Withdraw to PayPal</button>` : ''}
        </div>
        <div style="font-size:.7rem;color:#54607a;margin-top:8px">Monthly Etsy/Printify cap: ${hlp('The most the autonomous world may spend on Etsy/Printify listings per month. In Auto (budget) mode, spends over this cap wait for your approval in the God Console instead of running automatically.')}
          <button class="btn-sm" style="padding:2px 8px" onclick="treasurySetCap()" title="Change the monthly Etsy/Printify spend cap.">${fmtUSD(s.cap_cents)}/mo</button>
          · WordPress &amp; Cults3D publishing are free — only Etsy/Printify draw the reserve.</div>
      </div>

      <div style="background:var(--surface,#161a22);border:1px solid var(--border,#2a2f3d);border-radius:12px;padding:16px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
          <div style="font-weight:700">🅿️ PayPal</div>
          <div style="font-size:.76rem;color:${pp.configured ? '#6ee7a8' : '#f59e0b'}">${pp.configured ? `connected · ${esc(pp.mode)}` : 'not configured'}</div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
          <label style="font-size:.7rem;color:#7a86a0">Mode ${hlp('Sandbox uses fake PayPal test money for safe testing; Live moves real money. The keys below must match the mode you pick.')}
            <select id="tr-pp-mode" style="width:100%;margin-top:3px;padding:6px 8px;background:#0b1120;border:1px solid #26324a;border-radius:8px;color:#e8eefc">
              <option value="sandbox" ${pp.mode==='sandbox'?'selected':''}>Sandbox (test money)</option>
              <option value="live" ${pp.mode==='live'?'selected':''}>Live (real money)</option></select></label>
          <label style="font-size:.7rem;color:#7a86a0">Payout email (where earnings land) ${hlp('The PayPal address that receives withdrawals and payouts. Use your real PayPal email.')}
            <input id="tr-pp-email" value="${esc(pp.email||'')}" placeholder="you@email.com" style="width:100%;margin-top:3px;padding:6px 8px;background:#0b1120;border:1px solid #26324a;border-radius:8px;color:#e8eefc"></label>
          <label style="font-size:.7rem;color:#7a86a0">Client ID <span style="color:#54607a">(blank = keep)</span> ${hlp('PayPal REST app Client ID used to connect. Leave blank to keep the saved one. Must belong to the same Sandbox/Live mode selected above.')}
            <input id="tr-pp-cid" type="password" placeholder="••••••" style="width:100%;margin-top:3px;padding:6px 8px;background:#0b1120;border:1px solid #26324a;border-radius:8px;color:#e8eefc"></label>
          <label style="font-size:.7rem;color:#7a86a0">Secret <span style="color:#54607a">(blank = keep)</span> ${hlp('PayPal REST app Secret paired with the Client ID. Leave blank to keep the saved one. Stored server-side, never shown back.')}
            <input id="tr-pp-secret" type="password" placeholder="••••••" style="width:100%;margin-top:3px;padding:6px 8px;background:#0b1120;border:1px solid #26324a;border-radius:8px;color:#e8eefc"></label>
        </div>
        <div style="display:flex;gap:8px;margin-top:10px">
          <button class="btn-sm primary" onclick="treasuryPaypalSave()">💾 Save</button>
          <button class="btn-sm" onclick="treasuryVerify()" title="Test the saved PayPal keys and report whether they connect in the current Sandbox/Live mode. No money moves.">🔌 Verify connection</button>
        </div>
        <div style="font-size:.68rem;color:#54607a;margin-top:8px">Sandbox = safe testing with fake money. Switch to Live + paste Live app keys when you're ready for real payouts.</div>
      </div>
    </div>

    <div style="flex:1 1 460px;min-width:320px">
      <div style="background:var(--surface,#161a22);border:1px solid var(--border,#2a2f3d);border-radius:12px;padding:16px">
        <div style="font-weight:700;margin-bottom:10px">🧾 Transaction ledger</div>
        <div style="overflow-x:auto;max-height:520px;overflow-y:auto">
          <table style="width:100%;font-size:.76rem;border-collapse:collapse;color:#c7d2e5">
            <thead><tr style="color:#7a86a0;text-align:left;position:sticky;top:0;background:var(--surface,#161a22)">
              <th style="padding:5px 8px;font-weight:600">When</th><th style="padding:5px 8px;font-weight:600">Type</th>
              <th style="padding:5px 8px;font-weight:600">Source</th><th style="padding:5px 8px;font-weight:600">Note</th>
              <th style="padding:5px 8px;font-weight:600;text-align:right">Amount</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </div>
    </div>
  </div>`;
}

async function treasurySyncRevenue() {
  try {
    const r = await api('/api/world/ops/sync-revenue', { method: 'POST', body: JSON.stringify({}) });
    if (r.reason === 'disabled') toast?.('Sales sync is turned off');
    else toast?.(r.added ? `💰 ${r.added} sale(s) synced — +$${((r.revenue_cents||0)/100).toFixed(2)}` : 'No new sales since last sync');
  } catch (e) { toast?.(e?.message || 'Sync failed'); }
  renderTreasury();
}

/* ── actions (refresh the tab, not a modal) ── */
async function treasuryMoney(kind, source) {
  const amt = parseFloat(document.getElementById('tr-amt')?.value || '0');
  if (!amt || amt <= 0) { toast?.('Enter an amount'); return; }
  try {
    await api('/api/world/ops/budget/entry', { method: 'POST', body: JSON.stringify({ kind, source, amount_dollars: amt }) });
    toast?.('Recorded');
  } catch (e) { toast?.(e?.message || 'Failed'); }
  renderTreasury();
}
async function treasuryWithdraw(maxCents) {
  const v = prompt(`Withdraw how much to your PayPal? (max $${(maxCents / 100).toFixed(2)})`, (maxCents / 100).toFixed(2));
  if (v == null) return;
  const dollars = parseFloat(v);
  if (!dollars || dollars <= 0) { toast?.('Enter an amount'); return; }
  try {
    await api('/api/world/ops/paypal/withdraw', { method: 'POST', body: JSON.stringify({ amount_dollars: dollars }) });
    toast?.('🙏 Payout queued — bless it in the God Console to send it');
  } catch (e) { toast?.(e?.message || 'Withdraw failed'); }
  renderTreasury();
}
async function treasurySetCap() {
  const v = prompt('Monthly Etsy/Printify spend cap in dollars:');
  if (v == null) return;
  try { await api('/api/world/ops/config', { method: 'POST', body: JSON.stringify({ cap_dollars: parseFloat(v) || 0 }) }); }
  catch (e) { toast?.('Failed'); }
  renderTreasury();
}
async function treasuryPaypalSave() {
  const body = {
    mode: document.getElementById('tr-pp-mode')?.value,
    email: document.getElementById('tr-pp-email')?.value || '',
  };
  const cid = document.getElementById('tr-pp-cid')?.value;
  const sec = document.getElementById('tr-pp-secret')?.value;
  if (cid) body.client_id = cid;
  if (sec) body.secret = sec;
  try { await api('/api/world/ops/paypal/config', { method: 'POST', body: JSON.stringify(body) }); toast?.('PayPal saved'); }
  catch (e) { toast?.('Failed'); }
  renderTreasury();
}
async function treasuryVerify() {
  toast?.('Checking PayPal…');
  try {
    const r = await api('/api/world/ops/paypal/verify', { method: 'POST', body: JSON.stringify({}) });
    toast?.(r.connected ? `✓ Connected (${r.mode})` : `✕ ${r.error || 'not connected'}`);
  } catch (e) { toast?.('Verify failed'); }
}

window.renderTreasury = renderTreasury;
window.treasuryMoney = treasuryMoney;
window.treasuryWithdraw = treasuryWithdraw;
window.treasurySetCap = treasurySetCap;
window.treasuryPaypalSave = treasuryPaypalSave;
window.treasuryVerify = treasuryVerify;
