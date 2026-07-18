/* ── NEW LISTING ─────────────────────────────────────────────────── */
function renderResellNew(ct) {
  ct.innerHTML = `
<div style="max-width:720px;margin:0 auto;">

  <!-- Step 0: Describe It -->
  <div class="rs-section">
    <div class="rs-section-title">📝 Step 1 — Describe What You're Selling</div>
    <div style="font-size:.78rem;color:var(--muted);margin-bottom:10px;">Tell the AI what it is. The more detail here, the better the identification and pricing.</div>
    <label style="font-size:.72rem;color:var(--muted);text-transform:uppercase;">What is this item? <span style="color:var(--warn);">(helps AI)</span> ${hlp('Free-text description sent to the local Vision AI in Step 3. More detail → better item ID, condition guess, and price range. Saved on the listing as seller_description.')}</label>
    <textarea id="rs-seller-desc" rows="2" placeholder="e.g. Xbox 360 controller, black, works great, minor stick wear" style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:8px 10px;color:var(--text);resize:vertical;margin-bottom:10px;"></textarea>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
      <div>
        <label style="font-size:.72rem;color:var(--muted);text-transform:uppercase;">Why Selling? ${hlp('Optional context the AI weaves into the generated listing text (e.g. decluttering, upgrading). Not shown to buyers as a separate field.')}</label>
        <select id="rs-why-selling" style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:8px 10px;color:var(--text);">
          <option value="">&mdash; optional &mdash;</option>
          <option value="Decluttering">Decluttering</option>
          <option value="No longer use it">No longer use it</option>
          <option value="Upgrading to newer model">Upgrading to newer model</option>
          <option value="Moving / downsizing">Moving / downsizing</option>
          <option value="Gift I don't need">Gift I don't need</option>
          <option value="Other">Other</option>
        </select>
      </div>
      <div>
        <label style="font-size:.72rem;color:var(--muted);text-transform:uppercase;">What's Included? ${hlp('What comes with the item (box, charger, manual). Saved as whats_included, shown on the listing card and worked into the AI description.')}</label>
        <input id="rs-whats-included" type="text" placeholder="original box, charger, manual…" style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:8px 10px;color:var(--text);">
      </div>
    </div>
    <div style="margin-top:10px;">
      <label style="font-size:.72rem;color:var(--muted);text-transform:uppercase;">Known Defects / Flaws <span style="font-size:.65rem;color:var(--green);">— honesty builds trust</span> ${hlp('Flaws to disclose up front (scratches, missing parts). Saved as known_defects, shown on the listing card and given to the AI so the description stays honest.')}</label>
      <input id="rs-known-defects" type="text" placeholder="small scuff on back, missing battery cover — leave blank if none" style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:8px 10px;color:var(--text);">
    </div>
    <div style="margin-top:10px;">
      <label style="font-size:.72rem;color:var(--muted);text-transform:uppercase;">Tags <span style="font-size:.65rem;color:var(--muted);">(comma-separated, helps search)</span> ${hlp('Comma-separated keywords saved with the listing to help marketplace search. Extra search terms — not the category.')}</label>
      <input id="rs-tags" type="text" placeholder="xbox, controller, gaming, accessories" style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:8px 10px;color:var(--text);">
    </div>
  </div>

  <!-- Step 2: Photos -->
  <div class="rs-section">
    <div class="rs-section-title">📷 Step 2 — Photos</div>
    <div id="rs-photo-grid" style="display:flex;flex-wrap:wrap;gap:10px;margin-bottom:12px;min-height:100px;align-items:flex-start;">
      <div id="rs-add-photo-btn" style="width:100px;height:100px;border:2px dashed var(--border);border-radius:8px;display:flex;flex-direction:column;align-items:center;justify-content:center;cursor:pointer;font-size:1.6rem;color:var(--muted);flex-shrink:0;transition:border-color .2s;">
        ➕<div style="font-size:.65rem;margin-top:4px;">Add photo</div>
      </div>
    </div>
    <input type="file" id="rs-file-input" accept="image/*" multiple style="display:none">
    <div style="display:flex;gap:10px;align-items:center;margin-top:8px;">
      <span style="color:var(--muted);font-size:.78rem;">Or scan a folder:</span>
      <input id="rs-dir-path" type="text" placeholder="/home/user/Pictures/for-sale" title="A folder path ON THIS SERVER to look through for photos. Files are read from local disk only." style="flex:1;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:6px 10px;color:var(--text);font-size:.8rem;">
      <button class="btn-sm" id="rs-scan-btn" title="Lists image files found in that server folder. To actually attach them, drag files into the grid above (server-side copy is not wired yet).">Scan</button>
    </div>
    <div id="rs-scan-results" style="display:none;margin-top:10px;"></div>
  </div>

  <!-- Step 3: AI Identify -->
  <div class="rs-section">
    <div class="rs-section-title">🤖 Step 3 — AI Identify &amp; Price Research</div>
    <div style="display:flex;gap:10px;flex-wrap:wrap;">
      <button class="btn" id="rs-analyze-btn" title="Sends your first photo plus your description to the local Vision AI to identify the item, guess condition, and suggest a price range — then fills in Step 4 below." disabled>🔍 Identify Item (Vision AI)</button>
      <button class="btn-sm" id="rs-research-btn" title="Looks up comparable market prices (including recent eBay sold prices) for the identified item and suggests a list price and a minimum." disabled>💰 Research Prices</button>
    </div>
    <div id="rs-ai-result" style="margin-top:14px;display:none;"></div>
    <div id="rs-research-result" style="margin-top:10px;display:none;"></div>
  </div>

  <!-- Step 4: Listing Details -->
  <div class="rs-section" id="rs-details-section" style="display:none;">
    <div class="rs-section-title">📝 Step 4 — Listing Details</div>
    <label style="font-size:.72rem;color:var(--muted);text-transform:uppercase;">Title ${hlp('The listing headline buyers see. Auto-filled by the Vision AI — edit freely. Trimmed to 100 chars when posted to marketplaces.')}</label>
    <input id="rs-title" type="text" placeholder="e.g. Xbox 360 Controller" style="width:100%;margin-bottom:12px;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:8px 10px;color:var(--text);">

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px;">
      <div>
        <label style="font-size:.72rem;color:var(--muted);text-transform:uppercase;">Condition ${hlp('Item condition posted on the listing. Auto-guessed by the AI from your photo — override if it is wrong.')}</label>
        <select id="rs-condition" style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:8px 10px;color:var(--text);">
          <option>New</option><option>Like New</option><option selected>Good</option><option>Fair</option><option>Poor</option>
        </select>
      </div>
      <div>
        <label style="font-size:.72rem;color:var(--muted);text-transform:uppercase;">Category ${hlp('Product category for the listing (e.g. Electronics). Auto-suggested by the AI; helps marketplace placement.')}</label>
        <input id="rs-category" type="text" placeholder="e.g. Electronics" style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:8px 10px;color:var(--text);">
      </div>
    </div>

    <label style="font-size:.72rem;color:var(--muted);text-transform:uppercase;">Description ${hlp('The full listing body posted to each marketplace. Auto-drafted from your details — edit before posting.')}</label>
    <textarea id="rs-desc" rows="4" placeholder="Describe the item — what it is, any flaws, what's included…" style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:8px 10px;color:var(--text);resize:vertical;margin-bottom:12px;"></textarea>

    <!-- Pricing -->
    <div style="background:var(--surface);border-radius:8px;padding:14px;margin-bottom:12px;">
      <div style="font-weight:600;font-size:.85rem;margin-bottom:10px;">💲 Pricing</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:10px;">
        <div>
          <label style="font-size:.72rem;color:var(--muted);text-transform:uppercase;">List Price ($) ${hlp('The public asking price buyers see. Use Research Prices for a suggestion. On best-offer/negotiate, the AI haggles down from here toward your private minimum.')}</label>
          <input id="rs-price" type="number" step="0.01" min="0" placeholder="25.00" style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:8px 10px;color:var(--text);">
        </div>
        <div>
          <label style="font-size:.72rem;color:var(--muted);text-transform:uppercase;">Min I'll Accept ($) <span style="color:var(--muted);font-size:.68rem;">(private)</span> ${hlp('The lowest price you’ll take. Kept PRIVATE — never shown to buyers. The haggle/negotiation AI uses it as the floor when countering offers, so it never goes below this.')}</label>
          <input id="rs-min-price" type="number" step="0.01" min="0" placeholder="15.00" style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:8px 10px;color:var(--text);">
        </div>
      </div>
      <label style="font-size:.72rem;color:var(--muted);text-transform:uppercase;display:block;margin-bottom:6px;">Price Mode ${hlp('Firm = the price is fixed, no negotiation. OBO / best-offer = buyers can haggle and the AI negotiates down toward your private “Min I’ll Accept”. Sets buyer expectations on the listing.')}</label>
      <div style="display:flex;gap:8px;flex-wrap:wrap;">
        ${[['firm','🔒 Firm — No haggling'],['obo','🤝 Best Offer (OBO)'],['haggle','💬 Negotiate']].map(([v,l])=>
          `<label style="display:flex;align-items:center;gap:5px;cursor:pointer;font-size:.83rem;">
            <input type="radio" name="rs-price-mode" value="${v}" ${v==='obo'?'checked':''}> ${l}
          </label>`).join('')}
      </div>
    </div>

    <!-- Shipping -->
    <div style="background:var(--surface);border-radius:8px;padding:14px;margin-bottom:12px;">
      <div style="font-weight:600;font-size:.85rem;margin-bottom:10px;">📦 Shipping Policy</div>
      <div style="display:flex;flex-direction:column;gap:8px;">
        <label style="display:flex;align-items:flex-start;gap:8px;cursor:pointer;font-size:.85rem;">
          <input type="radio" name="rs-ship" value="never" style="margin-top:2px;"> <div><strong>🚫 Never ship</strong><div style="color:var(--muted);font-size:.75rem;">Local pickup only — period. (Use for cars, furniture, heavy items)</div></div>
        </label>
        <label style="display:flex;align-items:flex-start;gap:8px;cursor:pointer;font-size:.85rem;">
          <input type="radio" name="rs-ship" value="pickup_only" checked style="margin-top:2px;"> <div><strong>🏠 Pickup only</strong><div style="color:var(--muted);font-size:.75rem;">You come to me. I don't drive to you (unless buyer pays extra).</div></div>
        </label>
        <label style="display:flex;align-items:flex-start;gap:8px;cursor:pointer;font-size:.85rem;">
          <input type="radio" name="rs-ship" value="possible" style="margin-top:2px;"> <div><strong>📬 Possible if buyer covers it</strong><div style="color:var(--muted);font-size:.75rem;">I'll ship if buyer pays S&amp;H and item price meets my minimum.</div></div>
        </label>
      </div>
      <div id="rs-ship-min-wrap" style="display:none;margin-top:10px;display:flex;align-items:center;gap:8px;">
        <span style="font-size:.82rem;color:var(--muted);">Only ship if price ≥</span>
        <span style="font-weight:600;">$</span>
        <input id="rs-ship-min" type="number" step="1" min="0" value="50" title="Minimum sale price before you will bother shipping. Only used with the 'Possible if buyer covers it' option above." style="width:80px;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:6px 8px;color:var(--text);">
      </div>
    </div>

    <!-- Payment -->
    <div style="background:var(--surface);border-radius:8px;padding:14px;margin-bottom:16px;">
      <div style="font-weight:600;font-size:.85rem;margin-bottom:10px;">💵 Payment Methods</div>
      <div style="display:flex;flex-wrap:wrap;gap:10px;">
        ${[['cash','💵 Cash (preferred)'],['cashapp','$CashApp'],['venmo','@Venmo'],['zelle','Zelle'],['paypal','PayPal']].map(([v,l])=>
          `<label style="display:flex;align-items:center;gap:5px;cursor:pointer;font-size:.83rem;">
            <input type="checkbox" name="rs-pay" value="${v}" ${v==='cash'?'checked':''}> ${l}
          </label>`).join('')}
      </div>
    </div>

    <button class="btn" id="rs-save-btn">💾 Save Listing</button>
    <div id="rs-post-section" style="display:none;margin-top:16px;border-top:1px solid var(--border);padding-top:16px;">
      <div style="font-weight:600;font-size:.9rem;margin-bottom:10px;">🚀 Post to Marketplaces</div>
      <div style="font-size:.78rem;color:var(--muted);margin-bottom:10px;">Uses the <b>Store's own browser</b> (not OpenClaw). Log in once &mdash; cookies persist in the Store profile. Pick a platform to open its create page with your photos attached, then paste the generated text and submit (you keep control of login/CAPTCHA).</div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px;">
        <button class="btn-sm" onclick="rsBrowserLaunch('')" title="Opens the Store's OWN headed Chrome (separate from OpenClaw). Log into Facebook / Craigslist / Mercari once here — the logged-in session is reused for posting, haggling, and reading the inbox.">🌐 Launch Browser &amp; Log In</button>
        <span id="rs-browser-status" style="font-size:.75rem;color:var(--muted);align-self:center;"></span>
      </div>
      <div style="background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:10px;margin-bottom:10px;">
        <div style="font-size:.72rem;color:var(--muted);margin-bottom:6px;">✏️ Draft — edit before filling/posting:</div>
        <div style="display:flex;gap:8px;margin-bottom:6px;">
          <input id="rs-draft-title" placeholder="Title" title="Editable copy of the title used when the browser auto-fills the marketplace create page. Edits here override the saved listing for this post only." style="flex:2;background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:6px 8px;color:var(--text);font-size:.82rem;">
          <input id="rs-draft-price" placeholder="Price" title="Editable copy of the price used when auto-filling the create page. Overrides the saved listing for this post only." style="flex:1;background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:6px 8px;color:var(--text);font-size:.82rem;">
        </div>
        <textarea id="rs-draft-desc" placeholder="Description" rows="4" title="Editable copy of the description used when auto-filling the create page. Overrides the saved listing for this post only." style="width:100%;background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:6px 8px;color:var(--text);font-size:.82rem;"></textarea>
        <button class="btn-sm" style="margin-top:6px;" onclick="rsCopyDraft()" title="Copies the draft title, price, and description to your clipboard so you can paste them manually if auto-fill misses a field.">📋 Copy all</button>
      </div>
      <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:6px;">
        <button class="btn-sm" onclick="rsBrowserPost('facebook')" title="Opens Facebook Marketplace's create-item page in the Store browser, attaches this listing's photos, and auto-fills title/price/description. You review and submit — login/CAPTCHA stay in your hands.">📘 Facebook → Open &amp; Fill</button>
        <button class="btn-sm" onclick="rsBrowserPost('craigslist')" title="Opens Craigslist's posting flow in the Store browser and attaches photos. Craigslist is multi-step — click through for-sale-by-owner → category, then hit Fill Current Page.">🔵 Craigslist → Open</button>
        <button class="btn-sm" onclick="rsBrowserPost('mercari')" title="Opens Mercari's sell page in the Store browser, attaches photos, and auto-fills the fields. You review and submit.">🔴 Mercari → Open &amp; Fill</button>
        <button class="btn-sm primary" onclick="rsBrowserFill()" title="Fills title/price/description into whatever create form is already open in the Store browser — for multi-step sites like Craigslist. Does not navigate.">🖊️ Fill Current Page</button>
      </div>
      <div style="font-size:.72rem;color:var(--muted);margin-bottom:8px;">📘 Facebook auto-fills. 🔵 Craigslist is multi-step — click through “for sale by owner” → category, then hit <b>Fill Current Page</b>. 🟠 OfferUp posts from its mobile app only (no web posting).</div>
      <div id="rs-post-status" style="font-size:.8rem;color:var(--muted);"></div>
      <div id="rs-browser-shot" style="margin-top:10px;"></div>
      ${_rsActivityPanel()}
    </div>
  </div>

</div>`;

  // Photo grid logic
  const fileInput = document.getElementById('rs-file-input');
  const photoGrid = document.getElementById('rs-photo-grid');
  const addBtn    = document.getElementById('rs-add-photo-btn');
  let _pendingFiles = [];  // files waiting for save (no listing ID yet)
  let _savedLid    = null;

  addBtn.addEventListener('click', () => fileInput.click());
  addBtn.addEventListener('dragover', e => { e.preventDefault(); addBtn.style.borderColor = 'var(--accent)'; });
  addBtn.addEventListener('dragleave', () => { addBtn.style.borderColor = 'var(--border)'; });
  addBtn.addEventListener('drop', e => {
    e.preventDefault(); addBtn.style.borderColor = 'var(--border)';
    [...e.dataTransfer.files].forEach(f => addPhotoPreview(f));
  });
  fileInput.addEventListener('change', () => {
    [...fileInput.files].forEach(f => addPhotoPreview(f));
    fileInput.value = '';
  });

  function addPhotoPreview(file) {
    _pendingFiles.push(file);
    const idx = _pendingFiles.length - 1;
    const thumb = document.createElement('div');
    thumb.style.cssText = 'position:relative;width:100px;height:100px;flex-shrink:0;';
    const img = document.createElement('img');
    img.style.cssText = 'width:100px;height:100px;object-fit:cover;border-radius:8px;border:2px solid var(--border);';
    const del = document.createElement('button');
    del.textContent = '✕';
    del.style.cssText = 'position:absolute;top:2px;right:2px;background:#000a;color:#fff;border:none;border-radius:50%;width:20px;height:20px;cursor:pointer;font-size:.7rem;line-height:20px;padding:0;';
    del.onclick = () => { _pendingFiles[idx] = null; thumb.remove(); };
    const reader = new FileReader();
    reader.onload = ev => { img.src = ev.target.result; };
    reader.readAsDataURL(file);
    thumb.append(img, del);
    photoGrid.insertBefore(thumb, addBtn);
    document.getElementById('rs-analyze-btn').disabled = false;
  }

  // Scan directory
  document.getElementById('rs-scan-btn').addEventListener('click', async () => {
    const path = document.getElementById('rs-dir-path').value.trim();
    if (!path) return;
    const btn = document.getElementById('rs-scan-btn');
    btn.disabled = true; btn.textContent = '…';
    try {
      const data = await api('/api/resell/scan-directory', {method:'POST', body:JSON.stringify({path})});
      const ct2 = document.getElementById('rs-scan-results');
      if (!data.images.length) { toast('No images found in that folder.'); return; }
      ct2.style.display = 'block';
      ct2.innerHTML = `<div style="font-size:.8rem;color:var(--muted);margin-bottom:6px;">Found ${data.images.length} images — click to add:</div>
        <div style="display:flex;flex-wrap:wrap;gap:6px;">
          ${data.images.map((img,i) => `<button class="btn-sm rs-dir-pick" data-path="${esc(img.path)}">${esc(img.filename)}</button>`).join('')}
        </div>`;
      ct2.querySelectorAll('.rs-dir-pick').forEach(b => {
        b.addEventListener('click', async () => {
          // Fetch file from path and add to grid
          toast('⚠️ Directory auto-add: drag files from your file manager for now (server-side copy coming)');
        });
      });
    } catch(e) { toast('❌ ' + e.message); }
    finally { btn.disabled = false; btn.textContent = 'Scan'; }
  });

  // Shipping toggle
  document.querySelectorAll('[name=rs-ship]').forEach(r => {
    r.addEventListener('change', () => {
      const wrap = document.getElementById('rs-ship-min-wrap');
      if (wrap) wrap.style.display = r.value === 'possible' ? 'flex' : 'none';
    });
  });

  // Analyze button
  document.getElementById('rs-analyze-btn').addEventListener('click', async () => {
    const files = _pendingFiles.filter(Boolean);
    if (!files.length) return;
    const btn = document.getElementById('rs-analyze-btn');
    btn.disabled = true; btn.textContent = '⏳ Analyzing…';
    try {
      const fd = new FormData();
      fd.append('file', files[0]);  // vision uses first photo
      const sellerDesc = document.getElementById('rs-seller-desc')?.value.trim() || '';
      if (sellerDesc) fd.append('description', sellerDesc);
      const resp = await fetch(API + '/api/resell/analyze', {method:'POST', body:fd});
      if (!resp.ok) throw new Error(await resp.text());
      const data = await resp.json();
      // Populate form fields
      document.getElementById('rs-title').value     = data.title || '';
      document.getElementById('rs-category').value  = data.category || '';
      document.getElementById('rs-desc').value       = data.description || '';
      const cond = document.getElementById('rs-condition');
      [...cond.options].forEach(o => { o.selected = o.value === (data.condition_guess || 'Good'); });
      if (data.price_fair) document.getElementById('rs-price').value     = data.price_fair;
      if (data.price_low)  document.getElementById('rs-min-price').value = data.price_low;

      const aiDiv = document.getElementById('rs-ai-result');
      aiDiv.style.display = 'block';
      aiDiv.innerHTML = `<div style="background:var(--surface);border-radius:8px;padding:12px;font-size:.83rem;">
        <strong>AI found:</strong> ${esc(data.title)} &nbsp;·&nbsp; Condition: ${esc(data.condition_guess)} &nbsp;·&nbsp;
        <span style="color:var(--green);">Low $${data.price_low}</span> &nbsp;
        <span style="color:var(--accent);">Fair $${data.price_fair}</span> &nbsp;
        <span style="color:var(--warn);">High $${data.price_high}</span>
        ${data.key_features?.length ? `<div style="margin-top:6px;color:var(--muted);">${data.key_features.slice(0,4).map(esc).join(' · ')}</div>` : ''}
      </div>`;
      document.getElementById('rs-details-section').style.display = 'block';
      document.getElementById('rs-research-btn').disabled = false;
    } catch(e) { toast('❌ ' + e.message); }
    finally { btn.disabled = false; btn.textContent = '🔍 Identify Item (Vision AI)'; }
  });

  // Price research
  document.getElementById('rs-research-btn').addEventListener('click', async () => {
    const btn = document.getElementById('rs-research-btn');
    btn.disabled = true; btn.textContent = '⏳ Researching…';
    try {
      const data = await api('/api/resell/research', {method:'POST', body: JSON.stringify({
        title:     document.getElementById('rs-title').value,
        condition: document.getElementById('rs-condition').value,
        category:  document.getElementById('rs-category').value,
      })});
      const div = document.getElementById('rs-research-result');
      div.style.display = 'block';
      div.innerHTML = `<div style="background:var(--surface);border-radius:8px;padding:14px;font-size:.83rem;">
        <div style="font-weight:700;margin-bottom:8px;">💰 Market Research</div>
        <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:8px;">
          <div style="text-align:center;padding:8px 14px;background:var(--surface2);border-radius:6px;">
            <div style="font-size:.68rem;color:var(--muted);">Market Low</div>
            <div style="font-weight:700;color:var(--green);">$${data.market_low||'?'}</div>
          </div>
          <div style="text-align:center;padding:8px 14px;background:var(--surface2);border-radius:6px;">
            <div style="font-size:.68rem;color:var(--muted);">Market Fair</div>
            <div style="font-weight:700;color:var(--accent);">$${data.market_fair||'?'}</div>
          </div>
          <div style="text-align:center;padding:8px 14px;background:var(--surface2);border-radius:6px;">
            <div style="font-size:.68rem;color:var(--muted);">Market High</div>
            <div style="font-weight:700;color:var(--warn);">$${data.market_high||'?'}</div>
          </div>
          <div style="text-align:center;padding:8px 14px;background:var(--surface2);border-radius:6px;border:1px solid var(--accent);">
            <div style="font-size:.68rem;color:var(--muted);">Suggested List</div>
            <div style="font-weight:700;color:var(--text);">$${data.suggested_list||'?'}</div>
          </div>
        </div>
        ${data.price_rationale ? `<div style="color:var(--muted);margin-bottom:6px;font-style:italic;">"${esc(data.price_rationale)}"</div>` : ''}
        ${data.sell_fast_tip   ? `<div style="color:var(--green);">💡 ${esc(data.sell_fast_tip)}</div>` : ''}
        ${data.ebay_sold_prices?.length ? `<div style="margin-top:8px;color:var(--muted);font-size:.75rem;">eBay sold: ${data.ebay_sold_prices.map(p=>'$'+p.toFixed(2)).join(', ')}</div>` : ''}
        <div style="margin-top:10px;display:flex;gap:8px;">
          <button class="btn-sm" id="rs-use-suggested">Use Suggested ($${data.suggested_list||'?'})</button>
          <button class="btn-sm" id="rs-use-min">Use Min ($${data.suggested_minimum||'?'})</button>
        </div>
      </div>`;
      if (data.suggested_list) {
        document.getElementById('rs-use-suggested').addEventListener('click', () => {
          document.getElementById('rs-price').value = data.suggested_list;
          toast('✅ Price updated');
        });
      }
      if (data.suggested_minimum) {
        document.getElementById('rs-use-min').addEventListener('click', () => {
          document.getElementById('rs-min-price').value = data.suggested_minimum;
          toast('✅ Min price updated');
        });
      }
    } catch(e) { toast('❌ Research failed: ' + e.message); }
    finally { btn.disabled = false; btn.textContent = '💰 Research Prices'; }
  });

  // Save listing
  document.getElementById('rs-save-btn').addEventListener('click', async () => {
    const btn = document.getElementById('rs-save-btn');
    btn.disabled = true; btn.textContent = '⏳ Saving…';
    try {
      const payMethods = [...document.querySelectorAll('[name=rs-pay]:checked')].map(c=>c.value);
      const shipPol = document.querySelector('[name=rs-ship]:checked')?.value || 'pickup_only';
      const priceMode = document.querySelector('[name=rs-price-mode]:checked')?.value || 'obo';

      const row = await api('/api/resell/listings', {method:'POST', body:JSON.stringify({
        title:              document.getElementById('rs-title').value,
        description:        document.getElementById('rs-desc').value,
        condition:          document.getElementById('rs-condition').value,
        category:           document.getElementById('rs-category').value,
        asking_price:       parseFloat(document.getElementById('rs-price').value) || null,
        min_accept_price:   parseFloat(document.getElementById('rs-min-price').value) || null,
        price_mode:         priceMode,
        shipping_policy:    shipPol,
        will_ship_min_price: parseFloat(document.getElementById('rs-ship-min')?.value) || 50,
        payment_methods:    payMethods,
        seller_description: document.getElementById('rs-seller-desc')?.value.trim() || null,
        why_selling:        document.getElementById('rs-why-selling')?.value || null,
        whats_included:     document.getElementById('rs-whats-included')?.value.trim() || null,
        known_defects:      document.getElementById('rs-known-defects')?.value.trim() || null,
        tags:               document.getElementById('rs-tags')?.value.trim() || null,
      })});
      _savedLid = row.id;

      // Upload photos
      const files = _pendingFiles.filter(Boolean);
      for (const f of files) {
        const fd = new FormData(); fd.append('file', f);
        try {
          await fetch(`${API}/api/resell/listings/${_savedLid}/photos`, {method:'POST', body:fd});
        } catch {}
      }

      toast('✅ Listing saved with ' + files.length + ' photo(s)!');
      btn.textContent = '✅ Saved — ID #' + _savedLid;
      document.getElementById('rs-post-section').style.display = 'block';
      rsLoadDraft();
    } catch(e) {
      toast('❌ Save failed: ' + e.message);
      btn.disabled = false; btn.textContent = '💾 Save Listing';
    }
  });

  // Post to platforms
  document.getElementById('rs-post-btn')?.addEventListener('click', async () => {
    if (!_savedLid) { toast('Save the listing first.'); return; }
    const platforms = [...document.querySelectorAll('[name=rs-platform]:checked')].map(c=>c.value);
    if (!platforms.length) { toast('Select at least one platform.'); return; }
    const btn = document.getElementById('rs-post-btn');
    const status = document.getElementById('rs-post-status');
    btn.disabled = true; btn.textContent = '⏳ Starting…';
    status.textContent = '';
    try {
      const data = await api(`/api/resell/listings/${_savedLid}/post`, {method:'POST', body:JSON.stringify({platforms})});
      status.textContent = `Task #${data.task_id} started — browser automation running…`;
      // Poll for task completion
      const pollTask = async (taskId, attempt=0) => {
        if (attempt > 30) { status.textContent = 'Task taking longer than expected. Check back later.'; return; }
        const t = await api(`/api/resell/tasks/${taskId}`);
        if (t.status === 'done') {
          const results = JSON.parse(t.result || '{}');
          const summary = Object.entries(results).map(([p,r]) =>
            `${p}: ${r.status === 'posted' ? '✅' : r.status === 'needs_login' ? '🔐 needs login' : '❌ ' + r.status}`
          ).join(' | ');
          status.textContent = summary;
          btn.disabled = false; btn.textContent = '🚀 Post Now (Browser Automation)';
          toast('Posting complete: ' + summary);
        } else if (t.status === 'failed') {
          status.textContent = '❌ Failed: ' + (t.error || 'unknown');
          btn.disabled = false; btn.textContent = '🚀 Post Now (Browser Automation)';
        } else {
          status.textContent = `Task #${taskId} ${t.status}…`;
          setTimeout(() => pollTask(taskId, attempt+1), 5000);
        }
      };
      setTimeout(() => pollTask(data.task_id), 3000);
    } catch(e) {
      toast('❌ ' + e.message);
      btn.disabled = false; btn.textContent = '🚀 Post Now (Browser Automation)';
    }
  });
}
