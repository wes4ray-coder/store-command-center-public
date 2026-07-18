'use strict';

async function loadProductTypes() {
  try {
    const r = await api('/api/product-types');
    _productTypes = r.types || [...PRODUCT_TYPES];
    _customProductTypes = r.custom || [];
  } catch { /* keep defaults */ }
}

/* ══ PRODUCTS (pricing + custom types) ══ */
async function renderProducts() {
  await loadProductTypes();
  let settings = {};
  try { settings = await api('/api/settings'); } catch {}

  function calcRetailDisplay(baseCents, marginPct) {
    if (!baseCents) return '—';
    const margin = Math.min(Math.max(marginPct, 1), 99) / 100;
    const raw = baseCents / (1 - margin);
    const rawD = raw / 100;
    const ceiled = Math.ceil(rawD);
    const price = (ceiled - 0.01) >= rawD ? ceiled - 0.01 : ceiled + 0.99;
    return '$' + Math.max(price, 0.01).toFixed(2);
  }
  function calcProfitDisplay(baseCents, marginPct) {
    if (!baseCents) return '—';
    const margin = Math.min(Math.max(marginPct, 1), 99) / 100;
    const retail = baseCents / (1 - margin) / 100;
    const ceiled = Math.ceil(retail);
    const price = (ceiled - 0.01) >= retail ? ceiled - 0.01 : ceiled + 0.99;
    const profit = price - baseCents/100 - price * 0.095 - 0.20;
    const col = profit >= 3 ? 'var(--green)' : profit >= 1 ? 'var(--warn)' : '#e74c3c';
    return { val: profit > 0 ? '$'+profit.toFixed(2) : '—', col };
  }

  function pricingRows(marginPct) {
    return _productTypes.map(pt => {
      const ptKey = pt.replace(/ /g, '_');
      const savedBase = parseInt(settings['pricing_base_' + ptKey] || 0, 10);
      const retail  = calcRetailDisplay(savedBase, marginPct);
      const profit  = calcProfitDisplay(savedBase, marginPct);
      const isCustom = _customProductTypes.includes(pt);
      return `<tr style="border-bottom:1px solid var(--border);" data-pt="${esc(pt)}">
        <td style="padding:7px 10px;font-weight:600;">${esc(pt)}${isCustom ? ' <span style="font-size:.65rem;color:var(--accent2);">(custom)</span>' : ''}</td>
        <td style="padding:7px 10px;">
          <div style="display:flex;align-items:center;gap:6px;">$<input type="number" class="pricing-base-input" data-ptkey="${esc(ptKey)}" value="${savedBase?(savedBase/100).toFixed(2):''}" step="0.01" min="0" style="width:72px;font-size:.78rem;padding:3px 6px;" placeholder="0.00"></div>
        </td>
        <td style="padding:7px 10px;color:${savedBase?'var(--text)':'var(--muted)'}" class="retail-cell">${retail}</td>
        <td style="padding:7px 10px;color:${profit.col};font-weight:600;" class="profit-cell">${profit.val}</td>
        <td style="padding:7px 10px;">${isCustom ? `<button class="btn-sm danger" style="padding:2px 7px;font-size:.68rem;" data-action="remove-product-type" data-name="${esc(pt)}">&#10005;</button>` : ''}</td>
      </tr>`;
    }).join('');
  }

  const marginPct = parseFloat(settings.pricing_margin_pct || 40);

  let h = `
    <div class="view-header"><div class="view-title">&#128176; Products &amp; Pricing</div><div class="view-sub">Manage product types and set pricing for Printify listings</div></div>

    <div class="settings-group" style="margin-bottom:16px;">
      <div class="settings-group-title">&#10133; Add Custom Product Type</div>
      <div style="font-size:.76rem;color:var(--muted);margin-bottom:10px;">Add any product type not in the default list. It will appear in the Printify publish modal and pricing table.</div>
      <div style="display:flex;gap:8px;align-items:center;">
        <input type="text" id="new-product-name" placeholder="e.g. Canvas Print, Notebook, Apron&hellip;" style="flex:1;max-width:320px;">
        <button class="btn-sm primary" id="add-product-btn">&#10133; Add</button>
      </div>
    </div>

    <div class="settings-group" id="pricing-group">
      <div class="settings-group-title">&#128181; Pricing Table</div>
      <div style="font-size:.76rem;color:var(--muted);margin-bottom:12px;line-height:1.6;">
        Set base costs (what Printify charges you) and your target margin. Retail price is auto-calculated and pre-filled when you publish.<br>
        <span style="color:var(--accent);font-weight:600;">Etsy fees (~9.5%) come out of your margin on top. Example: T-Shirt base $9.50, 40% margin → retail $15.99 → keep ~$5 after fees.</span>
      </div>
      <div class="field" style="max-width:260px;margin-bottom:16px;">
        <label>Target Profit Margin % ${hlp('Your desired profit as a % of the retail price, applied to every product. The app auto-computes Suggested Retail = base cost ÷ (1 − margin), rounded to $X.99. Etsy’s ~9.5% fees come out on top, so real take-home is a bit less (see the estimate column).')}</label>
        <input type="number" id="s-margin-pct" min="1" max="90" step="1" value="${marginPct}" style="width:100px;">
        <div style="font-size:.7rem;color:var(--muted);margin-top:3px;">Applied globally. Etsy's ~9.5% fee is separate from this margin.</div>
      </div>
      <div style="overflow-x:auto;">
        <table style="width:100%;border-collapse:collapse;font-size:.78rem;">
          <thead><tr style="color:var(--muted);text-align:left;border-bottom:1px solid var(--border);">
            <th style="padding:6px 10px;">Product</th>
            <th style="padding:6px 10px;">Base Cost (Printify charges you) ${hlp('What Printify actually bills you to make + ship one unit of this product (blank/variant-dependent until you set it). Drives the Suggested Retail via your margin. Check your Printify product page for the real figure.')}</th>
            <th style="padding:6px 10px;">Suggested Retail</th>
            <th style="padding:6px 10px;">Est. Profit after Etsy fees</th>
            <th style="padding:6px 10px;"></th>
          </tr></thead>
          <tbody id="pricing-tbody">${pricingRows(marginPct)}</tbody>
        </table>
      </div>
      <div style="display:flex;gap:8px;margin-top:14px;">
        <button class="btn-sm primary" id="s-save-pricing">&#128190; Save Pricing</button>
        <button class="btn-sm" id="s-recalc-pricing">&#128260; Recalculate</button>
      </div>
    </div>`;

  _setContent(h);

  // Margin input → live recalc
  document.getElementById('s-margin-pct').addEventListener('input', function() {
    const mp = parseFloat(this.value) || 40;
    document.getElementById('pricing-tbody').innerHTML = pricingRows(mp);
    rebindPricingInputs();
  });

  function rebindPricingInputs() {
    // nothing to dynamically bind on base inputs — they're just read on save
  }

  // Save pricing
  document.getElementById('s-save-pricing').addEventListener('click', async () => {
    const marginPctVal = parseFloat(document.getElementById('s-margin-pct').value) || 40;
    const patch = { pricing_margin_pct: marginPctVal };
    document.querySelectorAll('.pricing-base-input').forEach(inp => {
      const val = parseFloat(inp.value);
      if (!isNaN(val) && val > 0) patch['pricing_base_' + inp.dataset.ptkey] = Math.round(val * 100);
    });
    try {
      await api('/api/settings', { method: 'PATCH', body: JSON.stringify(patch) });
      try { _settings = await api('/api/settings'); } catch {}
      settings = _settings;
      toast('Pricing saved \u2713');
    } catch(e) { toast('Save failed: ' + e.message, 'error'); }
  });

  // Recalc
  document.getElementById('s-recalc-pricing').addEventListener('click', () => {
    const mp = parseFloat(document.getElementById('s-margin-pct').value) || 40;
    document.getElementById('pricing-tbody').innerHTML = pricingRows(mp);
  });

  // Add custom product type
  document.getElementById('add-product-btn').addEventListener('click', async () => {
    const inp  = document.getElementById('new-product-name');
    const name = inp.value.trim();
    if (!name) return;
    try {
      await api('/api/product-types', { method: 'POST', body: JSON.stringify({ name }) });
      inp.value = '';
      await loadProductTypes();
      toast('Product type added \u2713');
      renderProducts();
    } catch(e) { toast('Error: ' + e.message, 'error'); }
  });

  // Remove custom product type
  document.getElementById('main-content').addEventListener('click', async e => {
    const btn = e.target.closest('[data-action="remove-product-type"]');
    if (!btn) return;
    if (!confirm('Remove product type "' + btn.dataset.name + '"?')) return;
    try {
      await api('/api/product-types?name=' + encodeURIComponent(btn.dataset.name), { method: 'DELETE' });
      await loadProductTypes();
      toast('Removed');
      renderProducts();
    } catch(e) { toast('Error: ' + e.message, 'error'); }
  });
}
