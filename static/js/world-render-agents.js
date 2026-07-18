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
  }
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
  const labouring = a.state === 'working' || a.state === 'skilling' || a.state === 'defending';  // all swing the work anim
  const mode = labouring ? 'work' : (moving ? 'walk' : 'idle');
  const facing = labouring ? 'down' : dir;               // face the workstation / node while labouring
  // fighters lunge forward at the enemy; builders hold at the wall
  let lx = 0, ly = 0;
  if (a.state === 'defending' && a.role !== 'build') { const t = Math.sin(performance.now() / 130 + a.id); lx = t * 3; ly = -Math.abs(t) * 2; }
  if (window.WA && WA.charsReady && WA.drawActor(ctx, facing, mode, x + lx, y + 2 + ly, 38)) {
    // real animated villager — mark identity with an agent-colour foot ring
    ctx.strokeStyle = c; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.ellipse(x, y + 2, 6, 2.6, 0, 0, 6.283); ctx.stroke();
    top = y - 26;
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

