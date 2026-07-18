'use strict';
/* ══ Knowledge Graph — native force-directed explorer (window.GE) ══
   A crisp, in-app force graph for a focused SLICE of the knowledge graph (folder,
   community, or ego-network). Canvas + a small force sim; pan / zoom / drag,
   community-coloured nodes sized by degree, click a node to inspect. Self-
   contained, no external libs. */
window.GE = (function () {
  let cv, ctx, raf = null, nodes = [], edges = [], adj = {};
  let cam = { x: 0, y: 0, s: 1 }, alpha = 1, hover = null, sel = null, drag = null, panning = null;
  let onClick = null, W = 0, H = 0, dpr = 1, hidden = new Set();
  const _vis = n => !hidden.has(n.community);

  const _hue = c => (typeof c === 'number' ? (c * 47) % 360 : Math.abs(_hash(String(c || 0))) % 360);
  function _hash(s) { let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0; return h; }
  const _rad = n => 2.5 + Math.sqrt((n.degree || 0) + 1) * 1.7;
  const _col = n => `hsl(${_hue(n.community)},60%,58%)`;

  function mount(canvas, opts) {
    cv = canvas; ctx = cv.getContext('2d'); onClick = (opts || {}).onNodeClick;
    _resize();
    cv.onwheel = _wheel; cv.onmousedown = _down; window.addEventListener('mousemove', _move);
    window.addEventListener('mouseup', _up); cv.onmousemove = _hoverMove;
    if (!raf) _loop();
  }
  function _resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = cv.clientWidth; H = cv.clientHeight;
    cv.width = W * dpr; cv.height = H * dpr;
  }
  window.__geResize = _resize;

  function setData(ns, es) {
    const prev = {}; nodes.forEach(n => prev[n.id] = n);
    nodes = ns.map((n, i) => {
      const p = prev[n.id];
      const a = (i / ns.length) * Math.PI * 2, R = 60 + (i % 40) * 6;
      return Object.assign({ x: p ? p.x : W / 2 + Math.cos(a) * R, y: p ? p.y : H / 2 + Math.sin(a) * R, vx: 0, vy: 0 }, n);
    });
    const byId = {}; nodes.forEach(n => byId[n.id] = n);
    edges = es.map(e => ({ s: byId[e.source], t: byId[e.target], rel: e.relation, conf: e.confidence })).filter(e => e.s && e.t);
    adj = {}; edges.forEach(e => { (adj[e.s.id] = adj[e.s.id] || []).push(e.t.id); (adj[e.t.id] = adj[e.t.id] || []).push(e.s.id); });
    alpha = 1; sel = null; hover = null;
    _fit();
  }
  function _fit() {
    if (!nodes.length) return;
    // spread initial positions a bit by degree so hubs sit central
    cam = { x: 0, y: 0, s: 1 };
  }

  function _tick() {
    if (alpha < 0.02) return;
    const n = nodes.length, REP = 1400, CENTER = 0.012;
    for (let i = 0; i < n; i++) {
      const a = nodes[i]; if (!_vis(a)) continue;
      for (let j = i + 1; j < n; j++) {
        const b = nodes[j]; if (!_vis(b)) continue;
        let dx = a.x - b.x, dy = a.y - b.y, d2 = dx * dx + dy * dy || 0.01;
        if (d2 > 90000) continue;                       // ignore far pairs (perf + local structure)
        const f = REP / d2, d = Math.sqrt(d2);
        const fx = (dx / d) * f, fy = (dy / d) * f;
        a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
      }
      a.vx += (W / 2 - a.x) * CENTER; a.vy += (H / 2 - a.y) * CENTER;
    }
    for (const e of edges) {                            // springs
      if (!_vis(e.s) || !_vis(e.t)) continue;
      let dx = e.t.x - e.s.x, dy = e.t.y - e.s.y, d = Math.hypot(dx, dy) || 0.01;
      const f = (d - 42) * 0.04, fx = (dx / d) * f, fy = (dy / d) * f;
      e.s.vx += fx; e.s.vy += fy; e.t.vx -= fx; e.t.vy -= fy;
    }
    for (const a of nodes) {
      if (a === (drag && drag.node) || !_vis(a)) continue;
      a.vx *= 0.86; a.vy *= 0.86;
      a.x += Math.max(-12, Math.min(12, a.vx * alpha));
      a.y += Math.max(-12, Math.min(12, a.vy * alpha));
    }
    alpha *= 0.985;
  }

  function _loop() {
    // Bail if the canvas was detached (view switch rebuilt #main-content) — otherwise
    // the sim runs forever drawing to a leaked, detached canvas. Self-clean and stop.
    if (!cv || !cv.isConnected) { destroy(); return; }
    _tick();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, cv.width, cv.height);
    ctx.setTransform(dpr * cam.s, 0, 0, dpr * cam.s, dpr * cam.x, dpr * cam.y);
    // edges — coloured by provenance: EXTRACTED solid, INFERRED dashed amber, AMBIGUOUS dashed red
    const _epass = (test, style, dash, w) => {
      ctx.setLineDash(dash.map(d => d / cam.s)); ctx.lineWidth = w / cam.s; ctx.strokeStyle = style; ctx.beginPath();
      for (const e of edges) { if (!_vis(e.s) || !_vis(e.t) || !test(e.conf)) continue; ctx.moveTo(e.s.x, e.s.y); ctx.lineTo(e.t.x, e.t.y); }
      ctx.stroke();
    };
    _epass(c => c !== 'INFERRED' && c !== 'AMBIGUOUS', 'rgba(130,160,205,.28)', [], 0.6);
    _epass(c => c === 'INFERRED', 'rgba(200,170,110,.4)', [3, 3], 0.5);
    _epass(c => c === 'AMBIGUOUS', 'rgba(225,110,110,.45)', [3, 3], 0.5);
    ctx.setLineDash([]);
    // highlight selected node's edges
    if (sel && _vis(sel)) {
      ctx.strokeStyle = 'rgba(160,190,255,.85)'; ctx.lineWidth = 1.4 / cam.s; ctx.beginPath();
      for (const e of edges) if ((e.s === sel || e.t === sel) && _vis(e.s) && _vis(e.t)) { ctx.moveTo(e.s.x, e.s.y); ctx.lineTo(e.t.x, e.t.y); }
      ctx.stroke();
    }
    // nodes
    for (const nn of nodes) {
      if (!_vis(nn)) continue;
      const r = _rad(nn);
      ctx.beginPath(); ctx.arc(nn.x, nn.y, r, 0, 6.283);
      ctx.fillStyle = nn.kind === 'document' ? `hsl(${_hue(nn.community)},45%,52%)` : _col(nn);
      ctx.fill();
      if (nn === sel || nn === hover) { ctx.lineWidth = 2 / cam.s; ctx.strokeStyle = '#fff'; ctx.stroke(); }
    }
    // labels: hubs + hover + selected + selected's neighbours
    ctx.textAlign = 'center'; ctx.fillStyle = '#e6eefc';
    const fs = Math.max(7, 9 / cam.s); ctx.font = `${fs}px sans-serif`;
    const nbr = sel ? new Set(adj[sel.id] || []) : null;
    for (const nn of nodes) {
      if (!_vis(nn)) continue;
      const show = nn === hover || nn === sel || (nbr && nbr.has(nn.id)) || nn.degree >= 14;
      if (!show) continue;
      const r = _rad(nn);
      ctx.fillStyle = 'rgba(8,12,20,.72)';
      const t = nn.label || nn.id, tw = ctx.measureText(t).width;
      ctx.fillRect(nn.x - tw / 2 - 2, nn.y - r - fs - 3, tw + 4, fs + 2);
      ctx.fillStyle = nn === sel ? '#fff' : '#cfe0ff';
      ctx.fillText(t, nn.x, nn.y - r - 4);
    }
    raf = requestAnimationFrame(_loop);
  }

  // ── interaction ──
  function _toWorld(ev) { const b = cv.getBoundingClientRect(); return { x: (ev.clientX - b.left - cam.x) / cam.s, y: (ev.clientY - b.top - cam.y) / cam.s }; }
  function _pick(ev) {
    const w = _toWorld(ev); let best = null, bd = 16 / cam.s;
    for (const nn of nodes) { if (!_vis(nn)) continue; const d = Math.hypot(nn.x - w.x, nn.y - w.y); if (d < Math.max(bd, _rad(nn) + 3) && d < bd + _rad(nn)) { if (!best || d < best.d) best = { n: nn, d }; } }
    return best && best.n;
  }
  function _wheel(ev) {
    ev.preventDefault(); const b = cv.getBoundingClientRect(), mx = ev.clientX - b.left, my = ev.clientY - b.top;
    const k = ev.deltaY < 0 ? 1.12 : 1 / 1.12, ns = Math.max(0.15, Math.min(6, cam.s * k));
    cam.x = mx - (mx - cam.x) * (ns / cam.s); cam.y = my - (my - cam.y) * (ns / cam.s); cam.s = ns;
  }
  function _down(ev) {
    const n = _pick(ev);
    if (n) { drag = { node: n, moved: false }; alpha = Math.max(alpha, 0.3); }
    else panning = { x: ev.clientX, y: ev.clientY, cx: cam.x, cy: cam.y };
  }
  function _move(ev) {
    if (drag) { const w = _toWorld(ev); drag.node.x = w.x; drag.node.y = w.y; drag.node.vx = drag.node.vy = 0; drag.moved = true; }
    else if (panning) { cam.x = panning.cx + (ev.clientX - panning.x); cam.y = panning.cy + (ev.clientY - panning.y); }
  }
  function _up(ev) {
    if (drag && !drag.moved) { sel = drag.node; if (onClick) onClick(sel); }
    else if (panning && Math.hypot(ev.clientX - panning.x, ev.clientY - panning.y) < 4) { const n = _pick(ev); sel = n || null; if (n && onClick) onClick(n); }
    drag = null; panning = null;
  }
  function _hoverMove(ev) { if (!drag && !panning) hover = _pick(ev); cv.style.cursor = hover ? 'pointer' : 'grab'; }

  function neighborsOf(id) { return adj[id] || []; }
  function setHidden(set) { hidden = set || new Set(); alpha = Math.max(alpha, 0.45); }
  function communities() {
    const m = {};
    for (const n of nodes) { const c = n.community; if (c == null) continue; if (!m[c]) m[c] = { community: c, name: n.community_name || ('#' + c), count: 0, color: `hsl(${_hue(c)},60%,58%)` }; m[c].count++; }
    return Object.values(m).sort((a, b) => b.count - a.count);
  }
  function exportPNG() { return cv ? cv.toDataURL('image/png') : null; }
  function destroy() { if (raf) cancelAnimationFrame(raf); raf = null; window.removeEventListener('mousemove', _move); window.removeEventListener('mouseup', _up); }
  return { mount, setData, destroy, neighborsOf, setHidden, communities, exportPNG, get count() { return nodes.length; } };
})();
