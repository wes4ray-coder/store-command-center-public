'use strict';
/* ══════════════════════════════════════════════════════════════════════════
   THE COMPANY — dynamic procedural sound (window.WAU).

   A WebAudio synth with a real mixer (master / ambient / effects channels,
   volumes persisted) and a DYNAMIC soundscape driven by live world state:

     • wind bed always — swells in autumn/winter, gusts roll through
     • birdsong by day (busiest in spring), crickets at night
     • hammer-taps when the crew is working, bar murmur when they're out
     • water plips when the camera is near a pond, drums during a raid
     • event SFX: doors, blessing chime, product ship, raid alarm, coin

   Two layers:
     1. synth — everything above synthesized live, zero audio files (fallback)
     2. GENERATED — real wavs rendered by the store's own audio models
        (Stable Audio / MusicGen via /api/world/audio, cached server-side).
        When assets exist and the mixer's "Generated" toggle is on, ambience
        plays those context-picked loops (day/season/night/raid) and SFX
        prefer the generated one-shots; the synth covers anything missing.

   AudioContext arms on the user's first click/keypress (autoplay policy).
   localStorage: world_snd on/off · world_snd_gen generated on/off ·
   world_vol_master/_amb/_sfx (0..1).
   ══════════════════════════════════════════════════════════════════════════ */
window.WAU = (function () {
  let ctx = null, master = null, amb = null, sfxG = null, windGain = null;
  let pulse = null;
  // live world signals (fed by WAU.update / updateCam from the world tab)
  const st = { hour: 12, season: 'spring', phase: 'peace', working: 0, leisure: 0, nearWater: false };

  const enabled = () => (localStorage.getItem('world_snd') ?? '1') === '1';
  const vol = k => {
    const v = parseFloat(localStorage.getItem('world_vol_' + k));
    return isNaN(v) ? (k === 'master' ? 0.5 : 0.8) : v;
  };
  function setVol(k, v) {
    localStorage.setItem('world_vol_' + k, String(v));
    _applyVols();
  }
  function _applyVols() {
    if (!ctx) return;
    master.gain.value = 0.30 * vol('master');
    amb.gain.value = vol('amb');
    sfxG.gain.value = vol('sfx');
  }

  function _boot() {
    if (ctx || !enabled()) return;
    try {
      ctx = new (window.AudioContext || window.webkitAudioContext)();
      master = ctx.createGain(); master.connect(ctx.destination);
      amb = ctx.createGain(); amb.connect(master);
      sfxG = ctx.createGain(); sfxG.connect(master);
      _applyVols();
      // wind bed: looping filtered noise
      const len = ctx.sampleRate * 2, buf = ctx.createBuffer(1, len, ctx.sampleRate);
      const d = buf.getChannelData(0);
      for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * 0.4;
      const src = ctx.createBufferSource(); src.buffer = buf; src.loop = true;
      const lp = ctx.createBiquadFilter(); lp.type = 'lowpass'; lp.frequency.value = 300;
      windGain = ctx.createGain(); windGain.gain.value = 0.10;
      src.connect(lp); lp.connect(windGain); windGain.connect(amb); src.start();
      clearInterval(pulse);
      pulse = setInterval(_ambTick, 600);              // the dynamic scheduler heartbeat
      _fetchGen();                                     // learn which generated wavs exist
    } catch (e) { ctx = null; }
  }

  /* ── generated soundscape (wavs from the store's own audio models) ── */
  const genOn = () => (localStorage.getItem('world_snd_gen') ?? '1') === '1';
  let genList = null;            // key → url (fetched once per page)
  const genBuf = {};             // key → AudioBuffer | 'loading' | 'err'
  let genLoop = { key: null, src: null, g: null };
  // API is a top-level const in app-core.js (script-global, not on window)
  const _api = () => (typeof API === 'undefined' ? '' : API);
  function _fetchGen() {
    if (genList !== null) return;
    genList = {};
    fetch(_api() + '/api/world/audio/assets')
      .then(r => r.json())
      .then(j => { for (const a of (j.assets || [])) if (a.ready) genList[a.key] = a.url; })
      .catch(() => {});
  }
  function _genBuffer(key) {     // decoded buffer, or null (kicks off an async decode)
    if (!ctx || !genList || !genList[key]) return null;
    const b = genBuf[key];
    if (b && b !== 'loading' && b !== 'err') return b;
    if (!b) {
      genBuf[key] = 'loading';
      fetch(_api() + genList[key])
        .then(r => r.arrayBuffer())
        .then(ab => ctx.decodeAudioData(ab))
        .then(buf => { genBuf[key] = buf; })
        .catch(() => { genBuf[key] = 'err'; });
    }
    return null;
  }
  function _genAmbKey() {        // context → which generated bed should play
    if (st.phase === 'raid') return 'amb_raid';
    if (!(st.hour >= 6 && st.hour < 20)) return 'amb_night';
    return 'amb_day_' + (_SEASON_BIRDS[st.season] !== undefined ? st.season : 'spring');
  }
  function _genLoopStop(fade = 1.2) {
    const { src, g } = genLoop;
    genLoop = { key: null, src: null, g: null };
    if (!src || !ctx) return;
    try {
      g.gain.setTargetAtTime(0.0001, ctx.currentTime, fade / 3);
      setTimeout(() => { try { src.stop(); } catch {} }, fade * 1000 + 200);
    } catch {}
  }
  function _genLoopTick() {      // keep the right bed looping (crossfade on change)
    if (!genOn()) { if (genLoop.src) _genLoopStop(); return false; }
    const want = _genAmbKey();
    if (genLoop.key === want) return !!genLoop.src;
    const buf = _genBuffer(want);
    if (!buf) return !!genLoop.src;          // still decoding — keep what's playing
    _genLoopStop();
    const src = ctx.createBufferSource(); src.buffer = buf; src.loop = true;
    const g = ctx.createGain(); g.gain.value = 0.0001;
    src.connect(g); g.connect(amb); src.start();
    g.gain.setTargetAtTime(0.55, ctx.currentTime, 0.8);
    genLoop = { key: want, src, g };
    return true;
  }
  function _playSfx(name, out) { // generated one-shot if ready, else the synth voice
    const b = genOn() ? _genBuffer(name) : null;
    if (b) {
      const s = ctx.createBufferSource(); s.buffer = b;
      s.connect(out || sfxG); s.start();
      return;
    }
    SFX[name] && SFX[name]();
  }
  function genToggle() {
    const on = !genOn();
    localStorage.setItem('world_snd_gen', on ? '1' : '0');
    if (!on) _genLoopStop();
    return on;
  }

  // one synth voice on a channel: freq glide + exponential envelope
  function _blip(freq, freq2, dur, type = 'sine', v = 1, when = 0, out = null) {
    if (!ctx) return;
    const t0 = ctx.currentTime + when;
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.type = type; o.frequency.setValueAtTime(freq, t0);
    if (freq2) o.frequency.exponentialRampToValueAtTime(Math.max(28, freq2), t0 + dur);
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(v, t0 + 0.012);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    o.connect(g); g.connect(out || sfxG); o.start(t0); o.stop(t0 + dur + 0.05);
  }
  function _noiseHit(dur, cutoff, v, when = 0, out = null) {   // percussive noise burst
    if (!ctx) return;
    const t0 = ctx.currentTime + when;
    const n = ctx.createBufferSource(), len = ctx.sampleRate * dur;
    const b = ctx.createBuffer(1, len, ctx.sampleRate), d = b.getChannelData(0);
    for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * (1 - i / len);
    n.buffer = b;
    const f = ctx.createBiquadFilter(); f.type = 'lowpass'; f.frequency.value = cutoff;
    const g = ctx.createGain(); g.gain.value = v;
    n.connect(f); f.connect(g); g.connect(out || sfxG); n.start(t0);
  }

  /* ── ambient voices ── */
  const _SEASON_BIRDS = { spring: 1.6, summer: 1.1, autumn: 0.6, winter: 0.18 };
  function _birdsong() {
    const base = 2100 + Math.random() * 1500, n = 2 + (Math.random() * 3 | 0);
    for (let i = 0; i < n; i++)
      _blip(base + Math.random() * 300, base + 700 + Math.random() * 500,
            0.09 + Math.random() * 0.05, 'sine', 0.4, i * 0.13 + Math.random() * 0.04, amb);
  }
  function _cricket() { for (let i = 0; i < 7; i++) _blip(4200, 4100, 0.025, 'triangle', 0.16, i * 0.045, amb); }
  function _gust() {                                   // wind swell
    if (!windGain) return;
    const t0 = ctx.currentTime, peak = 0.16 + Math.random() * 0.2;
    windGain.gain.cancelScheduledValues(t0);
    windGain.gain.setTargetAtTime(peak, t0, 0.7);
    windGain.gain.setTargetAtTime(_windBase(), t0 + 1.8, 1.4);
  }
  const _windBase = () => (st.season === 'winter' ? 0.16 : st.season === 'autumn' ? 0.12 : 0.07);
  function _workTaps() {                               // the crew hammering away
    const n = Math.min(3, st.working);
    for (let i = 0; i < n; i++) {
      _blip(190 + Math.random() * 60, 150, 0.045, 'square', 0.22, i * 0.16 + Math.random() * 0.05, amb);
      _noiseHit(0.03, 2500, 0.10, i * 0.16 + 0.01, amb);
    }
  }
  function _murmur() {                                 // bar/leisure chatter, wordless
    for (let i = 0; i < 4; i++)
      _blip(160 + Math.random() * 160, 120 + Math.random() * 120,
            0.10 + Math.random() * 0.08, 'sine', 0.07, i * 0.14 + Math.random() * 0.06, amb);
  }
  function _plip() { _blip(900 + Math.random() * 500, 300, 0.09, 'sine', 0.16, 0, amb); }
  function _warDrum() {
    _blip(70, 45, 0.22, 'sine', 0.7, 0, amb); _noiseHit(0.10, 900, 0.25, 0.01, amb);
    if (Math.random() < 0.35) _noiseHit(0.05, 5000, 0.15, 0.28, amb);   // metal clash
  }

  function _ambTick() {
    if (!ctx || !enabled() || document.hidden || !document.getElementById('world-canvas')) return;
    // generated bed (if any) replaces the synth BASE layer — wind/birds/crickets/
    // drums come from the real recording; live accents (taps, murmur, plips) stay.
    const gen = _genLoopTick();
    const wBase = gen ? 0.015 : _windBase();
    if (windGain && Math.abs(windGain.gain.value - wBase) > 0.06)
      windGain.gain.setTargetAtTime(wBase, ctx.currentTime, 2.5);
    const day = st.hour >= 6 && st.hour < 20;
    const r = Math.random();
    if (st.phase === 'raid') { if (!gen && r < 0.55) _warDrum(); return; }  // battle drowns the calm
    if (!gen) {
      if (day && r < 0.055 * (_SEASON_BIRDS[st.season] ?? 1)) _birdsong();
      else if (!day && r < 0.07) _cricket();
      if (Math.random() < (st.season === 'autumn' || st.season === 'winter' ? 0.05 : 0.02)) _gust();
    }
    if (st.working > 0 && Math.random() < 0.14) _workTaps();
    if (st.leisure >= 3 && Math.random() < 0.06) _murmur();
    if (st.nearWater && Math.random() < 0.10) _plip();
  }

  /* ── event SFX ── */
  const SFX = {
    door:  () => { _blip(300, 180, 0.05, 'square', 0.22); _blip(90, 70, 0.06, 'sine', 0.35, 0.04); },
    bless: () => { [523, 659, 784, 1047].forEach((f, i) => _blip(f, f, 0.28, 'sine', 0.45, i * 0.09)); },
    ship:  () => { _blip(600, 900, 0.08, 'sine', 0.4); _blip(1200, 1500, 0.05, 'sine', 0.28, 0.07); },
    raid:  () => { for (let i = 0; i < 3; i++) { _blip(880, 880, 0.16, 'square', 0.35, i * 0.4); _blip(660, 660, 0.16, 'square', 0.35, i * 0.4 + 0.19); } },
    coin:  () => { _blip(1568, 1568, 0.06, 'square', 0.3); _blip(2093, 2093, 0.14, 'square', 0.26, 0.06); },
    eat:   () => { _blip(500, 350, 0.06, 'triangle', 0.25); _blip(400, 300, 0.06, 'triangle', 0.2, 0.09); },
    // per-action foley — played positionally (sfxAt) at the spot where it happens
    mine:  () => { _blip(1500, 1100, 0.04, 'triangle', 0.30); _noiseHit(0.03, 6000, 0.12, 0.005); },     // pick clink
    chop:  () => { _noiseHit(0.05, 1600, 0.30); _blip(160, 110, 0.06, 'square', 0.22, 0.01); },          // axe thock
    farm:  () => { _noiseHit(0.09, 1100, 0.16); _noiseHit(0.06, 1400, 0.10, 0.10); },                    // hoe rustle
    fish:  () => { _blip(950, 300, 0.10, 'sine', 0.22); _blip(600, 250, 0.07, 'sine', 0.14, 0.13); },    // bobber plop
    build: () => { _blip(210, 150, 0.05, 'square', 0.26); _noiseHit(0.03, 2500, 0.14, 0.012); },         // hammer tap
    study: () => { _noiseHit(0.05, 5200, 0.10); _noiseHit(0.04, 4200, 0.07, 0.07); },                    // page flip
    pray:  () => { _blip(880, 880, 0.5, 'sine', 0.16); _blip(1320, 1320, 0.4, 'sine', 0.08, 0.12); },    // soft bell
    swing: () => { _noiseHit(0.07, 900, 0.16); _blip(2400, 1500, 0.05, 'square', 0.20, 0.05); },         // whoosh + clash
    kill:  () => { _blip(140, 55, 0.16, 'sine', 0.5); _noiseHit(0.08, 700, 0.28, 0.02); },               // felled thud
    levelup: () => { [659, 784, 988, 1319].forEach((f, i) => _blip(f, f, 0.12, 'square', 0.22, i * 0.07)); },
    shop:  () => { _noiseHit(0.04, 6500, 0.18); _blip(1568, 1568, 0.05, 'square', 0.24, 0.05); _blip(2093, 2093, 0.10, 'square', 0.2, 0.11); },  // register ka-ching
    place: () => { _blip(240, 130, 0.07, 'sine', 0.3); _noiseHit(0.04, 1800, 0.16, 0.01); },             // furniture thunk
  };
  const _last = {};
  function sfx(name, throttleMs = 400) {
    if (!ctx || !enabled() || document.hidden) return;
    const now = performance.now();
    if (now - (_last[name] || 0) < throttleMs) return;
    _last[name] = now;
    try { _playSfx(name); } catch {}
  }

  /* ── live state feeds ── */
  function update(state) {
    try {
      st.hour = state.clock_hour ?? st.hour;
      st.season = state.orchestra?.season || st.season;
      st.phase = state.orchestra?.phase || 'peace';
      st.working = Object.values(state.activity || {}).reduce((a, b) => a + (+b || 0), 0);
      st.leisure = (state.agents || []).filter(a => a.state === 'leisure').length;
    } catch {}
  }
  function updateCam(nearWater) { st.nearWater = !!nearWater; }

  /* ── positional audio: the camera is the listener ──
     setListener(cx, cy, scale) each frame/poll; sfxAt(name, wx, wy) plays the
     effect scaled by distance — zoom into a spot and its sounds get louder,
     pan away and they fade out. */
  const lis = { x: 0, y: 0, scale: 1 };
  function setListener(cx, cy, scale) { lis.x = cx; lis.y = cy; lis.scale = scale || 1; }
  function sfxAt(name, wx, wy, throttleMs = 400) {
    if (!ctx || !enabled() || document.hidden) return;
    const d = Math.hypot(wx - lis.x, wy - lis.y);
    const range = 700 / Math.max(0.6, lis.scale);      // zoomed in = tighter, louder world
    const fall = Math.max(0, 1 - d / range);
    if (fall <= 0.03) return;
    const now = performance.now();
    if (now - (_last[name] || 0) < throttleMs) return;
    _last[name] = now;
    // scale from the BASE channel volume (not the live gain — overlapping
    // positional calls would compound the attenuation and mute the channel)
    sfxG.gain.value = vol('sfx') * fall * Math.min(1.6, 0.7 + lis.scale * 0.35);
    try { _playSfx(name); } catch {}
    setTimeout(() => { if (ctx) sfxG.gain.value = vol('sfx'); }, 400);
  }

  function toggle() {
    const on = !enabled();
    localStorage.setItem('world_snd', on ? '1' : '0');
    if (on) _boot();
    else if (ctx) { _genLoopStop(0.1); try { ctx.close(); } catch {} ctx = null; clearInterval(pulse); }
    return on;
  }

  const arm = () => { _boot(); };
  window.addEventListener('pointerdown', arm, { passive: true });
  window.addEventListener('keydown', arm, { passive: true });

  return { sfx, sfxAt, setListener, toggle, update, updateCam, setVol, vol, genToggle,
           get on() { return enabled(); }, get ready() { return !!ctx; },
           get genPref() { return genOn(); } };
})();
