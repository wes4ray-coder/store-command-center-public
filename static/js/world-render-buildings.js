/* ══ THE COMPANY — building sprites, HQ interior, doors, depth, roofs, lights, wall art ══
   Split out of world-render.js (core keeps the loop + shared state). Runs in
   shared global scope (classic script, not a module). Loads right after
   world-render.js, before world-ui.js. Code moved verbatim. */


/* Real building sprites (Kenney) over the procedural lots — so shops/homes/venues
   read as actual buildings. Live-drawn (async sprites); box stays as the fallback. */
const _BLD_SPRITE = { bar: 'bld_tavern', arcade: 'bld_arcade', cafe: 'bld_cafe', tv: 'bld_shop_1',
                      lounge: 'bld_shop_1', church: 'bld_church', library: 'bld_library',
                      townhall: 'bld_townhall', exec: 'bld_shop_2', gas: 'bld_shop_2' };
function _bldSprite(b) {
  if (b.loc && _BLD_SPRITE[b.loc]) return _BLD_SPRITE[b.loc];
  if (b.kind === 'house') return (b.id % 2) ? 'bld_house_2' : 'bld_house_1';
  if (b.kind === 'shop') return (b.id % 2) ? 'bld_shop_2' : 'bld_shop_1';
  return null;
}
function _drawBuildingSprites(ctx) {
  if (!(window.WA && WA.hasSprite)) return;
  // exterior-shell layer — fades with the roofs so zooming in reveals the baked
  // interiors (bed/kitchen/office) instead of a flat building image on top.
  const alpha = _roofAlpha();
  if (alpha <= 0.02) return;
  const TL = WM.TILE;
  ctx.save();
  ctx.globalAlpha = alpha;
  for (const b of (WM.buildings || [])) {
    if (b.kind === 'hq') continue;                         // HQ keeps its furnished interior
    const name = _bldSprite(b); if (!name || !WA.hasSprite(name)) continue;
    const cx = (b.c + b.w / 2) * TL, baseY = (b.r + b.h) * TL - 2;
    const targetH = Math.min(b.h * TL * 1.02, b.w * TL * 1.1);   // fill the lot, keep aspect
    WA.drawSprite(ctx, name, cx, baseY, targetH);
  }
  ctx.restore();
}

/* Department nameplate + themed gear inside each HQ room (drawn live so the async
   Kenney sprites appear once loaded; falls back to a per-dept emoji). */
const _DEPT_EMOJI = { storefront: '🛒', image: '🖼️', video: '🎥', audio: '🔊', models3d: '🖨️',
                      publishing: '📚', devlab: '💻', resell: '📦', trends: '📈',
                      portal: '🌐', social: '📣', finance: '💰', netsec: '🛡️' };
const _DEPT_LABEL = { storefront: 'Store', image: 'Image', video: 'Video', audio: 'Audio', models3d: '3D',
                      publishing: 'Publish', devlab: 'Dev', resell: 'Resell', trends: 'Trends',
                      portal: 'Portal', social: 'Social', finance: 'Finance', netsec: 'NetSec' };
function _drawHQInterior(ctx) {
  const rooms = WM.hqRooms || []; if (!rooms.length) return;
  for (const room of rooms) {
    // small nameplate at the top of the room
    const t = _DEPT_LABEL[room.dept] || room.dept;
    ctx.font = 'bold 6px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
    const w = ctx.measureText(t).width, nx = room.x, ny = room.y0 + 8;
    ctx.fillStyle = 'rgba(10,14,22,.72)'; ctx.fillRect(nx - w / 2 - 2, ny - 6, w + 4, 8);
    ctx.fillStyle = room.tint || '#cfe0ff'; ctx.fillRect(nx - w / 2 - 2, ny - 6, 1.5, 8);
    ctx.fillStyle = '#e6eefc'; ctx.fillText(t, nx, ny);
    // themed gear (dept identity) — real extracted sprite if present, else a per-dept emoji.
    // Sits in the upper-middle, above the machine row (which draws at ~0.60 of the room).
    const gx = room.x, gy = room.y0 + room.h * 0.40, gh = Math.min(room.h * 0.42, 18);
    if (window.WA && WA.hasSprite && WA.hasSprite('gear_' + room.dept)) {
      WA.drawSprite(ctx, 'gear_' + room.dept, gx, gy + gh / 2, gh);
    } else {
      ctx.font = Math.round(gh) + 'px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText(_DEPT_EMOJI[room.dept] || '⚙️', gx, gy); ctx.textBaseline = 'alphabetic';
    }
  }
}

/* ── door triggers: doors swing open when anyone comes near ─────────────────── */
const _doorOpen = {};                                        // building id → open?
function _doorTile(b) {
  if (b.door === 'N') return { c: b.c + (b.w / 2 | 0), r: b.r };
  if (b.door === 'W') return { c: b.c, r: b.r + (b.h / 2 | 0) };
  if (b.door === 'E') return { c: b.c + b.w - 1, r: b.r + (b.h / 2 | 0) };
  return { c: b.c + (b.w / 2 | 0), r: b.r + b.h - 1 };
}
function _drawDoors(ctx) {
  const T = WM.TILE, R = T * 1.5;
  const walkers = Object.values(_sprites).map(s => ({ x: s.px, y: s.py }));
  if (window.WN && WN.positions) walkers.push(...WN.positions());
  for (const b of (WM.buildings || [])) {
    const d = _doorTile(b), dx = d.c * T, dy = d.r * T, cx = dx + T / 2, cy = dy + T / 2;
    let open = false;
    for (const w of walkers) {
      if (Math.abs(w.x - cx) < R && Math.abs(w.y - cy) < R) { open = true; break; }
    }
    if (open && !_doorOpen[b.id] && window.WAU) {
      (WAU.sfxAt || WAU.sfx)('door', cx, cy, 900);   // listener is set each frame in _drawWorld
    }
    _doorOpen[b.id] = open;
    if (!open) continue;                                     // baked closed door shows
    // swing open: clear the doorway to floor + door panel against the jamb
    ctx.fillStyle = '#7a5230'; ctx.fillRect(dx + 3, dy + 2, T - 6, T - 3);
    ctx.fillStyle = 'rgba(0,0,0,.25)'; ctx.fillRect(dx + 3, dy + 2, T - 6, 2);
    ctx.fillStyle = '#5b3a22';                                // the swung panel
    if (b.door === 'W' || b.door === 'E') ctx.fillRect(dx + (b.door === 'W' ? 2 : T - 5), dy + 1, 3, T * 0.55);
    else ctx.fillRect(dx + 1, dy + (b.door === 'N' ? 2 : T - 5), T * 0.55, 3);
  }
}

/* Drop shadow + colour-varied eaves trim on every lot, so buildings read as
   standing objects instead of flat outlines (the "everything looks the same
   beige box" fix). Pure overlay — the baked terrain stays untouched. */
const _TRIM_HUES = [14, 205, 355, 95, 265, 30, 180, 320];
function _drawBuildingDepth(ctx) {
  const TL = WM.TILE;
  for (const b of (WM.buildings || [])) {
    const x = b.c * TL, y = b.r * TL, w = b.w * TL, h = b.h * TL;
    // soft cast shadow bottom + right
    ctx.fillStyle = 'rgba(0,0,0,.22)';
    ctx.fillRect(x + 3, y + h, w, 4);
    ctx.fillRect(x + w, y + 4, 4, h - 1);
    // eaves band along the top wall, hue varied per building
    const hue = _TRIM_HUES[(b.id || 0) % _TRIM_HUES.length];
    ctx.fillStyle = `hsla(${hue},45%,42%,.85)`;
    ctx.fillRect(x, y - 2, w, 4);
    ctx.fillStyle = `hsla(${hue},50%,58%,.9)`;
    ctx.fillRect(x, y - 2, w, 1.5);
  }
}

/* ── pseudo-3D roofs ──────────────────────────────────────────────────────────
   The "3D pixel" pass: every building gets a gabled roof + a front wall face
   with windows and a door, as if the camera looks down at a standing building.
   Zoomed OUT the town reads as a real pixel village; zooming IN fades the roofs
   away so the interiors (desks, furniture, agents) the sim depends on stay
   visible. Drawn after agents — anyone indoors is naturally "under the roof". */
const WALL_H = 14, ROOF_OV = 3;
const _ROOF_PAL = {
  house:    [['#a84f35', '#7f3c28', '#c06a4a'], ['#5d6a7c', '#485460', '#75859a'],
             ['#5f7d49', '#4a6338', '#77985c'], ['#8a6a42', '#6d5334', '#a5854f']],
  shop:     [['#7a4a8a', '#5d3869', '#9a67ad'], ['#3f7fb0', '#2f6089', '#5b9cc9'], ['#b06a3f', '#8a4f2c', '#c98b5b']],
  leisure:  [['#a0623f', '#7c4a2f', '#bd8058']],
  church:   [['#6b5a8f', '#524370', '#8875ad']],
  library:  [['#4c7a68', '#3a5f50', '#639a85']],
  townhall: [['#a98a3f', '#846b2f', '#c4a557']],
  exec:     [['#8f4545', '#6d3434', '#ad6060']],
};
const _FACE_PAL = ['#d9c9a8', '#cbb491', '#c2c8ce', '#d1bfae'];
function _roofAlpha() {
  const s = WM.camera.scale;
  return s <= 1.6 ? 1 : s >= 2.4 ? 0 : 1 - (s - 1.6) / 0.8;
}
function _drawRoofs(ctx) {
  const alpha = _roofAlpha();
  if (alpha <= 0.02) return;
  const winter = _worldState?.orchestra?.season === 'winter';
  const now = performance.now();
  ctx.save();
  ctx.globalAlpha = alpha;
  for (const b of (WM.buildings || [])) {
    const T = WM.TILE, bx = b.c * T, by = b.r * T, bw = b.w * T, bh = b.h * T;
    if (b.kind === 'hq') { _flatRoof(ctx, bx, by, bw, bh, winter); continue; }
    const pal = _ROOF_PAL[b.kind] || _ROOF_PAL.house;
    const [main, dark, light] = pal[(b.id || 0) % pal.length];
    const faceTop = by + bh - WALL_H;
    // FRONT WALL FACE (the vertical surface you'd see standing before the building)
    const face = _FACE_PAL[(b.id || 0) % _FACE_PAL.length];
    ctx.fillStyle = face; ctx.fillRect(bx, faceTop, bw, WALL_H);
    ctx.fillStyle = 'rgba(0,0,0,.25)'; ctx.fillRect(bx, by + bh - 2, bw, 2);          // base shadow
    const nwin = Math.max(1, Math.min(4, b.w - 3));
    for (let i = 0; i < nwin; i++) {                                                  // windows on the face
      const wx = bx + (i + 0.5) * bw / nwin - 3;
      ctx.fillStyle = '#2c3a52'; ctx.fillRect(wx, faceTop + 4, 6, 6);
      ctx.fillStyle = 'rgba(190,220,255,.5)'; ctx.fillRect(wx + 1, faceTop + 5, 2, 2);
      ctx.fillStyle = '#efe6d2'; ctx.fillRect(wx - 1, faceTop + 10, 8, 1);            // sill
    }
    const dx = bx + bw / 2 - 4;                                                       // door, centred
    ctx.fillStyle = '#5b3a22'; ctx.fillRect(dx, faceTop + 4, 8, WALL_H - 5);
    ctx.fillStyle = '#734a2c'; ctx.fillRect(dx, faceTop + 4, 8, 2);
    ctx.fillStyle = '#e8c14a'; ctx.fillRect(dx + 6, faceTop + 9, 1.5, 1.5);
    // GABLED ROOF above the face (overhangs the footprint slightly)
    const rTop = by - WALL_H - ROOF_OV, rH = (faceTop + 2) - rTop, ridge = rTop + rH * 0.30;
    ctx.fillStyle = dark; ctx.fillRect(bx - ROOF_OV, rTop, bw + 2 * ROOF_OV, ridge - rTop);       // back slope (shaded)
    ctx.fillStyle = main; ctx.fillRect(bx - ROOF_OV, ridge, bw + 2 * ROOF_OV, faceTop + 2 - ridge); // front slope
    ctx.fillStyle = 'rgba(0,0,0,.14)';                                                 // shingle bands
    for (let y = ridge + 4; y < faceTop; y += 5) ctx.fillRect(bx - ROOF_OV, y, bw + 2 * ROOF_OV, 1);
    ctx.fillStyle = light; ctx.fillRect(bx - ROOF_OV, ridge - 1, bw + 2 * ROOF_OV, 2);  // lit ridge cap
    ctx.fillStyle = 'rgba(0,0,0,.30)'; ctx.fillRect(bx - ROOF_OV, faceTop, bw + 2 * ROOF_OV, 2);  // eaves shadow
    ctx.fillStyle = 'rgba(0,0,0,.18)';                                                 // side trim
    ctx.fillRect(bx - ROOF_OV, rTop, 2, rH + 2); ctx.fillRect(bx + bw + ROOF_OV - 2, rTop, 2, rH + 2);
    if (winter) { ctx.fillStyle = 'rgba(235,240,248,.55)'; ctx.fillRect(bx - ROOF_OV, rTop, bw + 2 * ROOF_OV, faceTop - rTop); }
    // chimney + smoke: hearth homes + food shops feel alive
    const hearth = (b.kind === 'house' && (b.id || 0) % 3 === 2) ||
                   (b.kind === 'shop' && ['Diner', 'Bakery', 'Deli'].includes(b.label));
    if (hearth) {
      const cx = bx + bw * 0.72;
      ctx.fillStyle = '#6f6a63'; ctx.fillRect(cx - 2.5, rTop - 5, 6, 9);
      ctx.fillStyle = '#4d4943'; ctx.fillRect(cx - 3.5, rTop - 6, 8, 2);
      for (let k = 0; k < 3; k++) {                                                   // smoke puffs
        const t = ((now / 1400) + k / 3 + ((b.id || 0) * 0.13)) % 1;
        ctx.fillStyle = `rgba(210,214,222,${(1 - t) * 0.45})`;
        ctx.beginPath();
        ctx.arc(cx + Math.sin(t * 5 + b.id) * 3, rTop - 8 - t * 14, 1.5 + t * 2.6, 0, 6.283);
        ctx.fill();
      }
    }
    if (b.kind === 'church') {                                                        // steeple + cross
      const sx = bx + bw / 2;
      ctx.fillStyle = dark; ctx.fillRect(sx - 4, rTop - 12, 8, 12);
      ctx.fillStyle = light; ctx.beginPath(); ctx.moveTo(sx - 5, rTop - 12); ctx.lineTo(sx, rTop - 19); ctx.lineTo(sx + 5, rTop - 12); ctx.closePath(); ctx.fill();
      ctx.strokeStyle = '#e8dfc8'; ctx.lineWidth = 1.4;
      ctx.beginPath(); ctx.moveTo(sx, rTop - 26); ctx.lineTo(sx, rTop - 20); ctx.moveTo(sx - 2.5, rTop - 24); ctx.lineTo(sx + 2.5, rTop - 24); ctx.stroke();
    }
  }
  ctx.restore();
}

/* THE COMPANY HQ gets a modern flat roof: parapet, skylight grid, AC units and a
   logo stripe — the corporate island in a gabled village. */
function _flatRoof(ctx, bx, by, bw, bh, winter) {
  const faceTop = by + bh - WALL_H;
  ctx.fillStyle = '#3c4250'; ctx.fillRect(bx - 2, by - WALL_H - 2, bw + 4, bh + 4); // slab (footprint shifted up by wall height)
  ctx.fillStyle = '#4a5162'; ctx.fillRect(bx + 2, by - WALL_H + 2, bw - 4, bh - 4);
  ctx.strokeStyle = '#5a6274'; ctx.lineWidth = 2; ctx.strokeRect(bx - 1, by - WALL_H - 1, bw + 2, bh + 2);  // parapet
  // face: glass-and-steel front
  ctx.fillStyle = '#2e3646'; ctx.fillRect(bx, faceTop, bw, WALL_H);
  for (let i = 0; i < Math.floor(bw / 14); i++) {
    ctx.fillStyle = 'rgba(140,190,240,.35)'; ctx.fillRect(bx + 3 + i * 14, faceTop + 3, 9, 8);
  }
  // skylights over the atrium
  for (let gy = 0; gy < 2; gy++) for (let gx = 0; gx < 4; gx++) {
    ctx.fillStyle = 'rgba(150,200,250,.28)';
    ctx.fillRect(bx + bw * 0.14 + gx * bw * 0.19, by - WALL_H + bh * 0.18 + gy * bh * 0.34, bw * 0.13, bh * 0.2);
    ctx.strokeStyle = 'rgba(20,26,38,.5)'; ctx.lineWidth = 1;
    ctx.strokeRect(bx + bw * 0.14 + gx * bw * 0.19, by - WALL_H + bh * 0.18 + gy * bh * 0.34, bw * 0.13, bh * 0.2);
  }
  // AC units + logo stripe
  ctx.fillStyle = '#8a919f'; ctx.fillRect(bx + bw - 26, by - WALL_H + 6, 9, 7); ctx.fillRect(bx + bw - 14, by - WALL_H + 6, 9, 7);
  ctx.fillStyle = 'rgba(0,0,0,.3)'; ctx.fillRect(bx + bw - 26, by - WALL_H + 9, 9, 1); ctx.fillRect(bx + bw - 14, by - WALL_H + 9, 9, 1);
  ctx.fillStyle = '#3f7fb0'; ctx.fillRect(bx + 6, by - WALL_H + 5, bw * 0.22, 4);
  if (winter) { ctx.fillStyle = 'rgba(235,240,248,.45)'; ctx.fillRect(bx - 2, by - WALL_H - 2, bw + 4, bh + 4); }
}
function _drawLights(ctx, canvas) {
  const L = _daylight(_worldState?.clock_hour ?? 12);
  if (L.dark <= 0.01) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 2), cam = WM.camera;
  // 1) darkening tint over the whole viewport (screen space)
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.globalCompositeOperation = 'source-over';
  ctx.fillStyle = `rgba(${L.tint[0]},${L.tint[1]},${L.tint[2]},${L.dark})`;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  // 2) light sources punch through (world space, additive)
  ctx.setTransform(dpr * cam.scale, 0, 0, dpr * cam.scale, dpr * cam.x, dpr * cam.y);
  ctx.globalCompositeOperation = 'lighter';
  const glow = Math.min(1, L.dark * 1.6);
  ctx.fillStyle = `rgba(255,205,130,${0.07 * glow})`;               // faint warm interior wash
  for (const b of WM.buildings) ctx.fillRect((b.c + 1) * WM.TILE, (b.r + 1) * WM.TILE, (b.w - 2) * WM.TILE, (b.h - 2) * WM.TILE);
  // lit WINDOWS along each building's bottom wall — the cozy village-at-night look
  const TL = WM.TILE, flick = performance.now() / 900;
  for (const b of WM.buildings) {
    const nwin = Math.max(1, Math.min(4, (b.w - 2) | 0));
    for (let i = 0; i < nwin; i++) {
      if (((b.id || 0) * 31 + i * 17) % 5 === 0) continue;          // some windows stay dark
      const wx = (b.c + 1 + (i + 0.5) * (b.w - 2) / nwin) * TL;
      const wy = (b.r + b.h - 0.5) * TL;
      const a = (0.5 + 0.08 * Math.sin(flick + i + (b.id || 0))) * glow;
      ctx.fillStyle = `rgba(255,214,140,${a})`;
      ctx.fillRect(wx - 2.5, wy - 4, 5, 5);
      const g = ctx.createRadialGradient(wx, wy, 1, wx, wy, 13);
      g.addColorStop(0, `rgba(255,214,140,${0.28 * glow})`); g.addColorStop(1, 'rgba(255,214,140,0)');
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(wx, wy, 13, 0, 6.283); ctx.fill();
    }
  }
  for (const d of WM.decor) {                                       // lamps + fountain glow
    if (d.kind !== 'lamp' && d.kind !== 'fountain') continue;
    const cx = d.x, cy = d.kind === 'lamp' ? d.y - 9 : d.y, R = d.kind === 'lamp' ? 26 : 16;
    const g = ctx.createRadialGradient(cx, cy, 1, cx, cy, R);
    g.addColorStop(0, `rgba(255,225,150,${(d.kind === 'lamp' ? 0.6 : 0.3) * glow})`); g.addColorStop(1, 'rgba(255,225,150,0)');
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(cx, cy, R, 0, 6.283); ctx.fill();
  }
  ctx.globalCompositeOperation = 'source-over';
}

/* Real store-generated images, framed and hung on house + HQ-department walls.
   Loaded lazily (async); only drawn once the image is available. */
const _artCache = {};
function _artImg(url) {
  let im = _artCache[url];
  if (im === undefined) { im = new Image(); im.onerror = () => { _artCache[url] = null; }; im.src = url; _artCache[url] = im; }
  return (im && im.complete && im.naturalWidth) ? im : null;
}
function _drawWallArt(ctx) {
  const art = _worldState && _worldState.art;
  if (!art || !art.length) return;
  const TL = WM.TILE;
  const frame = (im, fx, fy, fw, fh) => {
    ctx.fillStyle = '#3a2a1a'; ctx.fillRect(fx - 1.5, fy - 1.5, fw + 3, fh + 3);
    ctx.imageSmoothingEnabled = false; ctx.drawImage(im, fx, fy, fw, fh);
    ctx.strokeStyle = '#caa06a'; ctx.lineWidth = 1; ctx.strokeRect(fx, fy, fw, fh);
  };
  for (const b of (WM.buildings || [])) {
    if (b.kind !== 'house') continue;
    const n = 1 + (b.id % 2);                                   // 1–2 pictures per home
    for (let k = 0; k < n; k++) {
      const im = _artImg(art[(b.id + k) % art.length]); if (!im) continue;
      frame(im, (b.c + 1.4 + k * 2.1) * TL, (b.r + 1.05) * TL, TL * 1.25, TL * 0.95);
    }
  }
  for (let i = 0; i < (WM.hqRooms || []).length; i++) {          // one per HQ department room
    const rm = WM.hqRooms[i], im = _artImg(art[i % art.length]); if (!im) continue;
    const fw = TL * 1.05, fh = TL * 0.8;
    frame(im, rm.x - fw / 2, rm.y - TL * 1.5, fw, fh);
  }
}
