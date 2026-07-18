/* ══ THE COMPANY — The Republic / War Room ══
   The nation's strategy assembly: standing, the threat facing us, the adopted
   national plan, and the democratic vote that chose it. Convene to run a cycle
   (assess → propose → vote → adopt → act). Uses _worldModal + api()/esc()/toast().
   Global-scope classic script. */

const _RISK = { low: { c: '#6ee7a8', t: 'low risk' }, med: { c: '#f59e0b', t: 'med risk' }, high: { c: '#f87171', t: '☢️ risky' } };
const _CAT_ICON = { 'cost-cut': '🛡️', hustle: '💪', platform: '🌐', skill: '📚', tool: '🛠️', code: '💾', watch: '🔭' };

function _moneyR(c) { return '$' + ((c || 0) / 100).toFixed(2); }

async function worldRepublic() {
  let st;
  try { st = await api('/api/world/republic/state'); }
  catch (e) { toast?.('The Republic failed to load'); return; }
  _renderRepublic(st);
}

function _renderRepublic(st) {
  const standing = st.standing ?? 50;
  const sc = standing >= 66 ? '#6ee7a8' : standing >= 33 ? '#f59e0b' : '#f87171';
  const tr = st.treasury || {};
  const threatColor = st.threat === 'crisis' ? '#f87171' : st.threat === 'stagnation' ? '#f59e0b'
    : st.threat === 'deficit' ? '#fbbf24' : '#6ee7a8';

  // latest assembly = strategies from the highest cycle
  const recent = st.recent || [];
  const maxCycle = recent.reduce((m, s) => Math.max(m, s.cycle || 0), 0);
  const latest = recent.filter(s => s.cycle === maxCycle).sort((a, b) => (b.votes_for || 0) - (a.votes_for || 0));
  const totalVotes = latest.reduce((s, x) => s + (x.votes_for || 0), 0) || 1;

  const stratCard = (s, isWinner) => {
    const r = _RISK[s.risk] || _RISK.low;
    const pct = Math.round((s.votes_for || 0) / totalVotes * 100);
    const acted = s.status === 'acted';
    return `<div style="border:1px solid ${isWinner ? '#2a5a3a' : '#26324a'};border-radius:9px;padding:10px;margin-bottom:8px;background:${isWinner ? '#12251b' : '#0e1626'}">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
        <div style="min-width:0">
          <span>${_CAT_ICON[s.category] || '•'}</span>
          <b style="color:#e8eefc">${esc(s.title)}</b>
          <span style="font-size:.68rem;color:${r.c}"> · ${r.t}</span>
          ${isWinner ? '<span style="font-size:.68rem;color:#6ee7a8;font-weight:700"> · 🏛️ MANDATE</span>' : ''}
          ${acted ? `<span style="font-size:.68rem;color:#7dd3fc"> · ${s.actions_run} moves</span>` : ''}
        </div>
        <span style="font-size:.72rem;color:#8a97ad;flex-shrink:0">${s.votes_for || 0} 🗳️</span>
      </div>
      <div style="height:5px;background:#0b1120;border-radius:3px;overflow:hidden;margin:5px 0"><div style="height:100%;width:${pct}%;background:${isWinner ? '#2a5a3a' : '#3a4560'}"></div></div>
      <div style="font-size:.73rem;color:#aeb9cc">${esc(s.why)}</div>
      <div style="font-size:.66rem;color:#54607a;margin-top:3px">proposed by ${esc(s.proposer || 'the assembly')}
        ${!acted && s.status !== 'rejected' ? '' : ''}
        ${s.status !== 'acted' ? `<button class="btn" style="padding:1px 7px;font-size:.64rem;margin-left:6px" onclick="worldRepublicOverride(${s.id},'adopt')">⚡ Force this instead</button>` : ''}
      </div></div>`;
  };

  const plan = st.current_plan;
  const planCard = plan ? `
    <div style="background:#101c14;border:1px solid #2a5a3a;border-radius:10px;padding:12px;margin-bottom:14px">
      <div style="font-size:.66rem;color:#7a86a0;text-transform:uppercase;letter-spacing:.05em">📜 The national plan</div>
      <div style="font-size:1.02rem;font-weight:700;color:#e8eefc;margin-top:2px">${_CAT_ICON[plan.category] || ''} ${esc(plan.title)}</div>
      <div style="font-size:.76rem;color:#aeb9cc;margin-top:3px">${esc(plan.why)}</div>
      <div style="font-size:.68rem;color:#6ee7a8;margin-top:4px">${plan.actions_run || 0} moves underway · proposed by ${esc(plan.proposer || '—')}</div>
    </div>` : '<div style="color:#54607a;font-size:.82rem;margin-bottom:14px">No mandate yet. Convene the assembly to set the nation\'s course.</div>';

  const html = `
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-bottom:14px">
      <div style="background:#0e1626;border:1px solid #26324a;border-radius:8px;padding:10px">
        <div style="font-size:.64rem;color:#7a86a0">🏳️ NATIONAL STANDING</div>
        <div style="font-size:1.4rem;font-weight:800;color:${sc}">${standing}<span style="font-size:.7rem;color:#54607a">/100</span></div>
        <div style="height:5px;background:#0b1120;border-radius:3px;overflow:hidden;margin-top:3px"><div style="height:100%;width:${standing}%;background:${sc}"></div></div>
      </div>
      <div style="background:#0e1626;border:1px solid ${threatColor}44;border-radius:8px;padding:10px">
        <div style="font-size:.64rem;color:#7a86a0">⚔️ FACING</div>
        <div style="font-size:.95rem;font-weight:700;color:${threatColor};margin-top:4px">${esc(st.threat_label || st.threat)}</div>
      </div>
      <div style="background:#0e1626;border:1px solid #26324a;border-radius:8px;padding:10px">
        <div style="font-size:.64rem;color:#7a86a0">🏦 RESERVE</div>
        <div style="font-size:1.1rem;font-weight:700;color:${(tr.balance_cents||0)>=0?'#fcd34d':'#f87171'};margin-top:4px">${_moneyR(tr.balance_cents)}</div>
      </div>
      <div style="background:#0e1626;border:1px solid #26324a;border-radius:8px;padding:10px">
        <div style="font-size:.64rem;color:#7a86a0">💀 STAGNATION</div>
        <div style="font-size:1.1rem;font-weight:700;color:${st.stagnation?'#f59e0b':'#6ee7a8'};margin-top:4px">${st.stagnation || 0}</div>
        <div style="font-size:.6rem;color:#54607a">doing nothing costs us</div>
      </div>
    </div>

    ${planCard}

    <div style="display:flex;justify-content:space-between;align-items:center;margin:4px 0 8px">
      <div style="font-weight:700;color:#e8eefc">🗳️ ${latest.length ? `Assembly · cycle ${maxCycle}` : 'The assembly'}</div>
      <button class="btn" style="padding:5px 12px;font-size:.78rem;background:#2a1f4a;border-color:#6d5aff;color:#c4b5fd" onclick="worldRepublicConvene(this)">🏛️ Convene the assembly</button>
    </div>
    ${latest.length ? latest.map((s, i) => stratCard(s, i === 0 && s.status === 'acted')).join('')
      : '<div style="color:#54607a;font-size:.82rem">No debate yet — convene to hear the people.</div>'}

    <div style="font-size:.66rem;color:#54607a;margin-top:12px;line-height:1.6;border-top:1px solid #1b2740;padding-top:8px">
      ☢️ Risky/code strategies never run on a vote alone — they queue as prayers needing the dev swarm's review <b>and</b> your blessing. 💀 A cycle that acts on nothing decays our standing: doing nothing is the worse death.
    </div>`;

  _worldModal('🏛️ The Republic — War Room', html);
}

async function worldRepublicConvene(btn) {
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Deliberating…'; }
  try {
    const st = await api('/api/world/republic/convene', { method: 'POST', body: JSON.stringify({}) });
    toast?.('🏛️ The assembly has spoken');
    _renderRepublic(st);
  } catch (e) { toast?.('Convene failed'); if (btn) { btn.disabled = false; btn.textContent = '🏛️ Convene the assembly'; } }
}

async function worldRepublicOverride(id, decision) {
  try {
    const st = await api(`/api/world/republic/strategy/${id}/override`, { method: 'POST', body: JSON.stringify({ decision }) });
    toast?.(decision === 'adopt' ? '⚡ Your will overrides the vote' : 'Struck down');
    _renderRepublic(st);
  } catch (e) { toast?.('Override failed'); }
}

window.worldRepublic = worldRepublic;
window.worldRepublicConvene = worldRepublicConvene;
window.worldRepublicOverride = worldRepublicOverride;
