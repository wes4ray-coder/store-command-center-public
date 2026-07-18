'use strict';
/* ══════════════════════════════════════════════════════════════════════════
   THE COMPANY — per-department production lines (window.WF).

   Each HQ department room runs its OWN little assembly line: a row of machines,
   and a product that steps machine → machine (25% → 50% → 75% → 100%) while that
   department has real work. When the department is idle, its line sits still —
   no product wandering. Purely visual + client-side, driven by the live work
   `activity` map ({dept: jobCount}). Uses WM.hqRooms (room rect + dept).
   ══════════════════════════════════════════════════════════════════════════ */
window.WF = (function () {
  const MACHINES = 4;          // stations per department line (→ quarters: 25/50/75/100)
  const WORK = 1.5;            // seconds a product is worked at a machine
  const MOVE = 1.0;            // seconds gliding to the next machine
  const DEPT_HUE = { storefront: 40, image: 265, video: 330, audio: 155, models3d: 210,
                     publishing: 190, devlab: 0, resell: 45, trends: 280,
                     portal: 175, social: 200, finance: 50, netsec: 220 };
  let lines = {};              // dept -> { stage, phase, t, active }
  let shipped = {};            // dept -> count of finished products (visual tally)

  function reset() { lines = {}; shipped = {}; }

  // shipped tallies survive tab switches + reloads (lines are sub-second
  // animation state — always rebuilt). Backend progression is server-side;
  // this is only the view's memory of it.
  function save() { try { localStorage.setItem('world_wf_shipped', JSON.stringify(shipped)); } catch {} }
  function restore() {
    lines = {};
    try { shipped = JSON.parse(localStorage.getItem('world_wf_shipped') || '{}') || {}; }
    catch { shipped = {}; }
  }

  // MACHINES positions along the lower half of the room, left → right
  function _stations(room) {
    const y = room.y0 + room.h * 0.60;
    const x0 = room.x0 + room.w * 0.18, x1 = room.x0 + room.w * 0.82;
    const out = [];
    for (let i = 0; i < MACHINES; i++)
      out.push({ x: x0 + (x1 - x0) * (MACHINES === 1 ? 0.5 : i / (MACHINES - 1)), y });
    return out;
  }

  function tick(dt, activity) {
    for (const room of (WM.hqRooms || [])) {
      const busy = !!(activity && (activity[room.dept] || 0) > 0);
      const L = lines[room.dept] || (lines[room.dept] = { stage: 0, phase: 'work', t: 0, active: false });
      if (!busy) { L.active = false; L.phase = 'work'; L.stage = 0; L.t = 0; continue; }  // idle → line stops
      L.active = true;
      L.t += dt;
      if (L.phase === 'work') {
        if (L.t >= WORK) {
          L.t = 0;
          if (L.stage >= MACHINES - 1) { shipped[room.dept] = Math.min(20, (shipped[room.dept] || 0) + 1); save();
                                         if (window.WAU) (WAU.sfxAt || WAU.sfx)('ship', room.x, room.y, 2500); L.stage = 0; }  // done → ship AT the room
          else L.phase = 'move';
        }
      } else if (L.t >= MOVE) { L.t = 0; L.stage++; L.phase = 'work'; }
    }
  }

  function _machine(ctx, x, y, on, hue) {
    ctx.fillStyle = on ? `hsl(${hue},28%,30%)` : '#2a2f3a';
    ctx.fillRect(x - 5, y - 6, 10, 8);                                  // console body
    ctx.fillStyle = on ? `hsl(${hue},70%,55%)` : '#39414f';
    ctx.fillRect(x - 4, y - 5, 8, 3);                                   // screen
    ctx.fillStyle = on ? '#8fe0a0' : '#525c6b';
    ctx.fillRect(x + 3, y - 5.5, 1.6, 1.6);                             // status light
    ctx.strokeStyle = 'rgba(0,0,0,.35)'; ctx.lineWidth = 0.5; ctx.strokeRect(x - 5, y - 6, 10, 8);
  }

  function _box(ctx, x, y, s, hue) {
    ctx.save();
    ctx.shadowColor = `hsl(${hue},80%,60%)`; ctx.shadowBlur = 6;
    ctx.fillStyle = `hsl(${hue},60%,55%)`; ctx.fillRect(x - s / 2, y - s, s, s);
    ctx.fillStyle = `hsl(${hue},65%,72%)`; ctx.fillRect(x - s / 2, y - s, s, 2);
    ctx.restore();
  }

  function draw(ctx) {
    const now = performance.now();
    for (const room of (WM.hqRooms || [])) {
      const L = lines[room.dept]; if (!L) continue;
      const st = _stations(room), hue = DEPT_HUE[room.dept] != null ? DEPT_HUE[room.dept] : 200;
      // the machines (lit while the department is working, dim when idle)
      for (const m of st) _machine(ctx, m.x, m.y, L.active, hue);
      // a little conveyor belt line linking them
      ctx.strokeStyle = L.active ? `hsla(${hue},40%,55%,.5)` : 'rgba(90,100,116,.35)';
      ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(st[0].x, st[0].y + 3); ctx.lineTo(st[st.length - 1].x, st[st.length - 1].y + 3); ctx.stroke();
      // shipped tally on the room's back shelf
      if (shipped[room.dept]) {
        ctx.font = '7px sans-serif'; ctx.textAlign = 'right'; ctx.fillStyle = '#cfe0ff';
        ctx.fillText('📦' + shipped[room.dept], room.x0 + room.w - 4, room.y0 + 9);
      }
      if (!L.active) continue;
      // the product: sits at the current machine, glides to the next during 'move'
      const cur = st[L.stage];
      let px = cur.x, py = cur.y;
      if (L.phase === 'move' && L.stage < st.length - 1) {
        const nx = st[L.stage + 1], k = L.t / MOVE, e = k * k * (3 - 2 * k);
        px = cur.x + (nx.x - cur.x) * e; py = cur.y + (nx.y - cur.y) * e;
      }
      if (L.phase === 'work') {                         // pulse ring while being worked
        const pr = 5 + Math.sin(now / 140) * 1.5;
        ctx.strokeStyle = `hsla(${hue},80%,65%,.55)`; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.arc(px, py - 5, pr, 0, 6.283); ctx.stroke();
      }
      _box(ctx, px, py - 5 + Math.sin(now / 150 + L.stage) * 1.1, 6, hue);
      // progress % — 25 → 50 → 75 → 100 as it reaches each machine
      const pct = Math.round((L.stage + 1) / MACHINES * 100);
      ctx.font = 'bold 7px sans-serif'; ctx.textAlign = 'center'; ctx.fillStyle = '#e6f0ff';
      ctx.fillText(pct + '%', px, py - 13);
    }
  }

  return { reset, save, restore, tick, draw, get shipped() { return shipped; } };
})();
