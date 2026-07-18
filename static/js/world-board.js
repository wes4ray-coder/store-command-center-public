/* ══ THE COMPANY — Info Board (Chunk 2) ══
   The "come back and see what got done" surface: a collage of the newest
   creations, what the automation is doing, what's been published, and the
   community board. Reads /api/world/ops/board. Uses _worldModal + api()/esc()/toast().
   Global-scope classic script. */

function _agoShort(ts) {
  if (!ts) return '';
  const t = Date.parse((ts || '').replace(' ', 'T') + 'Z');
  if (isNaN(t)) return (ts || '').slice(5, 16);
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 90) return 'just now';
  if (s < 5400) return Math.round(s / 60) + 'm ago';
  if (s < 129600) return Math.round(s / 3600) + 'h ago';
  return Math.round(s / 86400) + 'd ago';
}

async function worldBoard() {
  let d;
  try { d = await api('/api/world/ops/board'); }
  catch (e) { toast?.('Info Board failed to load'); return; }

  const a = d.auto || {};
  const items = d.items || [];
  const msgs = d.messages || [];

  // ── collage ──
  const tile = (it) => {
    const cap = esc((it.title || it.type).slice(0, 40));
    // URL comes from agent-generated content → never interpolate it raw into a JS
    // string / src. esc() it into a data-url attribute and open via this.dataset.url.
    const u = esc(it.url);
    if (it.type === 'image' || it.type === 'prop') {
      return `<div style="position:relative;border-radius:8px;overflow:hidden;border:1px solid #26324a;aspect-ratio:1;background:#0b1120;cursor:pointer" title="${cap}" data-url="${u}" onclick="window.open(this.dataset.url,'_blank')">
        <img src="${u}" loading="lazy" style="width:100%;height:100%;object-fit:cover;display:block" onerror="this.onerror=null;this.replaceWith(Object.assign(document.createElement('div'),{style:'width:100%;height:100%;display:flex;align-items:center;justify-content:center;font-size:1.6rem;background:#0e1626',textContent:'🖼'}))">
        <div style="position:absolute;left:0;right:0;bottom:0;background:linear-gradient(transparent,#000a);color:#e8eefc;font-size:.6rem;padding:8px 4px 3px">${cap}</div></div>`;
    }
    const ic = it.type === 'video' ? '🎬' : '🎵';
    return `<div style="border-radius:8px;border:1px solid #26324a;aspect-ratio:1;background:#0e1626;display:flex;flex-direction:column;align-items:center;justify-content:center;cursor:pointer;padding:4px;text-align:center" title="${cap}" data-url="${u}" onclick="window.open(this.dataset.url,'_blank')">
      <div style="font-size:1.6rem">${ic}</div><div style="font-size:.58rem;color:#8a97ad;margin-top:3px">${cap}</div></div>`;
  };
  const collage = items.length
    ? `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(86px,1fr));gap:8px">${items.map(tile).join('')}</div>`
    : '<div style="color:#54607a;font-size:.82rem;padding:10px 0">No creations yet. Turn on automation or hit ✨ Create now.</div>';

  // ── published strip ──
  const pubs = (d.recent_published || []).filter(p => p.wp_link);
  const pubStrip = pubs.length
    ? `<div style="font-size:.72rem;color:#7a86a0;margin:12px 0 4px">🌐 Recently live on example.com</div>` +
      pubs.map(p => `<div style="font-size:.76rem;padding:1px 0"><a href="${esc(p.wp_link)}" target="_blank" style="color:#7dd3fc;text-decoration:none">${esc(p.title || 'item')}</a> <span style="color:#54607a">${_agoShort(p.pushed_at)}</span></div>`).join('')
    : '';

  // ── community board ──
  const MSG = { warning: '⚠️', praise: '🎉', need: '🙏', info: 'ℹ️' };
  const board = msgs.length
    ? msgs.map(m => `<div style="font-size:.76rem;padding:3px 0;display:flex;gap:6px">
        <span>${MSG[m.kind] || 'ℹ️'}</span>
        <span style="color:#c7d2e5">${m.from_agent ? `<b style="color:#9fb4d6">${esc(m.from_agent)}:</b> ` : ''}${esc(m.text)}</span>
        <span style="color:#54607a;margin-left:auto;flex-shrink:0">${_agoShort(m.created_at)}</span></div>`).join('')
    : '<div style="color:#54607a;font-size:.8rem">The community is content.</div>';

  // ── automation control ──
  const on = !!a.enabled;
  const nextTxt = a.running ? 'creating now…' : (on ? (a.next_due_sec ? `next in ~${Math.round(a.next_due_sec / 60)}m` : 'due now') : 'paused');
  const autoCard = `
    <div style="background:${on ? '#12251b' : '#0e1626'};border:1px solid ${on ? '#2a5a3a' : '#26324a'};border-radius:10px;padding:12px;margin-bottom:14px">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">
        <div>
          <b style="color:#e8eefc">🤖 Autonomous creation</b>
          <span style="font-size:.72rem;color:${on ? '#6ee7a8' : '#7a86a0'}"> · ${on ? 'ON' : 'OFF'} · ${nextTxt}</span>
        </div>
        <div style="display:flex;gap:6px">
          <button class="btn" style="padding:4px 10px;font-size:.74rem;${on ? 'background:#5a2a2a;border-color:#7c3a3a' : 'background:#1f4a32;border-color:#2a5a3a;color:#6ee7a8'}" onclick="worldAutoToggle(${on ? 'false' : 'true'})" title="Turn autonomous creation on or off. When ON, the world makes new media on a timer during active hours without asking.">${on ? '⏸ Pause' : '▶ Turn on'}</button>
          <button class="btn" style="padding:4px 10px;font-size:.74rem" onclick="worldAutoRunNow()" ${a.running ? 'disabled' : ''} title="Generate one new creation right now on the GPU box, without waiting for the timer.">✨ Create now</button>
        </div>
      </div>
      <div style="display:flex;gap:10px;align-items:center;margin-top:8px;font-size:.72rem;color:#8a97ad;flex-wrap:wrap">
        <span>Every <input id="auto-int" type="number" min="5" value="${a.interval_min || 120}" title="How often automation creates a new piece, in minutes, during active hours." style="width:56px;padding:2px 5px;background:#0b1120;border:1px solid #26324a;border-radius:5px;color:#e8eefc"> min</span>
        <span>Active <input id="auto-s" type="number" min="0" max="23" value="${a.active_start ?? 8}" title="Start of the daily active window (24h clock). Automation only creates between the start and end hours." style="width:44px;padding:2px 5px;background:#0b1120;border:1px solid #26324a;border-radius:5px;color:#e8eefc">–<input id="auto-e" type="number" min="0" max="24" value="${a.active_end ?? 22}" title="End of the daily active window (24h clock). Automation pauses outside these hours." style="width:44px;padding:2px 5px;background:#0b1120;border:1px solid #26324a;border-radius:5px;color:#e8eefc">h</span>
        <span>🏛️ Govern every <input id="auto-gov" type="number" min="0" value="${a.govern_min ?? 360}" title="How often the world runs a governance pass (strategy and spending decisions), in minutes. 0 = never." style="width:56px;padding:2px 5px;background:#0b1120;border:1px solid #26324a;border-radius:5px;color:#e8eefc"> min</span>
        <button class="btn" style="padding:2px 9px;font-size:.7rem" onclick="worldAutoSave()">💾 Save</button>
        ${d.pending_prayers ? `<span style="margin-left:auto;color:#fcd34d">🙏 ${d.pending_prayers} awaiting your blessing — <a onclick="worldCloseModal();worldGod()" style="color:#a78bfa;cursor:pointer">open God Console</a></span>` : ''}
      </div>
      <div style="display:flex;gap:6px;align-items:center;margin-top:8px;font-size:.72rem;color:#8a97ad;flex-wrap:wrap">
        <span>Make:</span>
        ${[['image', '🖼️ Art'], ['music', '🎵 Music'], ['video', '🎬 Video'], ['3d', '🧊 3D']].map(([k, lbl]) => {
          const on = (a.kinds || ['image']).includes(k);
          return `<button class="btn" style="padding:2px 9px;font-size:.7rem;${on ? 'background:#1f4a32;border-color:#2a5a3a;color:#6ee7a8' : ''}" onclick="worldAutoKind('${k}')" title="${({image:'Include AI images (fast) in what automation makes.',music:'Include AI music tracks in what automation makes.',video:'Include AI video (slow, GPU-heavy) in what automation makes.','3d':'Include 3D models (slow, GPU-heavy) in what automation makes.'})[k]} Click to toggle.">${on ? '✓ ' : ''}${lbl}</button>`;
        }).join('')}
        <span style="color:#54607a">· video &amp; 3D are slow &amp; GPU-heavy</span>
      </div>
    </div>`;

  const html = `${autoCard}
    <div style="font-weight:700;color:#e8eefc;margin:4px 0 8px">🖼️ Latest creations</div>
    ${collage}
    ${pubStrip}
    <div style="font-weight:700;color:#e8eefc;margin:16px 0 4px">📣 Community board</div>
    ${board}`;

  _worldModal('📋 Company Info Board', html);
}

async function worldAutoToggle(on) {
  try { await api('/api/world/ops/auto-config', { method: 'POST', body: JSON.stringify({ enabled: on }) }); toast?.(on ? '🤖 Automation on' : 'Automation paused'); }
  catch (e) { toast?.('Failed'); }
  worldBoard();
}
async function worldAutoRunNow() {
  try {
    const r = await api('/api/world/ops/auto-run-now', { method: 'POST', body: JSON.stringify({}) });
    toast?.(r.ok ? '✨ Creating a new piece… check back in a minute' : (r.error || 'Busy'));
  } catch (e) { toast?.('Failed'); }
}
async function worldAutoSave() {
  const body = {
    interval_min: parseInt(document.getElementById('auto-int')?.value || '120', 10),
    active_start: parseInt(document.getElementById('auto-s')?.value || '8', 10),
    active_end: parseInt(document.getElementById('auto-e')?.value || '22', 10),
    govern_min: parseInt(document.getElementById('auto-gov')?.value || '360', 10),
  };
  try { await api('/api/world/ops/auto-config', { method: 'POST', body: JSON.stringify(body) }); toast?.('Saved'); }
  catch (e) { toast?.('Failed'); }
  worldBoard();
}

async function worldAutoKind(k) {
  try {
    const st = await api('/api/world/ops/auto-config');
    let ks = st.kinds || ['image'];
    ks = ks.includes(k) ? ks.filter(x => x !== k) : ks.concat(k);
    if (!ks.length) ks = ['image'];
    await api('/api/world/ops/auto-config', { method: 'POST', body: JSON.stringify({ kinds: ks }) });
  } catch (e) { toast?.('Failed'); }
  worldBoard();
}

window.worldBoard = worldBoard;
window.worldAutoToggle = worldAutoToggle;
window.worldAutoRunNow = worldAutoRunNow;
window.worldAutoSave = worldAutoSave;
window.worldAutoKind = worldAutoKind;
