'use strict';

/* ══ PROPOSALS ══ */
async function renderProposals() {
  const list = await api('/api/proposals?status=pending');
  let h = `<div class="view-header"><div class="view-title">&#128161; Proposals</div><div class="view-sub">${list.length} pending</div></div>`;
  if (!list.length) {
    h += `<div class="empty"><div class="empty-icon">&#128161;</div>No pending proposals. Scan trends to generate more!</div>`;
  } else {
    h += `<div class="proposals-grid">`;
    for (const p of list) h += proposalCardHTML(p);
    h += `</div>`;
  }
  _setContent(h);
}

/* ══ REVIEW ══ */
async function renderReview() {
  const list = await api('/api/designs?status=review');
  let h = `<div class="view-header"><div class="view-title">&#128269; Review Queue</div><div class="view-sub">${list.length} designs awaiting review</div></div>`;
  if (!list.length) {
    h += `<div class="empty"><div class="empty-icon">&#128269;</div>No designs in review. Generate some designs first!</div>`;
  } else {
    h += `<div class="review-grid">`;
    for (const d of list) h += imageCardHTML(d);
    h += `</div>`;
  }
  _setContent(h);
}

/* ══ APPROVED ══ */
async function renderApproved() {
  const list = await api('/api/designs?status=approved');
  let h = `<div class="view-header"><div class="view-title">&#9989; Approved Designs</div><div class="view-sub">${list.length} ready to publish</div></div>`;
  if (!list.length) {
    h += `<div class="empty"><div class="empty-icon">&#9989;</div>No approved designs yet. Review and approve designs first!</div>`;
  } else {
    h += `<div class="approved-shelf">`;
    for (const d of list) h += approvedCardHTML(d);
    h += `</div>`;
  }
  _setContent(h);
}

/* ══ PUBLISHED ══ */
async function renderPublished() {
  const list = await api('/api/designs?status=published');
  let h = `<div class="view-header" style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px;">
    <div><div class="view-title">&#128717; Published</div><div class="view-sub">${list.length} designs live</div></div>
    <button class="btn-sm" onclick="showPrintifyImages()">&#128247; Printify Images</button>
  </div>`;
  if (!list.length) {
    h += `<div class="empty"><div class="empty-icon">&#128717;</div>Nothing published yet. Approve and publish your first design!</div>`;
  } else {
    h += `<div class="published-grid">`;
    for (const d of list) h += publishedCardHTML(d);
    h += `</div>`;
  }
  _setContent(h);
}

/* ── CARD HTML HELPERS ── */
function proposalCardHTML(p) {
  return `<div class="proposal-card" data-id="${p.id}">
    <div class="proposal-title">${esc(p.title)}</div>
    ${p.source ? `<span class="proposal-source">&#128204; ${esc(p.source)}</span>` : ''}
    <div class="proposal-desc">${esc((p.description||'').slice(0,150))}</div>
    ${p.tags ? `<div class="proposal-tags">&#127991;&#65039; ${esc(p.tags)}</div>` : ''}
    <div class="proposal-actions">
      <button class="btn-sm primary" data-action="approve-proposal" data-id="${p.id}">&#10003; Approve</button>
      <button class="btn-sm" data-action="reject-proposal" data-id="${p.id}">&#10005; Skip</button>
    </div>
  </div>`;
}

function imageCardHTML(d) {
  const url     = imgUrl(d.image_path);
  const title   = d.proposal_title || (d.prompt||'').slice(0,40) || `Design #${d.id}`;
  const caption = encodeURIComponent(d.prompt || title);
  return `<div class="image-card" data-id="${d.id}">
    ${url
      ? `<img src="${thumbUrl(d.image_path)}" alt="" data-lb="${url}" data-lb-caption="${caption}" loading="lazy" decoding="async" onerror="this.onerror=null;this.src='${url}'">`
      : `<div class="img-placeholder">&#127912;</div>`}
    <div class="image-card-info">
      <div class="image-card-title" title="${esc(title)}">${esc(title)}</div>
      <div class="image-card-meta">${esc(d.product_type||'T-Shirt')} &middot; #${d.id}</div>
      <div class="image-card-actions">
        <button class="btn-sm success" data-action="approve-design" data-id="${d.id}" title="Approve (one-click)">&#10003;</button>
        <button class="btn-sm" data-action="regen-design" data-id="${d.id}" data-prompt="${esc(d.prompt||'')}" title="Edit &amp; Regen">&#9998;&#65039;</button>
        <button class="btn-sm" data-action="make-collection" data-id="${d.id}" title="Make a matching collection — variants that share this design's layout/pose (ControlNet)">&#127912;</button>
        <button class="btn-sm" data-action="reject-design" data-id="${d.id}" title="Reject">&#10005;</button>
        <button class="btn-sm danger" data-action="delete-design" data-id="${d.id}" title="Delete">&#128465;&#65039;</button>
      </div>
    </div>
  </div>`;
}

function approvedCardHTML(d) {
  const url     = imgUrl(d.image_path);
  const title   = d.proposal_title || (d.prompt||'').slice(0,30) || `Design #${d.id}`;
  const caption = encodeURIComponent(d.prompt || title);
  const tEnc    = encodeURIComponent(d.proposal_title||'');
  const dEnc    = encodeURIComponent(d.proposal_description||'');
  const tagsEnc = encodeURIComponent(d.proposal_tags||'');
  return `<div class="approved-card" data-id="${d.id}">
    ${url
      ? `<img src="${thumbUrl(d.image_path)}" alt="" data-lb="${url}" data-lb-caption="${caption}" loading="lazy" decoding="async" onerror="this.onerror=null;this.src='${url}'">`
      : `<div class="img-placeholder">&#127912;</div>`}
    <div class="approved-card-info">
      <div class="approved-card-title" title="${esc(title)}">${esc(title)}</div>
      <div class="approved-card-type">${esc(d.product_type||'T-Shirt')}</div>
      <div class="approved-card-actions">
        <button class="btn-sm primary" data-action="publish-printify" data-id="${d.id}" data-title="${tEnc}" data-desc="${dEnc}" data-tags="${tagsEnc}" data-published-types="${encodeURIComponent(JSON.stringify(d.published_types||[]))}">${(d.published_types||[]).length ? '&#43; Printify' : '&rarr; Printify'}</button>
        <button class="btn-sm" data-action="publish-etsy" data-id="${d.id}" data-title="${tEnc}" data-tags="${tagsEnc}" data-printify-id="${d.printify_id||''}" data-etsy-id="${d.etsy_listing_id||''}">&#128717; Etsy</button>
        <button class="btn-sm danger" data-action="delete-design" data-id="${d.id}">&#128465;&#65039;</button>
      </div>
    </div>
  </div>`;
}

function publishedCardHTML(d) {
  const url      = imgUrl(d.image_path);
  const title    = d.proposal_title || (d.prompt||'').slice(0,30) || `Design #${d.id}`;
  const caption  = encodeURIComponent(d.prompt || title);
  const pubTypes = (d.published_types||[]).join(', ') || esc(d.product_type||'');
  const tEnc     = encodeURIComponent(title);
  const descEnc  = encodeURIComponent(d.description || d.prompt || '');
  return `<div class="published-card" data-id="${d.id}">
    ${url
      ? `<img src="${thumbUrl(d.image_path)}" alt="" data-lb="${url}" data-lb-caption="${caption}" loading="lazy" decoding="async" onerror="this.onerror=null;this.src='${url}'">`
      : `<div class="img-placeholder">&#127912;</div>`}
    <div class="published-card-info">
      <div class="published-card-title">${esc(title)}</div>
      <div style="font-size:.68rem;color:var(--muted);margin-bottom:4px;">${pubTypes}</div>
      <div class="published-card-links">
        ${d.printify_id ? `<a href="https://printify.com" target="_blank" rel="noopener">Printify &#8599;</a>` : ''}
        ${d.etsy_listing_id ? `<a href="https://etsy.com/listing/${d.etsy_listing_id}" target="_blank" rel="noopener">Etsy &#8599;</a>` : ''}
      </div>
      <div style="margin-top:5px;display:flex;gap:4px;flex-wrap:wrap;">
        <button class="btn-sm" style="font-size:.65rem;" data-action="edit-listing"
          data-id="${d.id}"
          data-title="${tEnc}"
          data-desc="${descEnc}"
          data-printify-id="${d.printify_id||''}"
          data-etsy-id="${d.etsy_listing_id||''}">&#9998; Edit</button>
        ${d.printify_id ? `<button class="btn-sm danger" style="font-size:.65rem;" data-action="unpublish-design" data-id="${d.id}" data-printify-id="${d.printify_id}" title="Archive on Printify">&#128465; Archive</button>` : ''}
      </div>
    </div>
  </div>`;
}
