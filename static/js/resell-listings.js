/* ── LISTINGS GRID ───────────────────────────────────────────────── */
let _resellStatusFilter = '';
async function renderResellListings(ct, initialFilter) {
  if (initialFilter !== undefined) _resellStatusFilter = initialFilter;
  ct.innerHTML = `<div class="empty"><div class="empty-icon">⏳</div>Loading…</div>`;
  try {
    const allRows = await api('/api/resell/listings');
    const filters = [
      {key:'',label:'All',count:allRows.length},
      {key:'active',label:'Active',count:allRows.filter(r=>r.status==='active'||!r.status).length},
      {key:'listed',label:'📢 Posted',count:allRows.filter(r=>r.status==='listed').length},
      {key:'sold',label:'✅ Sold',count:allRows.filter(r=>r.status==='sold').length},
    ];
    const filterBar = `<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px;">${
      filters.map(f=>`<button class="btn-sm rs-filter-btn${_resellStatusFilter===f.key?' primary':''}" data-fkey="${f.key}" style="font-size:.78rem;">${f.label} <span style="background:#ffffff22;border-radius:10px;padding:0 5px;">${f.count}</span></button>`).join('')
    }</div>`;
    const rows = _resellStatusFilter
      ? allRows.filter(r => _resellStatusFilter === 'active'
          ? (!r.status || r.status === 'active')
          : r.status === _resellStatusFilter)
      : allRows;
    const grid = rows.length
      ? `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px;">${rows.map(r=>resellCard(r)).join('')}</div>`
      : `<div class="empty"><div class="empty-icon">📦</div>No ${_resellStatusFilter || ''} listings.</div>`;
    ct.innerHTML = filterBar + grid;

    ct.querySelectorAll('.rs-filter-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        _resellStatusFilter = btn.dataset.fkey;
        renderResellListings(ct);
      });
    });
    ct.querySelectorAll('.rs-delete-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (!confirm('Delete this listing and all photos?')) return;
        await api(`/api/resell/listings/${btn.dataset.id}`, {method:'DELETE'});
        toast('🗑 Deleted'); renderResellListings(ct);
      });
    });
    ct.querySelectorAll('.rs-sold-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        await api(`/api/resell/listings/${btn.dataset.id}`, {method:'PATCH', body:JSON.stringify({status:'sold'})});
        toast('✅ Marked as sold!'); renderResellListings(ct);
      });
    });
    ct.querySelectorAll('.rs-edit-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        _resellEditId = parseInt(btn.dataset.id);
        _resellSubTab = 'edit';
        renderResellEdit(ct, _resellEditId);
      });
    });
    ct.querySelectorAll('.rs-copy-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        try {
          const d = await api(`/api/resell/listings/${btn.dataset.id}/generate-content`,
            {method:'POST', body:JSON.stringify({platform: btn.dataset.platform})});
          await navigator.clipboard.writeText(d.content);
          toast(`📋 Copied ${btn.dataset.platform} listing!`);
        } catch(e) { toast('❌ ' + e.message); }
      });
    });
  } catch(e) {
    ct.innerHTML = `<div class="empty"><div class="empty-icon">⚠️</div>${e.message}</div>`;
  }
}

let _resellEditId = null;
async function renderResellEdit(ct, lid) {
  ct.innerHTML = `<div class="empty"><div class="empty-icon">⏳</div>Loading listing…</div>`;
  try {
    const r = await api(`/api/resell/listings/${lid}`);
    ct.innerHTML = `
<div style="max-width:660px;margin:0 auto;">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px;">
    <button class="btn-sm" id="rs-edit-back">← Back to Listings</button>
    <span style="font-weight:700;">Edit Listing #${r.id}</span>
  </div>
  <div class="rs-section">
    <label style="font-size:.72rem;color:var(--muted);text-transform:uppercase;">Title</label>
    <input id="rse-title" type="text" value="${esc(r.title||'')}" style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:8px 10px;color:var(--text);margin-bottom:10px;">
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px;">
      <div>
        <label style="font-size:.72rem;color:var(--muted);text-transform:uppercase;">Condition</label>
        <select id="rse-condition" style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:8px 10px;color:var(--text);">
          ${['New','Like New','Good','Fair','Poor'].map(c=>`<option${r.condition===c?' selected':''}>${c}</option>`).join('')}
        </select>
      </div>
      <div>
        <label style="font-size:.72rem;color:var(--muted);text-transform:uppercase;">Category</label>
        <input id="rse-category" type="text" value="${esc(r.category||'')}" style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:8px 10px;color:var(--text);">
      </div>
    </div>
    <label style="font-size:.72rem;color:var(--muted);text-transform:uppercase;">Description</label>
    <textarea id="rse-desc" rows="4" style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:8px 10px;color:var(--text);resize:vertical;margin-bottom:10px;">${esc(r.description||'')}</textarea>
    <label style="font-size:.72rem;color:var(--muted);text-transform:uppercase;">Known Defects / Flaws</label>
    <input id="rse-defects" type="text" value="${esc(r.known_defects||'')}" style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:8px 10px;color:var(--text);margin-bottom:10px;">
    <label style="font-size:.72rem;color:var(--muted);text-transform:uppercase;">What's Included</label>
    <input id="rse-included" type="text" value="${esc(r.whats_included||'')}" style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:8px 10px;color:var(--text);margin-bottom:10px;">
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px;">
      <div>
        <label style="font-size:.72rem;color:var(--muted);text-transform:uppercase;">List Price ($) ${hlp('The public asking price buyers see for this listing.')}</label>
        <input id="rse-price" type="number" step="0.01" value="${r.asking_price||''}" style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:8px 10px;color:var(--text);">
      </div>
      <div>
        <label style="font-size:.72rem;color:var(--muted);text-transform:uppercase;">Min I'll Accept ($) ${hlp('The lowest price you’ll take on this listing — private, never shown to buyers. The negotiation AI won’t counter below it.')}</label>
        <input id="rse-min-price" type="number" step="0.01" value="${r.min_accept_price||''}" style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:8px 10px;color:var(--text);">
      </div>
    </div>
    <label style="font-size:.72rem;color:var(--muted);text-transform:uppercase;">Tags</label>
    <input id="rse-tags" type="text" value="${esc(r.tags||'')}" placeholder="comma-separated" style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:8px 10px;color:var(--text);margin-bottom:12px;">
    <label style="font-size:.72rem;color:var(--muted);text-transform:uppercase;">Status ${hlp('Active = draft in the Store only. Listed = posted to a marketplace. Sold = done, drops out of the active list. Controls which filter tab it shows under in Listings.')}</label>
    <select id="rse-status" style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:8px 10px;color:var(--text);margin-bottom:14px;">
      <option value="active"${(!r.status||r.status==='active')?' selected':''}>Active</option>
      <option value="listed"${r.status==='listed'?' selected':''}>Listed (posted)</option>
      <option value="sold"${r.status==='sold'?' selected':''}>Sold</option>
    </select>
    <button class="btn" id="rs-edit-save">💾 Save Changes</button>
    <div id="rs-edit-msg" style="margin-top:8px;font-size:.78rem;"></div>
  </div>
</div>`;
    document.getElementById('rs-edit-back').addEventListener('click', () => {
      _resellSubTab = 'listings';
      renderResellListings(ct);
    });
    document.getElementById('rs-edit-save').addEventListener('click', async () => {
      const btn = document.getElementById('rs-edit-save');
      const msg = document.getElementById('rs-edit-msg');
      btn.disabled = true; btn.textContent = '⏳ Saving…';
      try {
        await api(`/api/resell/listings/${lid}`, {method:'PATCH', body:JSON.stringify({
          title:            document.getElementById('rse-title').value,
          description:      document.getElementById('rse-desc').value,
          condition:        document.getElementById('rse-condition').value,
          category:         document.getElementById('rse-category').value,
          asking_price:     parseFloat(document.getElementById('rse-price').value) || null,
          min_accept_price: parseFloat(document.getElementById('rse-min-price').value) || null,
          known_defects:    document.getElementById('rse-defects').value,
          whats_included:   document.getElementById('rse-included').value,
          tags:             document.getElementById('rse-tags').value,
          status:           document.getElementById('rse-status').value,
        })});
        msg.style.color = 'var(--green)'; msg.textContent = '✓ Saved!';
        btn.disabled = false; btn.textContent = '💾 Save Changes';
        setTimeout(() => { _resellSubTab = 'listings'; renderResellListings(ct); }, 800);
      } catch(e) {
        msg.style.color = 'var(--warn)'; msg.textContent = 'Error: ' + e.message;
        btn.disabled = false; btn.textContent = '💾 Save Changes';
      }
    });
  } catch(e) {
    ct.innerHTML = `<div class="empty"><div class="empty-icon">⚠️</div>${e.message}</div>`;
  }
}

async function resellLoadPhotos(lid) {
  try {
    const photos = await api(`/api/resell/listings/${lid}/photos`);
    return photos;
  } catch { return []; }
}
