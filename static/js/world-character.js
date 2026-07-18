/* ══ THE COMPANY — character sheets ══
   Full per-agent sheet modal (richer than the side detail panel). Reads _worldState.
   Uses _worldModal (world-economy.js) + _needBar (world-ui.js). Global-scope classic script. */

function worldSheet(id) {
  const a = (_worldState?.agents || []).find(x => x.id === id);
  if (!a) { toast?.('Agent not found'); return; }
  const depts = _worldState.departments || [];
  const dept = depts.find(d => d.key === a.dept);
  const nextXp = Math.ceil(Math.pow((a.level) / 3, 2) * 120);
  const pct = Math.max(4, Math.min(100, Math.round((a.xp / Math.max(1, nextXp)) * 100)));
  let owned = []; try { owned = JSON.parse(a.upgrades || '[]'); } catch {}
  const bars = [['Energy', a.energy], ['Food', a.hunger], ['Fun', a.fun], ['Social', a.social], ['Purpose', a.fulfillment]]
    .map(([l, v]) => _needBar(l, v)).join('');
  const mult = a.earn_mult || 1;

  const html = `
    <div style="display:flex;gap:14px;margin-bottom:14px;align-items:center">
      <div style="width:64px;height:64px;border-radius:12px;background:${esc(a.color || '#8ab')};display:flex;align-items:center;justify-content:center;font-size:2rem;flex-shrink:0">${esc(a.mood_emoji || '🙂')}</div>
      <div style="min-width:0">
        <div style="font-size:1.2rem;font-weight:800;color:#e8eefc">${esc(a.name)} <span class="pill">L${a.level}</span></div>
        <div style="color:#aeb9cc;font-size:.86rem">${esc(dept ? dept.label : a.dept)}${a.job_class ? ' · ' + esc(a.job_class) : ''}${a.kind === 'openclaw' ? ' · <span style="color:#f472b6">real agent</span>' : ''}</div>
        <div style="color:#7a86a0;font-size:.78rem;margin-top:2px;text-transform:capitalize">${esc(a.mood_label || a.state)}${a.goal ? ` · 🚶 ${esc(a.goal)}` : ''}</div>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
      <div>
        <div style="font-weight:600;color:#e8eefc;font-size:.82rem;margin-bottom:4px">Needs</div>${bars}
        <div style="margin-top:10px;font-weight:600;color:#e8eefc;font-size:.82rem">Progress</div>
        <div style="font-size:.78rem;color:#aeb9cc;margin:2px 0">XP ${a.xp} / ${nextXp} · Jobs done <b>${a.jobs_done || 0}</b></div>
        <div style="height:8px;background:#0b1120;border-radius:4px;overflow:hidden"><div style="height:100%;width:${pct}%;background:${esc(a.color || '#7dd3fc')}"></div></div>
      </div>
      <div>
        <div style="font-weight:600;color:#e8eefc;font-size:.82rem;margin-bottom:4px">Economy</div>
        <div style="font-size:.9rem;color:#fcd34d;font-weight:700">🪙 ${a.coins || 0} <span style="color:#54607a;font-weight:400;font-size:.72rem">earned ${a.coins_earned || 0}</span></div>
        ${(a.debt || 0) > 0 ? `<div style="color:#f87171;font-size:.78rem;margin-top:2px">💸 owes ${a.debt}</div>` : ''}
        ${mult > 1 ? `<div style="color:#6ee7a8;font-size:.76rem;margin-top:2px">▲ +${Math.round((mult - 1) * 100)}% earnings</div>` : ''}
        <div style="margin-top:10px;font-weight:600;color:#e8eefc;font-size:.82rem">Owned upgrades</div>
        <div style="font-size:.76rem;color:#9fb0c9;line-height:1.6">${owned.length ? owned.map(esc).join(', ') : '—'}</div>
      </div>
    </div>
    ${a.mood ? `<div style="margin-top:14px;padding:8px 10px;background:#0e1626;border-radius:8px;color:#dfe7f5;font-style:italic">💭 ${esc(a.mood)}</div>` : ''}
    <div style="display:flex;gap:6px;margin-top:14px;flex-wrap:wrap">
      <button class="btn" style="padding:6px 10px;font-size:.76rem" onclick="worldLog(${a.id})">📔 Journal</button>
      <button class="btn" style="padding:6px 10px;font-size:.76rem" onclick="worldThink(${a.id})">💭 Provoke thought</button>
      <button class="btn" style="padding:6px 10px;font-size:.76rem" onclick="worldRename(${a.id})">✏️ Rename</button>
    </div>`;
  _worldModal(`📋 ${a.name} — Character Sheet`, html);
}
window.worldSheet = worldSheet;
