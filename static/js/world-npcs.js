'use strict';
/* ══════════════════════════════════════════════════════════════════════════
   THE COMPANY — ambient townsfolk (window.WN).
   Decorative wandering villagers (anokolisa Citizen_F peasants/tavern folk) that
   bring the town to life around the real job-agents. They are NOT tied to any
   backend state — pure client-side flavour: each ambles between random outdoor
   walkable tiles, idling in between. Side-facing sheets, mirrored for direction.
   Degrades to nothing (empty draw) if the pack is absent — never blocks the world.
   ══════════════════════════════════════════════════════════════════════════ */
window.WN = (function () {
  const NPC = "/store/static/world_assets/packs/anokolisa-pixel-crawler/Pixel Crawler - Free Pack/Entities/Npc's/Citizen_F";
  const FR = 64, WFR = 6, IFR = 4, WSPD = 130, ISPD = 240;
  const TYPES = [
    { walk: NPC + '/Peasant_A/Walk/Walk-Sheet.png',      idle: NPC + '/Peasant_A/Idle/Idle-Sheet.png' },
    { walk: NPC + '/Tavern_A/Walk/Walk_Side-Sheet.png',  idle: NPC + '/Tavern_A/Idle/Idle_Side-Sheet.png' },
    { walk: NPC + '/Tavern_B/Walk/Walk_Side-Sheet.png',  idle: NPC + '/Tavern_B/Idle/Idle_Side-Sheet.png' },
  ];
  const SPEED = 1.05;              // tiles / second — a slow amble (clickable, unhurried)
  const img = {};
  let ready = false, npcs = [];

  function _load(url) {
    return new Promise(res => { const im = new Image(); im.onload = () => { img[url] = im; res(true); }; im.onerror = () => res(false); im.src = encodeURI(url); });
  }
  async function init() {
    const oks = await Promise.all(TYPES.flatMap(t => [_load(t.walk), _load(t.idle)]));
    ready = oks.some(Boolean);
    if (ready) console.log('[WN] townsfolk sheets loaded');
    return ready;
  }

  // an outdoor, walkable tile not inside a building
  function _outdoor(c, r) { return WM.walkable(c, r) && !WM.buildingAtTile(c, r); }
  function _randTile() {
    for (let i = 0; i < 60; i++) {
      const c = 2 + (Math.random() * (WM.COLS - 4) | 0), r = 2 + (Math.random() * (WM.ROWS - 4) | 0);
      if (_outdoor(c, r)) return { col: c, row: r };
    }
    return null;
  }
  function _wander(n) {                          // pick a nearby outdoor goal + path to it
    for (let i = 0; i < 20; i++) {
      const c = n.col + (Math.random() * 16 - 8 | 0), r = n.row + (Math.random() * 16 - 8 | 0);
      if (_outdoor(c, r)) { const p = WM.findPath({ col: n.col, row: n.row }, { col: c, row: r }); if (p && p.length) { n.path = p; return; } }
    }
    n.wait = 600 + Math.random() * 1800;
  }

  // venues that always need someone running them (the NPCs' real jobs)
  const VENUES = [['bar', '🍺'], ['arcade', '🕹️'], ['tv', '📺'], ['cafe', '☕'], ['park', '🌳']];
  function spawn(n) {
    if (!ready || !window.WM) return;
    // already populated (e.g. re-entering the tab) → keep everyone where they
    // stood; just drop anyone whose tile became unwalkable after a map edit.
    if (npcs.length) {
      npcs = npcs.filter(x => x.staff ? (WM.locations && WM.locations[x.staff]) : _outdoor(x.col, x.row));
      if (npcs.length) return;
    }
    npcs = [];
    // 1) STAFF — one stationed at each venue, running the place (never wanders)
    VENUES.forEach(([v, icon], i) => {
      const loc = WM.locations && WM.locations[v]; if (!loc) return;
      npcs.push({ type: i % TYPES.length, col: loc.col, row: loc.row, px: (loc.col + 0.5) * WM.TILE, py: (loc.row + 0.5) * WM.TILE,
                  path: [], dir: 'right', moving: false, wait: 0, phase: Math.random() * 1000, staff: v, icon });
    });
    // 2) SENTRIES — two guards walking a patrol loop around the HQ perimeter,
    //    the visible face of the real security stack watching the company.
    const hq = (WM.buildings || []).find(b => b.kind === 'hq');
    if (hq) {
      const near = (c, r) => {                       // snap a corner to the closest outdoor tile
        for (let rad = 0; rad < 4; rad++)
          for (let dc = -rad; dc <= rad; dc++) for (let dr = -rad; dr <= rad; dr++)
            if (_outdoor(c + dc, r + dr)) return { col: c + dc, row: r + dr };
        return null;
      };
      const m = 2;   // patrol margin outside the walls
      const ring = [near(hq.c - m, hq.r - m), near(hq.c + hq.w + m, hq.r - m),
                    near(hq.c + hq.w + m, hq.r + hq.h + m), near(hq.c - m, hq.r + hq.h + m)].filter(Boolean);
      if (ring.length >= 2) {
        for (let g = 0; g < 2; g++) {
          const start = ring[(g * 2) % ring.length];
          npcs.push({ type: (g + 1) % TYPES.length, col: start.col, row: start.row,
                      px: (start.col + 0.5) * WM.TILE, py: (start.row + 0.5) * WM.TILE,
                      path: [], dir: 'right', moving: false, wait: g * 1200, phase: Math.random() * 1000,
                      guard: ring, wpi: (g * 2) % ring.length, icon: '🛡️' });
        }
      }
    }
    // 3) the rest are ambient wanderers
    for (let i = 0; i < n; i++) {
      const t = _randTile(); if (!t) continue;
      const px = (t.col + 0.5) * WM.TILE, py = (t.row + 0.5) * WM.TILE;
      npcs.push({ type: i % TYPES.length, col: t.col, row: t.row, px, py, path: [], dir: Math.random() < .5 ? 'left' : 'right', moving: false, wait: Math.random() * 2500, phase: Math.random() * 1000 });
    }
  }

  function tick(dt) {
    if (!ready) return;
    for (const n of npcs) {
      if (n.staff) { n.moving = false; continue; }   // venue staff hold their post
      if (n.guard && !(n.path && n.path.length) && n.wait <= 0) {
        // sentries loop the HQ patrol ring instead of wandering off
        n.wpi = (n.wpi + 1) % n.guard.length;
        const wp = n.guard[n.wpi];
        const p = WM.findPath({ col: n.col, row: n.row }, { col: wp.col, row: wp.row });
        if (p && p.length) { n.path = p; } else { n.wait = 1500; }
      }
      if (n.path && n.path.length) {
        const next = n.path[0], tx = (next.col + 0.5) * WM.TILE, ty = (next.row + 0.5) * WM.TILE;
        const dx = tx - n.px, dy = ty - n.py, dist = Math.hypot(dx, dy);
        if (Math.abs(dx) > 0.5) n.dir = dx < 0 ? 'left' : 'right';
        const step = SPEED * WM.TILE * dt;
        if (dist <= step) {
          n.px = tx; n.py = ty; n.col = next.col; n.row = next.row; n.path.shift();
          if (window.WM && WM.bumpWear) WM.bumpWear(next.col, next.row);              // townsfolk carve trails too
          if (!n.path.length) n.wait = n.guard ? 700 : 3000 + Math.random() * 5000;   // sentries barely pause
        } else { n.px += dx / dist * step; n.py += dy / dist * step; }
        n.moving = true;
      } else {
        n.moving = false;
        n.wait -= dt * 1000;
        if (n.wait <= 0 && !n.guard) _wander(n);
      }
    }
  }

  function draw(ctx) {
    if (!ready) return;
    for (const n of [...npcs].sort((a, b) => a.py - b.py)) {
      const t = TYPES[n.type], sheet = img[n.moving ? t.walk : t.idle]; if (!sheet) continue;
      const frames = n.moving ? WFR : IFR, spd = n.moving ? WSPD : ISPD;
      const f = (Math.floor((performance.now() + n.phase) / spd) % frames);
      const size = 32, dyp = n.py - size * 0.86;
      ctx.save();
      if (n.dir === 'left') { ctx.translate(2 * n.px, 0); ctx.scale(-1, 1); }
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(sheet, f * FR, 0, FR, FR, n.px - size / 2, dyp, size, size);
      ctx.restore();
      if (n.icon) {                                   // venue-staff / sentry badge so the role reads at a glance
        const bob = Math.sin(performance.now() / 400 + n.phase) * 1.2;
        ctx.font = '9px sans-serif'; ctx.textAlign = 'center';
        ctx.fillText(n.icon, n.px, dyp - 3 + bob);
      }
    }
  }

  return { init, spawn, tick, draw, positions: () => npcs.map(n => ({ x: n.px, y: n.py })),
           get ready() { return ready; }, get count() { return npcs.length; } };
})();
