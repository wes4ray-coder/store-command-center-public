/* ── OFFERS ──────────────────────────────────────────────────────── */
async function renderResellOffers(ct) {
  ct.innerHTML = `<div class="empty"><div class="empty-icon">⏳</div>Loading offers…</div>`;
  try {
    const offers = await api('/api/resell/offers');
    if (!offers.length) {
      ct.innerHTML = `${_rsInboxBar()}<div class="empty"><div class="empty-icon">💬</div>No offers yet. Once you post listings and buyers message you, offers will appear here. Or hit “Read FB Inbox” to pull them in.</div>`;
      return;
    }
    const statusColor = {pending:'var(--muted)',qualified:'var(--green)',lowball:'var(--warn)',rejected:'var(--danger,#e55)',accepted:'var(--accent)'};
    ct.innerHTML = `
      ${_rsInboxBar()}
      <div style="margin-bottom:12px;font-size:.82rem;color:var(--muted);">Offers are auto-filtered: <span style="color:var(--green);">Qualified</span> = meets your min price · <span style="color:var(--warn);">Lowball</span> = below 50% min · <span style="color:var(--muted);">Pending</span> = in between</div>
      <div style="display:flex;flex-direction:column;gap:12px;">
        ${offers.map(o => {
          const distInfo = o.distance_miles ? `<span style="margin-left:8px;">📍 ${o.distance_miles} mi · gas ≈ $${o.gas_cost?.toFixed(2)||'?'}</span>` : '';
          const col = statusColor[o.status] || 'var(--muted)';
          return `<div style="background:var(--surface2);border-radius:8px;border:1px solid var(--border);padding:14px;display:flex;gap:14px;align-items:flex-start;">
            <div style="flex:1;">
              <div style="font-weight:700;margin-bottom:2px;">${esc(o.title||'Item')}</div>
              <div style="font-size:.78rem;color:var(--muted);margin-bottom:6px;">From: ${esc(o.buyer_name||'Unknown')} via ${esc(o.platform||'?')} · ${o.created_at?.slice(0,16)||''}</div>
              <div style="font-size:.85rem;margin-bottom:6px;">${esc(o.buyer_message||'')}</div>
              ${o.buyer_location ? `<div style="font-size:.78rem;color:var(--muted);">📍 ${esc(o.buyer_location)}${distInfo}</div>` : ''}
            </div>
            <div style="text-align:right;flex-shrink:0;">
              <div style="font-size:1.3rem;font-weight:800;color:${col};">$${o.offer_amount?.toFixed(2)||'?'}</div>
              <div style="font-size:.72rem;font-weight:700;color:${col};">${(o.status||'pending').toUpperCase()}</div>
              <div style="margin-top:8px;display:flex;flex-direction:column;gap:4px;">
                <button class="btn-sm primary" onclick="rsOfferAiReply(${o.id})" title="Has the local AI draft an accept / counter / decline reply using this offer, the listing, and your PRIVATE minimum (it never counters below it). You review the draft before anything is sent to the buyer.">🤖 AI Reply</button>
                ${o.status==='qualified' ? `<button class="btn-sm rs-accept-offer" data-id="${o.id}" title="Marks this offer accepted and flags the buyer as notified. Does not message anyone — arrange the meetup yourself." style="background:var(--green);color:#000;">✅ Accept</button>` : ''}
                <button class="btn-sm rs-reject-offer" data-id="${o.id}" title="Marks this offer rejected in the Store. Does not send the buyer a message." style="background:#c0392b;color:#fff;">✕ Reject</button>
              </div>
              <div id="rs-ai-reply-${o.id}" style="margin-top:6px;font-size:.75rem;text-align:left;"></div>
            </div>
          </div>`;
        }).join('')}
      </div>
      ${_rsActivityPanel()}`;

    ct.querySelectorAll('.rs-accept-offer').forEach(btn => {
      btn.addEventListener('click', async () => {
        await api(`/api/resell/offers/${btn.dataset.id}`, {method:'PATCH', body:JSON.stringify({status:'accepted',notified:1})});
        toast('✅ Offer accepted! Set up the meetup details.');
        await renderResellOffers(ct);
      });
    });
    ct.querySelectorAll('.rs-reject-offer').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (!confirm('Reject this offer?')) return;
        await api(`/api/resell/offers/${btn.dataset.id}`, {method:'PATCH', body:JSON.stringify({status:'rejected'})});
        toast('Offer rejected.'); await renderResellOffers(ct);
      });
    });
  } catch(e) {
    ct.innerHTML = `<div class="empty"><div class="empty-icon">⚠️</div>${e.message}</div>`;
  }
}

/* ── RESELL PREFERENCES ─────────────────────────────────────────────────────── */
async function renderResellPrefs(ct) {
  let settings = {};
  try { settings = await api('/api/settings'); } catch {}
  ct.innerHTML = `
<div style="max-width:620px;margin:0 auto;">
  <div class="rs-section">
    <div class="rs-section-title">📍 Location &amp; Distance</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px;">
      <div class="field">
        <label>My Location <span style="font-size:.7rem;color:var(--muted);">(zip or city for distance calc)</span> ${hlp('Your zip or city. Used to estimate distance and gas cost to each buyer so far-away lowballs get flagged and the haggle AI can hold firm. Saved in settings, never shown to buyers.')}</label>
        <input type="text" id="rp-location" value="${esc(settings.resell_location||'')}" placeholder="e.g. 76002 or Arlington TX">
      </div>
      <div class="field">
        <label>Max Drive Distance (miles) ${hlp('How far you will drive for a meetup. Offers beyond this can be flagged by the distance filter on the Offers tab.')}</label>
        <input type="number" id="rp-max-miles" value="${settings.resell_max_drive_miles||'15'}" min="1" placeholder="15">
      </div>
      <div class="field">
        <label>Gas Cost per Mile ($) ${hlp('Your fuel cost per mile. Combined with buyer distance to estimate the round-trip gas cost the haggle AI factors into counteroffers.')}</label>
        <input type="number" id="rp-gas" value="${settings.resell_gas_cost_per_mile||'0.21'}" step="0.01" min="0" placeholder="0.21">
      </div>
      <div class="field">
        <label>Min Price to Ship ($) ${hlp('Default minimum sale price before shipping is worth it. Pre-fills the per-listing ship threshold on new listings.')}</label>
        <input type="number" id="rp-ship-min" value="${settings.resell_ship_min_price||'50'}" min="0" placeholder="50">
      </div>
    </div>
  </div>
  <div class="rs-section">
    <div class="rs-section-title">💵 Payment Preferences</div>
    <div class="field" style="margin-bottom:12px;">
      <label>Payment Details <span style="font-size:.7rem;color:var(--muted);">(shown to buyers)</span> ${hlp('Free-text payment note shown to buyers on listings (e.g. your CashApp tag). Saved in settings.')}</label>
      <input type="text" id="rp-payment-details" value="${esc(settings.resell_payment_details||'')}" placeholder="e.g. Cash preferred · CashApp $YourTag">
    </div>
    <div class="field" style="margin-bottom:12px;">
      <label>Preferred Payment Methods ${hlp('Default payment methods pre-checked on new listings. Saved in settings as your defaults.')}</label>
      <div style="display:flex;flex-wrap:wrap;gap:10px;margin-top:6px;">
        ${[['cash','💵 Cash'],['cashapp','$CashApp'],['venmo','@Venmo'],['zelle','Zelle'],['paypal','PayPal']].map(([v,l])=>{
          const checked = (settings.resell_default_payments||'cash').includes(v) ? 'checked' : '';
          return `<label style="display:flex;align-items:center;gap:5px;cursor:pointer;font-size:.83rem;"><input type="checkbox" class="rp-pay" value="${v}" ${checked}> ${l}</label>`;
        }).join('')}
      </div>
    </div>
  </div>
  <div class="rs-section">
    <div class="rs-section-title">📱 Platform Logins</div>
    <div style="font-size:.8rem;color:var(--muted);line-height:1.6;">
      Browser automation posts listings for you — but you need to be logged into each platform first.<br>
      1. Open the OpenClaw browser and log into <strong>Facebook</strong>, <strong>OfferUp</strong>, <strong>Craigslist</strong>, <strong>Mercari</strong>.<br>
      2. When you click <em>Post Now</em> in a listing, it reuses those sessions automatically.<br>
      3. Credentials are never stored — browser cookies handle auth.
    </div>
  </div>
  <button class="btn" id="rp-save">💾 Save Preferences</button>
  <span id="rp-msg" style="font-size:.78rem;margin-left:10px;"></span>
</div>`;

  document.getElementById('rp-save').addEventListener('click', async () => {
    const msg = document.getElementById('rp-msg');
    const payMethods = [...document.querySelectorAll('.rp-pay:checked')].map(c=>c.value).join(',');
    try {
      await api('/api/settings', {method:'PATCH', body:JSON.stringify({
        resell_location:          document.getElementById('rp-location').value.trim(),
        resell_max_drive_miles:   document.getElementById('rp-max-miles').value,
        resell_gas_cost_per_mile: document.getElementById('rp-gas').value,
        resell_ship_min_price:    document.getElementById('rp-ship-min').value,
        resell_payment_details:   document.getElementById('rp-payment-details').value.trim(),
        resell_default_payments:  payMethods,
      })});
      msg.style.color = 'var(--green)'; msg.textContent = '✓ Saved';
      setTimeout(() => { msg.textContent = ''; }, 3000);
    } catch(e) { msg.style.color = 'var(--warn)'; msg.textContent = 'Error: ' + e.message; }
  });
}
