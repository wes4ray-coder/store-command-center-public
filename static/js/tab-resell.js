/* Restored from pre_unification_backup (Jul 9) — real tab implementation.
   Part of the modular frontend: one file per tab. */
let _resellSubTab = 'new';
let _resellListingDraft = {};   // holds in-progress new listing data

async function renderResell() {
  const main = document.getElementById('main-content');
  if (!main) return;
  // Fetch monitoring status for badge
  let monStatus = {active_listings:0, unread_offers:0};
  try { monStatus = await api('/api/resell/monitor/status'); } catch {}

  const tabs = [
    { id:'new',      label:'🆕 New Listing' },
    { id:'listings', label:'📋 Listings' },
    { id:'offers',   label:'💬 Offers', badge: monStatus.unread_offers || 0 },
    { id:'prefs',    label:'⚙️ Preferences' },
  ];
  const tabBar = tabs.map(t => {
    const badge = t.badge ? `<span class="subtab-badge warn">${t.badge}</span>` : '';
    return `<div class="subtab${_resellSubTab===t.id?' active':''}" data-rs-tab="${t.id}">${t.label}${badge}</div>`;
  }).join('');

  const monBadge = monStatus.active_listings
    ? `<span style="background:var(--green);color:#000;border-radius:8px;padding:2px 8px;font-size:.7rem;font-weight:700;margin-left:8px;">👁 Monitoring ${monStatus.active_listings} listing${monStatus.active_listings>1?'s':''}</span>`
    : '';

  main.innerHTML = `
    <div class="view-title">&#128247; Resell${monBadge}</div>
    <div class="view-sub">Photo → AI ID + price research → post to Facebook, OfferUp, Craigslist &amp; more → monitor offers → get paid</div>
    <div class="subtab-bar">${tabBar}</div>
    <div id="rs-content"></div>`;

  main.querySelectorAll('[data-rs-tab]').forEach(el => {
    el.addEventListener('click', async () => {
      _resellSubTab = el.dataset.rsTab;
      main.querySelectorAll('[data-rs-tab]').forEach(x => x.classList.toggle('active', x.dataset.rsTab === _resellSubTab));
      await _renderResellSub(_resellSubTab);
    });
  });
  await _renderResellSub(_resellSubTab);
}

async function _renderResellSub(sub) {
  const ct = document.getElementById('rs-content');
  if (!ct) return;
  if      (sub === 'new')      renderResellNew(ct);
  else if (sub === 'listings') await renderResellListings(ct, '');
  else if (sub === 'offers')   await renderResellOffers(ct);
  else if (sub === 'prefs')    await renderResellPrefs(ct);
}

function resellCard(r) {
  const plats = (() => { try { return JSON.parse(r.platforms||'{}'); } catch { return {}; } })();
  const badges = Object.keys(plats).filter(p=>plats[p]?.status==='posted').map(p =>
    `<span style="background:var(--green);color:#000;border-radius:4px;padding:1px 6px;font-size:.65rem;font-weight:700;">${p}</span>`
  ).join(' ');
  const price = r.asking_price ? `$${parseFloat(r.asking_price).toFixed(2)}` : '—';
  const minPrice = r.min_accept_price ? ` (min $${parseFloat(r.min_accept_price).toFixed(2)})` : '';
  const shipIcon = {never:'🚫',pickup_only:'🏠',possible:'📬'}[r.shipping_policy||'pickup_only'];
  const modeIcon = {firm:'🔒',obo:'🤝',haggle:'💬'}[r.price_mode||'obo'];
  // Status badge
  const statusBadge = r.status === 'sold'
    ? `<span style="background:var(--green);color:#000;border-radius:4px;padding:1px 8px;font-size:.65rem;font-weight:700;">✅ SOLD</span>`
    : r.status === 'listed'
    ? `<span style="background:var(--accent);color:#fff;border-radius:4px;padding:1px 8px;font-size:.65rem;font-weight:700;">📢 LISTED</span>`
    : '';
  // Photo
  const _photoOrig = r.primary_photo ? `/store/static/${esc(r.primary_photo)}` : '';
  const _photoSrc  = (r.primary_photo && String(r.primary_photo).includes('resell_uploads'))
    ? esc(window.thumbAny('static/' + r.primary_photo, 400)) : _photoOrig;
  const photo = r.primary_photo
    ? `<img src="${_photoSrc}" data-full="${_photoOrig}" loading="lazy" decoding="async" style="width:100%;height:140px;object-fit:cover;" onerror="if(!this.dataset.fb){this.dataset.fb=1;this.src=this.dataset.full;}else{this.onerror=null;this.parentElement.innerHTML='<div style=height:140px;display:flex;align-items:center;justify-content:center;font-size:2rem;background:var(--surface)>'+'\ud83d\udcf7'+'</div>';}">`
    : `<div style="height:140px;background:var(--surface);display:flex;align-items:center;justify-content:center;font-size:2.5rem;">📷</div>`;
  // Defects / included hints
  const defectLine = r.known_defects ? `<div style="font-size:.7rem;color:var(--warn);margin-top:2px;">⚠️ ${esc(r.known_defects)}</div>` : '';
  const inclLine   = r.whats_included ? `<div style="font-size:.7rem;color:var(--muted);margin-top:1px;">✅ ${esc(r.whats_included)}</div>` : '';
  return `<div style="background:var(--surface2);border-radius:10px;border:1px solid var(--border);overflow:hidden;display:flex;flex-direction:column;">
    ${photo}
    <div style="padding:12px;flex:1;display:flex;flex-direction:column;gap:4px;">
      <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:6px;">
        <div style="font-weight:700;font-size:.88rem;">${esc(r.title)}</div>
        ${statusBadge}
      </div>
      <div style="color:var(--muted);font-size:.74rem;">${esc(r.condition||'')} · ${esc(r.category||'')}</div>
      <div style="display:flex;gap:6px;align-items:baseline;">
        <span style="font-size:1.1rem;font-weight:800;color:var(--accent);">${price}</span>
        <span style="font-size:.72rem;color:var(--muted);">${minPrice} ${modeIcon} ${shipIcon}</span>
      </div>
      ${defectLine}${inclLine}
      ${badges ? `<div style="margin-top:2px;">${badges}</div>` : ''}
      <div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:6px;">
        <button class="btn-sm rs-copy-btn" data-id="${r.id}" data-platform="facebook" style="font-size:.68rem;padding:3px 7px;">FB</button>
        <button class="btn-sm rs-copy-btn" data-id="${r.id}" data-platform="offerup" style="font-size:.68rem;padding:3px 7px;">OfferUp</button>
        <button class="btn-sm rs-copy-btn" data-id="${r.id}" data-platform="craigslist" style="font-size:.68rem;padding:3px 7px;">CL</button>
        <button class="btn-sm rs-copy-btn" data-id="${r.id}" data-platform="mercari" style="font-size:.68rem;padding:3px 7px;">Mercari</button>
      </div>
      <div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:4px;">
        ${r.status !== 'sold' ? `<button class="btn-sm rs-sold-btn" data-id="${r.id}" style="font-size:.68rem;padding:3px 7px;background:var(--green);color:#000;">✅ Mark Sold</button>` : ''}
        <button class="btn-sm rs-edit-btn" data-id="${r.id}" style="font-size:.68rem;padding:3px 7px;">✏️ Edit</button>
        <button class="btn-sm rs-delete-btn" data-id="${r.id}" style="font-size:.68rem;padding:3px 7px;background:#c0392b;color:#fff;">🗑</button>
      </div>
    </div>
  </div>`;
}
