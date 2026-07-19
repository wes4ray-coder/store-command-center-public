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
      <div style="font-weight:600;color:#9fc0ff;margin:10px 0 4px">🧱 Terrain tiles <span style="color:#54607a;font-weight:400;font-size:.72rem">· progressive — each tile is QA + style-checked before it goes live; procedural art is the permanent fallback</span></div>
      ${chk('world_tileset_auto', 'Agents slowly paint tiles (one pending tile at a time; failures are quietly scrapped)')}
      ${num('world_tileset_auto_min', 'Paint attempt every', 'minutes')}
      <div id="ws-tileset-grid" style="display:flex;gap:10px;flex-wrap:wrap;margin:7px 0"></div>
      <div style="display:flex;align-items:center;gap:8px;margin:7px 0;flex-wrap:wrap">
        <button class="btn" style="padding:5px 12px;font-size:.76rem" onclick="worldTilesetGen()"
          title="Fill ALL pending tiles from the world theme — runs the same per-tile QA + style gates sequentially on the GPU.">🧱 Fill all pending</button>
        <button class="btn" style="padding:5px 12px;font-size:.76rem" onclick="worldTilesetRemove()"
          title="Remove every generated tile — the map instantly falls back to the procedural terrain art.">🗑 Remove all (procedural)</button>
        <span id="ws-tileset-status" style="font-size:.72rem;color:#8a97ad"></span>
      </div>
      <div style="font-weight:600;color:#9fc0ff;margin:10px 0 4px">🏠 Roof cutaway <span style="color:#54607a;font-weight:400;font-size:.72rem">· how far out roofs fade away so you can see inside houses/buildings — lower = interiors reveal sooner</span></div>
      <div style="display:flex;align-items:center;gap:10px;margin:7px 0">
        <label style="font-size:.8rem;color:#c7d2e5;white-space:nowrap">Reveal interiors at zoom</label>
        <input id="ws-roof-fade" type="range" min="0.5" max="3" step="0.05" value="1.15"
               oninput="worldRoofFadePreview(this.value)" onchange="worldRoofFadeSave(this.value)" style="flex:1">
        <span id="ws-roof-fade-val" style="font-size:.75rem;color:#9fc0ff;min-width:3ch;text-align:right">1.15×</span></div>
      <div style="font-size:.68rem;color:#54607a;margin:-2px 0 4px">Slide left to see inside from further out; right to keep roofs on until you're zoomed in close.</div>
      <div style="font-weight:600;color:#9fc0ff;margin:10px 0 4px">🗺️ Whole-world terrain image <span style="color:#54607a;font-weight:400;font-size:.72rem">· one big top-down ground skin (grass/roads/plaza/ponds/forest) — town logic still lives on the grid</span></div>
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;margin:7px 0">
        <label style="font-size:.8rem;color:#c7d2e5">Show a generated terrain image (else procedural per-tile)</label>
        <input id="ws_world_terrain_image_enabled" type="checkbox" onchange="worldTerrainToggle(this.checked)" style="width:18px;height:18px"></div>
      <div style="display:flex;align-items:center;gap:10px;margin:7px 0;flex-wrap:wrap">
        <img id="ws-terrain-thumb" alt="terrain preview" style="display:none;width:96px;height:60px;object-fit:cover;border-radius:6px;border:1px solid #33456b;background:#0b1120">
        <button class="btn" id="ws-terrain-gen" style="padding:5px 12px;font-size:.76rem" onclick="worldTerrainGen()"
          title="Render one large top-down terrain image for the whole map on the GPU (~1–2 min, shares VRAM).">🗺️ Generate terrain</button>
        <button class="btn" id="ws-terrain-regen" style="display:none;padding:5px 12px;font-size:.76rem" onclick="worldTerrainGen()"
          title="Render a fresh terrain image, replacing the current one (~1–2 min on the GPU).">🔁 Regenerate</button>
        <button class="btn" id="ws-terrain-layout" style="padding:5px 12px;font-size:.76rem" onclick="worldTerrainGenLayout()"
          title="img2img: feeds your town's procedural layout render to the generator so the terrain matches your real roads/water/plaza.">🗺️ Generate from town layout (matches your map)</button>
        <button class="btn" id="ws-terrain-revert" style="padding:5px 12px;font-size:.76rem" onclick="worldTerrainRevert()"
          title="Drop the generated image — the map instantly falls back to procedural per-tile terrain.">🗑 Revert to procedural</button>
        <span id="ws-terrain-status" style="font-size:.72rem;color:#8a97ad"></span>
      </div>
      <div style="font-size:.68rem;color:#54607a;margin:-2px 0 4px">Uses your town's actual roads/water/plaza layout so the terrain lines up. Generation runs on the GPU (~1–2 min) and shares VRAM with other jobs.</div>
      <div style="font-weight:600;color:#9fc0ff;margin:10px 0 4px">🪵 Interior floor <span style="color:#54607a;font-weight:400;font-size:.72rem">· ONE shared generated floor texture under every building interior (per-type tint washed over it, so buildings still read distinct)</span></div>
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;margin:7px 0">
        <label style="font-size:.8rem;color:#c7d2e5">Show a generated interior floor (else procedural per-type tint)</label>
        <input id="ws_world_floor_image_enabled" type="checkbox" onchange="worldFloorToggle(this.checked)" style="width:18px;height:18px"></div>
      <div style="display:flex;align-items:center;gap:10px;margin:7px 0;flex-wrap:wrap">
        <img id="ws-floor-thumb" alt="floor preview" style="display:none;width:60px;height:60px;object-fit:cover;border-radius:6px;border:1px solid #33456b;background:#0b1120">
        <button class="btn" id="ws-floor-gen" style="padding:5px 12px;font-size:.76rem" onclick="worldFloorGen()"
          title="Render one seamless tileable interior-floor texture on the GPU (~1–2 min, shares VRAM).">🪵 Generate floor</button>
        <button class="btn" id="ws-floor-regen" style="display:none;padding:5px 12px;font-size:.76rem" onclick="worldFloorGen()"
          title="Render a fresh floor texture, replacing the current one (~1–2 min on the GPU).">🔁 Regenerate</button>
        <button class="btn" id="ws-floor-revert" style="padding:5px 12px;font-size:.76rem" onclick="worldFloorRevert()"
          title="Drop the generated floor — interiors fall back to the procedural per-type tint.">🗑 Revert to procedural</button>
        <span id="ws-floor-status" style="font-size:.72rem;color:#8a97ad"></span>
      </div>
      <div style="font-weight:600;color:#9fc0ff;margin:10px 0 4px">🌙 Moon <span style="color:#54607a;font-weight:400;font-size:.72rem">· drifts across the night sky when zoomed out, casts a shadow that sweeps the map at every zoom</span></div>
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;margin:7px 0">
        <label style="font-size:.8rem;color:#c7d2e5">Show the moon + its ground shadow (at night)</label>
        <input id="ws_world_moon_enabled" type="checkbox" onchange="worldMoonToggle(this.checked)" style="width:18px;height:18px"></div>
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;margin:7px 0">
        <label style="font-size:.8rem;color:#c7d2e5">Preview in daylight too (don't wait for sim-night)</label>
        <input id="ws_world_moon_daytime" type="checkbox" onchange="worldMoonDayToggle(this.checked)" style="width:18px;height:18px"></div>
      <div style="display:flex;align-items:center;gap:10px;margin:7px 0;flex-wrap:wrap">
        <img id="ws-moon-thumb" alt="moon preview" style="display:none;width:60px;height:60px;object-fit:cover;border-radius:50%;border:1px solid #33456b;background:#0b1120">
        <button class="btn" id="ws-moon-gen" style="padding:5px 12px;font-size:.76rem" onclick="worldMoonGen()"
          title="Render a pixel-art lunar-surface texture on the GPU (~1–2 min, shares VRAM). Swaps into the procedural moon; also the future moon-map ground.">🌙 Generate moon</button>
        <button class="btn" id="ws-moon-regen" style="display:none;padding:5px 12px;font-size:.76rem" onclick="worldMoonGen()"
          title="Render a fresh moon texture, replacing the current one (~1–2 min on the GPU).">🔁 Regenerate</button>
        <button class="btn" id="ws-moon-revert" style="padding:5px 12px;font-size:.76rem" onclick="worldMoonRevert()"
          title="Drop the generated moon texture — the moon falls back to the procedural cratered disc.">🗑 Revert to procedural</button>
        <span id="ws-moon-status" style="font-size:.72rem;color:#8a97ad"></span>
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
    _terrainStatus();
    _floorStatus();
    _moonStatus();
    // reflect the live roof-cutaway value in the slider
    { const rf = (window._wmRoofFade != null && window._wmRoofFade > 0) ? window._wmRoofFade : 1.15;
      const sl = document.getElementById('ws-roof-fade'), lb = document.getElementById('ws-roof-fade-val');
      if (sl) sl.value = rf; if (lb) lb.textContent = Number(rf).toFixed(2) + '×'; }
  } catch (e) { toast?.(e.message); }
}
const _TILE_PROC = { grass: '#3a7d44', path: '#9c8f77', floor: '#7a5230', wall: '#8b909c', plaza: '#b9b1a0', water: '#2c5f9e' };
async function _tilesetStatus() {
  const el = document.getElementById('ws-tileset-status');
  if (!el) return;
  try {
    const t = await api('/api/world/tileset');
    el.textContent = (t.installed ? '✅ generated tiles live' : 'all procedural')
      + (t.state ? ` · ${t.state}${t.note ? ` (${t.note})` : ''}` : '');
    const grid = document.getElementById('ws-tileset-grid');
    if (grid && t.tiles) {
      const D = 36, sc = D / (t.cell || 64);                 // thumbnail = atlas cell scaled down
      const atlasUrl = `/store/static/${t.atlas}?v=${t.v || 0}`;
      const sheetW = Math.round((t.tiles.length * (t.cell || 64)) * sc);
      grid.innerHTML = t.tiles.map(x => {
        const thumb = x.generated
          ? `background-image:url('${atlasUrl}');background-size:${sheetW}px ${D}px;background-position:-${Math.round(x.x * sc)}px 0;image-rendering:pixelated`
          : `background:${_TILE_PROC[x.key] || '#444'}`;
        const badge = x.locked ? '🔒' : (x.generated ? '🎨' : 'proc');
        const btns = x.locked
          ? `<span style="font-size:.62rem;color:#54607a" title="Structural tile — the renderer keeps its crafted procedural interior art.">kept</span>`
          : `<button class="btn" style="padding:1px 6px;font-size:.66rem" title="Generate a new '${x.key}' tile (QA + style-checked before it goes live)." onclick="worldTileGen('${x.key}')">🎨</button>`
            + (x.generated ? `<button class="btn" style="padding:1px 6px;font-size:.66rem" title="Reject: revert '${x.key}' to procedural art, and teach the painters what to avoid." onclick="worldTileReject('${x.key}')">👎</button>` : '');
        return `<div style="display:flex;flex-direction:column;align-items:center;gap:3px" title="${esc(x.desc || x.key)}">
          <div style="width:${D}px;height:${D}px;border-radius:5px;border:1px solid ${x.generated ? '#4d7fd0' : '#33456b'};${thumb}"></div>
          <div style="font-size:.66rem;color:#c7d2e5">${x.key} <span style="color:#54607a">${badge}</span></div>
          <div style="display:flex;gap:3px">${btns}</div></div>`;
      }).join('');
    }
  } catch {}
}
function _tilesetWatch(doneMsg) {
  const tick = setInterval(async () => {
    if (!document.getElementById('ws-tileset-status')) { clearInterval(tick); return; }
    await _tilesetStatus();
    const t = await api('/api/world/tileset').catch(() => null);
    if (t && t.state !== 'generating') {
      clearInterval(tick);
      if (t.state === 'done') { toast?.(doneMsg); location.reload(); }
      else if (t.state === 'failed') toast?.(`🧱 Tile discarded — ${t.note || 'did not pass the checks'}`);
    }
  }, 5000);
}
async function worldTilesetGen() {
  try {
    await api('/api/world/tileset', { method: 'POST', body: '{}' });
    toast?.('🧱 Filling pending terrain tiles — a few minutes on the GPU');
    _tilesetWatch('🧱 Tiles ready — reloading the map');
  } catch (e) { toast?.(e.message); }
}
async function worldTileGen(key) {
  try {
    await api('/api/world/tileset/tile', { method: 'POST', body: JSON.stringify({ key }) });
    toast?.(`🎨 Painting '${key}' — it only goes live if it passes QA + style checks`);
    _tilesetWatch(`🧱 '${key}' painted — reloading the map`);
  } catch (e) { toast?.(e.message); }
}
async function worldTileReject(key) {
  try {
    await api('/api/world/tileset/reject', { method: 'POST', body: JSON.stringify({ key }) });
    toast?.(`👎 '${key}' reverted to procedural — the painters will avoid that look`);
    location.reload();
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
window.worldTileGen = worldTileGen; window.worldTileReject = worldTileReject;

// ── Layer 2: whole-world terrain IMAGE (grass/roads/plaza/ponds/forest as one
// big top-down skin). GET /api/world/terrain → {generating,has_image,url,enabled,
// state,note}; POST renders (poll for progress); DELETE reverts to procedural.
// The enable flag is the setting world_terrain_image_enabled (PATCH /api/settings).
async function _terrainStatus() {
  const el = document.getElementById('ws-terrain-status');
  if (!el) return null;
  try {
    const t = await api('/api/world/terrain');
    const cb = document.getElementById('ws_world_terrain_image_enabled');
    if (cb && document.activeElement !== cb) cb.checked = !!t.enabled;   // reflect the setting
    const busy = !!(t.generating || t.state === 'generating');
    const gen = document.getElementById('ws-terrain-gen'), regen = document.getElementById('ws-terrain-regen');
    if (gen) gen.style.display = t.has_image ? 'none' : '';              // Generate vs Regenerate
    if (regen) regen.style.display = t.has_image ? '' : 'none';
    const thumb = document.getElementById('ws-terrain-thumb');
    if (thumb) {
      if (t.has_image && t.url) { thumb.src = '/store/static/' + t.url; thumb.style.display = ''; }  // url already carries ?v=
      else thumb.style.display = 'none';
    }
    let msg;
    if (busy) msg = '⏳ rendering on the GPU… (~1–2 min)';
    else if (t.state === 'failed') msg = '⚠️ ' + esc(t.note || 'render failed');
    else {
      const modeLbl = t.mode === 'layout' ? ' 🗺️ from your layout' : t.mode === 'generic' ? ' (generic)' : '';
      msg = (t.has_image ? '✅ image ready' + esc(modeLbl) : 'procedural (no image)')
          + (t.enabled ? ' · shown on the map' : ' · not shown (toggle off)');
      if (t.note) msg += ' · ' + esc(t.note);
    }
    el.innerHTML = msg;
    return t;
  } catch { return null; }
}
function _terrainWatch() {
  const tick = setInterval(async () => {
    if (!document.getElementById('ws-terrain-status')) { clearInterval(tick); return; }  // modal closed
    const t = await _terrainStatus();
    if (t && !(t.generating || t.state === 'generating')) {
      clearInterval(tick);
      if (t.state === 'failed') toast?.(`🗺️ Terrain render failed — ${t.note || 'did not finish'}`);
      else if (t.has_image) {
        toast?.('🗺️ Terrain image ready');
        if (t.enabled && t.url && window.WM && WM.setTerrainImage) WM.setTerrainImage('/store/static/' + t.url);
      }
    }
  }, 3000);
}
async function worldTerrainGen() {
  try {
    await api('/api/world/terrain', { method: 'POST', body: '{}' });
    toast?.('🗺️ Rendering the whole-world terrain image — ~1–2 min on the GPU');
    _terrainStatus(); _terrainWatch();
  } catch (e) { toast?.(e.message); }
}
// Layout-guided img2img: export the PROCEDURAL town layout (roads/water/plaza/fields +
// building footprints) and feed it as the init base so the generated terrain lines up
// with the real map. Reuses the SAME status poll as the generic Generate.
async function worldTerrainGenLayout() {
  try {
    const base = (window.WM && WM.exportLayoutBase) ? WM.exportLayoutBase(1216, 960) : null;
    if (!base) { toast?.('could not read the map'); return; }
    await api('/api/world/terrain', { method: 'POST', body: JSON.stringify({ base_image: base, denoise: 0.55 }) });
    toast?.('🗺️ Rendering terrain from your town layout — ~1–2 min on the GPU');
    _terrainStatus(); _terrainWatch();
  } catch (e) { toast?.(e.message); }
}
async function worldTerrainRevert() {
  try {
    await api('/api/world/terrain', { method: 'DELETE' });
    toast?.('🗑 Terrain image dropped — procedural terrain is back');
    if (window.WM && WM.setTerrainImage) WM.setTerrainImage(null);
    _terrainStatus();
  } catch (e) { toast?.(e.message); }
}
async function worldTerrainToggle(on) {
  try {
    await api('/api/settings', { method: 'PATCH', body: JSON.stringify({ world_terrain_image_enabled: on ? '1' : '0' }) });
    toast?.(on ? '🗺️ Generated terrain image will be shown when present' : '🗺️ Terrain image hidden — procedural terrain shown');
    const t = await _terrainStatus();
    if (window.WM && WM.setTerrainImage) {
      if (on && t && t.has_image && t.url) WM.setTerrainImage('/store/static/' + t.url);
      else if (!on) WM.setTerrainImage(null);
    }
  } catch (e) { toast?.(e.message); }
}

// ── Layer 2b: ONE shared interior-FLOOR texture blitted under every building
// interior (per-kind tint washed over it). GET /api/world/floor → {generating,
// has_image,url,enabled,state,note}; POST renders (poll for progress); DELETE
// reverts. Enable flag = world_floor_image_enabled (PATCH /api/settings). Mirrors
// the terrain status/watch helpers above.
async function _floorStatus() {
  const el = document.getElementById('ws-floor-status');
  if (!el) return null;
  try {
    const f = await api('/api/world/floor');
    const cb = document.getElementById('ws_world_floor_image_enabled');
    if (cb && document.activeElement !== cb) cb.checked = !!f.enabled;   // reflect the setting
    const busy = !!(f.generating || f.state === 'generating');
    const gen = document.getElementById('ws-floor-gen'), regen = document.getElementById('ws-floor-regen');
    if (gen) gen.style.display = f.has_image ? 'none' : '';              // Generate vs Regenerate
    if (regen) regen.style.display = f.has_image ? '' : 'none';
    const thumb = document.getElementById('ws-floor-thumb');
    if (thumb) {
      if (f.has_image && f.url) { thumb.src = '/store/static/' + f.url; thumb.style.display = ''; }  // url already carries ?v=
      else thumb.style.display = 'none';
    }
    let msg;
    if (busy) msg = '⏳ rendering on the GPU… (~1–2 min)';
    else if (f.state === 'failed') msg = '⚠️ ' + esc(f.note || 'render failed');
    else {
      msg = (f.has_image ? '✅ floor ready' : 'procedural (no floor)')
          + (f.enabled ? ' · shown under interiors' : ' · not shown (toggle off)');
      if (f.note) msg += ' · ' + esc(f.note);
    }
    el.innerHTML = msg;
    return f;
  } catch { return null; }
}
function _floorWatch() {
  const tick = setInterval(async () => {
    if (!document.getElementById('ws-floor-status')) { clearInterval(tick); return; }  // modal closed
    const f = await _floorStatus();
    if (f && !(f.generating || f.state === 'generating')) {
      clearInterval(tick);
      if (f.state === 'failed') toast?.(`🪵 Floor render failed — ${f.note || 'did not finish'}`);
      else if (f.has_image) {
        toast?.('🪵 Interior-floor texture ready');
        if (f.enabled && f.url && window.WM && WM.setFloorImage) WM.setFloorImage('/store/static/' + f.url);
      }
    }
  }, 3000);
}
async function worldFloorGen() {
  try {
    await api('/api/world/floor', { method: 'POST', body: '{}' });
    toast?.('🪵 Rendering the interior-floor texture — ~1–2 min on the GPU');
    _floorStatus(); _floorWatch();
  } catch (e) { toast?.(e.message); }
}
async function worldFloorRevert() {
  try {
    await api('/api/world/floor', { method: 'DELETE' });
    toast?.('🗑 Floor texture dropped — procedural per-type tint floor is back');
    if (window.WM && WM.setFloorImage) WM.setFloorImage(null);
    _floorStatus();
  } catch (e) { toast?.(e.message); }
}
async function worldFloorToggle(on) {
  try {
    await api('/api/settings', { method: 'PATCH', body: JSON.stringify({ world_floor_image_enabled: on ? '1' : '0' }) });
    toast?.(on ? '🪵 Generated floor will be shown under interiors when present' : '🪵 Floor hidden — procedural per-type tint shown');
    const f = await _floorStatus();
    if (window.WM && WM.setFloorImage) {
      if (on && f && f.has_image && f.url) WM.setFloorImage('/store/static/' + f.url);
      else if (!on) WM.setFloorImage(null);
    }
  } catch (e) { toast?.(e.message); }
}
window.worldTerrainGen = worldTerrainGen; window.worldTerrainRevert = worldTerrainRevert;
window.worldTerrainGenLayout = worldTerrainGenLayout;
window.worldTerrainToggle = worldTerrainToggle;

// 🌙 Moon — mirrors the floor controls. The moon layer + generated texture (world_moon.py).
async function _moonStatus() {
  const el = document.getElementById('ws-moon-status');
  if (!el) return null;
  try {
    const m = await api('/api/world/moon');
    const cbE = document.getElementById('ws_world_moon_enabled');
    if (cbE && document.activeElement !== cbE) cbE.checked = m.enabled !== false;
    const cbD = document.getElementById('ws_world_moon_daytime');
    if (cbD && document.activeElement !== cbD) cbD.checked = !!m.daytime;
    const busy = !!(m.generating || m.state === 'generating');
    const gen = document.getElementById('ws-moon-gen'), regen = document.getElementById('ws-moon-regen');
    if (gen) gen.style.display = m.has_image ? 'none' : '';
    if (regen) regen.style.display = m.has_image ? '' : 'none';
    const thumb = document.getElementById('ws-moon-thumb');
    if (thumb) { if (m.has_image && m.url) { thumb.src = '/store/static/' + m.url; thumb.style.display = ''; } else thumb.style.display = 'none'; }
    let msg;
    if (busy) msg = '⏳ rendering on the GPU… (~1–2 min)';
    else if (m.state === 'failed') msg = '⚠️ ' + esc(m.note || 'render failed');
    else msg = (m.has_image ? '✅ moon texture ready' : 'procedural moon (no texture)')
             + (m.enabled ? '' : ' · hidden (toggle off)') + (m.daytime ? ' · day-preview on' : '');
    el.innerHTML = msg;
    return m;
  } catch { return null; }
}
function _moonWatch() {
  const tick = setInterval(async () => {
    if (!document.getElementById('ws-moon-status')) { clearInterval(tick); return; }
    const m = await _moonStatus();
    if (m && !(m.generating || m.state === 'generating')) {
      clearInterval(tick);
      if (m.state === 'failed') toast?.(`🌙 Moon render failed — ${m.note || 'did not finish'}`);
      else if (m.has_image) {
        toast?.('🌙 Moon texture ready');
        if (m.url && window.WSKY && WSKY.setMoonImage) WSKY.setMoonImage('/store/static/' + m.url);
      }
    }
  }, 3000);
}
async function worldMoonGen() {
  try { await api('/api/world/moon', { method: 'POST', body: '{}' });
        toast?.('🌙 Rendering the moon texture — ~1–2 min on the GPU'); _moonStatus(); _moonWatch(); }
  catch (e) { toast?.(e.message); }
}
async function worldMoonRevert() {
  try { await api('/api/world/moon', { method: 'DELETE' });
        toast?.('🗑 Moon texture dropped — procedural cratered disc is back');
        if (window.WSKY && WSKY.setMoonImage) WSKY.setMoonImage(null); _moonStatus(); }
  catch (e) { toast?.(e.message); }
}
async function worldMoonToggle(on) {
  try { await api('/api/settings', { method: 'PATCH', body: JSON.stringify({ world_moon_enabled: on ? '1' : '0' }) });
        window._wskyMoonOn = !!on;
        toast?.(on ? '🌙 Moon shown at night' : '🌙 Moon hidden'); }
  catch (e) { toast?.(e.message); }
}
async function worldMoonDayToggle(on) {
  try { await api('/api/settings', { method: 'PATCH', body: JSON.stringify({ world_moon_daytime: on ? '1' : '0' }) });
        window._wskyMoonDay = !!on;
        toast?.(on ? '🌙 Moon now previews in daylight too' : '🌙 Moon back to night-only'); }
  catch (e) { toast?.(e.message); }
}
window.worldMoonGen = worldMoonGen; window.worldMoonRevert = worldMoonRevert;
window.worldMoonToggle = worldMoonToggle; window.worldMoonDayToggle = worldMoonDayToggle;

// 🏠 Roof cutaway slider — live-preview updates the renderer hook immediately; onchange
// persists it. Applies instantly (the render loop reads window._wmRoofFade every frame).
function worldRoofFadePreview(v) {
  const f = parseFloat(v); if (!isFinite(f) || f <= 0) return;
  window._wmRoofFade = f;
  const el = document.getElementById('ws-roof-fade-val'); if (el) el.textContent = f.toFixed(2) + '×';
}
async function worldRoofFadeSave(v) {
  const f = parseFloat(v); if (!isFinite(f) || f <= 0) return;
  worldRoofFadePreview(f);
  try { await api('/api/settings', { method: 'PATCH', body: JSON.stringify({ world_roof_fade_zoom: String(f) }) });
        toast?.(`🏠 Roofs now reveal interiors at ${f.toFixed(2)}× zoom`); }
  catch (e) { toast?.(e.message); }
}
window.worldRoofFadePreview = worldRoofFadePreview; window.worldRoofFadeSave = worldRoofFadeSave;
async function worldSaveSettings() {
  const keys = ['world_llm_enabled', 'world_llm_interval_min', 'world_active_start', 'world_active_end',
    'world_meetings_enabled', 'world_meeting_interval_min', 'world_incidents_enabled',
    'world_vision_enabled', 'world_vision_candidates', 'world_vision_retries', 'world_vision_min_score',
    'world_min_item_cost', 'world_allow_free', 'world_min_price_cents', 'world_max_discount_pct',
    'world_require_review', 'world_prop_model', 'world_prop_lora', 'world_crypto_mining_enabled',
    'world_music_lyrics', 'world_leader_upgrades', 'world_leader_upgrade_hours',
    'world_tileset_auto', 'world_tileset_auto_min'];
  const s = {};
  keys.forEach(k => { const el = document.getElementById('ws_' + k); if (el) s[k] = el.type === 'checkbox' ? (el.checked ? '1' : '0') : el.value; });
  try { await api('/api/world/settings', { method: 'POST', body: JSON.stringify({ settings: s }) });
        toast?.('Company settings saved ✓'); worldCloseModal(); }
  catch (e) { toast?.(e.message); }
}
