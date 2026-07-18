/* ══ THE COMPANY — shield dome, defeat FX, raid geometry, walls, threats, turret fire ══
   Split out of world-render.js (core keeps the loop + shared state). Runs in
   shared global scope (classic script, not a module). Loads right after
   world-render.js, before world-ui.js. Code moved verbatim. */


/* ── The HQ energy shield: the town's visible tie to the REAL security stack.
   Strength/opacity = fraction of the Command Center's defenses actually on
   (security.posture.shield). Full shield = a calm blue dome; weakened = dimmer
   and amber-tinged; during a raid it crackles. Drawn in world coords. ── */
function _drawShieldDome(ctx) {
  const p = _worldState?.security?.posture;
  if (!p || p.shield == null) return;
  const hq = (WM.buildings || []).find(b => b.kind === 'hq'); if (!hq) return;
  const TL = WM.TILE, t = performance.now() / 1000;
  const cx = (hq.c + hq.w / 2) * TL, cy = (hq.r + hq.h / 2) * TL;
  const rx = (hq.w / 2 + 1.6) * TL, ry = (hq.h / 2 + 1.4) * TL;
  const raid = _worldState?.orchestra?.phase === 'raid';
  const s = Math.max(0.15, p.shield);
  const hue = p.shield > 0.7 ? 205 : 38;                       // healthy blue vs weakened amber
  const flicker = raid ? 0.5 + 0.5 * Math.abs(Math.sin(t * 7)) : 1;
  ctx.save();
  // dome body — faint radial glass
  const g = ctx.createRadialGradient(cx, cy, Math.min(rx, ry) * 0.4, cx, cy, Math.max(rx, ry));
  g.addColorStop(0, `hsla(${hue},80%,70%,0)`);
  g.addColorStop(0.82, `hsla(${hue},80%,70%,${0.05 * s * flicker})`);
  g.addColorStop(1, `hsla(${hue},85%,65%,${0.16 * s * flicker})`);
  ctx.fillStyle = g;
  ctx.beginPath(); ctx.ellipse(cx, cy, rx, ry, 0, 0, 6.283); ctx.fill();
  // rim + two orbiting glints so it visibly hums
  ctx.strokeStyle = `hsla(${hue},85%,70%,${(0.28 + 0.1 * Math.sin(t * 2)) * s * flicker})`;
  ctx.lineWidth = 1.6;
  ctx.beginPath(); ctx.ellipse(cx, cy, rx, ry, 0, 0, 6.283); ctx.stroke();
  for (let k = 0; k < 2; k++) {
    const a = t * (0.7 + k * 0.35) + k * 3.1;
    ctx.fillStyle = `hsla(${hue},90%,80%,${0.7 * s * flicker})`;
    ctx.beginPath(); ctx.arc(cx + Math.cos(a) * rx, cy + Math.sin(a) * ry, 2.2, 0, 6.283); ctx.fill();
  }
  // shield readout over the dome apex
  ctx.font = 'bold 8px sans-serif'; ctx.textAlign = 'center';
  ctx.fillStyle = `hsla(${hue},85%,78%,.9)`;
  ctx.fillText(`🛡 ${Math.round(p.shield * 100)}%`, cx, cy - ry - 4);
  ctx.restore();
}

/* ── Defeat FX: when a raid monster dies, burst a ring + sparks + a floating
   label where it stood (client-side; positions tracked while it was alive). ── */
const _threatPos = {};        // id → last drawn {x,y}
let _threatSeen = {};         // id → status we last saw
const _poofs = [];            // {x,y,t0,label,kind}
function _trackDefeats() {
  const raid = _worldState?.raid; if (!raid) { _threatSeen = {}; return; }
  for (const t of (raid.threats || [])) {
    const prev = _threatSeen[t.id];
    if (prev === 'active' && t.status !== 'active' && _threatPos[t.id]) {
      const lbl = { domain: 'blocked!', finding: 'bug squashed!', attacker: 'repelled!' }[t.kind] || 'down!';
      _poofs.push({ ..._threatPos[t.id], t0: performance.now(), label: lbl, boss: !!t.is_boss });
      if (_poofs.length > 12) _poofs.shift();
      if (window.WAU && WAU.sfxAt) WAU.sfxAt('kill', _threatPos[t.id].x, _threatPos[t.id].y, 250);
    }
    _threatSeen[t.id] = t.status;
  }
}
function _drawDefeatFx(ctx) {
  _trackDefeats();
  const now = performance.now();
  for (let i = _poofs.length - 1; i >= 0; i--) {
    const p = _poofs[i], age = (now - p.t0) / 900;
    if (age >= 1) { _poofs.splice(i, 1); continue; }
    const r = (p.boss ? 34 : 20) * age + 4, al = 1 - age;
    ctx.strokeStyle = `rgba(255,210,90,${0.8 * al})`; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, 6.283); ctx.stroke();
    ctx.fillStyle = `rgba(255,240,160,${al})`;
    for (let k = 0; k < 6; k++) {
      const a = k * 1.047 + p.t0 % 6;
      ctx.fillRect(p.x + Math.cos(a) * r * 1.15 - 1, p.y + Math.sin(a) * r * 1.15 - 1, 2.5, 2.5);
    }
    ctx.font = 'bold 9px sans-serif'; ctx.textAlign = 'center';
    ctx.fillStyle = `rgba(255,225,120,${al})`;
    ctx.fillText((p.boss ? '🏆 ' : '⚔️ ') + p.label, p.x, p.y - 14 - age * 12);
  }
}

/* Where an enemy from a given edge sits right now: it marches in from the map edge
   toward the HQ, halting at the wall ring unless that side's wall is breached. */
function _raidGeom() {
  // the wall ring wraps the ACTUAL CITY — bounding box of every building plus a
  // margin — so defenders protect the town itself, not an arbitrary rectangle
  // slicing through it. Falls back to a centred ring on an empty map.
  const blds = WM.buildings || [];
  let cx = WM.COLS / 2, cy = WM.ROWS / 2, RX, RY;
  if (blds.length) {
    let c0 = 1e9, c1 = -1e9, r0 = 1e9, r1 = -1e9;
    for (const b of blds) {
      c0 = Math.min(c0, b.c); c1 = Math.max(c1, b.c + b.w);
      r0 = Math.min(r0, b.r); r1 = Math.max(r1, b.r + b.h);
    }
    const M = 3;                                             // breathing room outside the last lot
    cx = (c0 + c1) / 2; cy = (r0 + r1) / 2;
    RX = Math.min((c1 - c0) / 2 + M, (WM.COLS / 2 | 0) - 3);
    RY = Math.min((r1 - r0) / 2 + M, (WM.ROWS / 2 | 0) - 3);
  } else {
    RX = Math.min(34, (WM.COLS / 2 | 0) - 4); RY = Math.min(28, (WM.ROWS / 2 | 0) - 4);
  }
  return { cx, cy, RX, RY, EDGE: { N: { c: cx, r: 2 }, S: { c: cx, r: WM.ROWS - 3 }, E: { c: WM.COLS - 3, r: cy }, W: { c: 3, r: cy } } };
}

/* The town's defensive walls (4 sides) with destruction bars — breach = gaps + rubble. */
function _drawWalls(ctx) {
  const raid = _worldState?.raid;
  if (!raid || (raid.phase !== 'raid' && raid.phase !== 'recovery')) return;
  const g = _raidGeom(); if (!g) return;
  const wl = raid.walls || {}, TL = WM.TILE;
  const seg = {
    N: { horiz: 1, a: g.cx - g.RX, b: g.cx + g.RX, fix: g.cy - g.RY },
    S: { horiz: 1, a: g.cx - g.RX, b: g.cx + g.RX, fix: g.cy + g.RY },
    W: { horiz: 0, a: g.cy - g.RY, b: g.cy + g.RY, fix: g.cx - g.RX },
    E: { horiz: 0, a: g.cy - g.RY, b: g.cy + g.RY, fix: g.cx + g.RX },
  };
  for (const side in seg) {
    const w = wl[side]; if (!w) continue;
    const s = seg[side], frac = Math.max(0, (w.hp || 0) / (w.max_hp || 120));
    const blocks = Math.round(s.b - s.a);
    for (let i = 0; i < blocks; i++) {
      const t = s.a + i + 0.5, intact = (i / blocks) < frac;
      const px = (s.horiz ? t : s.fix) * TL, py = (s.horiz ? s.fix : t) * TL;
      if (intact) {
        ctx.fillStyle = '#8b8f9c'; ctx.fillRect(px - TL / 2, py - TL / 2, TL, TL);
        ctx.fillStyle = 'rgba(255,255,255,.14)'; ctx.fillRect(px - TL / 2, py - TL / 2, TL, 2);
        ctx.fillStyle = 'rgba(0,0,0,.28)'; ctx.fillRect(px - TL / 2, py + TL / 2 - 2, TL, 2);
        ctx.fillStyle = 'rgba(0,0,0,.2)'; ctx.fillRect(px - TL / 2, py, TL, 1);
      } else {                                                    // rubble where breached
        ctx.fillStyle = '#4a4038'; ctx.fillRect(px - 4, py + 2, 5, 3); ctx.fillRect(px + 1, py - 1, 4, 3);
      }
    }
    // destruction bar centred on the segment
    const mid = (s.a + s.b) / 2, bx = (s.horiz ? mid : s.fix) * TL, by = (s.horiz ? s.fix : mid) * TL;
    ctx.fillStyle = 'rgba(0,0,0,.6)'; ctx.fillRect(bx - 14, by - TL, 28, 3);
    ctx.fillStyle = frac > 0.4 ? '#5fb0e8' : '#e0a040'; ctx.fillRect(bx - 14, by - TL, 28 * frac, 3);
  }
}

/* Raid monsters: each advances from its spawn edge toward the HQ (halting at an intact
   wall), sized by tier, bosses larger, with HP bars + labels. */
function _drawThreats(ctx) {
  const raid = _worldState?.raid;
  if (!raid || (raid.phase !== 'raid' && raid.phase !== 'recovery')) return;
  const g = _raidGeom(); if (!g) return;
  const wl = raid.walls || {}, nowS = Date.now() / 1000, center = WM.tileToPx(g.cx, g.cy);
  const WALLPT = { N: { c: g.cx, r: g.cy - g.RY }, S: { c: g.cx, r: g.cy + g.RY }, E: { c: g.cx + g.RX, r: g.cy }, W: { c: g.cx - g.RX, r: g.cy } };
  for (const t of (raid.threats || [])) {
    if (t.status !== 'active') continue;
    const trait = t.trait || 'brute';
    // runners charge the WEAKEST wall; the shaman hangs back behind the horde
    let side = t.edge || 'S';
    if (trait === 'runner' && Object.keys(wl).length)
      side = Object.keys(wl).reduce((a, b) => ((wl[a]?.hp ?? 1e9) <= (wl[b]?.hp ?? 1e9) ? a : b));
    const e = g.EDGE[side] || g.EDGE.S;
    const breached = ((wl[side] && wl[side].hp) || 0) <= 0;
    const tgt = breached ? { c: g.cx, r: g.cy } : (WALLPT[side] || WALLPT.S);   // halt at the wall unless breached
    const speed = trait === 'runner' ? 6.5 : 11;                                // runners close fast
    let prog = Math.min(1, Math.max(0.04, (nowS - (t.spawn_t || nowS)) / speed));
    if (trait === 'healer') prog = Math.min(prog, 0.72);                        // shaman stays back
    const col = e.c + (tgt.c - e.c) * prog, row = e.r + (tgt.r - e.r) * prog;
    const p = WM.tileToPx(col, row), x = p.x, y = p.y;
    _threatPos[t.id] = { x, y };                       // defeat FX bursts where it fell
    const size = t.is_boss ? 58 : (t.size || 34);
    const lunge = Math.sin(nowS * 3 + t.id) * (prog >= 0.98 ? 2 : 0);   // press against the wall on arrival
    if (trait === 'healer') {                          // green mending aura
      const gl = 0.25 + 0.15 * Math.sin(nowS * 4 + t.id);
      ctx.fillStyle = `rgba(90,220,120,${gl})`;
      ctx.beginPath(); ctx.ellipse(x, y - size * 0.4, size * 0.55, size * 0.5, 0, 0, 6.283); ctx.fill();
    }
    if (trait === 'smash') {                           // boss shockwave ring every ~20s
      const ph = (nowS % 20) / 20;
      if (ph < 0.18) {
        ctx.strokeStyle = `rgba(255,120,60,${0.6 * (1 - ph / 0.18)})`; ctx.lineWidth = 2.5;
        ctx.beginPath(); ctx.arc(x, y - 4, 10 + ph * 260, 0, 6.283); ctx.stroke();
      }
    }
    if (window.WMob) WMob.draw(ctx, t.mob, x, y + lunge, size, x > center.x);
    const bw = t.is_boss ? 34 : 22, hp = Math.max(0, (t.hp || 0) / Math.max(1, t.max_hp || 1));
    ctx.fillStyle = 'rgba(0,0,0,.6)'; ctx.fillRect(x - bw / 2, y - size - 6, bw, t.is_boss ? 5 : 4);
    ctx.fillStyle = t.is_boss ? '#ff5a4a' : (hp > 0.5 ? '#e0483b' : '#b0201a'); ctx.fillRect(x - bw / 2, y - size - 6, bw * hp, t.is_boss ? 5 : 4);
    ctx.font = (t.is_boss ? 'bold 9px' : '7px') + ' sans-serif'; ctx.textAlign = 'center';
    ctx.fillStyle = t.is_boss ? '#ffcf3f' : '#ffd7d0';
    ctx.fillText((t.is_boss ? '👑 ' : '') + (t.label || '').slice(0, 18), x, y - size - 9);
  }
  _drawTurretFire(ctx, raid);
}

/* Built WATCHTOWERS are live turrets — bolts streak from each tower to a target. */
function _drawTurretFire(ctx, raid) {
  if (raid.phase !== 'raid' || !(raid.towers > 0)) return;
  const bn = WM.locations && WM.locations['build']; if (!bn) return;
  const built = _worldState?.company?.construction?.built || [];
  const towers = built.filter(b => b.kind === 'watchtower');
  const targets = (raid.threats || []).filter(t => t.status === 'active' && _threatPos[t.id]);
  if (!towers.length || !targets.length) return;
  const nowS = Date.now() / 1000;
  towers.forEach((tw, ti) => {
    const tp = WM.tileToPx(bn.col - 3 + (tw.slot % 5) * 1.6, bn.row + 3 + ((tw.slot / 5) | 0) * 2.3);
    const cyc = (nowS * 0.8 + ti * 0.5) % 1;                       // one bolt per tower per ~1.2s
    const tgt = _threatPos[targets[(ti + Math.floor(nowS / 1.25)) % targets.length].id];
    if (!tgt || cyc > 0.45) return;
    const k = cyc / 0.45;
    const bx = tp.x + (tgt.x - tp.x) * k, by = (tp.y - 24) + (tgt.y - 8 - (tp.y - 24)) * k - Math.sin(k * Math.PI) * 14;
    ctx.strokeStyle = 'rgba(255,220,140,.9)'; ctx.lineWidth = 1.6;
    ctx.beginPath(); ctx.moveTo(bx - 3, by + 1.5); ctx.lineTo(bx + 3, by - 1.5); ctx.stroke();
  });
}
