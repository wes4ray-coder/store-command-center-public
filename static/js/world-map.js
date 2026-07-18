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
  let terrainCanvas = null;
  const camera = { x: 0, y: 0, scale: 1 };
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
                       townhall: '#fde047', exec: '#fb7185', church: '#cdbff0', library: '#8fc7a9' };
  // distinct roof colour per named venue/loc so no two building types look alike
  const LOC_COLOR = { bar: '#e0714a', arcade: '#a26cf0', tv: '#4aa0e0', cafe: '#d1a05a',
                      church: '#cdbff0', library: '#8fc7a9', townhall: '#fde047', exec: '#fb7185',
                      park: '#5bb46a', gas: '#e05a6a', lounge: '#c07ad0' };

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
    const civic = [['church', 'Church ⛪'], ['library', 'Library 📚'], ['townhall', 'Town Hall 🏛️'], ['exec', 'Exec Office 💼']];
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
      } else if (b.loc) locations[b.loc] = interior;
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
    rasterize();
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
  const exportLayout = () => ({ buildings: buildings.map(b => ({ ...b })), decor,
                                nodes: nodes.map(n => ({ ...n })), landmarks: landmarks.map(l => ({ ...l })) });
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

  // ── bake terrain (+ decor) as detailed pixel art ──
  function _bake() {
    if (!terrainCanvas) { terrainCanvas = document.createElement('canvas'); terrainCanvas.width = W; terrainCanvas.height = H; }
    const x = terrainCanvas.getContext('2d'); x.imageSmoothingEnabled = false; x.clearRect(0, 0, W, H);
    waterTiles = [];
    for (let r = 0; r < ROWS; r++) for (let c = 0; c < COLS; c++) { _tile(x, c, r); if (grid[r][c] === T.WATER) waterTiles.push({ col: c, row: r }); }
    // (building walls are solid stone — drawn per-tile in _tile; no see-through fence frame)
    for (const b of buildings) _building(x, b);
    for (const d of decor) _decorSprite(x, d);
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
    hqRooms = [];
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
        hqRooms.push({ dept, x: zx + zw / 2, y: zy + zh / 2, x0: zx, y0: zy, w: zw, h: zh, tint: cc, door: band.door });
        locations['desk:' + dept] = { col: Math.round(zx / TILE + zw / TILE / 2 - 0.5), row: Math.round(zy / TILE + zh / TILE / 2 - 0.5) };  // agents operate here
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

  // per-building detail: floor tint, roof/awning trim, door, sign, interior furniture
  function _building(x, b) {
    const bx = b.c * TILE, by = b.r * TILE, bw = b.w * TILE, bh = b.h * TILE;
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
    // if a downloaded tileset maps this terrain, blit it and skip procedural art
    if (window.WA && WA.ready && WA.tile(x, _TKEY[t], px, py, TILE)) return;
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
    } else if (t === T.WALL) {                           // SOLID stone wall (mortar courses + top light / base shadow)
      // THINNER read: where a wall borders interior floor, show a sliver of the
      // room's floor along that edge so walls feel like walls, not solid blocks
      const fL = c > 0 && grid[r][c - 1] === T.FLOOR, fR = c < COLS - 1 && grid[r][c + 1] === T.FLOOR;
      const fU = r > 0 && grid[r - 1][c] === T.FLOOR, fD = r < ROWS - 1 && grid[r + 1][c] === T.FLOOR;
      x.fillStyle = '#7a5230'; x.fillRect(px, py, TILE, TILE);        // floor peeks through insets
      const ix = px + (fL ? 4 : 0), iy = py + (fU ? 4 : 0);
      const iw = TILE - (fL ? 4 : 0) - (fR ? 4 : 0), ih = TILE - (fU ? 4 : 0) - (fD ? 4 : 0);
      x.fillStyle = v < .5 ? '#8b909c' : '#7e838f'; x.fillRect(ix, iy, iw, ih);
      x.fillStyle = 'rgba(0,0,0,.17)'; for (let ry = 5; ry < ih; ry += 6) x.fillRect(ix, iy + ry, iw, 1);      // horizontal courses
      const soff = (r % 2) ? 10 : 0; x.fillStyle = 'rgba(0,0,0,.15)'; for (let rx = -soff; rx < iw; rx += 10) x.fillRect(ix + rx + 9, iy, 1, 6);  // staggered joints
      x.fillStyle = 'rgba(255,255,255,.14)'; x.fillRect(ix, iy, iw, 2);           // top light
      x.fillStyle = 'rgba(0,0,0,.32)'; x.fillRect(ix, iy + ih - 2, iw, 2);      // base shadow
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
  }

  function drawTerrain(ctx) { if (terrainCanvas) ctx.drawImage(terrainCanvas, 0, 0); }
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
      const tw = ctx.measureText(txt).width, padX = 4, h = big ? 16 : 13;
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
  function fit(vpW, vpH) { camera.scale = Math.min(vpW / W, vpH / H) * 0.98; camera.x = (vpW - W * camera.scale) / 2; camera.y = (vpH - H * camera.scale) / 2; }
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
      camera.scale = clamp(camera.scale * (e.deltaY < 0 ? 1.12 : 0.89), 0.3, 4);
      camera.x = mx - wx * camera.scale; camera.y = my - wy * camera.scale;
    }, { passive: false });
  }

  return {
    TILE, COLS, ROWS, W, H, T, camera,
    build, rasterize, locations, get houseSlots() { return houseSlots; }, get buildings() { return buildings; }, get decor() { return decor; }, get landmarks() { return landmarks; }, get nodes() { return nodes; }, get waterTiles() { return waterTiles; }, get hqRooms() { return hqRooms; },
    walkable, nearestWalkable, tileToPx, findPath,
    bumpWear, wearStage, loadWear, takeWearDirty, get wear() { return wear; },
    tileAt: (c, r) => (inb(c, r) ? grid[r][c] : -1),
    drawTerrain, drawBuildingLabels, fit, screenToWorld, worldToTile, attachControls, detachControls,
    // edit API
    moveBuilding, resizeBuilding, addBuilding, deleteBuilding, setBuilding, buildingAtTile, exportLayout,
    addDecor, removeDecorNear, decorIndexNear, pickDecor, previewDecor,
    nodeIndexNear, addNode, pickNode, removeNodeAt,
    landmarkIndexNear, addLandmark, pickLandmark, removeLandmarkAt,
  };
})();
