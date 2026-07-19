/* ══ THE COMPANY — the SPACE PROGRAM (JASA): a rocket that launches agents to the Moon ══
   Phase 5. Draws a launch pad + gantry in the town and a crewed rocket that boards,
   ascends, coasts to orbit, and lands — all driven by `_worldState.space` (polled by the
   sim, no separate fetch). Wired into the town render path by the orchestrator, which calls
   WROCKET.draw(ctx) with `ctx` already in world space (WM camera transform applied, so
   world px = tile*WM.TILE, same coordinate space as _drawLandmarks/_drawProps).

   Classic script, shared global scope — everything lives inside this IIFE so nothing but
   window.WROCKET leaks to the top level (a duplicate top-level const/let would be fatal).
   Gradients (flame/smoke) are built at the origin and reused via a translate, so they're
   cached once instead of rebuilt every frame (the app is laggy — no per-frame allocs). */
window.WROCKET = (function () {

  // ── cached gradients (built at origin, positioned with a translate; keyed by tile size) ──
  let _flameGrad = null, _smokeGrad = null, _gradT = 0;
  function _ensureGrads(ctx, T) {
    if (_gradT === T && _flameGrad && _smokeGrad) return;
    _gradT = T;
    // flame: unit height T*3 from nozzle downward; callers scale-y to flicker, gradient stays aligned
    const fg = ctx.createLinearGradient(0, 0, 0, T * 3);
    fg.addColorStop(0, 'rgba(255,246,196,0.95)');
    fg.addColorStop(0.35, 'rgba(255,150,40,0.9)');
    fg.addColorStop(0.7, 'rgba(230,70,24,0.65)');
    fg.addColorStop(1, 'rgba(200,40,20,0)');
    _flameGrad = fg;
    // smoke: unit puff radius T*1.6 at origin; callers translate+scale each puff
    const sg = ctx.createRadialGradient(0, 0, 0, 0, 0, T * 1.6);
    sg.addColorStop(0, 'rgba(232,232,238,0.72)');
    sg.addColorStop(0.6, 'rgba(206,206,214,0.4)');
    sg.addColorStop(1, 'rgba(200,200,210,0)');
    _smokeGrad = sg;
  }

  const _clamp = (v) => (v < 0 ? 0 : v > 1 ? 1 : v);
  function _shadow(ctx, x, y, r) { ctx.fillStyle = 'rgba(8,10,18,0.4)'; ctx.beginPath(); ctx.ellipse(x, y, r, r * 0.4, 0, 0, 6.283); ctx.fill(); }

  // little astronaut — same idiom as WMOON._drawAstronaut so crew read consistently
  function _astro(ctx, x, y, bob, T) {
    const s = T * 0.5, dy = Math.abs(Math.sin(bob)) * s * 0.15;
    _shadow(ctx, x, y + s, s * 0.7);
    ctx.fillStyle = '#eef1f6'; ctx.fillRect(x - s * 0.4, y - s * 0.9 - dy, s * 0.8, s * 1.1);   // suit
    ctx.fillStyle = '#dfe3ea'; ctx.fillRect(x - s * 0.6, y - s * 0.75 - dy, s * 0.25, s * 0.7);  // pack
    ctx.fillStyle = '#eef1f6'; ctx.beginPath(); ctx.arc(x, y - s * 1.05 - dy, s * 0.42, 0, 6.283); ctx.fill();  // helmet
    ctx.fillStyle = '#f0b000'; ctx.beginPath(); ctx.arc(x, y - s * 1.02 - dy, s * 0.26, 0, 6.283); ctx.fill();  // gold visor
  }

  // ── launch pad + gantry + JASA sign (always visible when space.enabled) ──
  function _drawPad(ctx, bx, by, T) {
    // concrete apron
    ctx.fillStyle = 'rgba(36,38,46,0.85)'; ctx.beginPath(); ctx.ellipse(bx, by + T * 0.35, T * 2.2, T * 0.9, 0, 0, 6.283); ctx.fill();
    ctx.fillStyle = 'rgba(58,61,72,0.95)'; ctx.fillRect(bx - T * 1.5, by - T * 0.2, T * 3, T * 0.7);
    // flame trench slot under the rocket
    ctx.fillStyle = 'rgba(18,18,24,0.9)'; ctx.fillRect(bx - T * 0.5, by - T * 0.1, T * 1.0, T * 0.4);
    // gantry tower (right of the pad)
    const gx = bx + T * 1.15, gw = T * 0.7, gTop = by - T * 4.6, gH = by - gTop;
    ctx.strokeStyle = '#8a8f9c'; ctx.lineWidth = 2;
    ctx.strokeRect(gx, gTop, gw, gH);
    for (let i = 1; i < 6; i++) {                       // cross-braces
      const yy = gTop + gH * (i / 6);
      ctx.beginPath(); ctx.moveTo(gx, yy - gH / 12); ctx.lineTo(gx + gw, yy + gH / 12); ctx.stroke();
    }
    ctx.strokeStyle = '#b7bcc8'; ctx.beginPath(); ctx.moveTo(gx, gTop + T * 1.2); ctx.lineTo(bx + T * 0.4, gTop + T * 1.2); ctx.stroke();  // swing-arm
    // JASA sign
    ctx.fillStyle = '#12305a'; ctx.fillRect(bx - T * 2.2, by - T * 1.05, T * 1.9, T * 0.6);
    ctx.fillStyle = 'rgba(120,200,255,0.8)'; ctx.fillRect(bx - T * 2.2, by - T * 1.05, T * 1.9, 2);
    ctx.fillStyle = '#eef4ff'; ctx.font = `${Math.round(T * 0.42)}px sans-serif`; ctx.textBaseline = 'middle'; ctx.textAlign = 'left';
    ctx.fillText('🚀 JASA', bx - T * 2.05, by - T * 0.73);
    ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  }

  // ── rocket body: nozzle sits at (cx, baseY), fuselage rises upward ──
  function _drawRocketBody(ctx, cx, baseY, T) {
    const bw = T * 1.0, bh = T * 3.0, topY = baseY - bh;
    _shadow(ctx, cx, baseY + T * 0.2, bw * 1.1);
    // fins
    ctx.fillStyle = '#c23b2e';
    ctx.beginPath(); ctx.moveTo(cx - bw / 2, baseY - T * 0.9); ctx.lineTo(cx - bw / 2 - T * 0.6, baseY + T * 0.2); ctx.lineTo(cx - bw / 2, baseY); ctx.closePath(); ctx.fill();
    ctx.beginPath(); ctx.moveTo(cx + bw / 2, baseY - T * 0.9); ctx.lineTo(cx + bw / 2 + T * 0.6, baseY + T * 0.2); ctx.lineTo(cx + bw / 2, baseY); ctx.closePath(); ctx.fill();
    // fuselage + nose cone
    ctx.fillStyle = '#e9edf3';
    ctx.beginPath();
    ctx.moveTo(cx - bw / 2, baseY);
    ctx.lineTo(cx - bw / 2, topY);
    ctx.quadraticCurveTo(cx - bw / 2, topY - T * 1.1, cx, topY - T * 1.5);   // nose
    ctx.quadraticCurveTo(cx + bw / 2, topY - T * 1.1, cx + bw / 2, topY);
    ctx.lineTo(cx + bw / 2, baseY);
    ctx.closePath(); ctx.fill();
    // nose cone tint
    ctx.fillStyle = '#c23b2e';
    ctx.beginPath();
    ctx.moveTo(cx - bw / 2, topY);
    ctx.quadraticCurveTo(cx - bw / 2, topY - T * 1.1, cx, topY - T * 1.5);
    ctx.quadraticCurveTo(cx + bw / 2, topY - T * 1.1, cx + bw / 2, topY);
    ctx.closePath(); ctx.fill();
    // porthole
    ctx.fillStyle = '#0e2a4a'; ctx.beginPath(); ctx.arc(cx, topY + bh * 0.4, bw * 0.26, 0, 6.283); ctx.fill();
    ctx.fillStyle = 'rgba(120,200,255,0.75)'; ctx.beginPath(); ctx.arc(cx - bw * 0.06, topY + bh * 0.4 - bw * 0.05, bw * 0.15, 0, 6.283); ctx.fill();
    // nozzle
    ctx.fillStyle = '#5a5f6b'; ctx.fillRect(cx - bw * 0.32, baseY - T * 0.15, bw * 0.64, T * 0.4);
  }

  // ── engine flame (cached gradient, scaled to flicker) ──
  function _drawFlame(ctx, x, y, T, intensity) {
    if (intensity <= 0.01) return;
    _ensureGrads(ctx, T);
    const flick = 0.75 + Math.abs(Math.sin(performance.now() / 55)) * 0.35;
    ctx.save();
    ctx.translate(x, y);
    ctx.scale(1, intensity * flick);                    // stretch the fixed-length gradient triangle
    ctx.fillStyle = _flameGrad;
    ctx.beginPath(); ctx.moveTo(-T * 0.34, 0); ctx.lineTo(T * 0.34, 0); ctx.lineTo(0, T * 3); ctx.closePath(); ctx.fill();
    ctx.fillStyle = 'rgba(255,255,220,0.85)';           // inner core
    ctx.beginPath(); ctx.moveTo(-T * 0.16, 0); ctx.lineTo(T * 0.16, 0); ctx.lineTo(0, T * 1.5); ctx.closePath(); ctx.fill();
    ctx.restore();
  }

  // ── smoke plume billowing off the pad (cached radial puff, translated + scaled) ──
  function _drawSmoke(ctx, x, y, T, amount) {
    if (amount <= 0.01) return;
    _ensureGrads(ctx, T);
    const now = performance.now() / 1000;
    ctx.save();
    ctx.fillStyle = _smokeGrad;
    for (let i = 0; i < 7; i++) {
      const t = (now * 0.5 + i / 7) % 1;
      const side = (i % 2 ? 1 : -1);
      const puffX = x + side * (T * 0.6 + t * T * 3) + Math.sin(now + i) * T * 0.4;
      const puffY = y + t * T * 2 - Math.sin(t * 3.14) * T * 0.6;
      const sc = (0.4 + t * 1.3) * amount;
      ctx.save();
      ctx.translate(puffX, puffY); ctx.scale(sc, sc);
      ctx.globalAlpha = (1 - t) * 0.6 * amount;
      ctx.beginPath(); ctx.arc(0, 0, T * 1.6, 0, 6.283); ctx.fill();
      ctx.restore();
    }
    ctx.globalAlpha = 1;
    ctx.restore();
  }

  // ── crew walking toward the rocket during boarding ──
  function _drawCrew(ctx, bx, by, T, crew, prog) {
    if (!crew || !crew.length) return;
    const now = performance.now() / 1000;
    for (let i = 0; i < crew.length; i++) {
      const c = crew[i];
      const sx = bx - T * (4.5 + (i % 3) * 1.3), sy = by + T * (1.4 + (i % 2) * 0.9);
      const p = _clamp(prog);
      const ax = sx + (bx - T * 0.1 - sx) * p;           // stop just at the pad
      const ay = sy + (by - sy) * p;
      _astro(ctx, ax, ay, now * 3 + i, T);
      // name pill
      const nm = (c && c.name) ? c.name : 'crew';
      ctx.font = `${Math.round(T * 0.42)}px sans-serif`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      const wpx = ctx.measureText(nm).width + T * 0.4;
      ctx.fillStyle = 'rgba(10,14,26,0.6)'; ctx.fillRect(ax - wpx / 2, ay - T * 1.9, wpx, T * 0.6);
      ctx.fillStyle = '#dfe8ff'; ctx.fillText(nm, ax, ay - T * 1.6);
      ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
    }
  }

  // ── main entry: draw the whole space program in world space ──
  function draw(ctx) {
    if (typeof _worldState === 'undefined' || !_worldState) return;
    const sp = _worldState.space;
    if (!sp || !sp.enabled) return;
    const WM = window.WM; if (!WM) return;
    const T = WM.TILE || 20;
    const pad = sp.pad || { col: 0, row: 0 };
    const bx = (pad.col + 0.5) * T, by = (pad.row + 0.5) * T;   // pad tile centre → world px

    _drawPad(ctx, bx, by, T);

    const L = sp.launch;
    if (!L) { _drawRocketBody(ctx, bx, by, T); return; }        // idle rocket standing on the pad
    const prog = _clamp(L.progress || 0);

    switch (L.phase) {
      case 'boarding':
        _drawRocketBody(ctx, bx, by, T);
        _drawCrew(ctx, bx, by, T, L.crew, prog);
        break;
      case 'ascending': {
        const nozzleY = by - prog * T * 22;                    // rise driven by progress
        _drawSmoke(ctx, bx, by, T, 1 - prog * 0.35);
        _drawFlame(ctx, bx, nozzleY, T, 1);
        _drawRocketBody(ctx, bx, nozzleY, T);
        break;
      }
      case 'transit': {
        // gone to orbit — a tiny receding dot arcing up toward where the moon hangs
        const dx = bx + prog * T * 26, dy = by - T * 20 - prog * T * 12;
        ctx.fillStyle = 'rgba(255,210,140,0.5)'; ctx.beginPath(); ctx.arc(dx - T * 0.7, dy + T * 0.5, T * 0.2, 0, 6.283); ctx.fill();
        ctx.fillStyle = 'rgba(255,255,255,0.95)'; ctx.beginPath(); ctx.arc(dx, dy, T * 0.26, 0, 6.283); ctx.fill();
        break;
      }
      case 'landing': {
        const alt = (1 - prog) * T * 22;                       // descend onto the pad (returns)
        const nozzleY = by - alt;
        _drawFlame(ctx, bx, nozzleY, T, 0.55);
        _drawSmoke(ctx, bx, by, T, prog);                      // dust kicks up as it nears
        _drawRocketBody(ctx, bx, nozzleY, T);
        break;
      }
      default:
        _drawRocketBody(ctx, bx, by, T);
    }
  }

  return { draw };
})();
