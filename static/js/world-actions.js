/* ══ THE COMPANY — agent & company actions (rename/think/want/buy/meeting/opinion/log/settings) ══
   Split out of tab-world.js for modularity. Runs in shared global scope
   (classic script, not a module) — same as world-map.js / world-assets.js. */

/* ── ACTIONS (global for inline onclick) ── */
async function worldRename(id) {
  const name = prompt('New name for this character:');
  if (!name) return;
  try { await api(`/api/world/agent/${id}/rename`, { method: 'POST', body: JSON.stringify({ name }) }); await _pollWorld(); }
  catch (e) { toast?.(e.message); }
}
async function worldThink(id) {
  try { await api('/api/world/think', { method: 'POST', body: JSON.stringify({ agent_id: id }) }); await _pollWorld(); }
  catch (e) { toast?.(e.message); }
}
async function worldWant(id) {
  const cost = _worldState?.economy?.item_cost ?? 30;
  const label = prompt(`What object should ${'they'} buy & conjure? (costs ${cost} 🪙)\ne.g. chair, computer, castle`);
  if (!label) return;
  try {
    const r = await api(`/api/world/agent/${id}/want`, { method: 'POST', body: JSON.stringify({ label }) });
    toast?.(`Spent ${r.spent} 🪙 — conjuring a ${r.label}…`);
    await _pollWorld();
  } catch (e) { toast?.(e.message); }
}
async function worldBuy(id, upgradeId) {
  try {
    const r = await api(`/api/world/agent/${id}/buy`, { method: 'POST', body: JSON.stringify({ upgrade_id: upgradeId }) });
    toast?.(`Upgrade bought! Earnings now +${Math.round((r.earn_mult-1)*100)}%`);
    await _pollWorld();
  } catch (e) { toast?.(e.message); }
}
async function worldMeeting() {
  try {
    const r = await api('/api/world/meeting', { method: 'POST', body: '{}' });
    toast?.(`🏛️ Voted: ${r.decision}`);
    await _pollWorld();
  } catch (e) { toast?.(e.message); }
}
async function worldOpinion() {
  try {
    const r = await api('/api/world/opinion', { method: 'POST', body: '{}' });
    toast?.(`💡 ${r.agent}: ${r.text}`);
    await _pollWorld();
  } catch (e) { toast?.(e.message); }
}
async function worldRaidDrill() {
  try {
    const r = await api('/api/world/raid', { method: 'POST', body: JSON.stringify({ drill: true }) });
    toast?.(r.ok ? `🚨 Raid! ${r.threats} threat(s) — all hands to defense` : (r.msg || 'no threats detected'));
    await _pollWorld();
  } catch (e) { toast?.(e.message); }
}
async function worldStandDown() {
  try { await api('/api/world/raid/standdown', { method: 'POST', body: '{}' }); toast?.('🩹 Standing down'); await _pollWorld(); }
  catch (e) { toast?.(e.message); }
}
async function worldLog(id) {
  try {
    const r = await api(`/api/world/agent/${id}/log`);
    if (typeof _consoleActive !== 'undefined') { _consoleActive = null; _consoleStrip?.(); }  // journal isn't a console tab
    document.getElementById('world-modal-title').textContent = `📔 ${r.name}'s Journal`;
    const el = document.getElementById('world-modal-body');
    el.style.whiteSpace = 'pre-wrap'; el.textContent = r.markdown;
    document.getElementById('world-modal').style.display = 'flex';
  } catch (e) { toast?.(e.message); }
}
function worldCloseModal() {
  const m = document.getElementById('world-modal');
  if (m) m.style.display = 'none';
  if (typeof _consoleActive !== 'undefined') _consoleActive = null;   // end the console session (world-economy.js)
}
async function worldResolveDirective(id) {
  try { await api(`/api/world/directive/${id}/resolve`, { method: 'POST', body: '{}' });
        toast?.('Directive marked done ✓'); await _pollWorld(); }
  catch (e) { toast?.(e.message); }
}
async function worldSettings() {
  try {
    const r = await api('/api/world/settings');
    const s = r.settings || {};
    const num = (k, lbl, hint = '') => `<div style="display:flex;justify-content:space-between;align-items:center;gap:10px;margin:7px 0">
      <label style="font-size:.8rem;color:#c7d2e5">${lbl}${hint ? `<span style="color:#54607a"> · ${hint}</span>` : ''}</label>
      <input id="ws_${k}" type="number" value="${esc(s[k] ?? '')}" style="width:88px;background:#0b1120;border:1px solid #33456b;color:#e8eefc;border-radius:6px;padding:4px 6px"></div>`;
    const chk = (k, lbl) => `<div style="display:flex;justify-content:space-between;align-items:center;gap:10px;margin:7px 0">
      <label style="font-size:.8rem;color:#c7d2e5">${lbl}</label>
      <input id="ws_${k}" type="checkbox" ${String(s[k]) === '1' ? 'checked' : ''} style="width:18px;height:18px"></div>`;
    const txt = (k, lbl, hint = '') => `<div style="display:flex;justify-content:space-between;align-items:center;gap:10px;margin:7px 0">
      <label style="font-size:.8rem;color:#c7d2e5">${lbl}${hint ? `<span style="color:#54607a"> · ${hint}</span>` : ''}</label>
      <input id="ws_${k}" type="text" value="${esc(s[k] ?? '')}" style="width:210px;background:#0b1120;border:1px solid #33456b;color:#e8eefc;border-radius:6px;padding:4px 6px"></div>`;
    const body = `
      <div style="font-weight:600;color:#9fc0ff;margin:2px 0 4px">🧠 Cognition schedule</div>
      ${chk('world_llm_enabled', 'Agents may think (load the model)')}
      ${num('world_llm_interval_min', 'Model runs every', 'minutes')}
      ${num('world_active_start', 'Active hours start', '0–23')}
      ${num('world_active_end', 'Active hours end', '0–23')}
      <div style="font-weight:600;color:#9fc0ff;margin:10px 0 4px">🏛️ Governance</div>
      ${chk('world_meetings_enabled', 'Hold town meetings')}
      ${num('world_meeting_interval_min', 'Meeting every', 'minutes')}
      ${chk('world_incidents_enabled', 'Random town incidents')}
      ${chk('world_leader_upgrades', 'Mayor/Boss file real dev-swarm upgrades from the company fund (charged only when you approve)')}
      ${num('world_leader_upgrade_hours', 'Leader proposal every', 'hours')}
      <div style="font-weight:600;color:#9fc0ff;margin:10px 0 4px">👁️ World-builder's eyes</div>
      ${chk('world_vision_enabled', 'Vision-review generated sprites')}
      ${num('world_vision_candidates', 'Candidates per build', 'pick best')}
      ${num('world_vision_retries', 'Retry rounds if poor', '')}
      ${num('world_vision_min_score', 'Min quality score', '1–10')}
      <div style="font-weight:600;color:#9fc0ff;margin:10px 0 4px">🎨 Pixel-art generation</div>
      ${txt('world_prop_model', 'Image model', 'blank = store default')}
      ${txt('world_prop_lora', 'Pixel-art LoRA', 'file:strength, blank = off')}
      <div style="font-weight:600;color:#9fc0ff;margin:10px 0 4px">🧱 Terrain tileset</div>
      <div style="display:flex;align-items:center;gap:8px;margin:7px 0;flex-wrap:wrap">
        <button class="btn" style="padding:5px 12px;font-size:.76rem" onclick="worldTilesetGen()"
          title="Render a 6-tile terrain set (grass/path/floor/wall/plaza/water) from the world theme with the pixel-art pipeline, made seamless, and swap it in for the procedural terrain. Takes a few minutes on the GPU.">🧱 Generate from theme</button>
        <button class="btn" style="padding:5px 12px;font-size:.76rem" onclick="worldTilesetRemove()"
          title="Remove the generated tileset — the map instantly falls back to the procedural terrain art.">🗑 Remove (procedural)</button>
        <span id="ws-tileset-status" style="font-size:.72rem;color:#8a97ad"></span>
      </div>
      <div style="font-weight:600;color:#9fc0ff;margin:10px 0 4px">🛡️ Real-world rules</div>
      ${num('world_min_item_cost', 'Min item cost', '🪙')}
      ${chk('world_allow_free', 'Allow free items')}
      ${num('world_min_price_cents', 'Store price floor', '¢')}
      ${num('world_max_discount_pct', 'Max discount', '%')}
      ${chk('world_require_review', 'Require review before posting (no AI-junk dumps)')}
      <div style="font-weight:600;color:#9fc0ff;margin:10px 0 4px">🪼 JellyCoin</div>
      ${chk('world_crypto_mining_enabled', 'Skilling boosts GPU mining (pays only in real mined blocks)')}
      <div style="font-weight:600;color:#9fc0ff;margin:10px 0 4px">🎵 Music</div>
      ${chk('world_music_lyrics', 'Agents may write & sing their own lyrics (vocal songs via ACE-Step)')}
      <div style="display:flex;gap:8px;margin-top:14px">
        <button class="btn" style="padding:7px 14px" onclick="worldSaveSettings()">💾 Save</button>
        <button class="btn" style="padding:7px 14px" onclick="worldCloseModal()">Cancel</button>
      </div>`;
    _worldModal('⚙️ Company Settings', body);   // via the shared helper so the console tab strip renders
    _tilesetStatus();
  } catch (e) { toast?.(e.message); }
}
async function _tilesetStatus() {
  const el = document.getElementById('ws-tileset-status');
  if (!el) return;
  try {
    const t = await api('/api/world/tileset');
    el.textContent = (t.installed ? '✅ installed' : 'not installed')
      + (t.state ? ` · ${t.state}${t.note ? ` (${t.note})` : ''}` : '');
  } catch {}
}
async function worldTilesetGen() {
  try {
    await api('/api/world/tileset', { method: 'POST', body: '{}' });
    toast?.('🧱 Generating terrain tiles — a few minutes on the GPU');
    const el = document.getElementById('ws-tileset-status');
    const tick = setInterval(async () => {
      if (!document.getElementById('ws-tileset-status')) { clearInterval(tick); return; }
      await _tilesetStatus();
      const t = await api('/api/world/tileset').catch(() => null);
      if (t && t.state !== 'generating') {
        clearInterval(tick);
        if (t.state === 'done') { toast?.('🧱 Tileset ready — reloading the map'); location.reload(); }
      }
    }, 5000);
  } catch (e) { toast?.(e.message); }
}
async function worldTilesetRemove() {
  try {
    await api('/api/world/tileset', { method: 'DELETE' });
    toast?.('🗑 Tileset removed — procedural terrain is back');
    location.reload();
  } catch (e) { toast?.(e.message); }
}
window.worldTilesetGen = worldTilesetGen; window.worldTilesetRemove = worldTilesetRemove;
async function worldSaveSettings() {
  const keys = ['world_llm_enabled', 'world_llm_interval_min', 'world_active_start', 'world_active_end',
    'world_meetings_enabled', 'world_meeting_interval_min', 'world_incidents_enabled',
    'world_vision_enabled', 'world_vision_candidates', 'world_vision_retries', 'world_vision_min_score',
    'world_min_item_cost', 'world_allow_free', 'world_min_price_cents', 'world_max_discount_pct',
    'world_require_review', 'world_prop_model', 'world_prop_lora', 'world_crypto_mining_enabled',
    'world_music_lyrics', 'world_leader_upgrades', 'world_leader_upgrade_hours'];
  const s = {};
  keys.forEach(k => { const el = document.getElementById('ws_' + k); if (el) s[k] = el.type === 'checkbox' ? (el.checked ? '1' : '0') : el.value; });
  try { await api('/api/world/settings', { method: 'POST', body: JSON.stringify({ settings: s }) });
        toast?.('Company settings saved ✓'); worldCloseModal(); }
  catch (e) { toast?.(e.message); }
}
