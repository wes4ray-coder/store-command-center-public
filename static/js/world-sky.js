/* ══ THE COMPANY — sky / space layers ══════════════════════════════════════════
   Phase 2: starfield + space-black backdrop that fades in as you zoom OUT into orbit
   (the town shrinks to a lit patch in space). Phases 3-4 add the drifting moon, its
   world-space shadow, and cloud parallax here too. Classic script, shared global scope
   like the other world-*.js. Everything here draws in SCREEN space (BEHIND the
   camera-transformed world) so it reads as a fixed-distance sky. */
const WSKY = (() => {
  let _stars = null, _sw = 0, _sh = 0;

  // The space band fades in as you zoom OUT below the fit scale. Keyed off WM.fitScale
  // (the zoom at which the whole map fits) so it's viewport-independent — fullscreen and
  // windowed have very different fit zooms. top = where stars begin; full = deep orbit.
  function _bands() {
    const f = (window.WM && WM.fitScale) ? WM.fitScale : 0.25;
    return { top: f * 0.92, full: f * 0.42 };
  }
  // 0 = normal town view (no space) … 1 = full orbit/space. Shared so later phases
  // (moon visibility, cloud fade) can key off the same ramp.
  function spaceAmount(scale) {
    const { top, full } = _bands();
    if (scale >= top) return 0;
    if (scale <= full) return 1;
    return (top - scale) / (top - full);
  }

  // Pre-render the starfield once per canvas size (cheap to blit each frame; rebuilt only
  // when the backing store changes). A few big stars get a soft halo for depth.
  function _buildStars(w, h) {
    const c = document.createElement('canvas'); c.width = w; c.height = h;
    const x = c.getContext('2d');
    const n = Math.round(w * h / 2400);
    for (let i = 0; i < n; i++) {
      const px = Math.random() * w, py = Math.random() * h;
      const big = Math.random() < 0.12;
      const r = big ? Math.random() * 1.3 + 0.9 : Math.random() * 0.8 + 0.3;
      const b = Math.random() * 0.5 + 0.5;
      const t = Math.random();
      x.fillStyle = t < 0.72 ? `rgba(255,255,255,${b})` : t < 0.9 ? `rgba(184,206,255,${b})` : `rgba(255,214,170,${b})`;
      x.beginPath(); x.arc(px, py, r, 0, 6.283); x.fill();
      if (big) { x.fillStyle = `rgba(255,255,255,${b * 0.22})`; x.beginPath(); x.arc(px, py, r * 2.4, 0, 6.283); x.fill(); }
    }
    return c;
  }

  // Draw the space backdrop BEHIND the world. Called with the transform at identity; we
  // save/restore so the caller's transform is untouched. amt 0 → no-op (normal view).
  function drawSpace(ctx, canvas, scale) {
    const amt = spaceAmount(scale);
    if (amt <= 0) return;
    const w = canvas.width, h = canvas.height;
    if (!_stars || _sw !== w || _sh !== h) { _stars = _buildStars(w, h); _sw = w; _sh = h; }
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.globalAlpha = amt;
    ctx.fillStyle = '#03040a'; ctx.fillRect(0, 0, w, h);      // deepen toward space-black
    const tw = 0.82 + 0.18 * Math.sin(performance.now() / 1500);   // gentle global twinkle
    ctx.globalAlpha = amt * tw;
    ctx.drawImage(_stars, 0, 0);
    ctx.restore();
  }

  // ── night strength (reuse the renderer's day/night curve so the moon rises with it) ──
  function _nightAmt() {
    if (window._wskyMoonDay) return 1;                 // daytime preview (world_moon_daytime): treat as full night
    // _worldState is a bare lexical global (declared in tab-world.js), NOT window._worldState.
    const h = (typeof _worldState !== 'undefined' && _worldState) ? (_worldState.clock_hour ?? 12) : 12;
    if (typeof _daylight === 'function') return Math.min(1, _daylight(h).dark / 0.34);
    return (h >= 19 || h < 6) ? 1 : 0;
  }
  // The moon's slow journey across the sky — a real-time drift (0..1) so you can watch it
  // cross. Same phase drives the ground shadow, so moon + shadow move together.
  const MOON_PERIOD = 150;                          // seconds per full pass
  function _moonPhase() {
    if (window._wskyMoonP != null) return window._wskyMoonP;   // optional override (test / future sim-night tie-in)
    return ((performance.now() / 1000) % MOON_PERIOD) / MOON_PERIOD;
  }

  // Generated pixel-art moon texture (Phase 3d); null → the procedural moon below. This
  // same texture becomes the moon MAP's ground in Phase 4.
  let _moonImg = null;
  function setMoonImage(url) {
    if (!url) { _moonImg = null; return; }
    const i = new Image(); i.onload = () => { _moonImg = i; }; i.onerror = () => { _moonImg = null; }; i.src = url;
  }

  // ── the moon (SCREEN space) — drifts across the sky at night, mainly when zoomed out ──
  function drawMoon(ctx, canvas, scale) {
    if (window._wskyMoonOn === false) return;          // moon layer toggled off (world_moon_enabled)
    const night = _nightAmt(); if (night <= 0.02) return;
    const a = night * Math.min(1, spaceAmount(scale) * 1.25);   // fades in as you pull back toward orbit
    if (a <= 0.02) return;
    const w = canvas.width, h = canvas.height, p = _moonPhase();
    const mr = 0.075 * Math.min(w, h);              // ~7.5% of the view — big enough to read, not the whole screen
    const mx = (-0.08 + 1.16 * p) * w;
    const my = h * (0.26 - 0.10 * Math.sin(p * Math.PI));   // gentle arc, high in the middle of the pass
    ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalAlpha = a;
    const glow = ctx.createRadialGradient(mx, my, mr * 0.6, mx, my, mr * 2.4);   // soft halo
    glow.addColorStop(0, 'rgba(220,226,248,0.32)'); glow.addColorStop(1, 'rgba(220,226,248,0)');
    ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(mx, my, mr * 2.4, 0, 6.283); ctx.fill();
    if (_moonImg && _moonImg.complete && _moonImg.naturalWidth) {
      // Generators tend to draw a moon DISC centered in the frame with dark space around
      // it; clip to the circle AND overscale ~1.5× so the central disc fills the circle
      // and those dark margins are cropped out (works whatever the texture looks like).
      ctx.save(); ctx.beginPath(); ctx.arc(mx, my, mr, 0, 6.283); ctx.clip();
      ctx.imageSmoothingEnabled = false;
      const s = mr * 1.5; ctx.drawImage(_moonImg, mx - s, my - s, s * 2, s * 2);
      // faint rim shadow so the disc reads round against the sky
      ctx.strokeStyle = 'rgba(20,22,34,0.35)'; ctx.lineWidth = Math.max(1, mr * 0.06);
      ctx.beginPath(); ctx.arc(mx, my, mr * 0.97, 0, 6.283); ctx.stroke();
      ctx.restore();
    } else {
      _drawProcMoon(ctx, mx, my, mr);
    }
    ctx.restore();
  }
  function _drawProcMoon(ctx, mx, my, mr) {
    const body = ctx.createRadialGradient(mx - mr * 0.3, my - mr * 0.3, mr * 0.2, mx, my, mr);
    body.addColorStop(0, '#f3f1e7'); body.addColorStop(0.7, '#d8d5c4'); body.addColorStop(1, '#b7b4a2');
    ctx.fillStyle = body; ctx.beginPath(); ctx.arc(mx, my, mr, 0, 6.283); ctx.fill();
    const craters = [[-.30, -.20, .16], [.25, .10, .12], [.05, .35, .10], [.40, -.30, .08], [-.15, .28, .09], [-.42, .16, .07], [.30, .38, .06]];
    for (const [dx, dy, rr] of craters) {
      ctx.fillStyle = 'rgba(122,118,102,0.5)'; ctx.beginPath(); ctx.arc(mx + dx * mr, my + dy * mr, rr * mr, 0, 6.283); ctx.fill();
      ctx.fillStyle = 'rgba(255,255,255,0.22)'; ctx.beginPath(); ctx.arc(mx + dx * mr - rr * mr * 0.25, my + dy * mr - rr * mr * 0.25, rr * mr * 0.7, 0, 6.283); ctx.fill();
    }
    ctx.strokeStyle = 'rgba(92,90,80,0.4)'; ctx.lineWidth = Math.max(1, mr * 0.05);
    ctx.beginPath(); ctx.arc(mx, my, mr * 0.97, 0, 6.283); ctx.stroke();
  }

  // ── the moon's shadow ON THE GROUND (WORLD space → scales & pans with zoom for free) ──
  // Called INSIDE the camera transform, so a small moon casts a shadow that reads correctly
  // at every zoom: a big soft patch sweeping the whole map when out, a scaled circle passing
  // over the area when zoomed in. Visible at night at EVERY layer (unlike the moon object).
  function drawGroundShadow(ctx) {
    if (window._wskyMoonOn === false) return;          // moon layer toggled off (world_moon_enabled)
    const night = _nightAmt(); if (night <= 0.02 || !window.WM) return;
    const p = _moonPhase(), W = WM.W, H = WM.H;
    const sx = (-0.10 + 1.20 * p) * W;              // sweeps across the map, offset-linked to the moon
    const sy = H * (0.42 + 0.16 * Math.sin(p * Math.PI));
    const R = 0.26 * W;                             // big soft patch in WORLD units
    const aMax = 0.30 * night;
    const g = ctx.createRadialGradient(sx, sy, R * 0.15, sx, sy, R);
    g.addColorStop(0, `rgba(6,10,26,${aMax})`);
    g.addColorStop(0.6, `rgba(6,10,26,${aMax * 0.55})`);
    g.addColorStop(1, 'rgba(6,10,26,0)');
    ctx.save(); ctx.fillStyle = g; ctx.beginPath(); ctx.arc(sx, sy, R, 0, 6.283); ctx.fill(); ctx.restore();
  }

  // ── CLOUD PARALLAX BAND ──────────────────────────────────────────────────────
  // Drifting semi-transparent clouds you pass THROUGH between orbit and the town — they
  // fade in around the mid transition (peak spaceAmount ~0.45) and are gone at both the
  // normal town view and deep orbit, so they're a pure fly-through effect, never fog over
  // gameplay. Two bands drift at different speeds for depth (screen space, over the moon).
  let _cloudBand = null, _cbW = 0;
  function _buildCloudBand(w) {
    const h = 170, c = document.createElement('canvas'); c.width = w; c.height = h;
    const x = c.getContext('2d');
    const puffs = Math.max(6, Math.round(w / 85));
    for (let i = 0; i < puffs; i++) {
      const cx = Math.random() * w, cy = 45 + Math.random() * 85, r = 42 + Math.random() * 74;
      const g = x.createRadialGradient(cx, cy, r * 0.2, cx, cy, r);
      g.addColorStop(0, 'rgba(214,223,238,0.55)'); g.addColorStop(1, 'rgba(214,223,238,0)');
      x.fillStyle = g; x.beginPath(); x.arc(cx, cy, r, 0, 6.283); x.fill();
    }
    return c;
  }
  function _cloudAmt(scale) { const s = spaceAmount(scale); return Math.max(0, 1 - Math.abs(s - 0.45) / 0.35); }
  function drawClouds(ctx, canvas, scale) {
    const amt = _cloudAmt(scale); if (amt <= 0.02) return;
    const w = canvas.width, h = canvas.height;
    if (!_cloudBand || _cbW !== w) { _cloudBand = _buildCloudBand(w); _cbW = w; }
    const t = performance.now() / 1000;
    ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0);
    for (const b of [{ y: h * 0.14, spd: 13, a: 0.55 }, { y: h * 0.44, spd: 27, a: 0.42 }]) {
      const off = (t * b.spd) % w;
      ctx.globalAlpha = amt * b.a;
      ctx.drawImage(_cloudBand, -off, b.y); ctx.drawImage(_cloudBand, w - off, b.y);   // tiled + wrap
    }
    ctx.restore();
  }

  return { drawSpace, spaceAmount, drawMoon, drawGroundShadow, setMoonImage, drawClouds };
})();
window.WSKY = WSKY;
