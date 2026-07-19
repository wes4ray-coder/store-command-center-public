/* ══ JELLYCOIN (JLY) — Crypto sub-tab ══
   The store's OWN GPU-mined token: chain stats, GPU rigs (old cards welcome, no
   CPU mining ever), Company skilling boosts (god-toggled), wallets & transfers,
   art NFTs, and agent push/sell missions (always behind god approval).
   Loaded by tab-crypto.js as pane 'jelly' → cryptoLoadJelly(). */

const _JLY = { st: null, tokenInfo: null };

function _jlyFmt(u) { return (u / 1e6).toLocaleString(undefined, { maximumFractionDigits: 2 }); }
function _jlyStat(label, val, hint) {
  return `<div style="flex:1;min-width:110px;background:var(--panel2,#0b1120);border:1px solid var(--border,#243049);border-radius:10px;padding:10px 12px;">
    <div style="font-size:.66rem;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;">${label}${hint ? ' ' + hlp(hint) : ''}</div>
    <div style="font-size:1.05rem;font-weight:700;margin-top:2px;">${val}</div></div>`;
}

/* ── tiny SVG chart kit (dataviz-skill spec: thin marks, recessive grid, muted
      text ink, hover tooltip on every plot, one series per chart → no legend) ── */
function _jlyChart(series, ys, { color, fmt, refY = null, refLabel = '' }) {
  const W = 320, H = 120, PL = 44, PR = 8, PT = 8, PB = 18;
  const pts = series.map((s, i) => ({ x: i, y: ys[i], t: s.t, h: s.h }))
                    .filter(p => p.y != null && isFinite(p.y));
  if (pts.length < 2) return `<div style="color:var(--muted);font-size:.74rem;padding:20px 0;">not enough blocks yet</div>`;
  let lo = Math.min(...pts.map(p => p.y)), hi = Math.max(...pts.map(p => p.y));
  if (refY != null) { lo = Math.min(lo, refY); hi = Math.max(hi, refY); }
  if (hi === lo) hi = lo + 1;
  const X = i => PL + (i / (pts.length - 1)) * (W - PL - PR);
  const Y = v => PT + (1 - (v - lo) / (hi - lo)) * (H - PT - PB);
  const path = pts.map((p, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)},${Y(p.y).toFixed(1)}`).join('');
  const grid = [lo, (lo + hi) / 2, hi].map(v =>
    `<line x1="${PL}" y1="${Y(v)}" x2="${W - PR}" y2="${Y(v)}" stroke="var(--border,#2a2f3d)" stroke-width="1"/>
     <text x="${PL - 5}" y="${Y(v) + 3}" text-anchor="end" font-size="8.5" fill="var(--muted)">${fmt(v)}</text>`).join('');
  const tfmt = t => new Date(t * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const ref = refY == null ? '' :
    `<line x1="${PL}" y1="${Y(refY)}" x2="${W - PR}" y2="${Y(refY)}" stroke="var(--muted)" stroke-width="1" stroke-dasharray="4 3"/>
     <text x="${W - PR}" y="${Y(refY) - 3}" text-anchor="end" font-size="8" fill="var(--muted)">${esc(refLabel)}</text>`;
  const data = esc(JSON.stringify(pts.map(p => [p.h, p.y, p.t])));
  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto;display:block;cursor:crosshair"
       data-pts="${data}" data-lo="${lo}" data-hi="${hi}" data-pl="${PL}" data-pr="${PR}"
       onmousemove="_jlyHover(event,this)" onmouseleave="_jlyHoverOff(this)">
    ${grid}${ref}
    <path d="${path}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round"/>
    <circle r="4" fill="${color}" stroke="var(--surface,#161a22)" stroke-width="2" style="display:none"/>
    <text x="${PL}" y="${H - 4}" font-size="8.5" fill="var(--muted)">${tfmt(pts[0].t)}</text>
    <text x="${W - PR}" y="${H - 4}" text-anchor="end" font-size="8.5" fill="var(--muted)">${tfmt(pts[pts.length - 1].t)}</text>
  </svg>`;
}
function _jlyChartInt(v) { return Math.round(v).toLocaleString(); }
function _jlyChartNum(v) { return (Math.abs(v) >= 100 ? Math.round(v) : v.toFixed(1)).toLocaleString(); }

function _jlyHover(ev, svg) {
  const pts = JSON.parse(svg.dataset.pts);
  const r = svg.getBoundingClientRect();
  const PL = +svg.dataset.pl, PR = +svg.dataset.pr;
  const fx = (ev.clientX - r.left) / r.width * 320;
  const i = Math.max(0, Math.min(pts.length - 1,
    Math.round((fx - PL) / (320 - PL - PR) * (pts.length - 1))));
  const [h, y, t] = pts[i];
  const cx = PL + i / (pts.length - 1) * (320 - PL - PR);
  const dot = svg.querySelector('circle');
  const lo = +svg.dataset.lo, hi = +svg.dataset.hi;
  dot.style.display = '';
  dot.setAttribute('cx', cx);
  dot.setAttribute('cy', 8 + (1 - (y - lo) / ((hi - lo) || 1)) * (120 - 8 - 18));
  let tip = svg.parentElement.querySelector('.jly-tip');
  if (!tip) {
    tip = document.createElement('div');
    tip.className = 'jly-tip';
    tip.style.cssText = 'position:absolute;pointer-events:none;background:var(--surface2,#1e2330);border:1px solid var(--border,#2a2f3d);border-radius:6px;padding:4px 8px;font-size:.68rem;color:var(--text,#e2e8f0);white-space:nowrap;z-index:5;';
    svg.parentElement.style.position = 'relative';
    svg.parentElement.appendChild(tip);
  }
  tip.style.display = '';
  tip.textContent = `block ${h} · ${(Math.abs(y) >= 100 ? Math.round(y).toLocaleString() : y.toFixed(1))} · ${new Date(t * 1000).toLocaleTimeString()}`;
  tip.style.left = Math.min(r.width - 130, Math.max(0, (cx / 320) * r.width + 8)) + 'px';
  tip.style.top = '4px';
}
function _jlyHoverOff(svg) {
  svg.querySelector('circle').style.display = 'none';
  const tip = svg.parentElement.querySelector('.jly-tip');
  if (tip) tip.style.display = 'none';
}
window._jlyHover = _jlyHover; window._jlyHoverOff = _jlyHoverOff;

function _jlyBars(perRig) {
  if (!perRig.length) return `<div style="color:var(--muted);font-size:.74rem;padding:20px 0;">no blocks mined yet</div>`;
  const max = Math.max(...perRig.map(r => r.blocks));
  return perRig.map(r => `
    <div style="display:flex;align-items:center;gap:8px;margin:6px 0;" title="${esc(r.miner)}: ${r.blocks} blocks">
      <div style="width:90px;font-size:.72rem;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(r.miner)}</div>
      <div style="flex:1;background:var(--surface,#161a22);border-radius:4px;height:14px;">
        <div style="width:${Math.max(2, r.blocks / max * 100)}%;height:100%;background:#6c63ff;border-radius:4px;"></div>
      </div>
      <div style="font-size:.72rem;color:var(--muted);min-width:40px;text-align:right;">${r.blocks.toLocaleString()}</div>
    </div>`).join('');
}

async function cryptoLoadJelly() {
  const pane = document.getElementById('pane-crypto-jelly');
  let st, wal, tok, nfts, missions, blocks, ws, pb, stats, pool, buddies, mine;
  try {
    [st, wal, tok, nfts, missions, blocks, ws, pb, stats, pool, buddies, mine] = await Promise.all([
      api('/api/jelly/status'), api('/api/jelly/wallets'), api('/api/jelly/miner-token'),
      api('/api/jelly/nft/list'), api('/api/jelly/missions'), api('/api/jelly/blocks?limit=8'),
      api('/api/world/settings').catch(() => ({ settings: {} })),
      api('/api/jelly/peer-billing').catch(() => null),
      api('/api/jelly/stats').catch(() => null),
      api('/api/jelly/pool').catch(() => null),
      api('/api/peers').catch(() => null),
      api('/api/peers/my-wallets').catch(() => null),
    ]);
  } catch (e) {
    pane.innerHTML = `<div class="empty"><div class="empty-icon">&#10060;</div>${esc(e.message)}</div>`;
    return;
  }
  _JLY.st = st;
  const companyOn = String((ws.settings || {}).world_crypto_mining_enabled) === '1';
  const rigs = st.miners || [];
  const paired = ((buddies || {}).peers || []).filter(p => p.status === 'approved');
  _JLY.paired = paired;

  pane.innerHTML = `
    <div class="section-header"><div><div class="section-title">🪼 JellyCoin (${esc(st.symbol)})</div>
      <div class="section-sub">Acme's own token. New JLY exists <b>only</b> when a real GPU solves a proof-of-work
      block — old cards get a second life, and there is deliberately no CPU mining. Community token, not an investment.</div></div>
      <button class="btn-sm" onclick="_cryptoLoaded.jelly=false;cryptoSub('jelly')">&#8635; Refresh</button>
    </div>

    <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px;">
      ${_jlyStat('Height', st.height)}
      ${_jlyStat('Supply', _jlyFmt(st.supply * 1e6) + ' JLY')}
      ${_jlyStat('Difficulty', st.difficulty, 'Relative to genesis (1.0). Auto-retargets toward one block per minute.')}
      ${_jlyStat('Block reward', st.block_reward + ' JLY')}
      ${_jlyStat('GPU rigs online', st.miners_online)}
      ${_jlyStat('Boosts pending', st.boosts_pending, 'Skilling tickets waiting to pay out inside the next mined blocks.')}
      ${_jlyStat('NFTs', st.nft_count)}
    </div>

    ${stats && (stats.series || []).length > 2 ? `<div class="settings-group" style="margin-bottom:16px;">
      <div class="settings-group-title">📊 Network graphs ${hlp('Derived live from the block table. Hover any chart for per-block values. Difficulty retargets every 20 blocks toward the dashed 60-second block goal.')}</div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px;">
        <div><div style="font-size:.72rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;">Difficulty</div>
          ${_jlyChart(stats.series, stats.series.map(s => s.difficulty), { color: '#6c63ff', fmt: _jlyChartInt })}</div>
        <div><div style="font-size:.72rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;">Block interval (sec)</div>
          ${_jlyChart(stats.series, stats.series.map(s => s.interval), { color: '#f59e0b', fmt: _jlyChartInt, refY: stats.target_block_sec, refLabel: 'target ' + stats.target_block_sec + 's' })}</div>
        <div><div style="font-size:.72rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;">Supply (JLY)</div>
          ${_jlyChart(stats.series, stats.series.map(s => s.supply), { color: '#00d4aa', fmt: _jlyChartInt })}</div>
        <div><div style="font-size:.72rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;">Blocks by rig</div>
          ${_jlyBars(stats.per_rig || [])}</div>
      </div>
    </div>` : ''}

    <div class="settings-group" style="margin-bottom:16px;">
      <div class="settings-group-title">⛏️ GPU rigs ${hlp('Any LAN box with an OpenCL GPU can mine — even cards far too old for AI. The miner refuses to run on CPU by design.')}</div>
      ${rigs.length ? `<table class="mini-table" style="width:100%;font-size:.78rem;">
        <tr><th style="text-align:left;">Rig</th><th style="text-align:left;">GPU</th><th>MH/s</th><th>Blocks</th><th></th></tr>
        ${rigs.map(m => `<tr><td>${esc(m.name)}</td><td style="color:var(--muted);">${esc(m.gpu || '?')}</td>
          <td style="text-align:center;">${(m.hashrate / 1e6).toFixed(1)}</td><td style="text-align:center;">${m.blocks}</td>
          <td style="text-align:center;color:${m.online ? 'var(--green)' : 'var(--muted)'};">${m.online ? '● online' : '○ offline'}</td></tr>`).join('')}
      </table>` : `<div style="font-size:.78rem;color:var(--muted);">No rigs yet. Dust off an old graphics card:</div>`}
      <div style="font-size:.76rem;color:var(--muted);line-height:1.8;margin-top:10px;">
        1&#41; On the GPU box: <code>pip install pyopencl numpy requests</code><br>
        2&#41; Download <a href="/api/jelly/mining/miner.py" style="color:var(--accent,#7aa2ff);">jellyminer.py</a> &nbsp;
        3&#41; Run: <code style="word-break:break-all;">${esc(tok.run)}</code>
        <button class="btn-sm" style="margin-left:6px;" onclick="navigator.clipboard.writeText(${JSON.stringify(tok.run)});toast?.('Copied ✓')">📋 Copy</button>
      </div>
    </div>

    <div class="settings-group" style="margin-bottom:16px;">
      <div class="settings-group-title">🏢 Company boosts
        <span style="font-size:.62rem;font-weight:700;background:${companyOn ? 'rgba(34,197,94,.16)' : 'rgba(148,163,184,.16)'};color:${companyOn ? 'var(--green)' : 'var(--muted)'};border-radius:10px;padding:2px 8px;margin-left:8px;text-transform:uppercase;">${companyOn ? 'on' : 'off'}</span>
      </div>
      <div style="font-size:.78rem;color:var(--muted);line-height:1.7;">
        When on, agents' woodcutting / mining / fishing queues boost tickets (${st.boosts_pending} pending,
        ${_jlyFmt(st.boosts_paid_jly * 1e6)} JLY paid so far). Tickets cash out <b>only inside a real GPU-mined
        block</b> — bonus JLY split between the agent and the company wallet. No rig online → nothing mines.
      </div>
      <button class="btn-sm" style="margin-top:8px;" onclick="jellyToggleCompany(${companyOn ? 0 : 1})">
        ${companyOn ? '⏸ Turn off' : '▶ Turn on'} skilling boosts</button>
      <span style="font-size:.7rem;color:var(--muted);margin-left:8px;">(same toggle lives in God Console → Company Settings)</span>
    </div>

    ${pb ? `<div class="settings-group" style="margin-bottom:16px;">
      <div class="settings-group-title">🤝 Buddy compute ${hlp('JLY meters the peer network\'s shared AI helper: a buddy\'s box doing LLM work for us EARNS their peer wallet JLY from the treasury; a buddy running jobs on our node SPENDS theirs. Broke buddies are comped, never blocked. Buddies see their balance via /api/peers/rpc/wallet.')}
        <span style="font-size:.62rem;font-weight:700;background:${pb.enabled ? 'rgba(34,197,94,.16)' : 'rgba(148,163,184,.16)'};color:${pb.enabled ? 'var(--green)' : 'var(--muted)'};border-radius:10px;padding:2px 8px;margin-left:8px;text-transform:uppercase;">${pb.enabled ? 'on' : 'off'}</span>
      </div>
      <div style="font-size:.78rem;color:var(--muted);line-height:1.7;">
        ${(pb.peer_wallets || []).length
          ? 'Buddy balances: ' + pb.peer_wallets.map(p => `<b>${esc(p.name.replace('peer:', ''))}</b> ${_jlyFmt(p.balance)} JLY`).join(' · ')
          : 'No buddy wallets yet — they appear the first time a paired peer runs or lends a job.'}
        ${pb.comped_jobs ? ` · ${pb.comped_jobs} job(s) comped so far` : ''}
      </div>
      <div style="display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap;margin-top:10px;">
        <div class="field" style="margin:0;"><label>JLY per LLM job ${hlp('Embedding jobs cost 1/10th of this.')}</label>
          <input id="jly-pb-price" type="number" step="0.1" min="0" value="${pb.price_jly}" style="width:90px;"></div>
        <button class="btn-sm" onclick="jellyPeerBilling(${pb.enabled ? 'false' : 'true'})">${pb.enabled ? '⏸ Turn off' : '▶ Turn on'} billing</button>
        <button class="btn-sm" onclick="jellyPeerBilling(${pb.enabled})">💾 Save price</button>
      </div>
    </div>` : ''}

    ${mine ? `<div class="settings-group" style="margin-bottom:16px;">
      <div class="settings-group-title">🌐 My wallets on buddies' chains ${hlp('JellyCoin is per-node: each store runs its OWN chain. What you earn on a buddy\'s network — mining shares, code reviews, lending them AI — sits in your wallet on THEIR ledger, not in your Wallets list below. This panel asks each paired buddy for your balance with the key they issued you.')}
        <span style="font-size:.62rem;font-weight:700;background:rgba(148,163,184,.16);color:var(--muted);border-radius:10px;padding:2px 8px;margin-left:8px;">${mine.reachable}/${mine.peers} reachable</span>
      </div>
      ${(mine.wallets || []).length ? `
      <div style="font-size:.78rem;color:var(--muted);line-height:1.7;margin-bottom:8px;">
        Total earned away from home: <b style="color:var(--text);">${Number(mine.total_jly).toLocaleString(undefined, { maximumFractionDigits: 4 })} JLY</b>
        across ${mine.peers} paired ${mine.peers === 1 ? 'buddy' : 'buddies'}.
      </div>
      <table class="mini-table" style="width:100%;font-size:.78rem;">
        <tr><th style="text-align:left;">Buddy's network</th><th style="text-align:left;">My wallet there</th><th style="text-align:right;">Balance</th></tr>
        ${(mine.wallets || []).map(w => `<tr>
          <td>${esc(w.peer)}<div style="font-size:.66rem;color:var(--muted);">${esc(w.base_url || '')}</div></td>
          <td style="color:var(--muted);">${w.ok ? esc(w.wallet || '—') : `<span style="color:var(--muted);">offline — ${esc(w.error || 'unreachable')}</span>`}</td>
          <td style="text-align:right;font-weight:600;">${w.ok ? Number(w.balance_jly).toLocaleString(undefined, { maximumFractionDigits: 4 }) + ' ' + esc(w.symbol) : '—'}</td></tr>`).join('')}
      </table>
      <div style="font-size:.72rem;color:var(--muted);line-height:1.7;margin-top:8px;">
        These are separate chains, not one shared ledger — a balance here can't be spent on your own network.
        It buys AI compute and reviews <i>on that buddy's node</i>.
      </div>`
      : `<div style="font-size:.78rem;color:var(--muted);">No paired buddies yet. Pair one in <b>Settings → Peers</b>, then your balance on their chain shows up here.</div>`}
    </div>` : ''}

    <div class="settings-group" style="margin-bottom:16px;">
      <div class="settings-group-title">🔗 Join a buddy's network ${hlp('Mining on YOUR node mints YOUR coin — a chain of your own. To grow a buddy\'s network instead, point the same miner at THEIR url with a rig token they hand you. Their node then pays your wallet on their chain (see the panel above).')}</div>
      <div style="font-size:.78rem;color:var(--muted);line-height:1.7;">
        Every store runs its own chain, so mining here grows <b>your</b> JLY. Pointing a rig at a buddy's node instead
        makes you a miner on <b>theirs</b> — if they've turned the buddy-share pool on, you earn a proportional cut of
        every block your shares helped find.
      </div>
      <div style="display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap;margin-top:10px;">
        <div class="field" style="margin:0;"><label>Buddy's node ${hlp('Paired buddies from Settings → Peers. Pick "custom" to type any node URL.')}</label>
          <select id="jly-join-peer" onchange="jellyJoinCmd()" style="min-width:150px;">
            ${paired.length ? paired.map(p => `<option value="${esc(p.base_url || '')}">${esc(p.name)}</option>`).join('') : ''}
            <option value="">— custom URL —</option>
          </select></div>
        <div class="field" style="margin:0;flex:1;min-width:170px;"><label>Node URL</label>
          <input id="jly-join-url" oninput="jellyJoinCmd()" placeholder="http://their-host:8787"
                 value="${esc((paired[0] || {}).base_url || '')}"></div>
        <div class="field" style="margin:0;"><label>Their rig token ${hlp('The X-Jelly-Token from THEIR store (Crypto → JellyCoin → Mining). They hand it to you out of band — it only lets you donate hashpower, never read or move their funds.')}</label>
          <input id="jly-join-token" oninput="jellyJoinCmd()" placeholder="paste their token" style="width:150px;"></div>
        <div class="field" style="margin:0;"><label>My rig name ${hlp('Ask them to map this rig to your peer:<name> wallet in their pool panel, so your share of each block lands in your wallet on their chain.')}</label>
          <input id="jly-join-rig" oninput="jellyJoinCmd()" placeholder="rig1" value="rig1" style="width:110px;"></div>
      </div>
      <div style="font-size:.76rem;color:var(--muted);line-height:1.8;margin-top:10px;">
        Run on your GPU box: <code id="jly-join-cmd" style="word-break:break-all;">python3 jellyminer.py --url &lt;their url&gt; --token &lt;their token&gt; --name rig1</code>
        <button class="btn-sm" style="margin-left:6px;" onclick="jellyJoinCopy()">📋 Copy</button>
      </div>
      <div style="font-size:.72rem;color:var(--muted);line-height:1.7;margin-top:8px;">
        Same <a href="/api/jelly/mining/miner.py" style="color:var(--accent,#7aa2ff);">jellyminer.py</a> either way — only
        <code>--url</code> changes. Ask your buddy to map <code>${esc((paired[0] || {}).name ? 'your rig' : 'your rig')}</code>
        to your <code>peer:&lt;name&gt;</code> wallet on their side, or your shares pay their default rig wallet instead of you.
      </div>
    </div>

    ${pool ? `<div class="settings-group" style="margin-bottom:16px;">
      <div class="settings-group-title">🤝 Buddy-Share Mining Pool ${hlp('When ON, every GPU-mined block is split proportionally by the shares each rig contributed this round, instead of winner-take-all. Map a buddy\'s rig to their peer:<name> wallet and their share of every block flows straight to it — the fair way to mine together with the friends you paired in the Peers/federation tab.')}
        <span style="font-size:.62rem;font-weight:700;background:${pool.enabled ? 'rgba(34,197,94,.16)' : 'rgba(148,163,184,.16)'};color:${pool.enabled ? 'var(--green)' : 'var(--muted)'};border-radius:10px;padding:2px 8px;margin-left:8px;text-transform:uppercase;">${pool.enabled ? 'on' : 'off'}</span>
      </div>
      <div style="font-size:.78rem;color:var(--muted);line-height:1.7;">
        <b>${pool.enabled ? 'ON — proportional share split' : 'OFF — winner-take-all mining'}.</b>
        ${pool.enabled
          ? 'Each block\'s reward is divided by the shares every rig submitted this round, then paid to each rig\'s mapped owner wallet.'
          : 'Whoever solves the block keeps its whole reward. Turn this on to share rewards fairly across your buddies\' rigs.'}
      </div>
      <button class="btn-sm" style="margin-top:8px;" onclick="jellyPoolToggle(${pool.enabled ? 'false' : 'true'})">
        ${pool.enabled ? '⏸ Turn off' : '▶ Turn on'} share splitting</button>

      <div style="display:flex;gap:10px;flex-wrap:wrap;margin:14px 0 4px;">
        ${_jlyStat('Round', '#' + pool.round_id)}
        ${_jlyStat('Block reward', pool.block_reward_jly + ' JLY')}
        ${_jlyStat('Share factor', pool.share_factor, 'How many shares a rig is credited per unit of proof-of-work it submits toward the current round.')}
      </div>

      <div style="font-size:.72rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin:12px 0 4px;">Shares this round</div>
      ${(pool.shares_by_rig || []).length ? `<table class="mini-table" style="width:100%;font-size:.78rem;">
        <tr><th style="text-align:left;">Rig</th><th style="text-align:left;">Owner wallet</th><th>Shares</th><th style="text-align:right;">Projected split</th></tr>
        ${(pool.shares_by_rig || []).map(r => `<tr><td>${esc(r.rig)}</td>
          <td style="color:var(--muted);">${esc(r.owner || '—')}</td>
          <td style="text-align:center;">${(r.shares || 0).toLocaleString()}</td>
          <td style="text-align:right;font-weight:600;">${(pool.projected_split || {})[r.owner] != null ? Number((pool.projected_split || {})[r.owner]).toLocaleString(undefined, { maximumFractionDigits: 4 }) + ' JLY' : '—'}</td></tr>`).join('')}
      </table>` : `<div style="font-size:.78rem;color:var(--muted);">No shares yet this round — buddies' rigs will appear here once they mine.</div>`}

      <div style="font-size:.72rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin:14px 0 4px;">Add / map a buddy rig</div>
      <div style="display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap;">
        <div class="field" style="margin:0;"><label>Rig ${hlp('Pick a rig that has already mined, or type the --name a buddy will start their miner with.')}</label>
          <input id="jly-pool-rig" list="jly-pool-riglist" placeholder="rig name" style="width:150px;">
          <datalist id="jly-pool-riglist">${(rigs || []).map(m => `<option value="${esc(m.name)}">`).join('')}</datalist></div>
        <div class="field" style="margin:0;flex:1;min-width:160px;"><label>Owner wallet ${hlp('peer:<buddyName> routes rewards to a paired buddy\'s wallet; miner:<rig> keeps them on your own rig wallet.')}</label>
          <input id="jly-pool-owner" placeholder="peer:willie" value="peer:"></div>
        <button class="btn-sm" onclick="jellyPoolMap()">💾 Save mapping</button>
      </div>
      <div style="font-size:.72rem;color:var(--muted);line-height:1.7;margin-top:8px;">
        A buddy joins by running <code style="word-break:break-all;">jellyminer.py --url http://127.0.0.1:8787 --token &lt;X-Jelly-Token from the Mining section above&gt; --name &lt;rigName&gt;</code>.
        Their rig then shows up here — map it to their <code>peer:&lt;name&gt;</code> wallet (a peer you paired in the Peers/federation tab) and every block's share flows to them.
      </div>

      ${(pool.recent_payouts || []).length ? `
      <div style="font-size:.72rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin:14px 0 4px;">Recent pool payouts</div>
      <table class="mini-table" style="width:100%;font-size:.74rem;">
        <tr><th>#</th><th style="text-align:left;">Owner</th><th style="text-align:right;">JLY</th></tr>
        ${(pool.recent_payouts || []).slice(0, 12).map(p => `<tr><td style="text-align:center;">${p.height}</td>
          <td>${esc(p.dst)}</td><td style="text-align:right;font-weight:600;">${_jlyFmt(p.amount)}</td></tr>`).join('')}
      </table>` : ''}
    </div>` : ''}

    <div class="settings-group" style="margin-bottom:16px;">
      <div class="settings-group-title">👛 Wallets</div>
      <table class="mini-table" style="width:100%;font-size:.78rem;">
        <tr><th style="text-align:left;">Wallet</th><th style="text-align:left;">Kind</th><th style="text-align:right;">Balance</th></tr>
        ${(wal.wallets || []).slice(0, 14).map(w => `<tr><td>${esc(w.name)} ${w.name === 'assistant' ? '🤖' : ''}</td>
          <td style="color:var(--muted);">${esc(w.kind)}</td>
          <td style="text-align:right;font-weight:600;">${_jlyFmt(w.balance)} JLY</td></tr>`).join('')}
      </table>
      <div style="display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap;margin-top:12px;">
        <div class="field" style="margin:0;"><label>From</label><input id="jly-tx-from" placeholder="treasury" style="width:130px;"></div>
        <div class="field" style="margin:0;"><label>To</label><input id="jly-tx-to" placeholder="miner:rig1" style="width:130px;"></div>
        <div class="field" style="margin:0;"><label>JLY</label><input id="jly-tx-amt" type="number" step="0.01" style="width:80px;"></div>
        <div class="field" style="margin:0;flex:1;min-width:120px;"><label>Memo</label><input id="jly-tx-memo"></div>
        <button class="btn-sm" onclick="jellyTransfer()">💸 Send</button>
        <button class="btn-sm" onclick="jellyTip()" title="Send from the AI friend's 'assistant' wallet">🤖 Tip from AI friend</button>
      </div>
    </div>

    <div class="settings-group" style="margin-bottom:16px;">
      <div class="settings-group-title">🖼️ Art NFTs ${hlp('Mints a real art file: its sha256 becomes the on-chain content hash. Fee: 5 JLY to the treasury (treasury mints free).')}</div>
      <div style="display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap;margin-bottom:12px;">
        <div class="field" style="margin:0;flex:2;min-width:220px;"><label>Art file path</label>
          <input id="jly-nft-path" placeholder="designs/…png (from Studio / Library)"></div>
        <div class="field" style="margin:0;flex:1;"><label>Title</label><input id="jly-nft-title"></div>
        <div class="field" style="margin:0;"><label>Owner</label><input id="jly-nft-owner" placeholder="treasury" style="width:110px;"></div>
        <button class="btn-sm" onclick="jellyMintNft()">🪙 Mint</button>
      </div>
      ${(nfts.nfts || []).length ? `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;">
        ${(nfts.nfts || []).slice(0, 12).map(n => `<div style="background:var(--panel2,#0b1120);border:1px solid var(--border,#243049);border-radius:10px;padding:8px;">
          <img src="${thumbUrl(n.file_path)}" onerror="this.style.display='none'" style="width:100%;border-radius:6px;aspect-ratio:1;object-fit:cover;">
          <div style="font-size:.74rem;font-weight:600;margin-top:6px;">${esc(n.title)}</div>
          <div style="font-size:.66rem;color:var(--muted);">owner: ${esc(n.owner)} · #${n.minted_height}</div>
          <div style="font-size:.6rem;color:var(--muted);word-break:break-all;" title="content sha256: ${esc(n.sha256)}">${esc(n.token_id)}</div>
        </div>`).join('')}</div>` : `<div style="font-size:.76rem;color:var(--muted);">Nothing minted yet — pick a Studio artwork you love.</div>`}
    </div>

    <div class="settings-group" style="margin-bottom:16px;">
      <div class="settings-group-title">📣 Push &amp; sell missions ${hlp('The Company drafts JLY promo/perk/sell pitches with the LLM. Every draft waits for YOUR approval — agents never post or sell anything on their own. Approved pitches hit the town feed for agents to talk up.')}</div>
      <div style="display:flex;gap:8px;margin-bottom:10px;">
        <button class="btn-sm" onclick="jellyDraft('promo')">✍️ Draft promo</button>
        <button class="btn-sm" onclick="jellyDraft('perk')">🎁 Draft store perk</button>
        <button class="btn-sm" onclick="jellyDraft('sell')">🤝 Draft sell offer</button>
      </div>
      ${(missions.missions || []).slice(0, 8).map(m => `
        <div style="border:1px solid var(--border,#243049);border-radius:10px;padding:10px 12px;margin-bottom:8px;background:var(--panel2,#0b1120);">
          <div style="display:flex;justify-content:space-between;gap:8px;align-items:center;">
            <div style="font-weight:600;font-size:.82rem;">${esc(m.title)} <span style="color:var(--muted);font-weight:400;">· ${esc(m.kind)} · ${esc(m.agent)}</span></div>
            <div>${m.status === 'proposed'
              ? `<button class="btn-sm" onclick="jellyDecide(${m.id},1)">✅ Approve</button>
                 <button class="btn-sm" onclick="jellyDecide(${m.id},0)">🚫 Reject</button>`
              : `<span style="font-size:.66rem;font-weight:700;text-transform:uppercase;color:${m.status === 'approved' ? 'var(--green)' : 'var(--red)'};">${esc(m.status)}</span>`}</div>
          </div>
          <div style="font-size:.76rem;color:var(--muted);white-space:pre-wrap;margin-top:6px;">${esc(m.pitch)}</div>
        </div>`).join('') || `<div style="font-size:.76rem;color:var(--muted);">No missions yet.</div>`}
    </div>

    <div class="settings-group" style="margin-bottom:16px;">
      <div class="settings-group-title">📜 Docs, security &amp; backups ${hlp('The white paper defines the coin (PoW spec, tokenomics, what it is and is not); the security doc covers the rig-token protocol, work integrity, and the incident playbook. Chain state lives in the store DB, so Settings → Backups snapshots cover it; the rig token ships in the Crypto key-backup zip.')}</div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;">
        <button class="btn-sm" onclick="jellyShowDoc('whitepaper','📜 JellyCoin White Paper')">📜 White paper</button>
        <button class="btn-sm" onclick="jellyShowDoc('security','🛡️ Security protocols & backups')">🛡️ Security &amp; backups</button>
        <a class="btn-sm" style="text-decoration:none;" href="https://github.com/youruser/jellycoin-core" target="_blank">🌐 Public core repo</a>
      </div>
      <div id="jly-doc-panel" style="display:none;margin-top:12px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
          <div id="jly-doc-title" style="font-weight:700;font-size:.85rem;"></div>
          <button class="btn-sm" onclick="document.getElementById('jly-doc-panel').style.display='none'">✕ Close</button>
        </div>
        <pre id="jly-doc-body" style="white-space:pre-wrap;font-size:.74rem;line-height:1.6;color:var(--text);background:var(--surface,#161a22);border:1px solid var(--border,#2a2f3d);border-radius:10px;padding:14px;max-height:420px;overflow-y:auto;"></pre>
      </div>
    </div>

    <div class="settings-group">
      <div class="settings-group-title">⛓️ Recent blocks</div>
      <table class="mini-table" style="width:100%;font-size:.74rem;">
        <tr><th>#</th><th style="text-align:left;">Hash</th><th style="text-align:left;">Miner</th><th>Reward</th><th>Boost</th></tr>
        ${(blocks.blocks || []).map(b => `<tr><td style="text-align:center;">${b.height}</td>
          <td style="font-family:monospace;color:var(--muted);">${esc(b.hash.slice(0, 20))}…</td>
          <td>${esc(b.miner)}</td><td style="text-align:center;">${_jlyFmt(b.reward)}</td>
          <td style="text-align:center;">${b.boost ? _jlyFmt(b.boost) : '—'}</td></tr>`).join('')}
      </table>
    </div>`;

  jellyJoinCmd();   // fill the join command from the pre-selected buddy
}
window.cryptoLoadJelly = cryptoLoadJelly;

function _jlyReload() { _cryptoLoaded.jelly = false; cryptoSub('jelly'); }

async function jellyToggleCompany(on) {
  try {
    await api('/api/world/settings', { method: 'POST', body: JSON.stringify({ settings: { world_crypto_mining_enabled: String(on) } }) });
    toast?.(on ? 'Company skilling now boosts GPU mining ⛏️' : 'Skilling boosts off');
    _jlyReload();
  } catch (e) { toast?.(e.message); }
}
window.jellyToggleCompany = jellyToggleCompany;

async function jellyShowDoc(name, title) {
  try {
    const r = await fetch(API + '/api/jelly/doc/' + name);   // same base the api() helper uses
    if (!r.ok) throw new Error('doc fetch failed: ' + r.status);
    document.getElementById('jly-doc-title').textContent = title;
    document.getElementById('jly-doc-body').textContent = await r.text();
    document.getElementById('jly-doc-panel').style.display = '';
    document.getElementById('jly-doc-panel').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  } catch (e) { toast?.(e.message); }
}
window.jellyShowDoc = jellyShowDoc;

async function jellyPeerBilling(enabled) {
  const body = { enabled: !!enabled,
    price_jly: parseFloat(document.getElementById('jly-pb-price')?.value || '1') };
  try {
    await api('/api/jelly/peer-billing', { method: 'POST', body: JSON.stringify(body) });
    toast?.('Buddy compute billing saved ✓'); _jlyReload();
  } catch (e) { toast?.(e.message); }
}
window.jellyPeerBilling = jellyPeerBilling;

async function jellyPoolToggle(enabled) {
  try {
    await api('/api/jelly/pool', { method: 'POST', body: JSON.stringify({ enabled: !!enabled }) });
    toast?.(enabled ? 'Buddy-share pool ON — blocks split by shares 🤝' : 'Pool off — back to winner-take-all');
    _jlyReload();
  } catch (e) { toast?.(e.message); }
}
window.jellyPoolToggle = jellyPoolToggle;

async function jellyPoolMap() {
  const rig = document.getElementById('jly-pool-rig')?.value.trim();
  const owner = document.getElementById('jly-pool-owner')?.value.trim();
  if (!rig || !owner) { toast?.('Give a rig name and an owner wallet'); return; }
  try {
    await api('/api/jelly/pool', { method: 'POST', body: JSON.stringify({ owners: { [rig]: owner } }) });
    toast?.(`Mapped ${rig} → ${owner} ✓`); _jlyReload();
  } catch (e) { toast?.(e.message); }
}
window.jellyPoolMap = jellyPoolMap;

// ── Join a buddy's network: build the miner command for THEIR node ───────────
// The rig token is theirs to hand out (it only donates hashpower), so we never
// fetch it — the user pastes what their buddy gave them.
function _jellyJoinCmdText() {
  const url = (document.getElementById('jly-join-url')?.value || '').trim();
  const token = (document.getElementById('jly-join-token')?.value || '').trim();
  const rig = (document.getElementById('jly-join-rig')?.value || '').trim() || 'rig1';
  return `python3 jellyminer.py --url ${url || '<their url>'} `
       + `--token ${token || '<their token>'} --name ${rig}`;
}

function jellyJoinCmd() {
  const sel = document.getElementById('jly-join-peer');
  const urlBox = document.getElementById('jly-join-url');
  // picking a paired buddy fills the URL; "custom" leaves whatever is typed
  if (sel && urlBox && document.activeElement === sel && sel.value) urlBox.value = sel.value;
  const el = document.getElementById('jly-join-cmd');
  if (el) el.textContent = _jellyJoinCmdText();
}
window.jellyJoinCmd = jellyJoinCmd;

function jellyJoinCopy() {
  navigator.clipboard.writeText(_jellyJoinCmdText());
  toast?.('Copied ✓ — run it on the GPU box');
}
window.jellyJoinCopy = jellyJoinCopy;

async function jellyTransfer(fromOverride) {
  const from = fromOverride || document.getElementById('jly-tx-from').value.trim();
  const body = { from, to: document.getElementById('jly-tx-to').value.trim(),
    amount_jly: parseFloat(document.getElementById('jly-tx-amt').value || '0'),
    memo: document.getElementById('jly-tx-memo').value.trim() };
  try {
    await api('/api/jelly/transfer', { method: 'POST', body: JSON.stringify(body) });
    toast?.('Sent ✓'); _jlyReload();
  } catch (e) { toast?.(e.message); }
}
window.jellyTransfer = jellyTransfer;

async function jellyTip() {
  const body = { to: document.getElementById('jly-tx-to').value.trim(),
    amount_jly: parseFloat(document.getElementById('jly-tx-amt').value || '0'),
    memo: document.getElementById('jly-tx-memo').value.trim() || 'tip from your AI friend' };
  try {
    await api('/api/jelly/tip', { method: 'POST', body: JSON.stringify(body) });
    toast?.('AI friend tipped ✓ 🤖'); _jlyReload();
  } catch (e) { toast?.(e.message); }
}
window.jellyTip = jellyTip;

async function jellyMintNft() {
  const body = { file_path: document.getElementById('jly-nft-path').value.trim(),
    title: document.getElementById('jly-nft-title').value.trim(),
    owner: document.getElementById('jly-nft-owner').value.trim() || 'treasury' };
  if (!body.file_path) { toast?.('Give it an art file path'); return; }
  try {
    const r = await api('/api/jelly/nft/mint', { method: 'POST', body: JSON.stringify(body) });
    toast?.(`Minted ${r.token_id} ✓`); _jlyReload();
  } catch (e) { toast?.(e.message); }
}
window.jellyMintNft = jellyMintNft;

async function jellyDraft(kind) {
  try {
    toast?.('Drafting with the LLM…');
    await api('/api/jelly/missions/draft', { method: 'POST', body: JSON.stringify({ kind }) });
    _jlyReload();
  } catch (e) { toast?.(e.message); }
}
window.jellyDraft = jellyDraft;

async function jellyDecide(id, approve) {
  try {
    await api(`/api/jelly/missions/${id}/decide`, { method: 'POST', body: JSON.stringify({ approve: !!approve }) });
    toast?.(approve ? 'Mission approved — the town hears about it 📣' : 'Mission rejected');
    _jlyReload();
  } catch (e) { toast?.(e.message); }
}
window.jellyDecide = jellyDecide;
