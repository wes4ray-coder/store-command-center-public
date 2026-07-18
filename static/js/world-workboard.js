/* ══ THE COMPANY — Workboard ══
   The whole pipeline in one place: the national plan, what awaits your blessing,
   what's in motion, and what's done. Ties the Republic + prayers + creations
   together. Reuses _PRAYER_ICON/_money (world-god.js) + _worldModal + api(). */

const _WB_ICON = {
  publish_wordpress: '🌐', post_etsy: '🛍️', post_printify: '👕', publish_cults3d: '🧊', paypal_payout: '💸',
  generate_image: '🖼️', add_affiliate: '🔗', add_software: '💾', library_research: '📖', misc: '✨',
};
function _wbMoney(c) { return '$' + ((c || 0) / 100).toFixed(2); }

async function worldWorkboard() {
  let d;
  try { d = await api('/api/world/ops/workboard'); }
  catch (e) { toast?.('Workboard failed to load'); return; }
  _renderWorkboard(d);
}

function _wbPrayer(p, withActions) {
  const icon = _WB_ICON[p.kind] || '✨';
  const cost = p.cost_cents ? ` · <span style="color:#fcd34d">${_wbMoney(p.cost_cents)}</span>` : '';
  const stat = { done: '#6ee7a8', approved: '#6ee7a8', failed: '#f87171', rejected: '#7a86a0' }[p.status];
  return `<div style="border:1px solid #26324a;border-radius:8px;padding:7px 9px;margin-bottom:6px;background:#0e1626">
    <div style="display:flex;justify-content:space-between;align-items:center;gap:6px">
      <div style="min-width:0;font-size:.78rem"><span>${icon}</span> <b style="color:#e8eefc">${esc(p.title)}</b>${cost}</div>
      ${stat ? `<span style="font-size:.64rem;color:${stat};flex-shrink:0">${esc(p.status)}</span>` : ''}
    </div>
    ${p.agent_name ? `<div style="font-size:.66rem;color:#7a86a0;margin-top:2px">${esc(p.agent_name)}</div>` : ''}
    ${p.taste != null ? `<div style="font-size:.62rem;color:#7a86a0;margin-top:2px" title="${esc(p.endorse_note || '')}">
      🎯 ${Math.round(p.taste * 100)}% · 💼 ${p.boss_ok ? '👍' : '👎'} · 🏛️ ${p.mayor_ok ? '👍' : '👎'}</div>` : ''}
    ${withActions ? `<div style="display:flex;gap:5px;margin-top:6px">
      <button class="btn" style="padding:2px 9px;font-size:.68rem;background:#1f4a32;border-color:#2a5a3a" onclick="wbBless(${p.id})">✓ Bless</button>
      <button class="btn" style="padding:2px 9px;font-size:.68rem;border-color:#5a2a2a" onclick="wbDeny(${p.id})">✕ Deny</button>
    </div>` : ''}
  </div>`;
}

function _renderWorkboard(d) {
  const rep = d.republic || {}, auto = d.auto || {};
  const pending = d.pending || [], done = d.done || [];
  const plan = rep.current_plan;
  const standing = rep.standing ?? 50;
  const sc = standing >= 66 ? '#6ee7a8' : standing >= 33 ? '#f59e0b' : '#f87171';

  const header = `
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(90px,1fr));gap:8px;margin-bottom:12px">
      <div style="background:#0e1626;border:1px solid #26324a;border-radius:8px;padding:7px 9px">
        <div style="font-size:.6rem;color:#7a86a0">STANDING</div><div style="font-weight:700;color:${sc}">${standing}</div></div>
      <div style="background:#0e1626;border:1px solid #26324a;border-radius:8px;padding:7px 9px">
        <div style="font-size:.6rem;color:#7a86a0">FACING</div><div style="font-weight:700;font-size:.8rem">${esc((rep.threat_label || '—').replace(/^[^ ]+ /, ''))}</div></div>
      <div style="background:#0e1626;border:1px solid #26324a;border-radius:8px;padding:7px 9px">
        <div style="font-size:.6rem;color:#7a86a0">RESERVE</div><div style="font-weight:700;color:${(d.balance_cents||0)>=0?'#fcd34d':'#f87171'}">${_wbMoney(d.balance_cents)}</div></div>
      <div style="background:#0e1626;border:1px solid #26324a;border-radius:8px;padding:7px 9px">
        <div style="font-size:.6rem;color:#7a86a0">AWAITING YOU</div><div style="font-weight:700;color:${pending.length?'#fcd34d':'#6ee7a8'}">${pending.length}</div></div>
    </div>`;

  const planCard = plan ? `
    <div style="background:#101c14;border:1px solid #2a5a3a;border-radius:10px;padding:10px 12px;margin-bottom:12px">
      <div style="font-size:.62rem;color:#7a86a0;text-transform:uppercase;letter-spacing:.05em">📜 Current mandate</div>
      <div style="font-weight:700;color:#e8eefc">${esc(plan.title)}</div>
      <div style="font-size:.72rem;color:#aeb9cc;margin-top:2px">${esc(plan.why || '')}</div>
    </div>`
    : '<div style="color:#54607a;font-size:.78rem;margin-bottom:12px">No mandate yet — <a onclick="worldCloseModal();worldRepublic()" style="color:#a78bfa;cursor:pointer">convene the Republic</a>.</div>';

  const runningRow = auto.running
    ? '<div style="font-size:.76rem;color:#7dd3fc;padding:4px 0">⚙️ A creation is in progress on the GPU…</div>'
    : (auto.enabled ? `<div style="font-size:.74rem;color:#8a97ad;padding:4px 0">🤖 Automation on · ${auto.next_due_sec ? `next in ~${Math.round(auto.next_due_sec / 60)}m` : 'due now'}</div>`
      : '<div style="font-size:.72rem;color:#54607a;padding:4px 0">Automation paused.</div>');

  const col = (title, inner) => `<div style="flex:1 1 250px;min-width:220px">
    <div style="font-weight:700;color:#e8eefc;margin-bottom:6px;font-size:.85rem">${title}</div>${inner}</div>`;

  const todo = pending.length ? pending.map(p => _wbPrayer(p, true)).join('')
    : '<div style="color:#54607a;font-size:.76rem">Nothing awaits you. 🕊️</div>';
  const doneCol = done.length ? done.map(p => _wbPrayer(p, false)).join('')
    : '<div style="color:#54607a;font-size:.76rem">Nothing finished yet.</div>';

  const html = `${header}${planCard}
    <div style="display:flex;gap:14px;flex-wrap:wrap;align-items:flex-start">
      ${col(`📥 Awaiting you ${pending.length ? `<span class="pill">${pending.length}</span>` : ''}`, todo)}
      ${col('✅ Recently done', runningRow + doneCol)}
    </div>`;

  _worldModal('🗂️ Company Workboard', html);
}

async function wbBless(id) {
  try { await api(`/api/world/ops/prayers/${id}/approve`, { method: 'POST', body: JSON.stringify({}) }); toast?.('🙏 Blessed'); }
  catch (e) { toast?.(e?.message || 'Failed'); }
  worldWorkboard();
}
async function wbDeny(id) {
  const comment = prompt('Reason (optional):') || '';
  try { await api(`/api/world/ops/prayers/${id}/reject`, { method: 'POST', body: JSON.stringify({ comment }) }); toast?.('Denied'); }
  catch (e) { toast?.(e?.message || 'Failed'); }
  worldWorkboard();
}

window.worldWorkboard = worldWorkboard;
window.wbBless = wbBless;
window.wbDeny = wbDeny;
