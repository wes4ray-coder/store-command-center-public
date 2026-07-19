'use strict';
/* ══════════════════════════════════════════════════════════════════════════
   THE COMPANY — tile world engine (v3: editable city).
   A large grid world with THE COMPANY HQ dead-centre. Terrain is split into a
   BASE layer (grass/roads/trees/parks/plaza) generated once, and a BUILDINGS
   layer stamped on top by rasterize(). That split is what makes "play god" edit
   mode possible: move/resize/add/delete a building and just re-rasterize. A*
   pathfinding + pan/zoom camera. Layout edits persist via /api/world/layout.
   ══════════════════════════════════════════════════════════════════════════ */
window.WM = (function () {
  const TILE = 20, COLS = 132, ROWS = 104;   // expanded: wild outskirts ring the city (wildlife, hunting, room to grow)
  const W = COLS * TILE, H = ROWS * TILE;
  const T = { GRASS: 0, PATH: 1, FLOOR: 2, WALL: 3, TREE: 4, WATER: 5, PLAZA: 6, MOUNTAIN: 7 };
  const WALK_COST = { 0: 3, 1: 1, 2: 1, 6: 1.2 };   // MOUNTAIN/WATER/TREE/WALL absent → impassable
  const WALL_PX = Math.round(TILE * 0.5);            // 10 — themed per-building wall shell band (HALF the old 20px stone ring; collision T.WALL is unchanged)

  // ── DESIRE LINES: foot traffic wears grass → dirt → packed → cobbled road ──
  // Every walker bumps the tile it steps on; worn tiles get CHEAPER for A*, so
  // popular shortcuts reinforce themselves into real roads organically.
  let wear = {};                                  // "c,r" -> step count
  let wearDirty = {};                             // un-pushed increments (synced to backend)
  const WEAR_STAGES = [110, 320, 700];            // steps → dirt / packed / cobbled (slow — a trail is EARNED)
  const WEAR_COST = [3, 2.2, 1.6, 1.05];          // grass walk-cost by wear stage
  function bumpWear(c, r) {
    if (!inb(c, r) || grid[r][c] !== T.GRASS) return;
    if (Math.random() > 0.4) return;              // not every footstep scuffs — keeps the town green
    const k = c + ',' + r;
    wear[k] = Math.min(1200, (wear[k] || 0) + 1);
    wearDirty[k] = (wearDirty[k] || 0) + 1;
  }
  function wearStage(c, r) {
    const n = wear[c + ',' + r] || 0;
    return n >= WEAR_STAGES[2] ? 3 : n >= WEAR_STAGES[1] ? 2 : n >= WEAR_STAGES[0] ? 1 : 0;
  }
  function loadWear(obj) { if (obj && typeof obj === 'object') wear = { ...obj }; }
  function takeWearDirty() { const d = wearDirty; wearDirty = {}; return d; }

  let baseGrid = [];         // terrain WITHOUT buildings (grass/road/tree/park/plaza)
  let grid = [];             // baseGrid + stamped buildings (what pathfinding/render use)
  const locations = {};      // name → {col,row}
  let houseSlots = [];       // interior tiles for agent homes
  let buildings = [];        // editable descriptors {id,c,r,w,h,kind,loc,dept,label,color,door}
  let decor = [];            // sub-grid objects {x,y,kind}
  let landmarks = [];        // big pack sprites (park trees) {col,row,kind}
  let nodes = [];            // resource nodes {col,row,kind} for idle-skilling (woodcut/mine/farm/fish/build)
  let waterTiles = [];       // {col,row} of pond/water cells — animated live by the renderer
  let _terrainImg = null;    // Layer-2: one generated whole-world ground image (null = procedural per-tile)
  let _floorImg = null;      // Layer-2b: ONE shared interior-floor texture blitted under every building (null = procedural per-kind tint only)
  // Self-heal: browsers reclaim the backing store of large off-DOM canvases / decoded
  // images under memory pressure. The element refs stay valid (.complete === true) but
  // draw nothing, so terrain silently blanks after a while. We keep the SOURCE URLs so
  // reheal() can re-decode from scratch and re-bake without a page/browser restart.
  let _terrainUrl = null, _floorUrl = null;
  let _rehealing = false;
  // ── CHUNKED TERRAIN + LOD STREAMER ───────────────────────────────────────────
  // Instead of one giant 2640×2080 resident canvas (which browsers evict under memory
  // pressure and which can't scale to 4k/8k/moon maps), the ground is rendered as:
  //   • _overview — a small whole-map canvas (W/_OV) used when zoomed OUT, and as a
  //     cheap fallback UNDER full-res chunks that are still baking (so never blank);
  //   • _chunks   — full-res tiles baked ON DEMAND for the visible viewport when zoomed
  //     IN, and EVICTED once off-screen for a while. Memory stays flat regardless of map
  //     size because only ~what's on screen is ever resident. The moon map reuses this.
  let _overview = null;
  const _OV = 2;                                   // overview downscale (W/2×H/2 ≈ crisp to ~0.5×)
  let _structPass = false;                         // true only during the full pass that fills waterTiles/hqRooms/locations
  const _chunks = new Map();                       // "cx,cy" -> {cv, wx, wy, seen}
  const CHUNK_CW = 22, CHUNK_CH = 26;              // chunk size in TILES (440×520 px; 132/22=6 × 104/26=4 = 24, exact)
  const CHUNK_LOD = 0.5;                           // below this camera.scale → overview only; at/above → stream full-res chunks
  const CHUNK_EVICT_MS = 8000;                     // free a chunk unseen for this long
  const CHUNK_BUDGET = 2;                          // max chunk bakes per frame (no hitch)
  const camera = { x: 0, y: 0, scale: 1 };
  let _fitScale = 0.25;      // scale at which the whole map fits the viewport (set in fit()); the space/orbit bands key off this so they're viewport-independent
  let _nextId = 1;

  const inb = (c, r) => c >= 0 && r >= 0 && c < COLS && r < ROWS;
  const bset = (c, r, t) => { if (inb(c, r)) baseGrid[r][c] = t; };
  const bfill = (c0, r0, w, h, t) => { for (let r = r0; r < r0 + h; r++) for (let c = c0; c < c0 + w; c++) bset(c, r, t); };
  const region = (x0, y0, x1, y1, q) => (x0 < q.x1 && x1 > q.x0 && y0 < q.y1 && y1 > q.y0);

  function mulberry32(a) {
    return function () { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
  }

  const KIND_COLOR = { hq: '#8fb3ff', house: '#6b7ba0', shop: '#6aa6d6', leisure: '#f0b45a',
                       townhall: '#fde047', exec: '#fb7185', church: '#cdbff0', library: '#8fc7a9',
                       research: '#818cf8' };
  // distinct roof colour per named venue/loc so no two building types look alike
  const LOC_COLOR = { bar: '#e0714a', arcade: '#a26cf0', tv: '#4aa0e0', cafe: '#d1a05a',
                      church: '#cdbff0', library: '#8fc7a9', townhall: '#fde047', exec: '#fb7185',
                      park: '#5bb46a', gas: '#e05a6a', lounge: '#c07ad0', research: '#818cf8' };

  // ── organic-map helpers ──
  const TAU = Math.PI * 2;
  function _brush(c, r, t) { if (inb(c, r)) bset(c, r, t); }
  function _areaGrass(x, y, w, h) {                    // footprint (+1 margin) is all clear grass?
    if (x < 2 || y < 2 || x + w > COLS - 2 || y + h > ROWS - 2) return false;
    for (let r = y; r < y + h; r++) for (let c = x; c < x + w; c++) if (baseGrid[r][c] !== T.GRASS) return false;
    return true;
  }
  function _nearRoad(x, y, w, h) {                     // a road within 2 tiles so buildings face a street
    for (let c = x - 2; c < x + w + 2; c++) for (let r = y - 2; r < y + h + 2; r++)
      if (inb(c, r) && baseGrid[r][c] === T.PATH) return true;
    return false;
  }
  // scatter a building of w×h in a distance band from centre, on grass. Phase 0 prefers a
  // roadside spot; phase 1 accepts any clear grass (then carves a short access lane to a road).
  function _tryPlace(w, h, minD, maxD, extra, rnd, pick, CX, CY) {
    for (let phase = 0; phase < 2; phase++) {
      const dHi = phase === 0 ? maxD : Math.max(maxD, 46);   // fallback pass searches the whole map
      for (let t = 0; t < 300; t++) {
        const a = rnd() * TAU, d = minD + rnd() * (dHi - minD);
        const ox = Math.round(CX + Math.cos(a) * d - w / 2), oy = Math.round(CY + Math.sin(a) * d * 0.8 - h / 2);
        if (!_areaGrass(ox - 1, oy - 1, w + 2, h + 2)) continue;
        if (phase === 0 && !_nearRoad(ox, oy, w, h)) continue;
        const b = { id: _nextId++, c: ox, r: oy, w, h, door: pick(['N', 'S', 'E', 'W']), ...extra };
        buildings.push(b);
        bfill(ox, oy, w, h, T.FLOOR);                 // reserve footprint so nothing else lands on it
        if (phase === 1) _laneToRoad(ox + (w >> 1), oy + h);   // connect off-road placements
        return b;
      }
    }
    return null;
  }
  // carve a short straight lane from (c,r) toward the map centre until it hits a road/plaza
  function _laneToRoad(c, r) {
    const CX = COLS / 2 | 0, CY = ROWS / 2 | 0;
    let x = c, y = r;
    for (let i = 0; i < 14; i++) {
      if (inb(x, y) && (baseGrid[y][x] === T.PATH || baseGrid[y][x] === T.PLAZA)) return;
      if (inb(x, y) && baseGrid[y][x] === T.GRASS) bset(x, y, T.PATH);
      x += Math.sign(CX - x) || 0; y += Math.sign(CY - y) || 0;
    }
  }

  // ── generate the BASE terrain + building descriptors (no walls stamped yet) ──
  function _genBase() {
    const rng = mulberry32(20260713);
    const rnd = () => rng(), ri = (a, b) => a + Math.floor(rnd() * (b - a + 1));
    const chance = p => rnd() < p, pick = arr => arr[Math.floor(rnd() * arr.length)];
    baseGrid = Array.from({ length: ROWS }, () => Array(COLS).fill(T.GRASS));
    buildings = []; decor = []; landmarks = []; _nextId = 1;
    const CX = COLS / 2 | 0, CY = ROWS / 2 | 0;

    // ── HQ + central plaza + fountain ──
    const hw = 26, hh = 14, hc = CX - (hw / 2 | 0), hr = CY - (hh / 2 | 0);   // widened: 13 departments now
    const hq = { x0: hc - 3, y0: hr - 3, x1: hc + hw + 3, y1: hr + hh + 3 };
    bfill(hq.x0, hq.y0, hq.x1 - hq.x0, hq.y1 - hq.y0, T.PLAZA);
    for (let x = hq.x0; x <= hq.x1; x++) { bset(x, hq.y0, T.PATH); bset(x, hq.y1, T.PATH); }
    for (let y = hq.y0; y <= hq.y1; y++) { bset(hq.x0, y, T.PATH); bset(hq.x1, y, T.PATH); }
    const fx = hc + (hw / 2 | 0), fy = hr - 2;
    for (let dy = 0; dy < 2; dy++) for (let dx = 0; dx < 2; dx++) bset(fx - 1 + dx, fy - 1 + dy, T.WATER);
    decor.push({ x: (fx + 0.5) * TILE, y: (fy + 0.5) * TILE, kind: 'fountain' });
    buildings.push({ id: _nextId++, c: hc, r: hr, w: hw, h: hh, kind: 'hq', loc: null,
                     label: '⬢ THE COMPANY HQ', color: KIND_COLOR.hq, door: 'S' });

    // ── organic road network: a winding ring + meandering avenues + plaza spokes ──
    const ringR = 21;
    for (let a = 0; a < TAU; a += 0.018) {
      const rr = ringR + 3.4 * Math.sin(a * 3 + 1) + 1.8 * Math.sin(a * 7 + 2);
      const rc = Math.round(CX + Math.cos(a) * rr), rw = Math.round(CY + Math.sin(a) * rr * 0.82);
      _brush(rc, rw, T.PATH); _brush(rc, rw + 1, T.PATH);
    }
    for (let k = 0; k < 6; k++) {                        // avenues meandering out to the countryside
      let a = k / 6 * TAU + rnd() * 0.6;
      let x = CX + Math.cos(a) * ringR, y = CY + Math.sin(a) * ringR * 0.82;
      for (let step = 0; step < 62; step++) {
        a += (rnd() - 0.5) * 0.34;
        x += Math.cos(a) * 1.5; y += Math.sin(a) * 1.5;
        const rc = Math.round(x), rw = Math.round(y);
        if (!inb(rc, rw)) break;
        _brush(rc, rw, T.PATH); _brush(rc + 1, rw, T.PATH);
      }
    }
    for (let k = 0; k < 5; k++) {                        // short spokes: plaza → ring
      const a = k / 5 * TAU + 0.7;
      for (let d = 8; d <= ringR + 1; d++) { const rc = Math.round(CX + Math.cos(a) * d), rw = Math.round(CY + Math.sin(a) * d * 0.82); _brush(rc, rw, T.PATH); _brush(rc, rw + 1, T.PATH); }
    }

    // ── rugged mountain range along the north edge (before buildings, so they avoid it) ──
    for (let c = 1; c < COLS - 1; c++) {
      const depth = 2 + Math.round(5 * (0.5 + 0.5 * Math.sin(c * 0.17 + 1.3)) * (0.55 + 0.45 * rnd()));
      for (let r = 0; r < depth; r++) if (baseGrid[r][c] !== T.PATH) bset(c, r, T.MOUNTAIN);
    }

    // ── scatter buildings organically along the roads (inner: civic/leisure; outer: shops/homes) ──
    const leisure = [['bar', 'Bar 🍺'], ['arcade', 'Arcade 🕹️'], ['tv', 'Lounge 📺'], ['cafe', 'Café ☕']];
    const civic = [['church', 'Church ⛪'], ['library', 'Library 📚'], ['townhall', 'Town Hall 🏛️'], ['exec', 'Exec Office 💼'], ['research', 'Research Lab 🔬']];
    const shopNames = ['Diner', 'Market', 'Bank', 'Gym', 'Salon', 'Bakery', 'Books', 'Garage', 'Clinic', 'Deli', 'Toys', 'Pharmacy'];
    for (const [k, lbl] of leisure) _tryPlace(ri(6, 7), ri(5, 6), 12, 26, { kind: 'leisure', loc: k, label: lbl, color: LOC_COLOR[k] || KIND_COLOR.leisure }, rnd, pick, CX, CY);
    for (const [k, lbl] of civic) _tryPlace(ri(6, 8), ri(5, 7), 13, 28, { kind: k, loc: k, label: lbl, color: KIND_COLOR[k] }, rnd, pick, CX, CY);
    for (let s = 0; s < 12; s++) _tryPlace(ri(5, 7), ri(5, 6), 13, 36, { kind: 'shop', loc: null, label: pick(shopNames), color: KIND_COLOR.shop, small: true }, rnd, pick, CX, CY);
    for (let h = 0; h < 28; h++) _tryPlace(ri(5, 6), ri(5, 6), 14, 42, { kind: 'house', loc: null, label: '', color: KIND_COLOR.house, house: true }, rnd, pick, CX, CY);

    // ── scattered parks with landmark trees, a well, and a couple of fishing ponds ──
    for (let p = 0; p < 6; p++) {
      for (let t = 0; t < 70; t++) {
        const pw = ri(6, 9), ph = ri(5, 7), a = rnd() * TAU, d = 15 + rnd() * 26;
        const px0 = Math.round(CX + Math.cos(a) * d - pw / 2), py0 = Math.round(CY + Math.sin(a) * d * 0.8 - ph / 2);
        if (!_areaGrass(px0, py0, pw, ph)) continue;
        const kinds = ['tree_green', 'tree_autumn', 'tree_yellow'];
        if (p < 2) _pond(px0, py0, pw, ph);
        _park(px0, py0, pw, ph, rnd, ri);
        landmarks.push({ col: px0 + 1, row: py0 + ph - 2, kind: kinds[p % 3] });
        if (pw >= 8) landmarks.push({ col: px0 + pw - 2, row: py0 + ph - 2, kind: kinds[(p + 1) % 3] });
        if (p % 2 === 0) landmarks.push({ col: px0 + pw - 3, row: py0 + 2, kind: 'well', scale: 1.6 });
        if (!locations['park']) locations['park'] = { col: px0 + (pw / 2 | 0), row: py0 + 1 };
        break;
      }
    }
    if (!locations['park']) locations['park'] = { col: CX + 8, row: CY + 8 };

    // ── natural cover: border trees (grass only, skips the mountains) + scattered woods ──
    for (let r = 0; r < ROWS; r++) for (let d = 0; d < 3; d++) {
      if (baseGrid[r][d] === T.GRASS && chance(0.6)) bset(d, r, T.TREE);
      if (baseGrid[r][COLS - 1 - d] === T.GRASS && chance(0.6)) bset(COLS - 1 - d, r, T.TREE);
    }
    for (let c = 0; c < COLS; c++) for (let d = 0; d < 3; d++) if (baseGrid[ROWS - 1 - d][c] === T.GRASS && chance(0.6)) bset(c, ROWS - 1 - d, T.TREE);
    for (let r = 1; r < ROWS - 1; r++) for (let c = 1; c < COLS - 1; c++) if (baseGrid[r][c] === T.GRASS && chance(0.045)) bset(c, r, T.TREE);
    for (let n = 0; n < 55; n++) { const cc = ri(2, COLS - 3), rr = ri(2, ROWS - 3); if (baseGrid[rr][cc] === T.GRASS) _blob(cc, rr, ri(2, 4), rnd); }

    // ── a couple of big organic lakes out in the open country ──
    for (let n = 0, lakes = 0; n < 12 && lakes < 2; n++) {
      const lx = ri(12, COLS - 22), ly = ri(16, ROWS - 16);
      if (region(lx - 2, ly - 2, lx + 16, ly + 12, hq) || baseGrid[ly][lx] !== T.GRASS) continue;
      _pond(lx, ly, ri(11, 16), ri(8, 12)); lakes++;
    }
    _decorate(rnd, ri, chance);

    // resource nodes for idle-skilling — placed on grass in distinct regions, cleared of trees
    nodes = [];
    _placeNode('woodcut', 15, 15, CX, CY);
    _placeNode('mine', COLS - 15, 15, CX, CY);
    _placeNode('farm', 15, ROWS - 15, CX, CY);
    _placeNode('build', CX + 15, CY + 11, CX, CY);
    _placeNode('hunt', COLS - 14, ROWS - 14, CX, CY);   // hunting grounds, deep in the wilds with the deer
    _placeFishNode(CX, CY);
  }

  // find a grass tile near (tc,tr), clear a little glade, register it as a skilling node + location
  function _placeNode(kind, tc, tr, CX, CY) {
    for (let rad = 0; rad < 24; rad++) for (let dr = -rad; dr <= rad; dr++) for (let dc = -rad; dc <= rad; dc++) {
      const c = tc + dc, r = tr + dr;
      if (!inb(c, r) || baseGrid[r][c] !== T.GRASS || Math.hypot(c - CX, r - CY) < 9) continue;
      for (let a = -1; a <= 1; a++) for (let b = -1; b <= 1; b++) if (inb(c + a, r + b) && baseGrid[r + b][c + a] === T.TREE) bset(c + a, r + b, T.GRASS);
      nodes.push({ col: c, row: r, kind }); locations[kind] = { col: c, row: r };
      return;
    }
  }
  // fishing node: first grass tile adjacent to any pond water
  function _placeFishNode(CX, CY) {
    for (let r = 2; r < ROWS - 2; r++) for (let c = 2; c < COLS - 2; c++) {
      if (baseGrid[r][c] !== T.WATER) continue;
      for (const [dc, dr] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const nc = c + dc, nr = r + dr;
        if (inb(nc, nr) && baseGrid[nr][nc] === T.GRASS) { nodes.push({ col: nc, row: nr, kind: 'fish' }); locations['fish'] = { col: nc, row: nr }; return; }
      }
    }
    _placeNode('fish', CX - 18, CY + 12, CX, CY);   // fallback if no ponds
  }

  function _park(x0, y0, w, h, rnd, ri) {
    for (let n = 0; n < (w * h) / 6; n++) { const cc = x0 + ri(0, w - 1), rr = y0 + ri(0, h - 1); if (rnd() < 0.6) bset(cc, rr, T.TREE); }
  }
  function _pond(x0, y0, w, h) {
    const cx = x0 + w / 2, cy = y0 + h / 2, rx = w * 0.46, ry = h * 0.44;   // bigger
    for (let r = y0 - 1; r < y0 + h + 1; r++) for (let c = x0 - 1; c < x0 + w + 1; c++) {
      if (!inb(c, r) || baseGrid[r][c] !== T.GRASS) continue;               // never eat paths/trees/buildings
      const dx = (c - cx) / rx, dy = (r - cy) / ry;
      const wob = 0.70 + 0.34 * Math.sin(c * 0.9 + r * 1.3) + 0.12 * Math.sin(c * 2.1);  // organic shoreline
      if (dx * dx + dy * dy <= wob) bset(c, r, T.WATER);
    }
  }
  function _blob(c, r, rad, rnd) {
    for (let dr = -rad; dr <= rad; dr++) for (let dc = -rad; dc <= rad; dc++)
      if (dc * dc + dr * dr <= rad * rad && rnd() < 0.7 && baseGrid[r + dr] && baseGrid[r + dr][c + dc] === T.GRASS) bset(c + dc, r + dr, T.TREE);
  }
  function _decorate(rnd, ri, chance) {
    for (let r = 1; r < ROWS - 1; r++) for (let c = 1; c < COLS - 1; c++) {
      const t = baseGrid[r][c];
      if (t === T.PATH && chance(0.03) && (baseGrid[r][c + 1] === T.GRASS || baseGrid[r][c - 1] === T.GRASS)) decor.push({ x: (c + 0.5) * TILE, y: (r + 0.5) * TILE, kind: 'lamp' });
      else if (t === T.PLAZA && chance(0.05)) decor.push({ x: (c + 0.5) * TILE, y: (r + 0.5) * TILE, kind: 'bench' });
      else if (t === T.GRASS && chance(0.02)) decor.push({ x: (c + ri(2, 8) / 10) * TILE, y: (r + ri(2, 8) / 10) * TILE, kind: rnd() < 0.6 ? 'bush' : 'rock' });
    }
  }

  // ── stamp a building into `grid` (walls + floor + door) ──
  function _stamp(b) {
    for (let r = b.r; r < b.r + b.h; r++) for (let c = b.c; c < b.c + b.w; c++) if (inb(c, r)) grid[r][c] = T.WALL;
    for (let r = b.r + 1; r < b.r + b.h - 1; r++) for (let c = b.c + 1; c < b.c + b.w - 1; c++) if (inb(c, r)) grid[r][c] = T.FLOOR;
    if (b.kind === 'hq') {                    // organic HQ: chamfered corners (octagon-ish)
      for (const [cc, rr, sx, sy] of [[b.c, b.r, 1, 1], [b.c + b.w - 1, b.r, -1, 1],
                                      [b.c, b.r + b.h - 1, 1, -1], [b.c + b.w - 1, b.r + b.h - 1, -1, -1]]) {
        if (inb(cc, rr)) grid[rr][cc] = T.GRASS;                       // cut the sharp corner
        if (inb(cc + sx, rr)) grid[rr][cc + sx] = T.WALL;              // diagonal wall step
        if (inb(cc, rr + sy)) grid[rr + sy][cc] = T.WALL;
      }
    }
    let dc, dr;
    if (b.door === 'N') { dc = b.c + (b.w / 2 | 0); dr = b.r; }
    else if (b.door === 'W') { dc = b.c; dr = b.r + (b.h / 2 | 0); }
    else if (b.door === 'E') { dc = b.c + b.w - 1; dr = b.r + (b.h / 2 | 0); }
    else { dc = b.c + (b.w / 2 | 0); dr = b.r + b.h - 1; }
    if (inb(dc, dr)) grid[dr][dc] = T.FLOOR;
    // Layer-3 interior doors are openings → walkable FLOOR so pathfinding allows them
    // (a door on the wall ring punches a real opening; on an interior tile it stays floor).
    if (b.interior) for (const it of b.interior) {
      if (it.kind !== 'door') continue;
      const ic = b.c + it.lc, ir = b.r + it.lr;
      if (inb(ic, ir)) grid[ir][ic] = T.FLOOR;
    }
    return { col: dc, row: dr };
  }

  // ── compose base + buildings → grid, recompute locations, bake ──
  function rasterize() {
    grid = baseGrid.map(row => row.slice());
    houseSlots = [];
    const deptKeys = ['storefront', 'image', 'video', 'audio', 'models3d', 'publishing', 'devlab', 'resell', 'trends'];
    for (const b of buildings) {
      _stamp(b);
      const interior = { col: b.c + (b.w / 2 | 0), row: b.r + (b.h / 2 | 0) };
      if (b.kind === 'hq') {
        const dcx = [b.c + 4, b.c + (b.w / 2 | 0), b.c + b.w - 4], dcy = [b.r + 3, b.r + (b.h / 2 | 0), b.r + b.h - 3];
        deptKeys.forEach((k, i) => { locations['desk:' + k] = { col: dcx[i % 3], row: dcy[i / 3 | 0] }; });
        locations['defense'] = { col: b.c + (b.w / 2 | 0), row: b.r + b.h + 2 };   // rally point south of HQ (raid)
      } else if (b.loc) {
        locations[b.loc] = interior;
        // the Research Geniuses' dept has no HQ desk — their "desk" IS the lab
        if (b.loc === 'research') locations['desk:research'] = interior;
      }
      else if (b.kind === 'house') houseSlots.push(interior);
    }
    if (!houseSlots.length) houseSlots.push({ col: COLS / 2 | 0, row: ROWS / 2 | 0 });
    _bake();
  }

  function build(saved) {
    _genBase();
    if (saved && Array.isArray(saved.buildings) && saved.buildings.length) {
      buildings = saved.buildings.map(b => ({ ...b }));
      if (Array.isArray(saved.decor)) decor = saved.decor.map(d => ({ ...d }));
      if (Array.isArray(saved.nodes) && saved.nodes.length) { nodes = saved.nodes.map(n => ({ ...n })); _rebuildLocations(); }
      if (Array.isArray(saved.landmarks)) landmarks = saved.landmarks.map(l => ({ ...l }));
      _nextId = Math.max(0, ...buildings.map(b => b.id || 0)) + 1;
    }
    _leisureSpots();
    rasterize();
  }

  // ── public-space leisure destinations (Mayor's park & plaza upgrade) ──
  // Anchored to the decor that's ACTUALLY on the map (works with saved/edited
  // layouts) so agents walk to what you see: a bench to sit on, the plaza
  // fountain to admire, and a picnic spot on the green (created on first run
  // if the layout predates it, then saved with the layout like any decor).
  function _leisureSpots() {
    const toTile = d => ({ col: Math.max(1, Math.min(COLS - 2, d.x / TILE | 0)),
                           row: Math.max(1, Math.min(ROWS - 2, d.y / TILE | 0)) });
    const fount = decor.find(d => d.kind === 'fountain');
    if (fount) locations['plaza'] = toTile(fount);
    const bench = decor.find(d => d.kind === 'bench');
    if (bench) locations['bench'] = toTile(bench);
    let pic = decor.find(d => d.kind === 'picnic_table');
    if (!pic) {
      const p = locations['park'] || { col: COLS / 2 | 0, row: ROWS / 2 | 0 };
      pic = { x: (p.col + 2.5) * TILE, y: (p.row + 1.5) * TILE, kind: 'picnic_table' };
      decor.push(pic);
    }
    locations['picnic'] = toTile(pic);
    for (const k of ['plaza', 'bench', 'picnic'])   // never strand an agent
      if (!locations[k]) locations[k] = locations['park'];
  }

  // ── EDIT API (play-god) ──
  const byId = id => buildings.find(b => b.id === id);
  function moveBuilding(id, c, r) {
    const b = byId(id); if (!b) return;
    b.c = Math.max(1, Math.min(COLS - b.w - 1, Math.round(c)));
    b.r = Math.max(1, Math.min(ROWS - b.h - 1, Math.round(r)));
    rasterize();
  }
  function resizeBuilding(id, dw, dh) {
    const b = byId(id); if (!b) return;
    b.w = Math.max(3, Math.min(30, b.w + dw));
    b.h = Math.max(3, Math.min(24, b.h + dh));
    b.c = Math.min(b.c, COLS - b.w - 1); b.r = Math.min(b.r, ROWS - b.h - 1);
    if (b.interior) b.interior = b.interior.filter(e => e.lc < b.w && e.lr < b.h);   // drop interior items now outside the smaller footprint
    rasterize();
  }
  function addBuilding(kind, c, r) {
    const spec = { house: { w: 6, h: 6, label: '', house: true }, shop: { w: 6, h: 5, label: 'Shop', small: true },
                   tree: null }[kind] || { w: 6, h: 6 };
    if (kind === 'tree') { for (let dr = -1; dr <= 1; dr++) for (let dc = -1; dc <= 1; dc++) bset(c + dc, r + dr, T.TREE); rasterize(); return null; }
    const b = { id: _nextId++, c: Math.round(c), r: Math.round(r), door: 'S', kind, loc: null,
                color: KIND_COLOR[kind] || '#6b7ba0', ...spec };
    buildings.push(b); rasterize(); return b.id;
  }
  function deleteBuilding(id) { buildings = buildings.filter(b => b.id !== id); rasterize(); }
  function setBuilding(id, patch) { const b = byId(id); if (b) { Object.assign(b, patch); rasterize(); } }
  function buildingAtTile(col, row) {
    for (let i = buildings.length - 1; i >= 0; i--) { const b = buildings[i]; if (col >= b.c && col < b.c + b.w && row >= b.r && row < b.r + b.h) return b; }
    return null;
  }
  // ── Layer-3 PER-TILE INTERIOR (play-god): doors / windows / objects on a BUILDING-LOCAL
  // grid (lc = col - b.c, lr = row - b.r). Building-local so they move with the building for
  // free; they ride exportLayout/build like any building field and auto-save via scheduleSave. ──
  function addInterior(id, col, row, kind) {
    const b = byId(id); if (!b) return false;
    const lc = col - b.c, lr = row - b.r;
    if (lc < 0 || lr < 0 || lc >= b.w || lr >= b.h) return false;         // must sit within the footprint
    const onRing = lc === 0 || lr === 0 || lc === b.w - 1 || lr === b.h - 1;
    if (onRing && kind !== 'door') return false;                         // only doors may sit on the wall ring (they are openings)
    if (!b.interior) b.interior = [];
    b.interior = b.interior.filter(e => !(e.lc === lc && e.lr === lr));   // one item per tile (replace)
    b.interior.push({ lc, lr, kind });
    rasterize();                                                         // re-stamp (door→FLOOR) + re-bake
    return true;
  }
  function removeInteriorAt(id, col, row) {
    const b = byId(id); if (!b || !b.interior || !b.interior.length) return false;
    const lc = col - b.c, lr = row - b.r, n = b.interior.length;
    b.interior = b.interior.filter(e => !(e.lc === lc && e.lr === lr));
    if (b.interior.length === n) return false;
    rasterize();
    return true;
  }
  const exportLayout = () => ({ buildings: buildings.map(b => b.interior ? { ...b, interior: b.interior.map(e => ({ ...e })) } : { ...b }), decor,
                                nodes: nodes.map(n => ({ ...n })), landmarks: landmarks.map(l => ({ ...l })) });

  // ── AUTO-SAVE (play-god): persist hand edits without a manual 💾 click ──
  // Debounced so a drag/resize burst coalesces into ONE POST after it settles.
  // Called only from user-edit paths (never build()/rasterize()), so loading a
  // saved layout can't trigger a save loop. Toggle: window._wmLayoutAutosave
  // (set from the world_layout_autosave setting on tab load); undefined = ON.
  let _saveTimer = null;
  function scheduleSave() {
    if (window._wmLayoutAutosave === false) return;   // toggle off → only 💾 saves
    clearTimeout(_saveTimer);
    _saveTimer = setTimeout(() => {
      _saveTimer = null;
      try {
        api('/api/world/layout', { method: 'POST', body: JSON.stringify({ layout: exportLayout() }) })
          .then(() => { const el = document.getElementById('world-autosave-note'); if (el) { el.textContent = '✓ saved'; setTimeout(() => { if (el.textContent === '✓ saved') el.textContent = ''; }, 1400); } })
          .catch(() => {});
      } catch (e) { /* never let a save error break editing */ }
    }, 800);
  }
  // fine-grained decor placement (play-god) — pixel-precise, saved in the layout
  function addDecor(px, py, kind) { decor.push({ x: px, y: py, kind }); _bake(); }
  function removeDecorNear(px, py) {
    const bi = decorIndexNear(px, py);
    if (bi >= 0) { decor.splice(bi, 1); _bake(); return true; }
    return false;
  }
  function decorIndexNear(px, py) {
    let bi = -1, bd = 26 * 26;
    for (let i = 0; i < decor.length; i++) { const dx = decor[i].x - px, dy = decor[i].y - py, d = dx * dx + dy * dy; if (d < bd) { bd = d; bi = i; } }
    return bi;
  }
  function pickDecor(index) { if (index < 0 || index >= decor.length) return null; const d = decor[index]; decor.splice(index, 1); _bake(); return d; }
  function previewDecor(ctx, kind, px, py) { ctx.save(); ctx.globalAlpha = 0.7; _decorSprite(ctx, { x: px, y: py, kind }); ctx.restore(); }

  // ── resource NODES (play-god): mine/woodcut/farm/fish/build — positioned by tile ──
  function _rebuildLocations() {                       // keep locations[kind] pointing at a live node
    for (const n of nodes) locations[n.kind] = { col: n.col, row: n.row };
  }
  function nodeIndexNear(px, py) {
    let bi = -1, bd = 26 * 26;
    for (let i = 0; i < nodes.length; i++) { const p = tileToPx(nodes[i].col, nodes[i].row); const dx = p.x - px, dy = p.y - py, d = dx * dx + dy * dy; if (d < bd) { bd = d; bi = i; } }
    return bi;
  }
  function addNode(kind, col, row) {
    const n = { col: Math.max(0, Math.min(COLS - 1, Math.round(col))), row: Math.max(0, Math.min(ROWS - 1, Math.round(row))), kind };
    nodes.push(n); _rebuildLocations(); return n;
  }
  function pickNode(index) { if (index < 0 || index >= nodes.length) return null; const n = nodes[index]; nodes.splice(index, 1); _rebuildLocations(); return n; }
  function removeNodeAt(index) { if (index < 0 || index >= nodes.length) return false; nodes.splice(index, 1); _rebuildLocations(); return true; }

  // ── LANDMARKS (play-god): big park sprites (trees, well, pond) — positioned by tile ──
  function landmarkIndexNear(px, py) {
    let bi = -1, bd = 30 * 30;
    for (let i = 0; i < landmarks.length; i++) { const p = tileToPx(landmarks[i].col, landmarks[i].row); const dx = p.x - px, dy = p.y - py, d = dx * dx + dy * dy; if (d < bd) { bd = d; bi = i; } }
    return bi;
  }
  function addLandmark(kind, col, row, scale) {
    const l = { col: Math.max(0, Math.min(COLS - 1, Math.round(col))), row: Math.max(0, Math.min(ROWS - 1, Math.round(row))), kind };
    if (scale) l.scale = scale;
    landmarks.push(l); return l;
  }
  function pickLandmark(index) { if (index < 0 || index >= landmarks.length) return null; const l = landmarks[index]; landmarks.splice(index, 1); return l; }
  function removeLandmarkAt(index) { if (index < 0 || index >= landmarks.length) return false; landmarks.splice(index, 1); return true; }

  // per-tile hash → stable pseudo-random variation (cozy pixel-art texture)
  const hsh = (c, r, s) => { let x = ((c + 1) * 374761393 + (r + 1) * 668265263 + (s || 0) * 2246822519) >>> 0; x = ((x ^ (x >>> 13)) * 1274126177) >>> 0; return (x >>> 0) / 4294967296; };
  const FLOWERS = ['#e05a6a', '#e8c14a', '#e8e0e0', '#d97ac0'];

  // Layer 2: swap in ONE generated whole-world ground image (loads async, then
  // re-bakes). Terrain LOGIC (pathfinding/water/wear) stays on the grid — this is
  // a pure visual skin. Passing a falsy url reverts to procedural per-tile art.
  function setTerrainImage(url) {
    _terrainUrl = url || null;
    if (!url) { _terrainImg = null; _bake(); return; }
    const img = new Image();
    img.onload = () => { _terrainImg = img; _bake(); };
    img.onerror = () => { _terrainImg = null; };
    img.src = url;
  }

  // Flicker fix: set the generated terrain image WITHOUT re-baking. The caller runs
  // build()→_bake() right after, so the (single) bake sees _terrainImg already present
  // and paints the image directly — no procedural→image swap on load. Pass the source
  // url too so reheal() can re-decode it after a browser memory-eviction.
  function setTerrainImageEl(img, url) { _terrainImg = img || null; if (url !== undefined) _terrainUrl = url || null; }

  // Layer-2b: swap in ONE shared generated interior-floor texture (loads async, then
  // re-bakes). It is blitted under EVERY building interior in _building() and the
  // per-kind FLOOR_TINT is washed over it at low alpha so buildings still read
  // distinct. Passing a falsy url reverts to the procedural per-kind tint floor.
  function setFloorImage(url) {
    _floorUrl = url || null;
    if (!url) { _floorImg = null; _bake(); return; }
    const img = new Image();
    img.onload = () => { _floorImg = img; _bake(); };
    img.onerror = () => { _floorImg = null; };
    img.src = url;
  }
  // Flicker-free variant (mirrors setTerrainImageEl): set WITHOUT re-baking; the
  // caller runs build()→_bake() right after so the single bake already sees it.
  function setFloorImageEl(img, url) { _floorImg = img || null; if (url !== undefined) _floorUrl = url || null; }

  // ── SELF-HEAL: detect + recover a browser-evicted overview ───────────────────
  // terrainAlive(): sample a few points of the small always-resident _overview. If they're
  // ALL fully transparent, the browser reclaimed its backing store and the ground has
  // silently blanked. (Full-res chunks self-recover — they're re-baked on demand — so the
  // overview is the only long-lived surface worth watching.) Returns true when there's
  // nothing to heal (no overview yet) so callers don't thrash before the first bake.
  function terrainAlive() {
    if (!_overview) return true;
    try {
      const x = _overview.getContext('2d'), ow = _overview.width, oh = _overview.height;
      const pts = [[ow*0.5, oh*0.5], [ow*0.15, oh*0.2], [ow*0.85, oh*0.25], [ow*0.2, oh*0.8], [ow*0.8, oh*0.82]];
      for (const [px, py] of pts) {
        const d = x.getImageData(px | 0, py | 0, 2, 2).data;
        for (let i = 3; i < d.length; i += 4) if (d[i] !== 0) return true;  // any opaque pixel → alive
      }
      return false;   // every probe fully transparent → evicted
    } catch (e) { return true; }   // readback blocked → assume alive, don't thrash
  }

  // reheal(): re-decode the terrain + floor images FROM their source URLs (the in-memory
  // elements may themselves be evicted, so a plain _bake() isn't enough) and re-bake. With
  // no URLs it just re-bakes procedural ground, which also restores an evicted canvas.
  async function reheal() {
    if (_rehealing) return;
    _rehealing = true;
    try {
      const jobs = [];
      if (_terrainUrl) jobs.push(_reload(_terrainUrl).then(img => { if (img) _terrainImg = img; }));
      if (_floorUrl)   jobs.push(_reload(_floorUrl).then(img => { if (img) _floorImg = img; }));
      if (jobs.length) await Promise.all(jobs);
      _bake();   // restores procedural ground even if the images failed to reload
    } catch (e) {
      try { _bake(); } catch {}
    } finally { _rehealing = false; }
  }
  function _reload(url) {
    return new Promise(res => {
      const img = new Image();
      img.onload = () => { (img.decode ? img.decode().catch(() => {}) : Promise.resolve()).then(() => res(img)); };
      img.onerror = () => res(null);
      img.src = url + (url.includes('?') ? '&' : '?') + '_rh=' + (W + H);  // stable suffix, avoids a stale evicted cache entry
    });
  }

  // Layout-guided img2img — the "alpha map maker" helper. Exports the PROCEDURAL layout
  // (roads/water/plaza/fields + building footprints) as a base image so the terrain
  // generator's img2img matches your real map. Crucially it must NOT export a generated
  // terrain image (that'd feed the image back into itself), so we paint PROCEDURAL ground
  // (_terrainImg temporarily nulled) DIRECTLY into the w×h target via _paintRegion — no
  // giant intermediate canvas, and it's independent of the chunk cache. Returns a PNG
  // dataURL, or null on failure.
  function exportLayoutBase(w, h) {
    const saved = _terrainImg;
    try {
      _terrainImg = null;
      const off = document.createElement('canvas'); off.width = w; off.height = h;
      const octx = off.getContext('2d'); octx.imageSmoothingEnabled = false;
      octx.setTransform(w / W, 0, 0, h / H, 0, 0);             // world coords → w×h target
      _paintRegion(octx, 0, 0, COLS, ROWS);                    // full procedural map (structPass off: no side effects)
      octx.setTransform(1, 0, 0, 1, 0, 0);
      return off.toDataURL('image/png');
    } catch (e) {
      return null;
    } finally {
      _terrainImg = saved; _bake();                            // restore the live view (overview + chunk cache)
    }
  }

  // ── PAINT one tile-region of the ground into an (already-transformed) context ──
  // Pure drawing: terrain tiles + buildings + decor whose footprint touches the region
  // (+1-tile margin so overhanging walls/roofs aren't clipped at chunk seams). The ONLY
  // side effects (waterTiles / hqRooms / desk-locations) are guarded by _structPass, so
  // they run exactly once (the overview full pass) and never per-chunk.
  function _bIntersects(b, tc0, tr0, tc1, tr1) {
    return b.c < tc1 + 1 && b.c + b.w > tc0 - 1 && b.r < tr1 + 1 && b.r + b.h > tr0 - 1;
  }
  function _paintRegion(x, tc0, tr0, tc1, tr1) {
    const useImg = _terrainImg && _terrainImg.complete && _terrainImg.naturalWidth;
    if (useImg) x.drawImage(_terrainImg, 0, 0, W, H);   // whole ground image; the ctx transform clips it to this region
    for (let r = tr0; r < tr1; r++) for (let c = tc0; c < tc1; c++) {
      const t = grid[r][c];
      if (!useImg || t === T.FLOOR || t === T.WALL) _tile(x, c, r);
      if (t === T.WATER && _structPass) waterTiles.push({ col: c, row: r });   // live-water list: full pass only
    }
    // Building floors/detail first, then the thin themed wall shell on top of the edge.
    for (const b of buildings) if (_bIntersects(b, tc0, tr0, tc1, tr1)) _building(x, b);
    for (const b of buildings) if (_bIntersects(b, tc0, tr0, tc1, tr1)) _drawBuildingShell(x, b);
    for (const d of decor) {
      const dc = d.x / TILE, dr = d.y / TILE;
      if (dc >= tc0 - 1 && dc < tc1 + 1 && dr >= tr0 - 1 && dr < tr1 + 1) _decorSprite(x, d);
    }
  }

  // Whole-map LOW-RES overview (the zoomed-out LOD + the fallback under baking chunks).
  // This is the ONE full pass over the map, so it also (re)populates waterTiles/hqRooms/
  // locations via _structPass. Small + always resident; if the browser evicts it,
  // terrainAlive()/reheal() rebuild it.
  function _bakeOverview() {
    if (!_overview) { _overview = document.createElement('canvas'); _overview.width = Math.ceil(W / _OV); _overview.height = Math.ceil(H / _OV); }
    const x = _overview.getContext('2d'); x.imageSmoothingEnabled = false;
    x.setTransform(1 / _OV, 0, 0, 1 / _OV, 0, 0);       // draw in world coords, scaled down
    x.clearRect(0, 0, W, H);
    _structPass = true;
    waterTiles = [];
    _paintRegion(x, 0, 0, COLS, ROWS);
    _structPass = false;
    x.setTransform(1, 0, 0, 1, 0, 0);
  }

  // One FULL-RES chunk (baked on demand for the visible viewport, evicted when off-screen).
  function _bakeChunk(cx, cy) {
    const tc0 = cx * CHUNK_CW, tr0 = cy * CHUNK_CH;
    const tc1 = Math.min(COLS, tc0 + CHUNK_CW), tr1 = Math.min(ROWS, tr0 + CHUNK_CH);
    const wx = tc0 * TILE, wy = tr0 * TILE, ww = (tc1 - tc0) * TILE, wh = (tr1 - tr0) * TILE;
    const cv = document.createElement('canvas'); cv.width = ww; cv.height = wh;
    const x = cv.getContext('2d'); x.imageSmoothingEnabled = false;
    x.translate(-wx, -wy);                               // world coords → chunk-local
    _paintRegion(x, tc0, tr0, tc1, tr1);                 // _structPass stays false → pure draw
    return { cv, wx, wy, seen: performance.now() };
  }

  // Structure/appearance changed (edit, terrain/floor image swap, decor add): rebuild the
  // overview (the one full pass) and drop the full-res cache so visible chunks re-bake lazily.
  function _bake() {
    _bakeOverview();
    _chunks.clear();
  }

  const _hex = (h, a) => { const n = parseInt((h || '#888').slice(1), 16); return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`; };

  // the 9 department rooms inside the HQ — tinted zones with divider walls + props
  const DEPT_ORDER = ['storefront', 'image', 'video', 'audio', 'models3d', 'publishing', 'devlab',
                      'resell', 'trends', 'portal', 'social', 'finance', 'netsec'];
  const DEPT_TINT = { storefront: '#6aa6d6', image: '#e0b050', video: '#e07a5a', audio: '#7ac0a0', models3d: '#b48fe0', publishing: '#e090c0', devlab: '#8fb3ff', resell: '#f0a860', trends: '#7fd4a0',
                      portal: '#2dd4bf', social: '#38bdf8', finance: '#eab308', netsec: '#94a3b8' };
  // expose the 9 room centres (px) so the factory can flow products desk→desk
  let hqRooms = [];
  // walls around a room with a centered DOOR gap on the hallway-facing side
  function _roomWalls(x, zx, zy, zw, zh, doorSide) {
    x.strokeStyle = 'rgba(44,33,22,.75)'; x.lineWidth = 2;
    const gap = Math.min(15, zw * 0.42), gx = zx + zw / 2 - gap / 2;
    x.beginPath();
    if (doorSide === 'top') { x.moveTo(zx, zy); x.lineTo(gx, zy); x.moveTo(gx + gap, zy); x.lineTo(zx + zw, zy); }
    else { x.moveTo(zx, zy); x.lineTo(zx + zw, zy); }
    if (doorSide === 'bottom') { x.moveTo(zx, zy + zh); x.lineTo(gx, zy + zh); x.moveTo(gx + gap, zy + zh); x.lineTo(zx + zw, zy + zh); }
    else { x.moveTo(zx, zy + zh); x.lineTo(zx + zw, zy + zh); }
    x.moveTo(zx, zy); x.lineTo(zx, zy + zh); x.moveTo(zx + zw, zy); x.lineTo(zx + zw, zy + zh);
    x.stroke();
    // door frame posts
    x.strokeStyle = 'rgba(210,170,110,.5)'; x.lineWidth = 1.2;
    const dy = doorSide === 'top' ? zy : zy + zh;
    x.beginPath(); x.moveTo(gx, dy - 2); x.lineTo(gx, dy + 2); x.moveTo(gx + gap, dy - 2); x.lineTo(gx + gap, dy + 2); x.stroke();
  }

  // The HQ interior: two rows of department rooms off a central HALLWAY (a real
  // building, not a plain grid). 5 rooms up top, 4 below, each with a door onto
  // the corridor. Gear + nameplates are drawn LIVE (they need async sprites).
  function _hqRooms(x, b) {
    if (_structPass) hqRooms = [];        // geometry list rebuilt only on the full pass, not per-chunk
    const ix0 = (b.c + 1) * TILE, iy0 = (b.r + 1) * TILE, iw = (b.w - 2) * TILE, ih = (b.h - 2) * TILE;
    const hallH = Math.max(TILE * 1.2, Math.round(ih * 0.15));
    const topH = Math.floor((ih - hallH) / 2), botH = ih - hallH - topH, hallY = iy0 + topH;
    // ── central hallway floor + carpet runner + planters ──
    x.fillStyle = 'rgba(54,60,74,.55)'; x.fillRect(ix0, hallY, iw, hallH);
    x.fillStyle = 'rgba(150,96,72,.30)'; x.fillRect(ix0 + 3, hallY + hallH / 2 - 2, iw - 6, 4);   // runner
    x.strokeStyle = 'rgba(0,0,0,.25)'; x.lineWidth = 1; x.strokeRect(ix0, hallY, iw, hallH);
    for (let px = ix0 + 10; px < ix0 + iw - 6; px += 34) {                                          // hallway planters
      x.fillStyle = '#6b4c2f'; x.fillRect(px - 2, hallY + hallH - 5, 4, 4);
      x.fillStyle = '#2f8542'; x.beginPath(); x.arc(px, hallY + hallH - 6, 3, 0, 6.283); x.fill();
    }
    const _half = Math.ceil(DEPT_ORDER.length / 2);
    const bands = [{ y: iy0, h: topH, depts: DEPT_ORDER.slice(0, _half), door: 'bottom' },
                   { y: hallY + hallH, h: botH, depts: DEPT_ORDER.slice(_half), door: 'top' }];
    for (const band of bands) {
      const rw = iw / band.depts.length;
      band.depts.forEach((dept, i) => {
        const zx = ix0 + i * rw, zy = band.y, zw = rw, zh = band.h, cc = DEPT_TINT[dept] || '#8ab';
        if (_structPass) {
          hqRooms.push({ dept, x: zx + zw / 2, y: zy + zh / 2, x0: zx, y0: zy, w: zw, h: zh, tint: cc, door: band.door });
          locations['desk:' + dept] = { col: Math.round(zx / TILE + zw / TILE / 2 - 0.5), row: Math.round(zy / TILE + zh / TILE / 2 - 0.5) };  // agents operate here
        }
        x.fillStyle = _hex(cc, 0.15); x.fillRect(zx + 1, zy + 1, zw - 2, zh - 2);                   // floor tint
        // OFFICE + FACTORY split: carpet-tiled office along the back wall, a
        // concrete production strip mid-room where the live WF machine line runs.
        const backTop = band.door === 'bottom';
        const carY = backTop ? zy + 2 : zy + zh * 0.72, carH = backTop ? zh * 0.42 : zh * 0.26;
        for (let ty = carY; ty < carY + carH - 3; ty += 7)                                          // carpet tiles
          for (let tx = zx + 3; tx < zx + zw - 8; tx += 7) {
            x.fillStyle = _hex(cc, ((tx / 7 | 0) + (ty / 7 | 0)) % 2 ? 0.13 : 0.22); x.fillRect(tx, ty, 6, 6);
          }
        x.fillStyle = 'rgba(120,126,138,.30)'; x.fillRect(zx + 2, zy + zh * 0.52, zw - 4, zh * 0.22); // concrete slab
        const beltY = zy + zh * 0.60 + 3, bx0 = zx + zw * 0.12, bx1 = zx + zw * 0.88;
        x.fillStyle = '#20242c'; x.fillRect(bx0, beltY, bx1 - bx0, 7);                              // conveyor belt
        x.fillStyle = 'rgba(160,170,185,.5)'; for (let rx = bx0 + 3; rx < bx1 - 2; rx += 6) x.fillRect(rx, beltY + 1, 1, 5);  // rollers
        for (let rx = bx0; rx < bx1 - 3; rx += 8) {                                                 // hazard stripe
          x.fillStyle = '#d8b13c'; x.fillRect(rx, beltY + 9, 4, 2);
          x.fillStyle = '#23262e'; x.fillRect(rx + 4, beltY + 9, 4, 2);
        }
        // office corner: desk + glowing monitor + chair + filing cabinet
        const deskY = backTop ? zy + zh * 0.24 : zy + zh * 0.80;
        x.fillStyle = '#5d4328'; x.fillRect(zx + 7, deskY, 18, 7);
        x.fillStyle = 'rgba(255,255,255,.12)'; x.fillRect(zx + 7, deskY, 18, 1.5);
        x.fillStyle = '#1c2530'; x.fillRect(zx + 11, deskY - 5, 9, 6);                              // monitor
        x.fillStyle = '#7fd0ff'; x.fillRect(zx + 12, deskY - 4, 7, 4);                              // screen glow
        x.fillStyle = '#39414f'; x.beginPath(); x.arc(zx + 16, deskY + (backTop ? 11 : -4), 3, 0, 6.283); x.fill();  // chair
        x.fillStyle = '#767d8a'; x.fillRect(zx + zw - 15, deskY - 2, 8, 10);                        // filing cabinet
        x.fillStyle = 'rgba(0,0,0,.35)'; x.fillRect(zx + zw - 15, deskY + 1, 8, 1); x.fillRect(zx + zw - 15, deskY + 4, 8, 1);
        // pallet of finished boxes at the belt's end
        x.fillStyle = '#8a6a3f'; x.fillRect(bx1 - 2, beltY - 2, 10, 10);
        x.fillStyle = '#c89b55'; x.fillRect(bx1 - 1, beltY - 1, 8, 4); x.fillRect(bx1 - 1, beltY + 4, 8, 4);
        x.fillStyle = 'rgba(0,0,0,.3)'; x.fillRect(bx1 - 1, beltY + 3, 8, 1);
        _deptSignature(x, dept, zx, zy, zw, zh, deskY, cc);   // each studio's own equipment
        _roomWalls(x, zx, zy, zw, zh, band.door);
        // shelf along the back wall (the wall away from the hallway)
        const backY = band.door === 'bottom' ? zy + 4 : zy + zh - 6, shw = Math.min(zw - 10, 24), shx = zx + (zw - shw) / 2;
        x.fillStyle = '#6b4a2c'; x.fillRect(shx, backY, shw, 3);
        for (let k = 0; k < (shw / 6 | 0); k++) { x.fillStyle = _hex([cc, '#d8c090', '#c07a5a'][(i + k) % 3], 0.9); x.fillRect(shx + 1 + k * 6, backY - 3, 4, 3); }
        // inner AO so the room reads enclosed
        x.strokeStyle = 'rgba(0,0,0,.18)'; x.lineWidth = 3; x.strokeRect(zx + 2.5, zy + 2.5, zw - 5, zh - 5);
      });
    }
    // reception up front: a welcome desk beside the HQ's hallway entrance
    x.fillStyle = '#5d4328'; x.fillRect(ix0 + 6, hallY + 3, 22, 6);
    x.fillStyle = 'rgba(255,255,255,.14)'; x.fillRect(ix0 + 6, hallY + 3, 22, 1.5);
    x.fillStyle = '#e8c14a'; x.fillRect(ix0 + 24, hallY + 4, 2, 2);                                 // bell
    x.fillStyle = '#39414f'; x.beginPath(); x.arc(ix0 + 17, hallY + 12, 3, 0, 6.283); x.fill();
  }
  // each department room's SIGNATURE equipment — no two studios look alike
  function _deptSignature(x, dept, zx, zy, zw, zh, deskY, cc) {
    const px0 = zx + zw - 34, py0 = deskY - 3;              // beside the filing cabinet
    if (dept === 'image') {                                  // easel with a canvas
      x.fillStyle = '#6b4a2c'; x.fillRect(px0 + 2, py0, 2, 12); x.fillRect(px0 + 10, py0, 2, 12);
      x.fillRect(px0 + 1, py0 + 10, 12, 1.5);
      x.fillStyle = '#efe6d2'; x.fillRect(px0 + 1, py0, 12, 9);
      x.fillStyle = _hex(cc, .7); x.fillRect(px0 + 3, py0 + 2, 5, 4); x.fillStyle = '#5f97c4'; x.fillRect(px0 + 8, py0 + 3, 3, 3);
    } else if (dept === 'video') {                           // tripod camera + greenscreen
      x.fillStyle = '#3fae62'; x.fillRect(px0 - 2, py0 - 2, 16, 5);              // greenscreen strip
      x.fillStyle = '#22262e'; x.fillRect(px0 + 4, py0 + 4, 7, 5);               // camera body
      x.fillStyle = '#7fd0ff'; x.fillRect(px0 + 9.5, py0 + 5, 2, 3);             // lens
      x.strokeStyle = '#4a505c'; x.lineWidth = 1.2;                              // tripod
      x.beginPath(); x.moveTo(px0 + 7, py0 + 9); x.lineTo(px0 + 3, py0 + 15); x.moveTo(px0 + 7, py0 + 9); x.lineTo(px0 + 11, py0 + 15); x.stroke();
    } else if (dept === 'audio') {                           // mixing desk + monitors + foam
      x.fillStyle = '#2c313c'; for (let i = 0; i < 5; i++) x.fillRect(px0 - 2 + i * 3.4, py0 - 2, 2.4, 3);  // foam wedges
      x.fillStyle = '#39414f'; x.fillRect(px0, py0 + 4, 14, 6);
      x.fillStyle = '#8fe0a0'; for (let i = 0; i < 4; i++) x.fillRect(px0 + 1.5 + i * 3.4, py0 + 5 + (i % 2), 1.4, 3);  // faders
      x.fillStyle = '#1c2530'; x.fillRect(px0 - 3, py0 + 4, 3, 6); x.fillRect(px0 + 14.5, py0 + 4, 3, 6);   // speakers
    } else if (dept === 'models3d') {                         // printer farm + spools
      for (let i = 0; i < 2; i++) {
        x.fillStyle = '#3a4150'; x.fillRect(px0 + i * 9, py0, 7, 10);
        x.fillStyle = '#f0a860'; x.fillRect(px0 + 2 + i * 9, py0 + 5, 3, 2.5);   // hot print glow
      }
      x.fillStyle = '#c25b4e'; x.beginPath(); x.arc(px0 + 4, py0 + 14, 2.4, 0, 6.283); x.fill();
      x.fillStyle = '#4e7fc2'; x.beginPath(); x.arc(px0 + 11, py0 + 14, 2.4, 0, 6.283); x.fill();
    } else if (dept === 'storefront') {                       // display shelf of products
      x.fillStyle = '#6b4a2c'; x.fillRect(px0 - 2, py0, 18, 12);
      x.fillStyle = 'rgba(0,0,0,.3)'; x.fillRect(px0 - 2, py0 + 5.5, 18, 1);
      for (let i = 0; i < 4; i++) { x.fillStyle = _hex(['#d8c090', '#c07a5a', cc, '#7ac0a0'][i % 4], .95); x.fillRect(px0 + i * 4.2, py0 + 1.5, 3, 3.5); x.fillRect(px0 + i * 4.2, py0 + 7, 3, 3.5); }
    } else if (dept === 'publishing') {                       // press rollers + paper stacks
      x.fillStyle = '#4a505c'; x.fillRect(px0, py0 + 2, 12, 7);
      x.fillStyle = '#8a919f'; x.beginPath(); x.arc(px0 + 3.5, py0 + 2, 2.4, 0, 6.283); x.fill(); x.beginPath(); x.arc(px0 + 8.5, py0 + 2, 2.4, 0, 6.283); x.fill();
      x.fillStyle = '#efe6d2'; x.fillRect(px0 + 13.5, py0 + 4, 6, 1.6); x.fillRect(px0 + 13.5, py0 + 6.2, 6, 1.6); x.fillRect(px0 + 13.5, py0 + 8.4, 6, 1.6);
    } else if (dept === 'devlab') {                           // server rack, blinking lights
      x.fillStyle = '#1a2029'; x.fillRect(px0 + 2, py0 - 2, 11, 15);
      for (let i = 0; i < 5; i++) {
        x.fillStyle = '#2c3542'; x.fillRect(px0 + 3.5, py0 + i * 2.8, 8, 2);
        x.fillStyle = i % 2 ? '#8fe0a0' : '#f08a8a'; x.fillRect(px0 + 10, py0 + 0.5 + i * 2.8, 1.2, 1.2);
      }
    } else if (dept === 'resell') {                           // parcel stack + scale
      x.fillStyle = '#c89b55'; x.fillRect(px0, py0 + 4, 7, 6); x.fillRect(px0 + 1.5, py0 - 1, 6, 5);
      x.fillStyle = 'rgba(0,0,0,.35)'; x.fillRect(px0 + 3, py0 + 4, 1, 6); x.fillRect(px0 + 4, py0 - 1, 1, 5);
      x.fillStyle = '#8a919f'; x.fillRect(px0 + 10, py0 + 8, 8, 2); x.fillRect(px0 + 13, py0 + 5, 2, 3);
      x.fillStyle = '#39414f'; x.fillRect(px0 + 10.5, py0 + 3, 7, 2.5);
    } else if (dept === 'trends') {                           // chart wall
      x.fillStyle = '#0e1626'; x.fillRect(px0 - 1, py0 - 2, 17, 11);
      x.strokeStyle = '#3f7fb0'; x.lineWidth = 1;
      x.beginPath(); x.moveTo(px0 + 1, py0 + 6); x.lineTo(px0 + 5, py0 + 3); x.lineTo(px0 + 9, py0 + 5); x.lineTo(px0 + 14, py0); x.stroke();
      x.strokeStyle = '#6ee7a8'; x.beginPath(); x.moveTo(px0 + 1, py0 + 8); x.lineTo(px0 + 6, py0 + 6.5); x.lineTo(px0 + 14, py0 + 7.5); x.stroke();
    }
  }

  const FLOOR_TINT = { shop: 'rgba(70,120,180,.16)', townhall: 'rgba(230,200,80,.14)', exec: 'rgba(230,110,120,.14)', leisure: 'rgba(230,160,70,.14)', church: 'rgba(180,150,235,.15)', library: 'rgba(90,180,130,.14)' };

  function _doorPx(b) {
    let dc, dr;
    if (b.door === 'N') { dc = b.c + (b.w / 2 | 0); dr = b.r; }
    else if (b.door === 'W') { dc = b.c; dr = b.r + (b.h / 2 | 0); }
    else if (b.door === 'E') { dc = b.c + b.w - 1; dr = b.r + (b.h / 2 | 0); }
    else { dc = b.c + (b.w / 2 | 0); dr = b.r + b.h - 1; }
    return { c: dc, r: dr, x: (dc + 0.5) * TILE, y: (dr + 1) * TILE, side: b.door || 'S' };
  }

  // ── themed thin per-building wall shell ──────────────────────────────────────
  // Muted stone/plaster wall tones per kind (fallback = house). A building may carry
  // its own b.theme (a hex colour) which round-trips through exportLayout; when absent
  // the tone derives from b.kind. The picker UI is a later task — support b.theme now.
  const _WALL_PAL = { hq: '#8b909c', house: '#9a8b76', shop: '#7f93ab', leisure: '#c19a5e',
                      townhall: '#bda257', exec: '#ab6a6a', church: '#897fb0', library: '#5f9a86',
                      research: '#7d86cf' };
  function _themeForKind(kind) { return _WALL_PAL[kind] || _WALL_PAL.house; }
  // lighten (f>0) / darken (f<0) a #rrggbb toward white / black
  function _shade(hex, f) {
    const n = parseInt((hex || '#888').slice(1), 16); let R = (n >> 16) & 255, G = (n >> 8) & 255, B = n & 255;
    if (f < 0) { const k = 1 + f; R *= k; G *= k; B *= k; } else { R += (255 - R) * f; G += (255 - G) * f; B += (255 - B) * f; }
    return `rgb(${R | 0},${G | 0},${B | 0})`;
  }
  // Geometry of the themed wall band: the outer WALL_PX of the footprint edge, with a
  // gap at the door tile (aligned with the T.FLOOR opening _stamp punches). Each rect is
  // tagged with its edge (T/B/L/R) so the painter can put the crisp keyline on the side
  // that faces OUT (toward terrain) vs IN (toward the floor).
  function _shellRects(b) {
    const bx = b.c * TILE, by = b.r * TILE, bw = b.w * TILE, bh = b.h * TILE, wp = WALL_PX;
    const d = _doorPx(b);                                   // door tile (same math as _stamp)
    const dx0 = d.c * TILE, dx1 = (d.c + 1) * TILE;         // door opening pixel span (horizontal edges)
    const dy0 = d.r * TILE, dy1 = (d.r + 1) * TILE;         // door opening pixel span (vertical edges)
    const rects = [];
    // TOP edge band (skip door span when door is on the N side)
    if (d.side === 'N') { rects.push({ x: bx, y: by, w: dx0 - bx, h: wp, edge: 'T' }, { x: dx1, y: by, w: (bx + bw) - dx1, h: wp, edge: 'T' }); }
    else rects.push({ x: bx, y: by, w: bw, h: wp, edge: 'T' });
    // BOTTOM edge band (skip door span when door is on the S side)
    if (d.side === 'S') { rects.push({ x: bx, y: by + bh - wp, w: dx0 - bx, h: wp, edge: 'B' }, { x: dx1, y: by + bh - wp, w: (bx + bw) - dx1, h: wp, edge: 'B' }); }
    else rects.push({ x: bx, y: by + bh - wp, w: bw, h: wp, edge: 'B' });
    // LEFT edge band (skip door span when door is on the W side)
    if (d.side === 'W') { rects.push({ x: bx, y: by, w: wp, h: dy0 - by, edge: 'L' }, { x: bx, y: dy1, w: wp, h: (by + bh) - dy1, edge: 'L' }); }
    else rects.push({ x: bx, y: by, w: wp, h: bh, edge: 'L' });
    // RIGHT edge band (skip door span when door is on the E side)
    if (d.side === 'E') { rects.push({ x: bx + bw - wp, y: by, w: wp, h: dy0 - by, edge: 'R' }, { x: bx + bw - wp, y: dy1, w: wp, h: (by + bh) - dy1, edge: 'R' }); }
    else rects.push({ x: bx + bw - wp, y: by, w: wp, h: bh, edge: 'R' });
    return rects;
  }
  // Paint the themed wall band so it reads UNMISTAKABLY as a wall standing proud of the
  // floor/terrain: a solid wall face (deeper than the floor tone) + a crisp dark keyline
  // on the OUTER pixel (separates the building from the ground) + a lit highlight just
  // inside it + a shadow on the INNER pixel (where the wall meets the interior floor).
  function _paintShell(x, b) {
    const theme = b.theme || _themeForKind(b.kind);
    const wall = _shade(theme, -0.10);                      // wall face — a touch deeper than the theme so it's never floor-coloured
    const lite = _shade(theme, 0.40), dark = _shade(theme, -0.34);
    const key = _shade(theme, -0.62);                       // crisp outer keyline against the terrain
    for (const s of _shellRects(b)) {
      if (s.w <= 0 || s.h <= 0) continue;
      x.fillStyle = wall; x.fillRect(s.x, s.y, s.w, s.h);
      if (s.edge === 'T') {                                 // outer=top, inner=bottom
        x.fillStyle = lite; x.fillRect(s.x, s.y + 1, s.w, 2);
        x.fillStyle = dark; x.fillRect(s.x, s.y + s.h - 1, s.w, 1);
        x.fillStyle = key; x.fillRect(s.x, s.y, s.w, 1);
      } else if (s.edge === 'B') {                          // outer=bottom, inner=top
        x.fillStyle = lite; x.fillRect(s.x, s.y, s.w, 1);
        x.fillStyle = dark; x.fillRect(s.x, s.y + s.h - 3, s.w, 2);
        x.fillStyle = key; x.fillRect(s.x, s.y + s.h - 1, s.w, 1);
      } else if (s.edge === 'L') {                          // outer=left, inner=right
        x.fillStyle = lite; x.fillRect(s.x + 1, s.y, 2, s.h);
        x.fillStyle = dark; x.fillRect(s.x + s.w - 1, s.y, 1, s.h);
        x.fillStyle = key; x.fillRect(s.x, s.y, 1, s.h);
      } else {                                              // R: outer=right, inner=left
        x.fillStyle = lite; x.fillRect(s.x, s.y, 1, s.h);
        x.fillStyle = dark; x.fillRect(s.x + s.w - 3, s.y, 2, s.h);
        x.fillStyle = key; x.fillRect(s.x + s.w - 1, s.y, 1, s.h);
      }
    }
  }
  const _drawBuildingShell = _paintShell;                   // painted per-region into the overview + chunks by _paintRegion()
  // Per-frame legibility pass: as the roofs fade away (zoom in) the walls fade IN on top of
  // everything, so the wall footprint is always crisp regardless of terrain/floor/lighting.
  // alpha is driven by the render layer (1 - roofAlpha); no-op when the roofs are solid.
  function drawWallBands(x, alpha) {
    if (!(alpha > 0.02)) return;
    x.save(); x.globalAlpha = Math.min(1, alpha);
    for (const b of buildings) _paintShell(x, b);
    x.restore();
  }

  // ── Layer-3: per-tile INTERIOR edits (doors / windows / objects) drawn in the zoomed-in
  // reveal layer (called from the render loop with 1-roofAlpha, i.e. as the roofs fade), ON
  // TOP of the per-frame wall bands so a wall-edge door punches through the wall as a real
  // opening. Procedural furniture (_homeFurnish/_hqRooms) stays the default look; these ADD. ─
  function drawInterior(x, alpha) {
    if (!(alpha > 0.02)) return;
    x.save(); x.globalAlpha = Math.min(1, alpha);
    for (const b of buildings) {
      const items = b.interior; if (!items || !items.length) continue;
      for (const it of items) {
        const px = (b.c + it.lc) * TILE, py = (b.r + it.lr) * TILE;
        if (it.kind === 'door') _interiorDoor(x, px, py);
        else if (it.kind === 'window') _interiorWindow(x, px, py);
        else _interiorObject(x, px, py, it.kind, b);
      }
    }
    x.restore();
  }
  function _interiorDoor(x, px, py) {
    const T = TILE;
    x.fillStyle = '#7a5230'; x.fillRect(px + 1, py + 1, T - 2, T - 2);          // floor opening under the leaf
    x.fillStyle = '#5b3a22'; x.fillRect(px + 4, py + 3, T - 8, T - 4);          // door leaf
    x.fillStyle = '#734a2c'; x.fillRect(px + 4, py + 3, T - 8, 2);              // top rail highlight
    x.fillStyle = 'rgba(0,0,0,.3)'; x.fillRect(px + 4, py + T - 2, T - 8, 1);   // threshold shadow
    x.fillStyle = '#e8c14a'; x.fillRect(px + T - 7, py + (T / 2 | 0), 2, 2);    // knob
  }
  function _interiorWindow(x, px, py) {
    const T = TILE;
    x.fillStyle = '#26303f'; x.fillRect(px + 3, py + 5, T - 6, T - 10);                          // frame
    x.fillStyle = '#3a5170'; x.fillRect(px + 4, py + 6, T - 8, T - 12);                          // glass
    x.fillStyle = 'rgba(190,220,255,.55)'; x.fillRect(px + 5, py + 7, (T - 10) / 2 - 1, T - 14); // sky reflection
    x.fillStyle = '#3a2a1a'; x.fillRect(px + (T / 2 | 0) - 0.5, py + 5, 1, T - 10);              // mullion
    x.fillStyle = '#efe6d2'; x.fillRect(px + 2, py + T - 5, T - 4, 1.5);                         // sill
  }
  function _interiorObject(x, px, py, kind, b) {
    const T = TILE, cx = px + T / 2, cy = py + T / 2;
    x.fillStyle = 'rgba(0,0,0,.22)'; x.beginPath(); x.ellipse(cx, py + T - 3, T * 0.32, T * 0.13, 0, 0, 6.283); x.fill();
    if (kind === 'plant') {
      x.fillStyle = '#8a5a2b'; x.fillRect(cx - 3, cy + 2, 6, 5);                // pot
      x.fillStyle = '#a9763f'; x.fillRect(cx - 3, cy + 2, 6, 1.5);
      x.fillStyle = '#2f8542'; x.beginPath(); x.arc(cx, cy - 1, 5, 0, 6.283); x.fill();
      x.fillStyle = '#3ea355'; x.beginPath(); x.arc(cx - 2, cy - 3, 2.6, 0, 6.283); x.fill();
    } else if (kind === 'crate') {
      x.fillStyle = '#8a6238'; x.fillRect(cx - 6, cy - 5, 12, 11);             // crate body
      x.fillStyle = '#a9763f'; x.fillRect(cx - 6, cy - 5, 12, 2);             // lit top edge
      x.strokeStyle = '#5a3d24'; x.lineWidth = 1; x.strokeRect(cx - 6, cy - 5, 12, 11);
      x.beginPath(); x.moveTo(cx - 6, cy - 5); x.lineTo(cx + 6, cy + 6); x.moveTo(cx + 6, cy - 5); x.lineTo(cx - 6, cy + 6); x.stroke();  // banding
    } else {                                                                   // generic furniture — tinted to the building's colour
      x.fillStyle = '#5d4328'; x.fillRect(cx - 6, cy - 3, 12, 8);             // table / chest body
      x.fillStyle = _hex(b.color, 0.9); x.fillRect(cx - 6, cy - 3, 12, 2.5);  // coloured top
      x.fillStyle = 'rgba(255,255,255,.15)'; x.fillRect(cx - 6, cy - 3, 12, 1);
      x.fillStyle = 'rgba(0,0,0,.3)'; x.fillRect(cx - 5, cy + 4, 2, 2); x.fillRect(cx + 3, cy + 4, 2, 2);  // legs
    }
  }

  // per-building detail: floor tint, roof/awning trim, door, sign, interior furniture
  function _building(x, b) {
    const bx = b.c * TILE, by = b.r * TILE, bw = b.w * TILE, bh = b.h * TILE;
    // Layer-2b: ONE shared generated interior-floor texture (warm planks/tiles) as
    // the base under every interior, then the per-kind FLOOR_TINT washed OVER it at
    // low alpha so buildings still read distinct. No floor image → the classic
    // per-kind tint fill only (exact prior behavior).
    const iw = bw - 2 * TILE, ih = bh - 2 * TILE;
    const useFloor = _floorImg && _floorImg.complete && _floorImg.naturalWidth && iw > 0 && ih > 0;
    if (useFloor) x.drawImage(_floorImg, bx + TILE, by + TILE, iw, ih);   // baked in _bake()
    const tint = FLOOR_TINT[b.kind]; if (tint) { x.fillStyle = tint; x.fillRect(bx + TILE, by + TILE, bw - 2 * TILE, bh - 2 * TILE); }
    if (b.kind === 'hq') _hqRooms(x, b);               // divide HQ into furnished department rooms
    // roof / awning trim in the building colour (makes each type distinct) — skip when
    // the Kenney wall ring is drawn (it would paint over the top wall tiles)
    if (!(window.WB && WB.ready)) {
      x.fillStyle = _hex(b.color, b.kind === 'hq' ? .9 : .8); x.fillRect(bx, by, bw, b.kind === 'hq' ? 6 : 4);
      x.fillStyle = 'rgba(255,255,255,.18)'; x.fillRect(bx, by, bw, 1);
      x.fillStyle = 'rgba(0,0,0,.3)'; x.fillRect(bx, by + (b.kind === 'hq' ? 6 : 4), bw, 1);
    }
    // door
    const d = _doorPx(b), dx = d.c * TILE, dy = d.r * TILE;
    x.fillStyle = '#5b3a22'; x.fillRect(dx + 4, dy + 3, TILE - 8, TILE - 3);
    x.fillStyle = '#734a2c'; x.fillRect(dx + 4, dy + 3, TILE - 8, 2);
    x.fillStyle = '#e8c14a'; x.fillRect(dx + TILE - 7, dy + TILE / 2, 2, 2);           // knob
    // hanging sign near the door for named/shop buildings
    if (b.label && b.kind !== 'hq' && b.kind !== 'house') {
      x.fillStyle = _hex(b.color, .95); x.fillRect(dx + 2, dy - 6, TILE - 4, 5);
      x.fillStyle = 'rgba(0,0,0,.35)'; x.fillRect(dx + 2, dy - 1, TILE - 4, 1);
    }
    if (b.kind === 'house' && !(window.WB && WB.ready)) _fence(x, b);   // wall ring replaces the yard fence
    // department banners hung on the top wall — restores the colour identity the
    // roof-trim used to give, in-theme (needs the extracted pennant sprites)
    const bn = _bannerFor(b);
    if (bn && window.WA && WA.hasSprite && WA.hasSprite(bn)) {
      const bh2 = TILE * 1.3, byb = by + TILE * 1.35;
      if (b.kind === 'hq') { WA.drawSprite(x, bn, bx + bw * 0.30, byb, bh2); WA.drawSprite(x, bn, bx + bw * 0.70, byb, bh2); }
      else if (b.label) WA.drawSprite(x, bn, bx + bw / 2, byb, bh2);
    }
    // interior furniture: a rug + a potted plant (skip HQ — it has desks)
    if (b.kind !== 'hq' && b.w >= 5 && b.h >= 5) {
      const cxp = bx + bw / 2, cyp = by + bh / 2;
      x.fillStyle = _hex(b.color, .20); x.beginPath(); x.roundRect(cxp - TILE * 0.9, cyp - TILE * 0.55, TILE * 1.8, TILE * 1.1, 3); x.fill();
      x.strokeStyle = _hex(b.color, .5); x.lineWidth = 1; x.stroke();
      // real barrel + crate in the corners (fallback: procedural potted plant)
      if (window.WA && WA.hasSprite && WA.hasSprite('barrel')) {
        WA.drawSprite(x, 'barrel', bx + TILE + 4, by + bh - TILE - 2, TILE * 0.95);
        WA.drawSprite(x, (b.c + b.r) % 2 ? 'crate' : 'crate_produce', bx + bw - TILE - 4, by + bh - TILE - 2, TILE * 0.95);
      } else {
        const pxp = bx + TILE + 3, pyp = by + bh - TILE - 3;                             // plant, back corner
        x.fillStyle = '#6b4c2f'; x.fillRect(pxp - 2, pyp, 4, 4);
        x.fillStyle = '#2f8542'; x.beginPath(); x.arc(pxp, pyp - 1, 3.2, 0, 6.283); x.fill();
        x.fillStyle = '#3ea355'; x.beginPath(); x.arc(pxp - 1, pyp - 2, 1.8, 0, 6.283); x.fill();
      }
    }
    if (b.kind === 'house') _homeFurnish(x, b, bx, by, bw, bh);   // beds, table — lived-in homes
  }

  // procedural home interior — a real two-room home: bedroom behind a partition
  // (bed/wardrobe/nightstand/rug) + living space (archetype piece, dining table),
  // with sunlight falling in from the windows. Varied per building id.
  function _homeFurnish(x, b, bx, by, bw, bh) {
    const vtint = ['rgba(210,170,110,.07)', 'rgba(150,190,230,.07)', 'rgba(220,150,150,.07)'][(b.id || 0) % 3];
    x.fillStyle = vtint; x.fillRect(bx + TILE, by + TILE, bw - 2 * TILE, bh - 2 * TILE);  // per-house floor tone
    // sunlight streaks from the top-wall windows
    x.fillStyle = 'rgba(255,240,200,.09)';
    x.fillRect(bx + bw * 0.18, by + TILE, TILE * 0.8, bh * 0.42);
    x.fillRect(bx + bw * 0.62, by + TILE, TILE * 0.8, bh * 0.42);
    // bedroom PARTITION: wall stub from the top wall, with a door gap
    const partX = bx + bw * 0.46, partH = bh * 0.52;
    x.strokeStyle = 'rgba(44,33,22,.7)'; x.lineWidth = 2;
    x.beginPath(); x.moveTo(partX, by + TILE); x.lineTo(partX, by + TILE + partH * 0.62); x.stroke();
    x.strokeStyle = 'rgba(210,170,110,.45)'; x.lineWidth = 1;
    x.beginPath(); x.moveTo(partX, by + TILE + partH * 0.62); x.lineTo(partX, by + TILE + partH * 0.62 + 4); x.stroke();  // door frame hint
    // bedroom rug
    x.fillStyle = _hex(b.color, .12); x.beginPath(); x.roundRect(bx + TILE * 0.7, by + bh * 0.36, TILE * 2.2, TILE * 1.5, 3); x.fill();
    const bex = bx + TILE * 0.8, bey = by + bh * 0.42;             // bed along the left wall (clear of the wall art)
    x.fillStyle = '#6e4a2b'; x.fillRect(bex, bey, TILE * 1.5, TILE * 0.95);
    x.fillStyle = '#c9b48a'; x.fillRect(bex + 2, bey + 2, TILE * 1.5 - 4, TILE * 0.9 - 3);   // mattress
    x.fillStyle = '#e6ebf3'; x.fillRect(bex + 2, bey + 2, TILE * 0.5, TILE * 0.9 - 3);       // pillow
    x.fillStyle = _hex(b.color, .8); x.fillRect(bex + TILE * 0.55, bey + 2, TILE * 0.95 - 2, TILE * 0.9 - 3); // blanket
    x.fillStyle = 'rgba(0,0,0,.25)'; x.fillRect(bex, bey + TILE * 0.95 - 2, TILE * 1.5, 2);
    // nightstand by the bed + wardrobe in the bedroom's bottom corner
    x.fillStyle = '#7a5230'; x.fillRect(bex + TILE * 1.6, bey + 2, 6, 7);
    x.fillStyle = '#e8c14a'; x.fillRect(bex + TILE * 1.6 + 2, bey + 4, 2, 1);
    const wx = bx + TILE * 0.75, wy = by + bh - TILE * 1.7;
    x.fillStyle = '#664526'; x.fillRect(wx, wy, 12, TILE * 0.9);                             // wardrobe
    x.fillStyle = 'rgba(0,0,0,.35)'; x.fillRect(wx + 5.5, wy + 1, 1, TILE * 0.9 - 2);        // door split
    x.fillStyle = '#e8c14a'; x.fillRect(wx + 3.5, wy + 8, 1.5, 2); x.fillRect(wx + 7, wy + 8, 1.5, 2);
    // dining table + stools, bottom-right (living room)
    const tx = bx + bw - TILE * 1.3, ty = by + bh - TILE * 1.3;
    x.fillStyle = '#5a3d24'; x.beginPath(); x.arc(tx, ty, 6, 0, 6.283); x.fill();
    x.fillStyle = '#7a5230'; x.beginPath(); x.arc(tx, ty, 4.5, 0, 6.283); x.fill();
    x.fillStyle = '#d8c9a5'; x.fillRect(tx - 2.5, ty - 2.5, 5, 5);                           // table setting
    x.fillStyle = '#8a97ad'; x.beginPath(); x.arc(tx - 8, ty + 1, 2, 0, 6.283); x.fill(); x.beginPath(); x.arc(tx + 8, ty - 1, 2, 0, 6.283); x.fill();
    // archetype piece in the LIVING room, along the top wall right of the partition
    const ax0 = partX + 5, ay0 = by + TILE * 1.1, v = (b.id || 0) % 3;
    if (v === 0) {                                     // KITCHEN: counter run + stove + sink
      const cw = Math.min(bw - TILE * 2.6, TILE * 2.6);
      x.fillStyle = '#8b8f98'; x.fillRect(ax0, ay0, cw, 7);                       // counter
      x.fillStyle = '#b9bec7'; x.fillRect(ax0, ay0, cw, 2);                       // top light
      x.fillStyle = '#2a2f3a'; x.fillRect(ax0 + 2, ay0 + 2, 8, 4);                // stove
      x.fillStyle = '#f0a860'; x.fillRect(ax0 + 3, ay0 + 3, 2, 2); x.fillRect(ax0 + 7, ay0 + 3, 2, 2); // burners
      x.fillStyle = '#5f97c4'; x.fillRect(ax0 + cw - 9, ay0 + 2, 6, 3);           // sink
    } else if (v === 1) {                              // READER: bookshelf + reading chair
      x.fillStyle = '#5d3f26'; x.fillRect(ax0, ay0, TILE * 1.6, 8);
      for (let i = 0; i < 6; i++) { x.fillStyle = ['#c25b4e', '#4e7fc2', '#57a06a', '#c2a44e'][i % 4]; x.fillRect(ax0 + 2 + i * 5, ay0 + 2, 3, 5); }
      x.fillStyle = _hex(b.color, .75); x.fillRect(ax0 + TILE * 1.9, ay0, 9, 8);  // armchair
      x.fillStyle = 'rgba(255,255,255,.2)'; x.fillRect(ax0 + TILE * 1.9, ay0, 9, 2);
    } else {                                           // HEARTH: fireplace + dresser
      x.fillStyle = '#6f6a63'; x.fillRect(ax0, ay0 - 2, 14, 10);                  // stone chimney breast
      x.fillStyle = '#241d16'; x.fillRect(ax0 + 3, ay0 + 2, 8, 5);                // firebox
      x.fillStyle = '#f0a03c'; x.fillRect(ax0 + 4, ay0 + 4, 6, 3);                // embers
      x.fillStyle = '#e8c14a'; x.fillRect(ax0 + 6, ay0 + 3, 2, 2);
      x.fillStyle = '#7a5230'; x.fillRect(ax0 + TILE * 1.4, ay0, 12, 8);          // dresser
      x.fillStyle = 'rgba(0,0,0,.3)'; x.fillRect(ax0 + TILE * 1.4, ay0 + 4, 12, 1);
      x.fillStyle = '#e8c14a'; x.fillRect(ax0 + TILE * 1.4 + 5, ay0 + 2, 2, 1); x.fillRect(ax0 + TILE * 1.4 + 5, ay0 + 6, 2, 1);
    }
    // inner AO ring — the room reads enclosed instead of painted-on
    x.strokeStyle = 'rgba(0,0,0,.16)'; x.lineWidth = 3;
    x.strokeRect(bx + TILE + 1.5, by + TILE + 1.5, bw - 2 * TILE - 3, bh - 2 * TILE - 3);
  }

  // pick a heraldry banner colour for a building kind (identity coding)
  const _BANNER = { hq: 'banner_blue', shop: 'banner_green', townhall: 'banner_red', exec: 'banner_red', leisure: 'banner_green', church: 'banner_blue', library: 'banner_green' };
  function _bannerFor(b) { return _BANNER[b.kind] || null; }

  const _TKEY = { 0: 'grass', 1: 'path', 2: 'floor', 3: 'wall', 4: 'tree', 5: 'water', 6: 'plaza' };
  function _tile(x, c, r) {
    const t = grid[r][c], px = c * TILE, py = r * TILE, v = hsh(c, r);
    // Generated/atlas terrain is OFF by default: the auto-painted atlas produced a
    // stamped single-cell grid + noisy water and kept regenerating the manifest on
    // world load, so procedural terrain (varied per-tile) always wins unless someone
    // explicitly opts in via window.WORLD_ATLAS_TERRAIN = true after the tileset is
    // fixed (per-tile variation + water QA). This is the durable kill-switch.
    if (window.WORLD_ATLAS_TERRAIN === true && window.WA && WA.ready
        && WA.tile(x, _TKEY[t], px, py, TILE)) return;
    if (t === T.GRASS) {
      x.fillStyle = v < .5 ? '#3a7d44' : '#357640'; x.fillRect(px, py, TILE, TILE);
      x.fillStyle = 'rgba(74,150,86,.55)'; for (let i = 0; i < 3; i++) { const a = hsh(c, r, i + 1), b = hsh(c, r, i + 5); x.fillRect(px + (a * (TILE - 3) | 0), py + (b * (TILE - 3) | 0), 2, 1); }
      x.fillStyle = 'rgba(30,70,40,.4)'; x.fillRect(px + (hsh(c, r, 9) * TILE | 0), py + (hsh(c, r, 10) * TILE | 0), 1, 2);
      if (v > .93) { x.fillStyle = FLOWERS[(hsh(c, r, 3) * FLOWERS.length | 0)]; const fx = px + 6 + (hsh(c, r, 4) * 7 | 0), fy = py + 6 + (hsh(c, r, 6) * 7 | 0); x.fillRect(fx, fy, 2, 2); x.fillStyle = '#e8e0a0'; x.fillRect(fx, fy, 1, 1); }
    } else if (t === T.PATH || t === T.PLAZA) {
      x.fillStyle = t === T.PLAZA ? '#b9b1a0' : '#9c8f77'; x.fillRect(px, py, TILE, TILE);      // cobble/stone
      x.fillStyle = 'rgba(0,0,0,.12)'; x.fillRect(px, py, TILE, 1); x.fillRect(px, py, 1, TILE);  // grout
      x.fillStyle = t === T.PLAZA ? 'rgba(255,255,255,.10)' : 'rgba(255,240,210,.08)';
      for (let i = 0; i < 2; i++) x.fillRect(px + (hsh(c, r, i + 1) * (TILE - 4) | 0) + 1, py + (hsh(c, r, i + 3) * (TILE - 4) | 0) + 1, 3, 2);
      // bevel where the road meets grass — the path reads as slightly sunken (3D cue)
      const gU = r > 0 && grid[r - 1][c] === T.GRASS, gD = r < ROWS - 1 && grid[r + 1][c] === T.GRASS;
      const gL = c > 0 && grid[r][c - 1] === T.GRASS, gR = c < COLS - 1 && grid[r][c + 1] === T.GRASS;
      if (gU) { x.fillStyle = 'rgba(0,0,0,.22)'; x.fillRect(px, py, TILE, 2); }
      if (gD) { x.fillStyle = 'rgba(255,250,235,.18)'; x.fillRect(px, py + TILE - 2, TILE, 2); }
      if (gL) { x.fillStyle = 'rgba(0,0,0,.14)'; x.fillRect(px, py, 2, TILE); }
      if (gR) { x.fillStyle = 'rgba(255,250,235,.10)'; x.fillRect(px + TILE - 2, py, 2, TILE); }
    } else if (t === T.FLOOR) {                         // warm wood-plank interior
      x.fillStyle = v < .5 ? '#7a5230' : '#734c2c'; x.fillRect(px, py, TILE, TILE);
      x.fillStyle = 'rgba(0,0,0,.18)'; x.fillRect(px, py + (r % 2 ? 6 : 13), TILE, 1);
      x.fillStyle = 'rgba(255,220,170,.06)'; x.fillRect(px, py + 1, TILE, 1);
    } else if (t === T.WALL) {                           // WALL cell is still solid for collision, but no longer
      // rendered as a fat 20px stone ring: paint it as the interior FLOOR look so the
      // baked terrain shows no thick stone band. The thin themed wall is drawn on top
      // per-building by _drawBuildingShell (outer WALL_PX of the footprint edge).
      x.fillStyle = v < .5 ? '#7a5230' : '#734c2c'; x.fillRect(px, py, TILE, TILE);   // warm wood-plank (matches T.FLOOR)
      x.fillStyle = 'rgba(0,0,0,.18)'; x.fillRect(px, py + (r % 2 ? 6 : 13), TILE, 1);
      x.fillStyle = 'rgba(255,220,170,.06)'; x.fillRect(px, py + 1, TILE, 1);
      return;
    } else if (t === T.WALL_UNUSED_BRICK) {              // (legacy procedural brick — no longer reached)
      x.fillStyle = '#8a5a44'; x.fillRect(px, py, TILE, TILE);
      x.fillStyle = 'rgba(0,0,0,.22)'; for (let ry = 0; ry < TILE; ry += 6) x.fillRect(px, py + ry, TILE, 1);
      const off = (r % 2) ? 10 : 0; for (let rx = -off; rx < TILE; rx += 20) x.fillRect(px + rx + 9, py, 1, TILE);
      x.fillStyle = 'rgba(255,235,200,.14)'; x.fillRect(px, py, TILE, 2);
      x.fillStyle = 'rgba(0,0,0,.25)'; x.fillRect(px, py + TILE - 2, TILE, 2);
      if (v > .82) { x.fillStyle = '#bfe3ff'; x.fillRect(px + 6, py + 6, 8, 7); x.fillStyle = '#5b3d2e'; x.strokeStyle = '#5b3d2e'; x.strokeRect(px + 5.5, py + 5.5, 9, 8); x.fillRect(px + 9, py + 6, 1, 7); }  // window
    } else if (t === T.WATER) {
      x.fillStyle = '#2f6a9e'; x.fillRect(px, py, TILE, TILE); x.fillStyle = 'rgba(150,210,255,.4)'; x.fillRect(px + 3, py + (hsh(c, r, 1) * TILE | 0), 8, 1);
    } else if (t === T.TREE) {
      // TALL tree — trunk on this tile, layered canopy rising into the tile above
      // (rows bake top→down, so drawing upward paints over already-baked grass).
      _grassBg(x, px, py, c, r);
      const mx = px + TILE / 2, tall = TILE * (0.75 + v * 0.35);
      x.fillStyle = 'rgba(0,0,0,.30)'; x.beginPath(); x.ellipse(mx + 2, py + TILE - 2, TILE * 0.46, TILE * 0.16, 0, 0, 6.283); x.fill();
      x.fillStyle = '#5a3d24'; x.fillRect(mx - 1.5, py + TILE - 11, 3.5, 10);               // trunk
      x.fillStyle = 'rgba(0,0,0,.25)'; x.fillRect(mx + 1, py + TILE - 11, 1, 10);           // trunk shade
      const cy = py + TILE * 0.35 - tall * 0.45;                                            // canopy centre (raised)
      x.fillStyle = '#1f5c2d'; x.beginPath(); x.ellipse(mx + 1.5, cy + 3, TILE * 0.5, tall * 0.52, 0, 0, 6.283); x.fill();   // dark under-canopy
      x.fillStyle = '#2b7a3d'; x.beginPath(); x.ellipse(mx, cy, TILE * 0.44, tall * 0.48, 0, 0, 6.283); x.fill();
      x.fillStyle = '#3a9450'; x.beginPath(); x.ellipse(mx - 2, cy - tall * 0.14, TILE * 0.3, tall * 0.3, 0, 0, 6.283); x.fill();  // lit side
      x.fillStyle = '#55b168'; x.beginPath(); x.ellipse(mx - 3.5, cy - tall * 0.24, TILE * 0.15, tall * 0.15, 0, 0, 6.283); x.fill();
      if (v > .8) { x.fillStyle = 'rgba(255,235,170,.7)'; x.fillRect(mx + 3, cy + 2, 1.5, 1.5); x.fillRect(mx - 5, cy + 5, 1.5, 1.5); }  // fruit glints
    } else if (t === T.MOUNTAIN) {                        // rocky peak (drawn tall so a band reads as a range)
      _grassBg(x, px, py, c, r);
      const pk = 5 + (v * 9 | 0), mid = px + TILE / 2;
      x.fillStyle = v < .5 ? '#5c606b' : '#666a75'; x.beginPath(); x.moveTo(px - 1, py + TILE); x.lineTo(mid, py - pk); x.lineTo(px + TILE + 1, py + TILE); x.closePath(); x.fill();
      x.fillStyle = '#7d828f'; x.beginPath(); x.moveTo(mid, py - pk); x.lineTo(mid, py + TILE); x.lineTo(px + TILE + 1, py + TILE); x.closePath(); x.fill();   // lit face
      x.fillStyle = 'rgba(0,0,0,.25)'; x.beginPath(); x.moveTo(px - 1, py + TILE); x.lineTo(mid, py + TILE); x.lineTo(mid, py + TILE - 3); x.closePath(); x.fill();
      if (v > .32) { x.fillStyle = '#eef2f8'; x.beginPath(); x.moveTo(mid, py - pk); x.lineTo(mid + 3.5, py - pk + 6); x.lineTo(mid - 3.5, py - pk + 6); x.closePath(); x.fill(); }  // snow cap
    }
  }
  function _grassBg(x, px, py, c, r) { x.fillStyle = hsh(c, r) < .5 ? '#3a7d44' : '#357640'; x.fillRect(px, py, TILE, TILE); }

  // a little picket fence / yard around a house — 3 sides, leaving the door open
  function _fence(x, b) {
    const m = TILE * 0.4, x0 = b.c * TILE - m, y0 = b.r * TILE - m, x1 = (b.c + b.w) * TILE + m, y1 = (b.r + b.h) * TILE + m;
    const post = (px, py) => { x.fillStyle = '#a89168'; x.fillRect(px - 1, py - 5, 2, 6); x.fillStyle = '#c9b488'; x.fillRect(px - 1, py - 5, 2, 1); };
    const rail = (ax, ay, bx, by) => { x.strokeStyle = 'rgba(168,145,104,.85)'; x.lineWidth = 1.5; x.beginPath(); x.moveTo(ax, ay - 2); x.lineTo(bx, by - 2); x.stroke(); };
    const s = b.door;
    if (s !== 'N') { rail(x0, y0, x1, y0); for (let p = x0; p <= x1; p += 7) post(p, y0); }
    if (s !== 'S') { rail(x0, y1, x1, y1); for (let p = x0; p <= x1; p += 7) post(p, y1); }
    if (s !== 'W') { rail(x0, y0, x0, y1); for (let p = y0; p <= y1; p += 7) post(x0, p); }
    if (s !== 'E') { rail(x1, y0, x1, y1); for (let p = y0; p <= y1; p += 7) post(x1, p); }
  }

  function _decorSprite(x, d) {
    if (d.kind === 'lamp') { x.fillStyle = '#2a2f3a'; x.fillRect(d.x - 1, d.y - 9, 2, 9); x.fillStyle = '#4a5568'; x.fillRect(d.x - 2, d.y - 11, 4, 3); x.fillStyle = '#ffe9a8'; x.fillRect(d.x - 1, d.y - 10, 2, 2); x.fillStyle = 'rgba(255,233,168,.25)'; x.beginPath(); x.arc(d.x, d.y - 9, 5, 0, 6.283); x.fill(); }
    else if (d.kind === 'bench') { x.fillStyle = '#6b4c2f'; x.fillRect(d.x - 6, d.y - 2, 12, 3); x.fillStyle = '#4a3b2a'; x.fillRect(d.x - 6, d.y + 1, 2, 3); x.fillRect(d.x + 4, d.y + 1, 2, 3); x.fillStyle = '#7a5836'; x.fillRect(d.x - 6, d.y - 5, 12, 2); }
    else if (d.kind === 'bush') { x.fillStyle = '#256b34'; x.beginPath(); x.arc(d.x, d.y, 4, 0, 6.283); x.fill(); x.fillStyle = '#3ea355'; x.beginPath(); x.arc(d.x - 1, d.y - 1, 2.4, 0, 6.283); x.fill(); if (d.x % 3 < 1) { x.fillStyle = '#e05a6a'; x.fillRect(d.x + 1, d.y - 1, 1, 1); } }
    else if (d.kind === 'rock') { x.fillStyle = '#8a8f9c'; x.beginPath(); x.arc(d.x, d.y, 3, 0, 6.283); x.fill(); x.fillStyle = '#aeb4c0'; x.beginPath(); x.arc(d.x - 1, d.y - 1, 1.4, 0, 6.283); x.fill(); }
    else if (d.kind === 'fountain') { x.fillStyle = '#8a8f9c'; x.beginPath(); x.arc(d.x, d.y, 9, 0, 6.283); x.fill(); x.fillStyle = '#3f7fb0'; x.beginPath(); x.arc(d.x, d.y, 7, 0, 6.283); x.fill(); x.fillStyle = '#aeb4c0'; x.fillRect(d.x - 1, d.y - 8, 2, 8); x.fillStyle = '#bfe4ff'; x.fillRect(d.x - 1, d.y - 10, 2, 3); x.fillStyle = 'rgba(190,228,255,.7)'; x.fillRect(d.x - 3, d.y - 1, 1, 1); x.fillRect(d.x + 2, d.y - 2, 1, 1); }
    else if (d.kind === 'statue') { x.fillStyle = '#6b6f7a'; x.fillRect(d.x - 5, d.y - 2, 10, 3); x.fillStyle = '#9aa0ad'; x.fillRect(d.x - 2, d.y - 14, 4, 12); x.beginPath(); x.arc(d.x, d.y - 15, 2.5, 0, 6.283); x.fill(); x.fillStyle = 'rgba(255,255,255,.2)'; x.fillRect(d.x - 2, d.y - 14, 1.5, 12); }
    else if (d.kind === 'plant') { x.fillStyle = '#6b4c2f'; x.fillRect(d.x - 2, d.y - 3, 4, 4); x.fillStyle = '#2f8542'; x.beginPath(); x.arc(d.x, d.y - 5, 4, 0, 6.283); x.fill(); x.fillStyle = '#3ea355'; x.beginPath(); x.arc(d.x - 1, d.y - 6, 2.4, 0, 6.283); x.fill(); }
    else if (d.kind === 'picnic_table') {
      // checkered blanket + wooden table with side benches + a little basket
      x.fillStyle = '#b8433f'; x.fillRect(d.x - 8, d.y - 5, 16, 11);
      x.fillStyle = '#e8e2d4';
      for (let r = 0; r < 3; r++) for (let c = 0; c < 4; c++)
        if ((r + c) % 2) x.fillRect(d.x - 8 + c * 4, d.y - 5 + r * 4, 4, Math.min(4, 11 - r * 4));
      x.fillStyle = '#6b4c2f'; x.fillRect(d.x - 5, d.y - 3, 10, 5);
      x.fillStyle = '#7a5836'; x.fillRect(d.x - 5, d.y - 4, 10, 2);
      x.fillStyle = '#4a3b2a'; x.fillRect(d.x - 7, d.y - 2, 2, 3); x.fillRect(d.x + 5, d.y - 2, 2, 3);
      x.fillStyle = '#8a5a2b'; x.fillRect(d.x + 1, d.y - 6, 4, 3);
      x.fillStyle = '#c9a15a'; x.fillRect(d.x + 2, d.y - 7, 2, 1);
    }
  }

  // Draw the ground under the live camera transform. Zoomed OUT → the cheap whole-map
  // overview. Zoomed IN → the overview as an instant fallback, then full-res chunks for
  // just the visible viewport (baked on a per-frame budget, evicted once off-screen), so
  // memory stays flat no matter how big the map is. `canvas` gives the viewport size used
  // to pick visible chunks (falls back to overview-only if it's missing).
  function drawTerrain(ctx, canvas) {
    if (!_overview) return;
    ctx.drawImage(_overview, 0, 0, W, H);                       // base LOD (also the fallback under baking chunks)
    if (camera.scale < CHUNK_LOD || !canvas) return;            // zoomed out → overview is enough

    const vw = canvas._cssW || canvas.clientWidth || 0, vh = canvas._cssH || canvas.clientHeight || 0;
    if (!vw || !vh) return;
    // visible world rect → chunk index span (+1 chunk margin so panning stays ahead)
    const wx0 = (0 - camera.x) / camera.scale, wy0 = (0 - camera.y) / camera.scale;
    const wx1 = (vw - camera.x) / camera.scale, wy1 = (vh - camera.y) / camera.scale;
    const cwPx = CHUNK_CW * TILE, chPx = CHUNK_CH * TILE;
    const nX = Math.ceil(COLS / CHUNK_CW), nY = Math.ceil(ROWS / CHUNK_CH);
    const cx0 = Math.max(0, Math.floor(wx0 / cwPx) - 1), cx1 = Math.min(nX - 1, Math.floor(wx1 / cwPx) + 1);
    const cy0 = Math.max(0, Math.floor(wy0 / chPx) - 1), cy1 = Math.min(nY - 1, Math.floor(wy1 / chPx) + 1);
    const now = performance.now();
    let budget = CHUNK_BUDGET;
    for (let cy = cy0; cy <= cy1; cy++) for (let cx = cx0; cx <= cx1; cx++) {
      const k = cx + ',' + cy;
      let ch = _chunks.get(k);
      if (!ch) {
        if (budget <= 0) continue;                              // over budget this frame → overview shows through until baked
        budget--; ch = _bakeChunk(cx, cy); _chunks.set(k, ch);
      }
      ch.seen = now;
      ctx.drawImage(ch.cv, ch.wx, ch.wy);
    }
    if (_chunks.size > 16) for (const [k, ch] of _chunks)       // evict off-screen chunks (bounded memory)
      if (now - ch.seen > CHUNK_EVICT_MS) _chunks.delete(k);
  }
  const BLD_ICON = { hq: '🏢', townhall: '🏛️', exec: '💼', library: '📚', church: '⛪',
                     bar: '🍺', arcade: '🕹️', tv: '📺', cafe: '☕', park: '🌳',
                     gas: '⛽', lounge: '🛋️', shop: '🏪', house: '🏠' };
  function _bldIcon(b) { return BLD_ICON[b.loc] || BLD_ICON[b.kind] || '🏢'; }
  function _plainLabel(b) { return (b.label || '').replace(/[\u{1F000}-\u{1FFFF}☀-➿️]/gu, '').trim(); }

  // Readable name-plate over every building so you can tell them apart at a glance:
  // a dark pill + type ICON + name, colour-keyed to the building.
  function drawBuildingLabels(ctx) {
    ctx.textBaseline = 'alphabetic';
    for (const b of buildings) {
      const icon = _bldIcon(b);
      const name = b.kind === 'hq' ? 'THE COMPANY HQ' : _plainLabel(b);
      if (b.house) {                                  // houses: just a small roof glyph, no clutter
        ctx.font = '9px sans-serif'; ctx.textAlign = 'center';
        ctx.globalAlpha = 0.5; ctx.fillText('🏠', (b.c + b.w / 2) * TILE, b.r * TILE - 2); ctx.globalAlpha = 1;
        continue;
      }
      const big = b.kind === 'hq';
      ctx.font = `${big ? 'bold 11' : b.small ? '8' : 'bold 9'}px sans-serif`;
      const txt = name ? `${icon} ${name}` : icon;
      // measureText was called for every labelled building EVERY frame though the
      // text + font never change — cache the width on the building (invalidate if
      // the label/font ever changes).
      const twKey = ctx.font + '|' + txt;
      if (b._twKey !== twKey) { b._tw = ctx.measureText(txt).width; b._twKey = twKey; }
      const tw = b._tw, padX = 4, h = big ? 16 : 13;
      const cx = (b.c + b.w / 2) * TILE, bx = Math.round(cx - tw / 2 - padX), by = b.r * TILE - h - 2;
      ctx.fillStyle = 'rgba(10,14,22,.82)';           // pill background
      ctx.fillRect(bx, by, tw + padX * 2, h);
      ctx.fillStyle = b.color || '#cfe0ff';           // colour bar keyed to the building type
      ctx.fillRect(bx, by, 2, h);
      ctx.fillStyle = '#eef4ff'; ctx.textAlign = 'left';
      ctx.fillText(txt, bx + padX, by + h - (big ? 5 : 4));
    }
  }

  // ── geometry + A* ──
  const walkable = (c, r) => inb(c, r) && WALK_COST[grid[r][c]] !== undefined;
  function nearestWalkable(t) {
    if (walkable(t.col, t.row)) return t;
    for (let rad = 1; rad < 10; rad++) for (let dr = -rad; dr <= rad; dr++) for (let dc = -rad; dc <= rad; dc++) { const c = t.col + dc, r = t.row + dr; if (walkable(c, r)) return { col: c, row: r }; }
    return t;
  }
  const tileToPx = (col, row) => ({ x: (col + 0.5) * TILE, y: (row + 0.5) * TILE });
  const DIRS = [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [1, -1], [-1, 1], [-1, -1]];
  function findPath(start, goal) {
    start = { col: Math.round(start.col), row: Math.round(start.row) };
    goal = nearestWalkable({ col: Math.round(goal.col), row: Math.round(goal.row) });
    if (!walkable(start.col, start.row)) start = nearestWalkable(start);
    const key = (c, r) => c + ',' + r;
    const g = {}, f = {}, came = {}, open = new Map();
    const h = (c, r) => Math.hypot(c - goal.col, r - goal.row);
    const sk = key(start.col, start.row); g[sk] = 0; f[sk] = h(start.col, start.row); open.set(sk, start);
    let iter = 0;
    while (open.size && iter++ < 14000) {
      let bk = null, bf = Infinity, bn = null;
      for (const [k, n] of open) { const fv = f[k] ?? Infinity; if (fv < bf) { bf = fv; bk = k; bn = n; } }
      if (bn.col === goal.col && bn.row === goal.row) { const path = []; let cur = bn; while (cur) { path.push(cur); cur = came[key(cur.col, cur.row)]; } return path.reverse(); }
      open.delete(bk);
      for (const [dc, dr] of DIRS) {
        const nc = bn.col + dc, nr = bn.row + dr;
        if (!walkable(nc, nr)) continue;
        if (dc && dr && (!walkable(bn.col + dc, bn.row) || !walkable(bn.col, bn.row + dr))) continue;
        const t = grid[nr][nc];
        const base = t === T.GRASS ? WEAR_COST[wearStage(nc, nr)] : WALK_COST[t];  // worn trails are faster
        const step = (dc && dr ? 1.414 : 1) * base;
        const nk = key(nc, nr), ng = (g[bk] ?? Infinity) + step;
        if (ng < (g[nk] ?? Infinity)) { came[nk] = { col: bn.col, row: bn.row }; g[nk] = ng; f[nk] = ng + h(nc, nr); if (!open.has(nk)) open.set(nk, { col: nc, row: nr }); }
      }
    }
    return null;
  }

  // ── camera ──
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  function fit(vpW, vpH) { camera.scale = Math.min(vpW / W, vpH / H) * 0.98; _fitScale = camera.scale; camera.x = (vpW - W * camera.scale) / 2; camera.y = (vpH - H * camera.scale) / 2; }
  const screenToWorld = (sx, sy) => ({ x: (sx - camera.x) / camera.scale, y: (sy - camera.y) / camera.scale });
  const worldToTile = (wx, wy) => ({ col: Math.floor(wx / TILE), row: Math.floor(wy / TILE) });

  // Window-level drag listeners were re-added on EVERY renderWorld() and never removed —
  // each old pair pinned a stale canvas backing store (8-30MB). Keep refs to the current
  // pair so a new attach (or teardown) can removeEventListener the previous ones.
  let _winMove = null, _winUp = null;
  function detachControls() {
    if (_winMove) window.removeEventListener('mousemove', _winMove);
    if (_winUp) window.removeEventListener('mouseup', _winUp);
    _winMove = _winUp = null;
  }
  function attachControls(canvas, opts) {
    opts = opts || {};
    detachControls();                       // drop any prior view's window listeners
    let drag = null;
    canvas.addEventListener('mousedown', e => {
      if (opts.isEditing && opts.isEditing()) { if (opts.onEditDown && opts.onEditDown(e)) return; }
      drag = { x: e.clientX, y: e.clientY, cx: camera.x, cy: camera.y, moved: 0 };
    });
    _winMove = e => {
      if (opts.isEditing && opts.isEditing() && opts.onEditMove && opts.onEditMove(e)) return;
      if (!drag) return;
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y; drag.moved += Math.abs(dx) + Math.abs(dy);
      camera.x = drag.cx + dx; camera.y = drag.cy + dy;
    };
    _winUp = e => { if (opts.onEditUp) opts.onEditUp(e); if (drag) { canvas._dragMoved = drag.moved; drag = null; } };
    window.addEventListener('mousemove', _winMove);
    window.addEventListener('mouseup', _winUp);
    canvas.addEventListener('wheel', e => {
      e.preventDefault();
      const rect = canvas.getBoundingClientRect(), mx = e.clientX - rect.left, my = e.clientY - rect.top;
      const wx = (mx - camera.x) / camera.scale, wy = (my - camera.y) / camera.scale;
      // min extended far below fit so you can pull ALL the way back into orbit (the
      // town shrinks to a lit patch in space — world-sky.js fades stars in down there).
      camera.scale = clamp(camera.scale * (e.deltaY < 0 ? 1.12 : 0.89), 0.06, 4);
      camera.x = mx - wx * camera.scale; camera.y = my - wy * camera.scale;
    }, { passive: false });
  }

  return {
    TILE, COLS, ROWS, W, H, T, camera,
    build, rasterize, locations, get houseSlots() { return houseSlots; }, get buildings() { return buildings; }, get decor() { return decor; }, get landmarks() { return landmarks; }, get nodes() { return nodes; }, get waterTiles() { return waterTiles; }, get hqRooms() { return hqRooms; },
    walkable, nearestWalkable, tileToPx, findPath,
    bumpWear, wearStage, loadWear, takeWearDirty, get wear() { return wear; },
    tileAt: (c, r) => (inb(c, r) ? grid[r][c] : -1),
    drawTerrain, drawBuildingLabels, drawWallBands, drawInterior, fit, get fitScale() { return _fitScale; }, screenToWorld, worldToTile, attachControls, detachControls,
    setTerrainImage, setTerrainImageEl, exportLayoutBase,
    setFloorImage, setFloorImageEl, terrainAlive, reheal,
    // edit API
    moveBuilding, resizeBuilding, addBuilding, deleteBuilding, setBuilding, buildingAtTile, addInterior, removeInteriorAt, exportLayout, scheduleSave,
    addDecor, removeDecorNear, decorIndexNear, pickDecor, previewDecor,
    nodeIndexNear, addNode, pickNode, removeNodeAt,
    landmarkIndexNear, addLandmark, pickLandmark, removeLandmarkAt,
  };
})();
