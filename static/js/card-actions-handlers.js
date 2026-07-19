/* Split from card-actions.js — individual action-handler functions that bindCards()
   dispatches to (Printify images manager, publish/regen/approve/etsy/edit modals),
   plus their top-level event wiring. Classic non-module script: shared global scope
   with card-actions.js — these functions are called from bindCards via bare globals. */

/* ══ PRINTIFY IMAGES MANAGER ══ */
async function showPrintifyImages() {
  const main = document.getElementById('main-content');
  // Insert a floating panel below the published header
  let panel = document.getElementById('printify-img-panel');
  if (panel) { panel.remove(); return; } // toggle

  panel = document.createElement('div');
  panel.id = 'printify-img-panel';
  panel.style.cssText = 'margin-top:16px;background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px;';
  panel.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
    <b style="font-size:.9rem;">&#128247; Printify Uploaded Images</b>
    <button class="btn-sm" onclick="document.getElementById('printify-img-panel').remove()">&#10005; Close</button>
  </div>
  <div id="printify-imgs-body"><div style="color:var(--muted);font-size:.8rem;">Loading&#8230;</div></div>`;
  main.prepend(panel);

  try {
    const data = await api('/api/printify/images');
    const imgs = data.images || [];
    if (!imgs.length) {
      document.getElementById('printify-imgs-body').innerHTML = '<div style="color:var(--muted);font-size:.8rem;">No images uploaded to Printify yet.</div>';
      return;
    }
    let h = `<div class="agent-printify-images">`;
    for (const img of imgs) {
      const previewUrl = img.preview_url || img.url || '';
      const name = (img.file_name || img.filename || img.id || '').slice(0, 24);
      const locals = img.local_designs || [];
      const matchTag = locals.length
        ? `<div style="font-size:.6rem;color:var(--accent2);margin:2px 0;">✓ ${locals.map(l=>esc(l.product_type)).join(', ')}</div>`
        : `<div style="font-size:.6rem;color:var(--muted);margin:2px 0;">&#9888; no local match</div>`;
      h += `<div class="printify-img-card">
        ${previewUrl ? `<img src="${esc(previewUrl)}" alt="" loading="lazy">` : '<div style="height:90px;background:var(--surface);display:flex;align-items:center;justify-content:center;font-size:1.5rem;">🖼️</div>'}
        <div class="printify-img-card-info">
          <div class="img-name" title="${esc(img.file_name||img.id||'')}">${esc(name)}</div>
          ${matchTag}
          <button class="btn-sm danger" style="width:100%;font-size:.65rem;" data-action="delete-printify-img" data-imgid="${esc(img.id||'')}">&#128465; Delete</button>
        </div>
      </div>`;
    }
    h += `</div>`;
    document.getElementById('printify-imgs-body').innerHTML = h;

    // Bind delete buttons
    document.getElementById('printify-imgs-body').addEventListener('click', async (e) => {
      const btn = e.target.closest('[data-action="delete-printify-img"]');
      if (!btn) return;
      const imgId = btn.dataset.imgid;
      if (!confirm('Delete this image from Printify? This does NOT delete associated products.')) return;
      btn.disabled = true; btn.textContent = '⏳';
      try {
        // Printify doesn't always have a standalone image delete — use the products endpoint as fallback
        await api(`/api/printify/images/${encodeURIComponent(imgId)}`, { method: 'DELETE' });
        btn.closest('.printify-img-card')?.remove();
        toast('Image deleted from Printify');
      } catch(e2) {
        toast('Delete failed: ' + e2.message, 'error');
        btn.disabled = false; btn.textContent = '🗑 Delete';
      }
    });
  } catch(e) {
    document.getElementById('printify-imgs-body').innerHTML = `<div style="color:var(--error);font-size:.8rem;">${esc(e.message)}</div>`;
  }
}

async function pollAudioDownload(key, safe) {
  try {
    const s = await api(`/api/audio-models/${encodeURIComponent(key)}/download-status`);
    if (s.status === 'downloading') { setTimeout(() => pollAudioDownload(key, safe), 4000); return; }
    if (s.status === 'done') { toast('✅ Audio model ready'); }
    else if (s.status === 'error') { toast('Download failed — see the model card', 'error'); }
    renderModels();
  } catch { setTimeout(() => pollAudioDownload(key, safe), 5000); }
}
window.pollAudioDownload = pollAudioDownload;

/* ── PUBLISH MODAL ── */
function _getConfiguredPrice(productType) {
  // Returns retail price in dollars from settings, or null if not set
  const s = _settings || {};
  const marginPct = parseFloat(s.pricing_margin_pct || 40);
  const ptKey = (productType || 'T-Shirt').replace(/ /g, '_');
  const baseCentsStr = s['pricing_base_' + ptKey];
  if (!baseCentsStr) return null;
  const baseCents = parseInt(baseCentsStr, 10);
  if (!baseCents) return null;
  // Calc retail: base / (1 - margin)
  const margin = Math.min(Math.max(marginPct, 1), 99) / 100;
  const raw = baseCents / (1 - margin);
  const rawDollars = raw / 100;
  const ceiled = Math.ceil(rawDollars);
  const price = (ceiled - 0.01) >= rawDollars ? ceiled - 0.01 : ceiled + 0.99;
  return Math.round(price * 100) / 100;
}

function _updatePublishPriceHint() {
  // No-op: prices are now per-type, managed inline in _buildPublishTypeCheckboxes
}

function _buildPublishTypeCheckboxes(liveTypes) {
  const defaultPt = _settings.default_product_type || 'T-Shirt';
  document.getElementById('publish-product-types').innerHTML = _productTypes.map(pt => {
    const live = liveTypes.includes(pt);
    const isDefault = !liveTypes.length && pt === defaultPt;
    const checked = live || isDefault;
    const suggested = _getConfiguredPrice(pt);
    const priceVal = suggested ? suggested.toFixed(2) : '';
    const priceHtml = !live
      ? `<input type="number" class="pt-price" data-pt="${esc(pt)}" step="0.01" min="0.99" placeholder="price" value="${priceVal}" title="Retail price for ${esc(pt)}" style="display:${checked?'inline-block':'none'}">`
      : '';
    return `<div class="product-type-item">
      <label style="${live?'opacity:.5;':''}">
        <input type="checkbox" value="${esc(pt)}"${live?' checked disabled':checked?' checked':''}>
        ${esc(pt)}${live?' ✅':''}
      </label>
      ${priceHtml}
    </div>`;
  }).join('');
  // Show/hide price input when checkbox toggled
  document.querySelectorAll('#publish-product-types input[type=checkbox]').forEach(cb => {
    cb.addEventListener('change', () => {
      const priceInput = cb.closest('.product-type-item')?.querySelector('.pt-price');
      if (priceInput) priceInput.style.display = cb.checked ? 'inline-block' : 'none';
    });
  });
}

async function _runPublishGenerate() {
  const sourceBadge = document.getElementById('publish-source-badge');
  const confirmBtn  = document.getElementById('publish-confirm');
  const genBtn      = document.getElementById('publish-generate-btn');
  genBtn.disabled = true; genBtn.textContent = '\u23F3 Generating\u2026';
  confirmBtn.disabled = true;
  if (sourceBadge) { sourceBadge.textContent = '\u235f Generating listing info\u2026'; sourceBadge.style.display = 'inline'; }
  try {
    const resp = await api(`/api/designs/${_publishDesignId}/generate-listing`, { method: 'POST' });
    let info = resp.ready ? resp : null;
    if (!info) {
      for (let i = 0; i < 120; i++) {
        await new Promise(r => setTimeout(r, 2000));
        const t = await api(`/api/task/${resp.task_id}`);
        if (t.status === 'done') { info = t.result; break; }
        if (t.status === 'error') throw new Error(t.error || 'AI generation failed');
        if (t.status === 'not_found') throw new Error('Task expired — try again');
      }
    }
    if (info) {
      document.getElementById('publish-title').value = info.title || document.getElementById('publish-title').value;
      document.getElementById('publish-desc').value  = info.description || '';
      document.getElementById('publish-tags').value  = info.tags || '';
      if (sourceBadge) {
        sourceBadge.textContent = info.source === 'proposal'
          ? '\u2705 From proposal \u2014 edit if needed'
          : '\u2728 AI-generated \u2014 edit if needed';
        sourceBadge.style.display = 'inline';
      }
    }
  } catch(e) {
    if (sourceBadge) { sourceBadge.textContent = '\u26a0\ufe0f Generation failed \u2014 fill manually'; sourceBadge.style.display = 'inline'; }
    toast('Generate failed: ' + e.message, 'error');
  } finally {
    genBtn.disabled = false; genBtn.textContent = '\uD83C\uDFA8 Generate Listing';
    confirmBtn.disabled = false;
  }
}

async function openPublishModal(btn) {
  _publishDesignId = btn.dataset.id;
  const prefillTitle = decodeURIComponent(btn.dataset.title || '');
  const prefillDesc  = decodeURIComponent(btn.dataset.desc  || '');
  const prefillTags  = decodeURIComponent(btn.dataset.tags  || '');
  // Store prefill data for radio button switching
  _publishPrefillTitle = prefillTitle;
  _publishPrefillDesc  = prefillDesc;
  _publishPrefillTags  = prefillTags;

  // Build product type checkboxes with per-type price inputs
  const liveTypes = JSON.parse(decodeURIComponent(btn.dataset.publishedTypes || '[]'));
  _buildPublishTypeCheckboxes(liveTypes);

  const sourceBadge = document.getElementById('publish-source-badge');
  const confirmBtn  = document.getElementById('publish-confirm');

  // Default to proposal radio if we have proposal data
  const hasProposal = prefillTitle && prefillDesc && prefillTags;
  document.querySelectorAll('input[name="publish_source"]').forEach(r => { r.checked = r.value === (hasProposal ? 'proposal' : 'ai'); });

  if (hasProposal) {
    document.getElementById('publish-title').value = prefillTitle;
    document.getElementById('publish-desc').value  = prefillDesc;
    document.getElementById('publish-tags').value  = prefillTags;
    if (sourceBadge) { sourceBadge.textContent = '\u2705 From proposal \u2014 edit if needed'; sourceBadge.style.display = 'inline'; }
    document.getElementById('publish-modal').style.display = 'flex';
    return;
  }

  // No proposal data — clear fields, show modal, auto-generate
  document.getElementById('publish-title').value = prefillTitle;
  document.getElementById('publish-desc').value  = prefillDesc;
  document.getElementById('publish-tags').value  = prefillTags;
  document.getElementById('publish-modal').style.display = 'flex';
  await _runPublishGenerate();
}

document.getElementById('publish-confirm').addEventListener('click', async () => {
  const title = document.getElementById('publish-title').value.trim();
  const desc  = document.getElementById('publish-desc').value.trim();
  const tags  = document.getElementById('publish-tags').value.trim();
  // Only non-disabled (non-already-live) checked types
  const types = [...document.querySelectorAll('#publish-product-types input[type=checkbox]:checked:not([disabled])')].map(c => c.value);

  if (!title)        { toast('Title is required', 'error');                  return; }
  if (!types.length) { toast('Select at least one product type', 'error');   return; }

  const btn = document.getElementById('publish-confirm');
  btn.disabled = true; btn.textContent = '\u23F3 Publishing\u2026';

  let ok = 0; const errs = [];
  for (const pt of types) {
    try {
      // Per-type retail price from inline input
      const _inp = document.querySelector('#publish-product-types .pt-price[data-pt="' + CSS.escape(pt) + '"]');
      const _ptPrice = _inp ? parseFloat(_inp.value) : 0;
      await api('/api/printify/publish', { method: 'POST', body: JSON.stringify({
        design_id: parseInt(_publishDesignId, 10), title, description: desc, tags,
        product_type: pt,
        ...(_ptPrice > 0 ? { retail_price_cents: Math.round(_ptPrice * 100) } : {})
      }) });
      ok++;
    } catch(e) { errs.push(`${pt}: ${e.message}`); }
  }

  if (ok) {
    toast(`\u2713 Published ${ok} product type${ok>1?'s':''} to Printify!`);
    closeModal('publish-modal');
    loadStats();
    if (_currentView === 'etsy-printify' && _etsySubTab === 'approved') { _etsySubTab='approved'; renderEtsyPrintify(); }
  }
  if (errs.length) toast('Some failed: ' + errs.join('; '), 'error');

  btn.disabled = false; btn.textContent = '\u{1F680} Publish to Printify';
});

// Generate Listing button
document.getElementById('publish-generate-btn').addEventListener('click', _runPublishGenerate);

// Radio buttons: proposal vs AI — switch between stored prefill data and AI generation
document.querySelectorAll('input[name="publish_source"]').forEach(r => {
  r.addEventListener('change', () => {
    if (r.value === 'proposal') {
      document.getElementById('publish-title').value = _publishPrefillTitle;
      document.getElementById('publish-desc').value  = _publishPrefillDesc;
      document.getElementById('publish-tags').value  = _publishPrefillTags;
      const badge = document.getElementById('publish-source-badge');
      if (badge) { badge.textContent = '\u2705 From proposal'; badge.style.display = _publishPrefillTitle ? 'inline' : 'none'; }
    }
    // 'ai' — user clicks "Generate Listing" to trigger AI
  });
});

/* ── REGEN MODAL ── */
function openRegenModal(designId, prompt) {
  _regenDesignId = designId;
  document.getElementById('regen-prompt').value = decodeURIComponent(prompt);
  openModal('regen-modal');
}

document.getElementById('regen-confirm').addEventListener('click', async () => {
  const prompt = document.getElementById('regen-prompt').value.trim();
  const variations = parseInt(document.getElementById('regen-variations').value) || 3;
  if (!prompt) { toast('Prompt is required', 'error'); return; }
  const btn = document.getElementById('regen-confirm');
  btn.disabled = true; btn.textContent = '\u23F3 Generating\u2026';
  try {
    await api('/api/generate', { method: 'POST', body: JSON.stringify({ prompt, variations }) });
    closeModal('regen-modal'); toast('\u{1F3A8} Regenerating!');
  } catch(e) { toast('Error: ' + e.message, 'error'); }
  finally { btn.disabled = false; btn.textContent = '\u{1F3A8} Regenerate'; }
});

/* ── APPROVE PROPOSAL MODAL ── */
async function openApproveProposalModal(proposalId, card) {
  _approveProposalId   = proposalId;
  _approveProposalCard = card;

  const confirmBtn = document.getElementById('approve-proposal-confirm');
  const statusEl   = document.getElementById('approve-proposal-status');
  const promptEl   = document.getElementById('approve-prompt');

  promptEl.value = '';
  confirmBtn.disabled = true;
  statusEl.textContent = '\u23F3 Enhancing prompt with AI\u2026';
  openModal('approve-proposal-modal');

  try {
    const r = await api(`/api/proposals/${proposalId}/enhance-prompt`, { method: 'POST' });
    const taskId = r.task_id;
    for (let i = 0; i < 180; i++) {
      await new Promise(res => setTimeout(res, 2000));
      // Show elapsed time so it doesn't look frozen
      const elapsed = (i + 1) * 2;
      if (elapsed >= 20) {
        const mins = Math.floor(elapsed / 60);
        const secs = elapsed % 60;
        const timeStr = mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
        statusEl.textContent = `\u23F3 Still enhancing\u2026 (${timeStr} \u2014 LLM may be loading)`;
      }
      const t = await api(`/api/task/${taskId}`);
      if (t.status === 'done') {
        const result = t.result;
        promptEl.value = (typeof result === 'string') ? result : (result.enhanced || result.prompt || result.enhanced_prompt || '');
        statusEl.textContent = '\u2728 Enhanced \u2014 edit if needed';
        confirmBtn.disabled = false;
        return;
      }
      if (t.status === 'error') throw new Error(t.error || 'Enhancement failed');
      if (t.status === 'not_found') throw new Error('Task expired \u2014 please try again');
      if (t.status === 'cancelled') throw new Error('Enhancement was cancelled');
    }
    throw new Error('Enhancement timed out after 6 minutes \u2014 enter prompt manually');
  } catch(e) {
    statusEl.textContent = '\u26a0\ufe0f Enhancement failed \u2014 enter prompt manually';
    promptEl.placeholder = 'Enter image generation prompt\u2026';
    confirmBtn.disabled = false;
    toast('Enhance error: ' + e.message, 'error');
  }
}

document.getElementById('approve-proposal-confirm').addEventListener('click', async () => {
  const prompt     = document.getElementById('approve-prompt').value.trim();
  const variations = parseInt(document.getElementById('approve-variations').value) || 3;
  if (!prompt) { toast('Prompt is required', 'error'); return; }

  const btn = document.getElementById('approve-proposal-confirm');
  btn.disabled = true; btn.textContent = '\u23F3 Generating\u2026';
  try {
    await api(`/api/proposals/${_approveProposalId}/approve`, { method: 'PATCH', body: JSON.stringify({ prompt, variations }) });
    _approveProposalCard?.remove();
    closeModal('approve-proposal-modal');
    toast('\u{1F3A8} Generation started!');
    loadStats();
  } catch(e) { toast('Error: ' + e.message, 'error'); }
  finally { btn.disabled = false; btn.textContent = '\u{1F3A8} Generate'; }
});

/* ── ETSY MODAL ── */
function openEtsyModal(btn) {
  const printifyId = btn.dataset.printifyId;
  const etsyId     = btn.dataset.etsyId;
  // If already published via Printify, Etsy gets it automatically through sales channel sync
  if (printifyId) {
    toast('\u26a0\ufe0f Already on Etsy via Printify sync \u2014 publishing to Printify pushes it to your Etsy store automatically. No direct listing needed.', 'warn');
    return;
  }
  if (etsyId) {
    toast('\u26a0\ufe0f Already has a direct Etsy listing (#' + etsyId + '). Open Etsy to view it.', 'warn');
    return;
  }
  _etsyDesignId = btn.dataset.id;
  document.getElementById('etsy-title').value = decodeURIComponent(btn.dataset.title || '');
  document.getElementById('etsy-tags').value  = decodeURIComponent(btn.dataset.tags  || '');
  // Populate product type options dynamically
  const ptSel2 = document.getElementById('etsy-product-type');
  if (ptSel2) ptSel2.innerHTML = _productTypes.map(pt => `<option value="${esc(pt)}">${esc(pt)}</option>`).join('');
  // Auto-fill price from product type
  const defaultPt = _settings.default_product_type || 'T-Shirt';
  if (ptSel2 && defaultPt) ptSel2.value = defaultPt;
  const suggested = _getConfiguredPrice(defaultPt);
  const etsyPriceInput = document.getElementById('etsy-price');
  if (etsyPriceInput && suggested) etsyPriceInput.value = suggested.toFixed(2);
  // Update price when product type changes
  if (ptSel2) ptSel2.onchange = () => {
    const p = _getConfiguredPrice(ptSel2.value);
    if (p && etsyPriceInput) etsyPriceInput.value = p.toFixed(2);
  };
  openModal('etsy-modal');
}

document.getElementById('etsy-confirm').addEventListener('click', async () => {
  const title   = document.getElementById('etsy-title').value.trim();
  const tags    = document.getElementById('etsy-tags').value.trim();
  const product = document.getElementById('etsy-product-type').value;
  const priceVal = parseFloat(document.getElementById('etsy-price').value) || 25.0;
  if (!title) { toast('Title is required', 'error'); return; }
  const btn = document.getElementById('etsy-confirm');
  btn.disabled = true; btn.textContent = '\u23F3 Creating\u2026';
  try {
    await api('/api/etsy/publish', { method: 'POST', body: JSON.stringify({ design_id: _etsyDesignId, title, tags, product_type: product, price: priceVal }) });
    closeModal('etsy-modal'); toast('\u{1F6CD}\ufe0f Etsy draft created!'); loadStats();
  } catch(e) { toast('Error: ' + e.message, 'error'); }
  finally { btn.disabled = false; btn.textContent = '\u{1F6CD}\ufe0f Create Draft Listing'; }
});

/* ── EDIT LISTING MODAL ── */
let _editDesignId = null, _editPrintifyId = null, _editEtsyId = null;

function openEditListingModal(btn) {
  _editDesignId  = btn.dataset.id;
  _editPrintifyId = btn.dataset.printifyId || '';
  _editEtsyId    = btn.dataset.etsyId || '';
  document.getElementById('el-title').value = decodeURIComponent(btn.dataset.title || '');
  document.getElementById('el-desc').value  = decodeURIComponent(btn.dataset.desc  || '');
  document.getElementById('el-tags').value  = '';
  const targets = [];
  if (_editPrintifyId) targets.push('Printify product ' + _editPrintifyId);
  if (_editEtsyId)     targets.push('Etsy listing #' + _editEtsyId);
  document.getElementById('el-targets').innerHTML = targets.length
    ? '&#9989; Will update: <b>' + targets.join(' &amp; ') + '</b>'
    : '<span style="color:var(--warn);">&#9888; No Printify ID or Etsy listing ID found for this design.</span>';
  openModal('edit-listing-modal');
}

document.getElementById('el-confirm').addEventListener('click', async () => {
  const title = document.getElementById('el-title').value.trim();
  const desc  = document.getElementById('el-desc').value.trim();
  const tags  = document.getElementById('el-tags').value.trim();
  if (!title && !desc && !tags) { toast('Nothing to update', 'error'); return; }
  const btn = document.getElementById('el-confirm');
  btn.disabled = true; btn.textContent = '\u23F3 Saving\u2026';
  const errs = [];
  try {
    const body = {};
    if (title) body.title = title;
    if (desc)  body.description = desc;
    if (tags)  body.tags = tags;
    if (_editPrintifyId) {
      try {
        await api('/api/printify/products/' + _editPrintifyId, { method: 'PATCH', body: JSON.stringify(body) });
      } catch(e) { errs.push('Printify: ' + e.message); }
    }
    if (_editEtsyId) {
      try {
        await api('/api/etsy/listings/' + _editEtsyId, { method: 'PATCH', body: JSON.stringify(body) });
      } catch(e) { errs.push('Etsy: ' + e.message); }
    }
    if (errs.length) {
      toast('Partial save \u2014 ' + errs.join('; '), 'error');
    } else {
      closeModal('edit-listing-modal');
      toast('\u2705 Listing updated!');
    }
  } catch(e) { toast('Error: ' + e.message, 'error'); }
  finally { btn.disabled = false; btn.textContent = '\u{1F4BE} Save Changes'; }
});
