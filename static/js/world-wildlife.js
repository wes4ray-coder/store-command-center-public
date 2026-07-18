'use strict';
/* ══════════════════════════════════════════════════════════════════════════
   THE COMPANY — ambient wildlife (window.WW).
   Procedural pixel critters that make the outdoors feel alive:
     • birds       — fly in, land on grass/near trees, hop & peck, FLEE when a
                     walker gets close (a real proximity trigger)
     • butterflies — flutter loops over flowery grass, harmless drifters
     • rabbits     — hop between tree lines, bolt from anyone who comes near
   Pure client-side, zero assets, degrades to nothing without WM.
   ══════════════════════════════════════════════════════════════════════════ */
window.WW = (function () {
  const FLEE_R = 34;                 // px — how close a walker can get before panic
  let critters = [];
  let getWalkers = () => [];         // injected: () => [{x, y}] of moving entities

  function _grassSpot() {
    for (let i = 0; i < 40; i++) {
      const c = 3 + (Math.random() * (WM.COLS - 6) | 0), r = 3 + (Math.random() * (WM.ROWS - 6) | 0);
      if (WM.walkable(c, r) && !WM.buildingAtTile(c, r)) return { x: (c + 0.5) * WM.TILE, y: (r + 0.5) * WM.TILE };
    }
    return null;
  }

  function spawn(walkerFn) {
    if (walkerFn) getWalkers = walkerFn;
    if (critters.length) return;                    // keep populations across tab switches
    for (let i = 0; i < 5; i++) {
      const t = _grassSpot(); if (!t) continue;
      critters.push({ kind: 'bird', x: t.x, y: t.y - 220 - Math.random() * 120, tx: t.x, ty: t.y,
                      state: 'fly', vx: 0, wait: 0, phase: Math.random() * 1000,
                      hue: [200, 12, 40][i % 3] });
    }
    for (let i = 0; i < 6; i++) {
      const t = _grassSpot(); if (!t) continue;
      critters.push({ kind: 'butterfly', x: t.x, y: t.y, ax: t.x, ay: t.y,
                      phase: Math.random() * 1000, hue: [28, 285, 200, 340][i % 4] });
    }
    for (let i = 0; i < 5; i++) {
      const t = _grassSpot(); if (!t) continue;
      critters.push({ kind: 'rabbit', x: t.x, y: t.y, tx: t.x, ty: t.y,
                      state: 'sit', wait: 1000 + Math.random() * 3000, phase: Math.random() * 1000 });
    }
    // DEER graze the wild outskirts (far from the city centre) — skittish, and
    // the future quarry when hunting gets wired into the food economy.
    for (let i = 0; i < 4; i++) {
      const t = _wildSpot(); if (!t) continue;
      critters.push({ kind: 'deer', x: t.x, y: t.y, tx: t.x, ty: t.y,
                      state: 'sit', wait: 2000 + Math.random() * 4000, phase: Math.random() * 1000 });
    }
  }

  function _wildSpot() {                             // grass far from the map centre = the wilds
    for (let i = 0; i < 60; i++) {
      const t = _grassSpot(); if (!t) continue;
      const dx = t.x - WM.W / 2, dy = t.y - WM.H / 2;
      if (Math.hypot(dx, dy) > Math.min(WM.W, WM.H) * 0.33) return t;
    }
    return _grassSpot();
  }

  function _threatNear(cr) {
    for (const w of getWalkers()) {
      if (Math.abs(w.x - cr.x) < FLEE_R && Math.abs(w.y - cr.y) < FLEE_R &&
          Math.hypot(w.x - cr.x, w.y - cr.y) < FLEE_R) return true;
    }
    return false;
  }

  function tick(dt) {
    if (!window.WM || !critters.length) return;
    for (const cr of critters) {
      if (cr.kind === 'bird') {
        if (cr.state === 'fly') {
          const dx = cr.tx - cr.x, dy = cr.ty - cr.y, d = Math.hypot(dx, dy);
          if (d < 3) { cr.state = 'ground'; cr.wait = 2500 + Math.random() * 5000; }
          else { const sp = 85 * dt; cr.x += dx / d * sp; cr.y += dy / d * sp; cr.vx = dx; }
        } else {                                     // pecking about — watch for walkers
          cr.wait -= dt * 1000;
          if (_threatNear(cr) || cr.wait <= 0) {
            const t = _grassSpot();
            if (t) { cr.tx = t.x; cr.ty = t.y; cr.state = 'fly'; }
            else cr.wait = 2000;
          } else if (Math.random() < dt * 0.8) {     // little hops — but never into a wall
            const nx = cr.x + (Math.random() * 8 - 4);
            if (WM.walkable(nx / WM.TILE | 0, cr.y / WM.TILE | 0)) cr.x = nx;
          }
        }
      } else if (cr.kind === 'butterfly') {
        const t = performance.now() / 1000 + cr.phase;
        cr.x = cr.ax + Math.sin(t * 1.1) * 16 + Math.sin(t * 3.7) * 5;
        cr.y = cr.ay + Math.cos(t * 0.9) * 12 + Math.sin(t * 4.3) * 4;
        if (Math.random() < dt * 0.05) { const n = _grassSpot(); if (n) { cr.ax = n.x; cr.ay = n.y; } }
      } else if (cr.kind === 'rabbit' || cr.kind === 'deer') {
        // GROUND critters walk the world like everyone else — A* around walls,
        // buildings, water and trees (no more ghosting through the town).
        if (cr.state === 'sit') {
          cr.wait -= dt * 1000;
          const scare = _threatNear(cr);
          if (scare || cr.wait <= 0) {
            const t = cr.kind === 'deer' ? _wildSpot() : _grassSpot();
            if (t) {
              const p = WM.findPath(
                { col: cr.x / WM.TILE | 0, row: cr.y / WM.TILE | 0 },
                { col: t.x / WM.TILE | 0, row: t.y / WM.TILE | 0 });
              if (p && p.length) { cr.path = p.slice(1); cr.state = 'hop'; cr.fast = scare; }
            }
            cr.wait = 2000;
          }
        } else {
          const next = cr.path && cr.path[0];
          if (!next) { cr.state = 'sit'; cr.wait = 1500 + Math.random() * 4000; cr.fast = false; }
          else {
            const tx = (next.col + 0.5) * WM.TILE, ty = (next.row + 0.5) * WM.TILE;
            const dx = tx - cr.x, dy = ty - cr.y, d = Math.hypot(dx, dy);
            const sp = (cr.fast ? 95 : cr.kind === 'deer' ? 36 : 46) * dt;
            if (d <= sp) { cr.x = tx; cr.y = ty; cr.path.shift(); }
            else { cr.x += dx / d * sp; cr.y += dy / d * sp; }
          }
        }
      }
    }
  }

  function draw(ctx) {
    const now = performance.now();
    for (const cr of critters) {
      const x = Math.round(cr.x), y = Math.round(cr.y);
      if (cr.kind === 'bird') {
        if (cr.state === 'fly') {                    // 2-frame wing flap
          const up = Math.floor((now + cr.phase) / 110) % 2;
          ctx.strokeStyle = `hsl(${cr.hue},35%,30%)`; ctx.lineWidth = 1.4;
          ctx.beginPath();
          ctx.moveTo(x - 4, y + (up ? -3 : 1)); ctx.lineTo(x, y); ctx.lineTo(x + 4, y + (up ? -3 : 1));
          ctx.stroke();
        } else {
          ctx.fillStyle = 'rgba(0,0,0,.2)'; ctx.beginPath(); ctx.ellipse(x, y + 2, 3, 1.1, 0, 0, 6.283); ctx.fill();
          ctx.fillStyle = `hsl(${cr.hue},45%,45%)`; ctx.beginPath(); ctx.ellipse(x, y - 1.5, 2.6, 2, 0, 0, 6.283); ctx.fill();
          ctx.fillStyle = `hsl(${cr.hue},45%,32%)`; ctx.beginPath(); ctx.arc(x + 2, y - 3, 1.3, 0, 6.283); ctx.fill();
          ctx.fillStyle = '#e8b04a'; ctx.fillRect(x + 3.2, y - 3.3, 1.6, 0.9);          // beak
          const peck = Math.floor((now + cr.phase) / 700) % 3 === 0;
          if (peck) { ctx.fillStyle = 'rgba(0,0,0,.15)'; ctx.fillRect(x + 2, y - 1, 2, 1); }
        }
      } else if (cr.kind === 'butterfly') {
        const flap = Math.sin((now + cr.phase) / 60);
        ctx.fillStyle = `hsla(${cr.hue},75%,65%,.95)`;
        ctx.beginPath(); ctx.ellipse(x - 1.4 * Math.abs(flap) - 0.4, y, 1.6 * Math.abs(flap) + 0.4, 1.3, 0, 0, 6.283); ctx.fill();
        ctx.beginPath(); ctx.ellipse(x + 1.4 * Math.abs(flap) + 0.4, y, 1.6 * Math.abs(flap) + 0.4, 1.3, 0, 0, 6.283); ctx.fill();
        ctx.fillStyle = '#2a2a2a'; ctx.fillRect(x - 0.5, y - 1.5, 1, 3);
      } else if (cr.kind === 'deer') {
        const step = cr.state === 'hop' ? Math.abs(Math.sin((now + cr.phase) / 110)) * 2 : 0;
        ctx.fillStyle = 'rgba(0,0,0,.22)'; ctx.beginPath(); ctx.ellipse(x, y + 3, 5, 1.6, 0, 0, 6.283); ctx.fill();
        const gy = y - 3 - step;
        ctx.fillStyle = '#8a6a4a'; ctx.beginPath(); ctx.ellipse(x, gy, 5, 3, 0, 0, 6.283); ctx.fill();   // body
        ctx.fillRect(x - 4, gy + 1, 1.4, 4); ctx.fillRect(x + 3, gy + 1, 1.4, 4);                          // legs
        ctx.beginPath(); ctx.arc(x + 5, gy - 2.6, 2, 0, 6.283); ctx.fill();                                // head
        ctx.strokeStyle = '#6a4c30'; ctx.lineWidth = 1;                                                    // antlers
        ctx.beginPath(); ctx.moveTo(x + 5, gy - 4); ctx.lineTo(x + 3.6, gy - 7); ctx.moveTo(x + 5, gy - 4); ctx.lineTo(x + 6.6, gy - 7); ctx.stroke();
        ctx.fillStyle = '#f0e6d8'; ctx.beginPath(); ctx.arc(x - 4.6, gy - 0.6, 1.2, 0, 6.283); ctx.fill(); // tail
      } else if (cr.kind === 'rabbit') {
        const hop = cr.state === 'hop' ? Math.abs(Math.sin((now + cr.phase) / 90)) * 3 : 0;
        ctx.fillStyle = 'rgba(0,0,0,.2)'; ctx.beginPath(); ctx.ellipse(x, y + 2, 3.2, 1.2, 0, 0, 6.283); ctx.fill();
        const gy = y - 2 - hop;
        ctx.fillStyle = '#b8aca0'; ctx.beginPath(); ctx.ellipse(x, gy, 3, 2.3, 0, 0, 6.283); ctx.fill();
        ctx.beginPath(); ctx.arc(x + 2.6, gy - 1.4, 1.6, 0, 6.283); ctx.fill();
        ctx.fillRect(x + 2.2, gy - 4.6, 1, 2.6); ctx.fillRect(x + 3.6, gy - 4.4, 1, 2.4);   // ears
        ctx.fillStyle = '#fff'; ctx.beginPath(); ctx.arc(x - 2.6, gy - 0.4, 1, 0, 6.283); ctx.fill();  // tail
      }
    }
  }

  return { spawn, tick, draw, get count() { return critters.length; } };
})();
