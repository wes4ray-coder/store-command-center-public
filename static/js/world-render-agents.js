/* ══ THE COMPANY — speech bubbles, state badges, the pixel character ══
   Split out of world-render.js (core keeps the loop + shared state). Runs in
   shared global scope (classic script, not a module). Loads right after
   world-render.js, before world-ui.js. Code moved verbatim. */


/* small speech bubble */
function _bubble(ctx, x, y, text) {
  ctx.font = '9px system-ui'; ctx.textAlign = 'left';
  const w = Math.min(180, ctx.measureText(text).width + 12);
  const bx = x - w / 2, by = y - 16;
  ctx.fillStyle = 'rgba(20,28,44,.95)'; ctx.strokeStyle = '#3a4a66';
  ctx.lineWidth = 1;
  ctx.beginPath(); ctx.roundRect(bx, by - 14, w, 20, 5); ctx.fill(); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(x - 4, by + 5); ctx.lineTo(x + 4, by + 5); ctx.lineTo(x, by + 11); ctx.fill();
  ctx.fillStyle = '#e8eefc'; ctx.textAlign = 'center';
  ctx.fillText(text.length > 30 ? text.slice(0, 29) + '…' : text, x, by - 1);
}

const _HAIR = ['#3a2a1e', '#6b4423', '#111318', '#8a5a2b', '#c9a15a', '#5a3d5c', '#8a2e2e'];
const _hairColor = a => _HAIR[(a.id * 7) % _HAIR.length];

/* every backend state gets a readable visual — before this, sleep/study/prayer/
   breakdown/downed all rendered as a generic idler and the state machine was
   invisible. Unknown/new states still degrade to nothing (no crash). */
function _stateBadge(ctx, a, x, y, top) {
  const t = performance.now();
  switch (a.state) {
    case 'sleep': {                                  // drifting Zzz
      const k = (t / 900 + a.id) % 3;
      ctx.font = '8px serif'; ctx.globalAlpha = 0.85;
      ctx.fillStyle = '#cfe0ff';
      ctx.fillText('z', x + 7 + k, top - 3 - k * 3);
      if (k > 1) ctx.fillText('Z', x + 10 + k, top - 8 - k * 2);
      ctx.globalAlpha = 1;
      break;
    }
    case 'studying':
      ctx.font = '8px serif'; ctx.fillText('📖', x + 10, y - 14);
      break;
    case 'praying': {
      ctx.font = '8px serif'; ctx.fillText('🙏', x + 10, y - 14);
      const g = 0.25 + 0.15 * Math.sin(t / 500 + a.id);      // soft halo
      ctx.strokeStyle = `rgba(255,235,160,${g})`; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.arc(x, y - 20, 8, 0, 6.283); ctx.stroke();
      break;
    }
    case 'breakdown': {                              // storm cloud + fizz
      ctx.font = '9px serif';
      ctx.fillText(Math.floor(t / 400 + a.id) % 2 ? '💢' : '🌧️', x + 10, y - 16);
      break;
    }
    case 'downed': {                                 // KO'd: dizzy stars + red pulse ring
      ctx.font = '9px serif'; ctx.fillText('💫', x, top - 10);
      const g = 0.35 + 0.25 * Math.sin(t / 260);
      ctx.strokeStyle = `rgba(239,68,68,${g})`; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.ellipse(x, y + 1, 9, 4, 0, 0, 6.283); ctx.stroke();
      break;
    }
    case 'skilling':
      ctx.font = '8px serif'; ctx.fillText('⛏️', x + 11, y - 14);
      break;
    case 'defending':
      ctx.font = '8px serif';
      ctx.fillText(a.role === 'build' ? '🧱' : a.role === 'medic' ? '💊' : '⚔️', x + 11, y - 14);
      break;
    case 'overseeing':
      ctx.font = '8px serif'; ctx.fillText('🧐', x + 10, y - 14);
      break;
    case 'shopping':
      ctx.font = '8px serif'; ctx.fillText('🛍️', x + 10, y - 14);
      break;
    case 'sitting':                                  // settled on a bench
      ctx.font = '8px serif'; ctx.fillText('🪑', x + 10, y - 14);
      break;
    case 'picnicking': {                             // picnic basket + drifting crumbs
      ctx.font = '8px serif'; ctx.fillText('🧺', x + 10, y - 14);
      const k = (t / 700 + a.id) % 2;
      if (k > 1.4) { ctx.fillStyle = '#e8d9a8'; ctx.fillRect(x - 6, y - 8 - k, 1, 1); }
      break;
    }
    case 'admiring': {                               // sparkle that twinkles as they take it in
      ctx.font = '8px serif'; ctx.globalAlpha = 0.6 + 0.4 * Math.sin(t / 400 + a.id);
      ctx.fillText('✨', x + 10, y - 14); ctx.globalAlpha = 1;
      break;
    }
  }
}

/* ── what is this agent ACTUALLY doing? → {key, swing} or null ──────────────
   swing = play the strike animation. Fishing/farming/desk/study don't swing —
   their tool overlay carries the action instead. */
function _actionOf(a) {
  if (a.state === 'skilling') {
    // Map EVERY gatherable location to its own tool. `hunt` was added to the
    // backend skills but was missing here — hunters fell through to the pickaxe
    // default and swung a pick over the (art-less) hunt node = "swinging at
    // nothing". Unknown locations no longer swing (swing:0) so a stray skilling
    // spot never phantom-pickaxes.
    return { woodcut: { key: 'chop', swing: 1 }, mine: { key: 'mine', swing: 1 },
             build: { key: 'build', swing: 1 }, farm: { key: 'farm', swing: 0 },
             fish: { key: 'fish', swing: 0 }, hunt: { key: 'hunt', swing: 0 } }[a.location]
           || { key: 'build', swing: 0 };
  }
  if (a.state === 'defending')
    return a.role === 'build' ? { key: 'build', swing: 1 }
         : a.role === 'medic' ? { key: 'medic', swing: 0 } : { key: 'fight', swing: 1 };
  if (a.state === 'working') return { key: 'desk', swing: 0 };
  if (a.state === 'studying') return { key: 'study', swing: 0 };
  return null;
}

/* ── held TOOLS: a matching implement drawn in-hand per action ──────────────── */
function _heldTool(ctx, key, x, y) {
  const t = performance.now();
  ctx.save();
  if (key === 'mine' || key === 'chop' || key === 'build' || key === 'fight') {
    // swing in sync-ish with the strike animation
    const ang = Math.sin(t / 160) * 0.85 - 0.5;
    ctx.translate(x + 5, y - 10); ctx.rotate(ang);
    ctx.strokeStyle = '#7a5230'; ctx.lineWidth = 1.6;
    ctx.beginPath(); ctx.moveTo(0, 3); ctx.lineTo(0, -7); ctx.stroke();     // haft
    if (key === 'mine') {                                                   // pick head
      ctx.strokeStyle = '#9aa3b2'; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(-4, -8); ctx.quadraticCurveTo(0, -11, 4, -8); ctx.stroke();
    } else if (key === 'chop') {                                            // axe blade
      ctx.fillStyle = '#aeb6c4'; ctx.beginPath();
      ctx.moveTo(0, -8); ctx.lineTo(4.5, -9.5); ctx.lineTo(4.5, -5.5); ctx.closePath(); ctx.fill();
    } else if (key === 'build') {                                           // hammer head
      ctx.fillStyle = '#8a919f'; ctx.fillRect(-2.5, -9.5, 5, 3);
    } else {                                                                // sword
      ctx.strokeStyle = '#cdd6e4'; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(0, -7); ctx.lineTo(0, -14); ctx.stroke();
      ctx.strokeStyle = '#e8c14a'; ctx.lineWidth = 1.2;
      ctx.beginPath(); ctx.moveTo(-2.5, -6.5); ctx.lineTo(2.5, -6.5); ctx.stroke();
    }
  } else if (key === 'fish') {                                              // rod + line + bobber
    ctx.strokeStyle = '#7a5230'; ctx.lineWidth = 1.4;
    ctx.beginPath(); ctx.moveTo(x + 3, y - 8); ctx.lineTo(x + 12, y - 16); ctx.stroke();
    const bob = Math.sin(t / 600) * 1.5;
    ctx.strokeStyle = 'rgba(220,230,245,.6)'; ctx.lineWidth = 0.8;
    ctx.beginPath(); ctx.moveTo(x + 12, y - 16); ctx.lineTo(x + 15, y + 4 + bob); ctx.stroke();
    ctx.fillStyle = '#e0483b'; ctx.beginPath(); ctx.arc(x + 15, y + 5 + bob, 1.6, 0, 6.283); ctx.fill();
    if (Math.floor(t / 2400) % 4 === 0) {                                   // occasional ripple
      const k = (t % 2400) / 2400;
      ctx.strokeStyle = `rgba(160,210,250,${0.5 * (1 - k)})`; ctx.lineWidth = 0.8;
      ctx.beginPath(); ctx.arc(x + 15, y + 6, 2 + k * 6, 0, 6.283); ctx.stroke();
    }
  } else if (key === 'hunt') {                                              // bow, drawn + released
    const draw = (Math.sin(t / 700) + 1) / 2;                              // 0..1 nock→loose cycle
    ctx.strokeStyle = '#7a5230'; ctx.lineWidth = 1.4;
    ctx.beginPath(); ctx.arc(x + 7, y - 8, 6, -1.1, 1.1); ctx.stroke();    // bow limb
    ctx.strokeStyle = 'rgba(230,235,245,.7)'; ctx.lineWidth = 0.8;         // string, pulled back when drawing
    const sx = x + 7 + Math.cos(-1.1) * 6, sy = y - 8 + Math.sin(-1.1) * 6;
    const ex = x + 7 + Math.cos(1.1) * 6, ey = y - 8 + Math.sin(1.1) * 6;
    const nk = x + 2 - draw * 3;                                           // nock point
    ctx.beginPath(); ctx.moveTo(sx, sy); ctx.lineTo(nk, y - 8); ctx.lineTo(ex, ey); ctx.stroke();
    ctx.strokeStyle = '#caa06a'; ctx.lineWidth = 1;                        // arrow shaft
    ctx.beginPath(); ctx.moveTo(nk, y - 8); ctx.lineTo(x + 13, y - 8); ctx.stroke();
  } else if (key === 'farm') {                                              // slow hoe sweep
    const ang = 0.5 + Math.sin(t / 520) * 0.45;
    ctx.translate(x + 5, y - 9); ctx.rotate(ang);
    ctx.strokeStyle = '#7a5230'; ctx.lineWidth = 1.4;
    ctx.beginPath(); ctx.moveTo(0, 4); ctx.lineTo(0, -8); ctx.stroke();
    ctx.fillStyle = '#8a919f'; ctx.fillRect(-3.5, -9.5, 4, 2);
  } else if (key === 'study') {                                             // open book in hands
    ctx.fillStyle = '#efe6d2'; ctx.fillRect(x - 5, y - 10, 4.5, 3.5); ctx.fillRect(x + 0.5, y - 10, 4.5, 3.5);
    ctx.strokeStyle = '#5b3a22'; ctx.lineWidth = 0.7; ctx.strokeRect(x - 5, y - 10, 10, 3.5);
  } else if (key === 'medic') {                                             // medkit
    ctx.fillStyle = '#efe6d2'; ctx.fillRect(x + 4, y - 8, 6, 4.5);
    ctx.fillStyle = '#e0483b'; ctx.fillRect(x + 6.4, y - 7.4, 1.2, 3.2); ctx.fillRect(x + 5.4, y - 6.4, 3.2, 1.2);
  }
  ctx.restore();
}

/* ── UNIQUE bodies: per-agent clothing tint + accessory over the shared sheet ── */
const _tintCv = document.createElement('canvas'); _tintCv.width = 96; _tintCv.height = 96;
const _tintCtx = _tintCv.getContext('2d');
function _drawTintedActor(ctx, a, facing, mode, x, y, h) {
  _tintCtx.clearRect(0, 0, 96, 96);
  if (!WA.drawActor(_tintCtx, facing, mode, 48, 76, h)) return false;
  _tintCtx.globalCompositeOperation = 'source-atop';                        // clothe them in their colour
  _tintCtx.globalAlpha = 0.28;
  _tintCtx.fillStyle = a.color || '#8ab';
  _tintCtx.fillRect(0, 0, 96, 96);
  _tintCtx.globalAlpha = 1;
  // accessory by identity: none / headband / cap / hood
  const style = (a.id || 0) % 4, headY = 76 - h * 0.80;
  if (style === 1) { _tintCtx.fillStyle = _hairColor(a); _tintCtx.fillRect(40, headY + 3, 16, 2.5); }
  else if (style === 2) { _tintCtx.fillStyle = a.color || '#8ab'; _tintCtx.fillRect(41, headY - 1, 14, 4); _tintCtx.fillRect(46, headY + 3, 12, 1.8); }
  else if (style === 3) { _tintCtx.strokeStyle = 'rgba(20,24,34,.85)'; _tintCtx.lineWidth = 2.2; _tintCtx.beginPath(); _tintCtx.arc(48, headY + 5, 8, Math.PI, 0); _tintCtx.stroke(); }
  _tintCtx.globalCompositeOperation = 'source-over';
  ctx.drawImage(_tintCv, x - 48, y - 76, 96, 96);
  return true;
}

/* ── SELF-GENERATED look: the agent's own commissioned sprite ──────────────── */
const _agentImgs = {};
function _drawCustomSprite(ctx, a, x, y, moving, s) {
  let im = _agentImgs[a.sprite_path];
  if (im === undefined) {
    im = new Image(); im.onerror = () => { _agentImgs[a.sprite_path] = null; };
    im.src = a.sprite_path; _agentImgs[a.sprite_path] = im;
  }
  if (!im || !im.complete || !im.naturalWidth) return false;
  const H = 40, W = 40;
  const hop = moving ? Math.abs(Math.sin((s.bob || 0) * 3)) * 2 : 0;
  ctx.save();
  ctx.imageSmoothingEnabled = false;
  if (s.dir === 'left') { ctx.translate(2 * x, 0); ctx.scale(-1, 1); }
  ctx.drawImage(im, x - W / 2, y - H - hop + 2, W, H);
  ctx.restore();
  return true;
}

/* pixel character — a little person with hair, shirt (agent colour), a face that
   turns to face its walking direction, and a 2-frame walk. */
function _character(ctx, s, moving) {
  const a = s.agent;
  const x = Math.round(s.px), y = Math.round(s.py);
  const sel = _selectedId === a.id;
  const c = a.color || '#8ab', hair = _hairColor(a), skin = '#f0c49a';
  const dir = s.dir || 'down';
  const step = moving ? (Math.floor(s.bob) % 2 ? 1 : -1) : 0;   // leg swing

  // shadow
  ctx.fillStyle = 'rgba(0,0,0,.30)'; ctx.beginPath(); ctx.ellipse(x, y + 1, 6, 2.4, 0, 0, 6.283); ctx.fill();

  let top = y - 24;    // where labels/emblems sit above the head
  // WHAT ARE THEY ACTUALLY DOING? Only true swinging work plays the swing
  // animation — no more pickaxing at fish, deskwork or books. Each action also
  // gets a matching held TOOL drawn in-hand.
  const ACT = _actionOf(a);
  // Only STRIKE when planted at the task. A skilling agent keeps its state the
  // whole walk over to its node, so gating the swing on !moving stops agents
  // from "walking around swinging a pickaxe" en route — they walk, then strike
  // once they arrive on the node.
  const mode = ACT && ACT.swing && !moving ? 'work' : (moving ? 'walk' : 'idle');
  const facing = ACT ? 'down' : dir;                     // face the task while acting
  // fighters lunge forward at the enemy; builders hold at the wall
  let lx = 0, ly = 0;
  if (a.state === 'defending' && a.role !== 'build') { const t = Math.sin(performance.now() / 130 + a.id); lx = t * 3; ly = -Math.abs(t) * 2; }
  const drew = a.sprite_path
    ? _drawCustomSprite(ctx, a, x + lx, y + 2 + ly, moving, s)
    : (window.WA && WA.charsReady && _drawTintedActor(ctx, a, facing, mode, x + lx, y + 2 + ly, 38));
  if (drew) {
    // identity: agent-colour foot ring (tint/accessory/custom sprite carry the rest)
    ctx.strokeStyle = c; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.ellipse(x, y + 2, 6, 2.6, 0, 0, 6.283); ctx.stroke();
    top = y - 26;
    if (ACT) _heldTool(ctx, ACT.key, x + lx, y + ly);
    if (sel) { ctx.strokeStyle = '#fff'; ctx.lineWidth = 1; ctx.strokeRect(x - 12, y - 26, 24, 30); }
  } else {
    // ── procedural fallback villager ──
    ctx.fillStyle = '#32405a'; ctx.fillRect(x - 3, y - 6 + Math.max(0, step), 2, 6); ctx.fillRect(x + 1, y - 6 + Math.max(0, -step), 2, 6);
    ctx.fillStyle = '#20283a'; ctx.fillRect(x - 3, y - 1 + Math.max(0, step), 2, 1); ctx.fillRect(x + 1, y - 1 + Math.max(0, -step), 2, 1);
    ctx.fillStyle = c; ctx.fillRect(x - 4, y - 15, 8, 10);
    ctx.fillStyle = 'rgba(255,255,255,.14)'; ctx.fillRect(x - 4, y - 15, 2, 10);
    ctx.fillStyle = 'rgba(0,0,0,.20)'; ctx.fillRect(x + 3, y - 15, 1, 10);
    ctx.fillStyle = c; ctx.fillRect(x - 5, y - 14, 1, 6); ctx.fillRect(x + 4, y - 14, 1, 6);
    ctx.fillStyle = skin; ctx.fillRect(x - 5, y - 9, 1, 2); ctx.fillRect(x + 4, y - 9, 1, 2);
    ctx.fillStyle = skin; ctx.fillRect(x - 4, y - 23, 8, 8);
    ctx.fillStyle = hair; ctx.fillRect(x - 4, y - 24, 8, 4);
    if (dir === 'up') ctx.fillRect(x - 4, y - 24, 8, 7);
    else { ctx.fillRect(x - 4, y - 22, 1, 3); ctx.fillRect(x + 3, y - 22, 1, 3); }
    if (dir !== 'up') {
      ctx.fillStyle = '#26313f';
      if (dir === 'left') ctx.fillRect(x - 3, y - 19, 1, 2);
      else if (dir === 'right') ctx.fillRect(x + 2, y - 19, 1, 2);
      else { ctx.fillRect(x - 2, y - 19, 1, 2); ctx.fillRect(x + 1, y - 19, 1, 2); }
    }
    if (sel) { ctx.strokeStyle = '#fff'; ctx.lineWidth = 1; ctx.strokeRect(x - 6, y - 25, 12, 26); }
  }

  ctx.textAlign = 'center';
  const leader = a.kind === 'mayor' ? '👑' : a.kind === 'boss' ? '💼' : null;
  if (leader) { ctx.font = '11px serif'; ctx.fillText(leader, x, top - 5); }
  if (a.blessed) {                                     // god's buff — a golden halo
    const g = 0.5 + 0.25 * Math.sin(performance.now() / 350 + a.id);
    ctx.strokeStyle = `rgba(255,215,90,${g})`; ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.ellipse(x, top - 8, 6, 2.2, 0, 0, 6.283); ctx.stroke();
  }
  ctx.font = '10px serif';
  const wob = a.state === 'working' ? Math.sin(s.bob * 0.5 + performance.now() / 300) * 1.5 : 0;
  ctx.fillText(a.mood_emoji || '🙂', x, top - 1 + (leader ? 0 : wob));
  if (a.thriving) { ctx.font = '7px serif'; ctx.fillText('🌟', x - 10, top - 1); }
  if (a.state === 'working') { ctx.font = '8px serif'; ctx.fillText('⚙️', x + 11, y - 14); }
  _stateBadge(ctx, a, x, y, top);

  // name pill + level/coins
  ctx.font = 'bold 7px monospace';
  const nw = ctx.measureText(a.name).width + 5;
  ctx.fillStyle = 'rgba(10,16,26,.72)'; ctx.beginPath(); ctx.roundRect(x - nw / 2, y + 3, nw, 8, 2); ctx.fill();
  ctx.fillStyle = sel ? '#fff' : '#e2e8f4'; ctx.fillText(a.name, x, y + 9);
  ctx.font = '6px monospace'; ctx.fillStyle = '#a9c7e8'; ctx.fillText('L' + a.level + '  \u{1FA99}' + (a.coins || 0), x, y + 16);
}

