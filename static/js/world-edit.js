/* ══ THE COMPANY — play-god map edit mode ══
   Split out of tab-world.js for modularity. Runs in shared global scope
   (classic script, not a module) — same as world-map.js / world-assets.js. */

/* ── play-god edit mode ── */
function _updateEditSel() {
  const el = document.getElementById('world-editsel'); if (!el) return;
  const b = _edit.sel != null ? WM.buildings.find(x => x.id === _edit.sel) : null;
  el.textContent = b ? `selected: ${b.label || b.kind} (${b.w}×${b.h}) — drag to move, resize/delete →` : '— drag a PERSON onto a work node to put them to work, or anywhere to post them · drag objects to move · Erase to remove';
}
function _placeAdd(tile, w) {
  const a = _edit.add;
  if (window.WAU && WAU.sfxAt && w) WAU.sfxAt('place', w.x, w.y, 150);                          // thunk where it lands
  if (a === 'erase') { _eraseAt(w, tile); return; }                                            // stay in erase mode
  if (a && a.indexOf('decor:') === 0) { if (w) { WM.addDecor(w.x, w.y, a.slice(6)); WM.scheduleSave(); } return; }   // place many
  if (a && a.indexOf('node:') === 0) { WM.addNode(a.slice(5), tile.col, tile.row); WM.scheduleSave(); toast?.(`Placed ${a.slice(5)} node`); return; }
  if (a && a.indexOf('landmark:') === 0) { WM.addLandmark(a.slice(9), tile.col, tile.row); WM.scheduleSave(); return; }
  if (a && a.indexOf('interior:') === 0) {                                                    // Layer-3: place INSIDE a building (stay in mode)
    const b = WM.buildingAtTile(tile.col, tile.row);
    if (b && WM.addInterior(b.id, tile.col, tile.row, a.slice(9))) { WM.scheduleSave(); }
    else toast?.('Place interior items inside a building (doors may sit on the wall)');
    return;
  }
  WM.addBuilding(a, tile.col, tile.row); WM.scheduleSave();                                     // buildings: place one, exit
  toast?.(`Added ${a}`); _edit.add = null;
  document.getElementById('world-canvas').style.cursor = 'grab';
}
/* Erase whatever sits under the cursor — decor, node, landmark, then building. */
function _eraseAt(w, tile) {
  let i;
  if (w && (i = WM.decorIndexNear(w.x, w.y)) >= 0) { WM.pickDecor(i); WM.scheduleSave(); toast?.('Removed decor'); return; }
  if (w && (i = WM.nodeIndexNear(w.x, w.y)) >= 0) { WM.removeNodeAt(i); WM.scheduleSave(); toast?.('Removed node'); return; }
  if (w && (i = WM.landmarkIndexNear(w.x, w.y)) >= 0) { WM.removeLandmarkAt(i); WM.scheduleSave(); toast?.('Removed landmark'); return; }
  const b = WM.buildingAtTile(tile.col, tile.row);
  // a Layer-3 interior item on this tile is erased BEFORE the building itself
  if (b && WM.removeInteriorAt(b.id, tile.col, tile.row)) { WM.scheduleSave(); toast?.('Removed interior item'); return; }
  if (b) { WM.deleteBuilding(b.id); WM.scheduleSave(); if (_edit.sel === b.id) { _edit.sel = null; _updateEditSel(); } toast?.('Removed building'); return; }
  toast?.('Nothing here to erase');
}
function worldToggleEdit() {
  _edit.on = !_edit.on; _edit.sel = null; _edit.add = null; _edit.drag = null; _edit.ghost = null; _edit.addGhost = null;
  _edit.pdrag = null; _edit.pghost = null; _edit.agentDrag = null; _edit.agentGhost = null;
  document.getElementById('world-editbar').style.display = _edit.on ? 'flex' : 'none';
  document.getElementById('world-god-btn').style.background = _edit.on ? '#5b3ea8' : '';
  const cv = document.getElementById('world-canvas'); if (cv) cv.style.cursor = _edit.on ? 'pointer' : 'grab';
  _updateEditSel();
}
function worldEditResize(dw, dh) { if (_edit.sel != null) { WM.resizeBuilding(_edit.sel, dw, dh); WM.scheduleSave(); _updateEditSel(); } else toast?.('Select a building first'); }
function worldEditAdd(kind) { _edit.add = kind; toast?.(`Click on the map to place a ${kind}`); const cv = document.getElementById('world-canvas'); if (cv) cv.style.cursor = 'crosshair'; }
function worldEditDelete() { if (_edit.sel != null) { WM.deleteBuilding(_edit.sel); WM.scheduleSave(); _edit.sel = null; _updateEditSel(); toast?.('Deleted'); } else toast?.('Select a building first'); }
/* Auto-save toggle — owner's "gates get a toggle" preference. On → hand edits
   persist (debounced) without 💾; off → only the 💾 Save button persists. */
function worldToggleAutosave(on) {
  window._wmLayoutAutosave = !!on;
  api('/api/settings', { method: 'PATCH', body: JSON.stringify({ world_layout_autosave: on ? '1' : '0' }) }).catch(() => {});
  toast?.(on ? 'Auto-save on — edits persist' : 'Auto-save off — use 💾 to save');
}
window.worldToggleAutosave = worldToggleAutosave;
/* RCT-style: drop a picked-up person onto a task (work node) or a free spot. */
async function worldDropAgent(id, name, assign) {
  try {
    await api(`/api/world/agent/${id}/assign`, { method: 'POST', body: JSON.stringify(assign) });
    toast?.(assign.kind === 'skill' ? `✋ ${name} → put to work at the ${assign.location}` : `✋ ${name} posted to that spot`);
    if (typeof _pollWorld === 'function') _pollWorld();
  } catch (e) { toast?.(e.message); }
}
window.worldDropAgent = worldDropAgent;

/* ── movable placements: agents' bought furniture is draggable in god mode ── */
function _placementNear(x, y) {
  const list = window._placePos;                      // rebuilt each frame by _drawPlacements
  if (!list || !list.length) return null;
  let best = null, bd = 12;
  for (const e of list) { const d = Math.hypot(e.x - x, e.y - y); if (d < bd) { bd = d; best = e; } }
  return best;
}
async function worldMovePlacement(p, x, y) {
  p.ox = x; p.oy = y;                                 // optimistic — draws at the new spot right away
  if (window.WAU && WAU.sfxAt) WAU.sfxAt('place', x, y, 200);
  try {
    await api('/api/world/placement/move', { method: 'POST', body: JSON.stringify(
      { agent_key: p.agent_key, spot: p.spot, slot: p.slot, ox: x, oy: y }) });
    toast?.(`${p.emoji || ''} ${p.item} moved`);
  } catch (e) { toast?.(e.message); }
}
window.worldMovePlacement = worldMovePlacement;

/* ── movable structures: agent-built structures are draggable in god mode ── */
function _structureNear(x, y) {
  const list = window._structPos;                     // rebuilt each frame by _drawConstruction
  if (!list || !list.length) return null;
  let best = null, bd = 14;
  for (const e of list) { const d = Math.hypot(e.x - x, e.y - y); if (d < bd) { bd = d; best = e; } }
  return best;
}
async function worldMoveStructure(s, x, y) {
  s.ox = x; s.oy = y;                                 // optimistic — renders at the new spot right away
  if (window.WAU && WAU.sfxAt) WAU.sfxAt('place', x, y, 200);
  try {
    await api('/api/world/structure/move', { method: 'POST', body: JSON.stringify(
      { id: s.id, x, y }) });
    toast?.(`${s.name || 'Structure'} moved`);
  } catch (e) { toast?.(e.message); }
}
window.worldMoveStructure = worldMoveStructure;

async function worldEditSave() {
  try { await api('/api/world/layout', { method: 'POST', body: JSON.stringify({ layout: WM.exportLayout() }) }); toast?.('🗺️ Map saved'); }
  catch (e) { toast?.(e.message); }
}
async function worldEditReset() {
  if (!confirm('Reset the map to the procedural layout? Your edits will be lost.')) return;
  try { await api('/api/world/layout', { method: 'POST', body: JSON.stringify({ layout: null }) }); WM.build(); _edit.sel = null; _updateEditSel(); toast?.('Map reset'); }
  catch (e) { toast?.(e.message); }
}
