'use strict';

/* ── STATS ── */
async function loadStats() {
  try {
    const s = await api('/api/stats');
    const map = {
      'badge-proposals': s.proposals_pending || 0,
      'badge-review':    s.review_count      || 0,
      'badge-approved':  s.approved_count    || 0,
      'badge-published': s.published_count   || 0,
    };
    for (const [id, val] of Object.entries(map)) {
      const el = document.getElementById(id);
      if (el) el.textContent = val;
    }
    // Etsy/Printify nav badge: show proposals pending (most urgent)
    const epBadge = document.getElementById('badge-ep');
    if (epBadge) {
      const tot = (s.proposals_pending || 0);
      epBadge.textContent = tot;
      epBadge.style.display = tot > 0 ? '' : 'none';
    }
    const ids = ['stat-proposals','stat-review','stat-approved','stat-live'];
    const vals = [s.proposals_pending||0, s.review_count||0, s.approved_count||0, s.published_count||0];
    ids.forEach((id,i) => { const el = document.getElementById(id); if (el) el.textContent = vals[i]; });
  } catch {}
}

/* ══ DASHBOARD ══ */
async function renderDashboard() {
  const [statsR, gensR, jobsR, portalR, homelabR] = await Promise.allSettled([
    api('/api/stats'),
    api('/api/generations?status=generating'),
    api('/api/github/jobs'),
    api('/api/portal/status'),
    api('/api/homelab/services'),
  ]);
  const s     = statsR.value || {};
  const gens  = gensR.value || [];
  const jobs  = jobsR.value || [];
  const portal= portalR.value || {};
  const hl    = homelabR.value || null;

  // dev-swarm rollup
  const WORKING = ['planning','coding','reviewing','testing'];
  const NEEDS   = ['awaiting_input','awaiting_review','awaiting_system'];
  const jStat = (arr) => jobs.filter(j => arr.includes(j.status)).length;
  const jNeed = jStat(NEEDS), jWork = jStat(WORKING), jDone = jStat(['done']);
  // services rollup
  let svcUp = 0, svcTot = 0;
  if (hl) hl.groups.forEach(g => g.services.forEach(x => { if (x.source==='docker'){ svcTot++; if (x.running) svcUp++; } }));

  const stat = (icon,label,val,cls,view) =>
    `<div class="stat-card" ${view?`style="cursor:pointer" onclick="switchView('${view}')"`:''}>
       <div class="stat-label">${icon} ${label}</div><div class="stat-val ${cls}">${val}</div></div>`;

  let h = `
    <div class="view-header">
      <div class="view-title">Dashboard</div>
      <div class="view-sub">Your platform at a glance — store, dev swarm, media, and services.</div>
    </div>
    <div class="stats-row" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr));">
      ${stat('&#128722;','Store products', portal.connected ? (portal.total_products ?? '—') : 'off', 'c-accent2', 'portal')}
      ${stat('&#129302;','Swarm — needs you', jNeed, jNeed?'c-warn':'c-accent', 'github')}
      ${stat('&#9889;','Generating now', gens.length, gens.length?'c-warn':'c-accent', null)}
      ${stat('&#128268;','Services up', hl?`${svcUp}/${svcTot}`:'—', 'c-green', 'homelab')}
      ${stat('&#128717;','POD live', s.published_count||0, 'c-accent2', 'published')}
    </div>`;

  // Dev swarm strip
  h += `<div class="section-header"><div><div class="section-title">&#129302; Dev Swarm</div>
        <div class="section-sub">${jobs.length} jobs · ${jWork} working · ${jNeed} need you · ${jDone} done</div></div>
        <button class="btn-sm" onclick="switchView('github')">Open board &rarr;</button></div>`;
  if (jNeed) {
    const need = jobs.filter(j=>NEEDS.includes(j.status)).slice(0,4);
    h += `<div style="display:flex;flex-direction:column;gap:6px;margin-bottom:20px;">`;
    for (const j of need) h += `<div class="gen-bar" style="cursor:pointer" onclick="switchView('github')">
      <div class="gen-bar-pulse" style="background:var(--warn)"></div>
      <div class="gen-bar-label">${esc(j.title)}</div><div class="gen-bar-model">${esc(j.status)}</div></div>`;
    h += `</div>`;
  } else {
    h += `<div style="color:var(--muted);font-size:.82rem;margin-bottom:20px;">Nothing awaiting you.${jobs.length?'':' Propose a job to get the swarm working.'}</div>`;
  }

  // Generating now
  if (gens.length) {
    h += `<div class="section-header"><div class="section-title">&#9889; Generating Now</div></div><div class="gen-bars">`;
    for (const g of gens)
      h += `<div class="gen-bar"><div class="gen-bar-pulse"></div><div class="gen-bar-label">${esc((g.prompt||'').slice(0,80))}</div><div class="gen-bar-model">${esc(g.model||'')}</div></div>`;
    h += `</div>`;
  }

  // Storefront + POD summary
  h += `<div class="section-header"><div><div class="section-title">&#128722; Storefront</div>
        <div class="section-sub">${portal.connected?`WordPress connected · ${portal.total_products??'?'} products`:'WordPress not connected'} ·
        POD: ${s.review_count||0} in review, ${s.approved_count||0} approved</div></div></div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px;">
          <button class="btn-sm" onclick="switchView('portal')">&#127760; Portal &rarr; WordPress</button>
          <button class="btn-sm" onclick="switchView('etsy-printify')">&#128717; Etsy / Printify</button>
          <button class="btn-sm" onclick="switchView('cults3d')">&#128424;&#65039; Cults3D</button>
          <button class="btn-sm" onclick="switchView('resell')">&#128247; Resell</button>
        </div>`;

  // Quick actions
  h += `<div class="section-header"><div class="section-title">&#9193; Quick actions</div></div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <button class="btn-sm primary" onclick="switchView('image-gen')">&#127912; Generate image</button>
          <button class="btn-sm" onclick="switchView('videos')">&#127916; Video</button>
          <button class="btn-sm" onclick="switchView('audio')">&#127925; Audio</button>
          <button class="btn-sm" onclick="switchView('models3d')">&#127981; 3D</button>
          <button class="btn-sm" onclick="switchView('github')">&#129302; New swarm job</button>
          <button class="btn-sm" onclick="switchView('homelab')">&#128268; Services</button>
        </div>`;

  document.getElementById('main-content').innerHTML = h;
}

/* ══ STORE STATS ══ */
async function renderStoreStats() {
  _setContent(`
    <div class="view-header">
      <div class="view-title">&#128200; Store Stats</div>
      <div class="view-sub">Live data from Printify &amp; Etsy</div>
      <button class="btn-sm" onclick="renderStoreStats()">&#8635; Refresh</button>
    </div>
    <div id="stats-body" style="padding:0 4px;"><div style="color:var(--muted);margin-top:20px;text-align:center;">&#8987; Loading&hellip;</div></div>`);
  try {
    const st = await api('/api/store-stats');
    let h = '';

    // ── Printify ────────────────────────────────────────────────
    h += `<div class="settings-group"><div class="settings-group-title">&#128640; Printify</div>`;
    if (st.error?.printify) {
      h += `<div style="color:var(--error);font-size:.8rem;">Error: ${esc(st.error.printify)}</div>`;
    } else if (!st.printify) {
      h += `<div style="color:var(--muted);font-size:.8rem;">Not configured — add Printify API key in Settings.</div>`;
    } else {
      const p = st.printify;
      h += `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:10px;margin-top:6px;">`;
      h += statCard('&#128230; Products Live', p.live_products);
      h += statCard('&#128196; Drafts',         p.draft_products);
      h += statCard('&#128666; Recent Orders',   p.recent_orders);
      h += statCard('&#9201;&#65039; Pending',    p.pending_orders);
      h += statCard('&#9989; Fulfilled',          p.fulfilled_orders);
      h += `</div>`;
    }
    h += `</div>`;

    // ── Etsy ────────────────────────────────────────────────────
    h += `<div class="settings-group"><div class="settings-group-title">&#128717; Etsy</div>`;
    if (st.error?.etsy) {
      h += `<div style="color:var(--error);font-size:.8rem;">Error: ${esc(st.error.etsy)}</div>`;
    } else if (!st.etsy) {
      h += `<div style="color:var(--muted);font-size:.8rem;">Not connected — authorize Etsy in Settings.</div>`;
    } else {
      const e = st.etsy;
      h += `<div style="font-size:.8rem;color:var(--muted);margin-bottom:8px;">Shop: <b style="color:var(--text);">${esc(e.shop_name)}</b></div>`;
      h += `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:10px;margin-bottom:12px;">`;
      h += statCard('&#128717; Active Listings', e.listing_count);
      h += statCard('&#128065;&#65039; Total Views',   e.total_views);
      h += statCard('&#10084;&#65039; Favorites',      e.total_favorites);
      h += statCard('&#128181; Sales',                e.transaction_sold_count);
      h += statCard('&#11088; Avg Review',             e.review_average ? e.review_average.toFixed(1) : '—');
      h += `</div>`;

      if (e.top_listings && e.top_listings.length) {
        h += `<div style="font-size:.78rem;font-weight:600;margin-bottom:6px;color:var(--text);">&#128293; Top Listings by Views</div>`;
        h += `<div style="display:flex;flex-direction:column;gap:5px;">`;
        for (const l of e.top_listings) {
          h += `<div style="display:flex;justify-content:space-between;align-items:center;padding:5px 8px;background:var(--surface);border-radius:6px;font-size:.75rem;">`;
          h += `<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(l.title||'').slice(0,60)}</span>`;
          h += `<span style="color:var(--muted);white-space:nowrap;margin-left:12px;">&#128065;&#65039; ${l.views||0} &nbsp;&#10084;&#65039; ${l.num_favorers||0}</span>`;
          h += `<a href="https://etsy.com/listing/${l.listing_id}" target="_blank" rel="noopener" style="color:var(--accent);font-size:.7rem;margin-left:10px;">&#8599;</a>`;
          h += `</div>`;
        }
        h += `</div>`;
      }
    }
    h += `</div>`;

    document.getElementById('stats-body').innerHTML = h;
  } catch(e) {
    document.getElementById('stats-body').innerHTML = `<div style="color:var(--error);margin-top:20px;">${esc(e.message)}</div>`;
  }
}
