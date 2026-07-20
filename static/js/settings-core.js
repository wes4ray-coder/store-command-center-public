/* Settings tab renderer. Split from app-main.js; the admin panel lives in admin.js. */
/* ══ SETTINGS ══ */
/* Helper: load trend sources into the #trend-body div inside Settings */
async function _loadTrendIntoSettings() {
  let cfg = {}, scanStatus = {};
  try { cfg = await api('/api/trends/config'); } catch {}
  try { scanStatus = await api('/api/trends/status'); } catch {}
  const body = document.getElementById('trend-body');
  if (!body) return;

  const googleOn  = cfg.google_enabled !== false;
  const redditOn  = cfg.reddit_enabled !== false;
  const rssOn     = cfg.rss_enabled    !== false;
  const rssFeeds  = cfg.rss_urls ? cfg.rss_urls.split('\n').filter(Boolean) : [];
  const redditSubs = cfg.reddit_subs || '';
  const scanMsg = scanStatus.status === 'running'
    ? '&#9881; Scanning now…'
    : esc(scanStatus.message || (cfg.last_run ? `Last scan: ${new Date(cfg.last_run).toLocaleString()} — ${cfg.last_count||0} proposals added` : 'No scans run yet'));

  let th = `
    <div style="font-size:.78rem;color:var(--muted);margin-bottom:10px;">${scanMsg}</div>
    <div style="margin-bottom:12px;"><button class="btn-sm primary" id="scan-now-btn" title="Scan every enabled source now and turn trending topics into product proposals in the Backlog. Runs on this server; takes a minute or two.">&#128269; Scan Now</button></div>
    <div class="trend-grid">
      <div class="trend-card">
        <div class="trend-card-header">
          <div class="trend-card-title">&#127758; Google Trends</div>
          <div class="toggle ${googleOn?'on':''}" id="toggle-google" data-source="google" title="Include Google Trends when scanning. On = a scan pulls trending searches for the region below into the proposal Backlog. Saved instantly."></div>
        </div>
        <div class="field">
          <label>Region ${hlp('Which country Google Trends pulls trending searches from during a scan. Affects the Google source only. Saved the moment you change it.')}</label>
          <select id="google-region">
            ${['US','GB','CA','AU','DE','FR','JP','BR','IN','MX'].map(r => `<option value="${r}"${cfg.google_region===r?' selected':''}>${r}</option>`).join('')}
          </select>
        </div>
      </div>
      <div class="trend-card">
        <div class="trend-card-header">
          <div class="trend-card-title">&#128992; Reddit</div>
          <div class="toggle ${redditOn?'on':''}" id="toggle-reddit" data-source="reddit" title="Include Reddit when scanning. On = a scan reads hot posts from the subreddits below into the proposal Backlog. Saved instantly."></div>
        </div>
        <div class="field">
          <label>Subreddits (comma-separated) ${hlp('Which subreddits a scan reads hot posts from when Reddit is on. Comma-separated (e.g. gifts, cats, woodworking). Click Save Subreddits to apply.')}</label>
          <textarea id="reddit-subs" rows="4" style="font-size:.73rem;resize:vertical;">${esc(redditSubs)}</textarea>
        </div>
        <button class="btn-sm" id="save-reddit-btn" style="margin-top:6px;">&#128190; Save Subreddits</button>
      </div>
      <div class="trend-card">
        <div class="trend-card-header">
          <div class="trend-card-title">&#128225; RSS Feeds</div>
          <div class="toggle ${rssOn?'on':''}" id="toggle-rss" data-source="rss" title="Include your custom RSS feeds when scanning. On = a scan reads new items from the feed URLs below into the proposal Backlog. Saved instantly."></div>
        </div>`;
  if (rssFeeds.length) {
    th += `<ul class="rss-list">`;
    for (const feed of rssFeeds)
      th += `<li class="rss-item"><span class="rss-item-url" title="${esc(feed)}">${esc(feed)}</span><button class="btn-sm" style="padding:2px 7px;font-size:.68rem;" data-action="remove-rss" data-url="${esc(feed)}">&#10005;</button></li>`;
    th += `</ul>`;
  } else {
    th += `<div style="font-size:.75rem;color:var(--muted);margin-bottom:8px;">No custom feeds added.</div>`;
  }
  th += `<div class="add-rss-row">
    <input type="text" id="rss-add-input" placeholder="https://feed.url/rss.xml">
    <button class="btn-sm primary" id="rss-add-btn">Add</button>
  </div></div></div>`;

  body.innerHTML = th;

  document.getElementById('scan-now-btn')?.addEventListener('click', async () => {
    const btn = document.getElementById('scan-now-btn');
    btn.disabled = true; btn.textContent = '\u231B Scanning…';
    try {
      const r = await api('/api/trends/scan', { method: 'POST' });
      if (r.ok === false) { toast(r.message || 'Already scanning', 'warn'); return; }
      toast('Trend scan started!');
      for (let i = 0; i < 120; i++) {
        await new Promise(res => setTimeout(res, 3000));
        const st = await api('/api/trends/status');
        if (st.status !== 'running') { toast(st.message || 'Scan complete'); _loadTrendIntoSettings(); return; }
      }
    } catch(e) { toast('Scan error: ' + e.message, 'error'); }
    finally { btn.disabled = false; btn.textContent = '\u{1F50D} Scan Now'; }
  });

  body.querySelectorAll('.toggle[data-source]').forEach(el => {
    el.addEventListener('click', async () => {
      el.classList.toggle('on');
      const on = el.classList.contains('on');
      const patch = {}; patch[el.dataset.source + '_enabled'] = on;
      try {
        await api('/api/trends/config', { method: 'PATCH', body: JSON.stringify(patch) });
        toast(`${el.dataset.source} trends ${on ? 'enabled' : 'disabled'}`);
      } catch(e) { toast('Error: ' + e.message, 'error'); el.classList.toggle('on'); }
    });
  });

  document.getElementById('google-region')?.addEventListener('change', async (e) => {
    try { await api('/api/trends/config', { method: 'PATCH', body: JSON.stringify({ google_region: e.target.value }) }); toast('Region saved'); }
    catch(e2) { toast('Error: ' + e2.message, 'error'); }
  });

  document.getElementById('save-reddit-btn')?.addEventListener('click', async () => {
    const subs = document.getElementById('reddit-subs').value.trim();
    try { await api('/api/trends/config', { method: 'PATCH', body: JSON.stringify({ reddit_subs: subs }) }); toast('Subreddits saved \u2713'); }
    catch(e) { toast('Error: ' + e.message, 'error'); }
  });

  document.getElementById('rss-add-btn')?.addEventListener('click', async () => {
    const input = document.getElementById('rss-add-input');
    const url = input.value.trim();
    if (!url) return;
    try {
      const cfg2 = await api('/api/trends/config');
      const feeds = [...(cfg2.rss_urls ? cfg2.rss_urls.split('\n').filter(Boolean) : []), url];
      await api('/api/trends/config', { method: 'PATCH', body: JSON.stringify({ rss_urls: feeds.join('\n') }) });
      toast('Feed added'); input.value = ''; _loadTrendIntoSettings();
    } catch(e) { toast('Error: ' + e.message, 'error'); }
  });

  // Bind to the freshly rendered buttons — NOT a delegated listener on #trend-body,
  // which persists across re-renders and would stack a duplicate handler per reload.
  body.querySelectorAll('[data-action="remove-rss"]').forEach(btn => {
    btn.addEventListener('click', async () => {
      try {
        const cfg2 = await api('/api/trends/config');
        const feeds = (cfg2.rss_urls ? cfg2.rss_urls.split('\n').filter(Boolean) : []).filter(f => f !== btn.dataset.url);
        await api('/api/trends/config', { method: 'PATCH', body: JSON.stringify({ rss_urls: feeds.join('\n') }) });
        toast('Feed removed'); _loadTrendIntoSettings();
      } catch(e) { toast('Error: ' + e.message, 'error'); }
    });
  });
}

// Settings sub-tabs: every field stays in the DOM (so all save/wire logic is
// untouched) — we only toggle which pane is visible.
const _SETTINGS_PANES = ['system', 'models', 'integrations', 'store', 'account', 'prompts', 'systems', 'plugins'];
function settingsSub(k) {
  _SETTINGS_PANES.forEach(name => {
    const pane = document.getElementById('pane-' + name);
    if (pane) pane.style.display = (name === k) ? '' : 'none';
  });
  document.querySelectorAll('#settings-subtabs .subtab').forEach((el, i) => {
    el.classList.toggle('active', _SETTINGS_PANES[i] === k);
  });
  if (k === 'prompts') loadPromptsEditor();
  if (k === 'models') loadModelRegistry();
  if (k === 'systems' && typeof renderSystemsPane === 'function') renderSystemsPane();
  if (k === 'plugins' && typeof renderPluginsPane === 'function') renderPluginsPane();
}

async function renderSettings() {
  let settings = {}, settingsLoaded = true;
  try { settings = await api('/api/settings'); } catch { settingsLoaded = false; }
  // Etsy connection status hits Etsy's external API and is slow — load it AFTER paint
  // (see _loadEtsyStatus) so the Settings tab appears instantly.

  let h = `
    <div class="view-header"><div class="view-title">&#9881;&#65039; Settings</div><div class="view-sub">Configure integrations, your store, the system, and your account.</div></div>
    <div class="subtab-bar" id="settings-subtabs" style="margin-bottom:16px;">
      <div class="subtab active" onclick="settingsSub('system')">&#128421;&#65039; System</div>
      <div class="subtab" onclick="settingsSub('models')">&#129504; Models</div>
      <div class="subtab" onclick="settingsSub('integrations')">&#128279; Integrations</div>
      <div class="subtab" onclick="settingsSub('store')">&#127978; Store &amp; Content</div>
      <div class="subtab" onclick="settingsSub('account')">&#128274; Account</div>
      <div class="subtab" onclick="settingsSub('prompts')">&#128221; Prompts</div>
      <div class="subtab" onclick="settingsSub('systems')">&#129513; Systems</div>
      <div class="subtab" onclick="settingsSub('plugins')">&#128268; Plugins</div>
    </div>

    <div class="settings-tabpane" id="pane-system">
      <div class="settings-grid">
      <div class="settings-group" id="admin-panel-slot">
        <div class="settings-group-title">&#128421;&#65039; System</div>
        <div style="font-size:.78rem;color:var(--muted);">Loading&hellip;</div>
      </div>
      <div class="settings-group" id="updates-slot">
        <div class="settings-group-title">&#128260; Updates</div>
        <div style="font-size:.78rem;color:var(--muted);">Loading&hellip;</div>
      </div>
      <div class="settings-group" id="github-slot">
        <div class="settings-group-title">&#128025; GitHub</div>
        <div style="font-size:.78rem;color:var(--muted);">Loading&hellip;</div>
      </div>
      </div>
    </div>

    <div class="settings-tabpane" id="pane-models" style="display:none;">
      <div class="settings-group">
        <div class="settings-group-title">&#129504; Models — one place to pick what runs where</div>
        <div style="font-size:.78rem;color:var(--muted);margin-bottom:12px;line-height:1.5">
          Every feature that uses an AI model, with the model it's set to. LLM/text and vision jobs
          all funnel through the <b>unified GPU queue</b> (the single authority that loads &amp; unloads
          models on the node) — including OpenClaw's local agents — so the model you pick here is what
          the queue loads for that job. Changes apply on the next job (no restart).
        </div>
        <div id="model-registry-slot" style="font-size:.8rem;color:var(--muted)">Loading&hellip;</div>
      </div>
    </div>

    <div class="settings-tabpane" id="pane-integrations" style="display:none;">
      <div class="settings-grid">
      <div class="settings-group">
        <div class="settings-group-title">&#128424;&#65039; Printify</div>
        <div class="field"><label>API Key ${hlp('Your Printify personal access token (Printify \u2192 Settings \u2192 Connections). Lets the app create products and push them to your print-on-demand shop. Stored locally; never shown after saving.')}</label><input type="password" id="s-printify-key" value="${esc(settings.printify_key||'')}" placeholder="pk_\u2026"></div>
        <div class="field"><label>Shop ID ${hlp('Which Printify shop to publish into (a Printify account can have several \u2014 Etsy, eBay, etc.). Click \u201cList Shops\u201d below to find the numeric ID. Determines where \u201c\u2192 Printify\u201d sends a design.')}</label><input type="text" id="s-printify-shop" value="${esc(settings.printify_shop_id||'')}" placeholder="12345678"></div>
        <div style="display:flex;gap:8px;margin-top:10px;">
          <button class="btn-sm primary" id="s-save">&#128190; Save</button>
          <button class="btn-sm" id="s-shops">&#127978; List Shops</button>
        </div>
        <div id="shops-list" style="margin-top:12px;font-size:.78rem;color:var(--muted);"></div>
      </div>
      <div class="settings-group">
        <div class="settings-group-title">&#128717; Etsy</div>
        <div class="field"><label>API Key ${hlp('Your Etsy app \u201ckeystring\u201d from the Etsy Developer portal. Used for the DIRECT Etsy listing path (creates draft listings via the Etsy API). Not needed if you sell through Printify\u2192Etsy.')}</label><input type="password" id="s-etsy-key" value="${esc(settings.etsy_key||'')}" placeholder="your-etsy-api-key"></div>
        <div class="field"><label>Shop ID ${hlp('Your Etsy shop name/ID that new draft listings are created under. Only used by the direct Etsy API path.')}</label><input type="text" id="s-etsy-shop" value="${esc(settings.etsy_shop_id||'')}" placeholder="MyEtsyShop"></div>
        <div class="field"><label>OAuth Secret ${hlp('The Etsy app\u2019s shared secret, paired with the API Key to authorize (OAuth) so the app can act on your shop. Kept local; only used by the direct Etsy path.')}</label><input type="password" id="s-etsy-secret" value="${esc(settings.etsy_shared_secret||'')}" placeholder="secret\u2026"></div>
        <div style="margin-top:6px;font-size:.78rem;color:var(--muted);">Status: <span id="etsy-conn-status" style="color:var(--muted)">Checking&hellip;</span></div>
        <div style="display:flex;gap:8px;margin-top:10px;">
          <button class="btn-sm primary" id="s-save-2">&#128190; Save</button>
          <span id="etsy-conn-btn"></span>
        </div>
        <div style="margin-top:12px;padding:10px;background:var(--surface);border-radius:8px;border:1px solid var(--border);font-size:.75rem;color:var(--muted);line-height:1.5;">
          <b style="color:var(--text);">&#9432; How Etsy works here &mdash; choose ONE path:</b><br><br>
          <b style="color:var(--text);">Path A &mdash; Printify &rarr; Etsy (recommended if Etsy is your Printify sales channel):</b><br>
          Click <b>&rarr; Printify</b> on an approved design. Printify creates the product AND automatically pushes a live listing to your connected Etsy store. Printify handles production &amp; fulfillment. <em>This is the right path if Etsy is set as your main store inside Printify.</em><br><br>
          <b style="color:var(--text);">Path B &mdash; Direct Etsy API:</b><br>
          Click <b>&#128717; Etsy</b> to create a draft listing directly on Etsy. Use this <em>only</em> if a design is NOT going through Printify (e.g. digital downloads, self-fulfilled items).<br><br>
          <b style="color:#e74c3c;">&#9888; DUPLICATE RISK:</b> If Etsy is already your Printify sales channel, using <em>both</em> buttons for the same design will create two Etsy listings. The app will warn you and block the Etsy button if a design is already published to Printify.
        </div>
      </div>
      <div class="settings-group" style="grid-column:1/-1;" id="peers-slot">
        <div class="settings-group-title">&#129309; Peers</div>
        <div style="font-size:.78rem;color:var(--muted);">Loading&hellip;</div>
      </div>
      </div>
    </div>

    <div class="settings-tabpane" id="pane-store" style="display:none;">
      <div class="settings-grid">
      <div class="settings-group">
        <div class="settings-group-title">&#127978; Store</div>
        <div class="field">
          <label>Store Name ${hlp('Your brand name. Shown in the app header and used as context when the LLM auto-writes listing titles/descriptions. Cosmetic + prompt context; does not rename anything on Etsy/Printify.')}</label>
          <input type="text" id="s-store-name" value="${esc(settings.store_name||'')}" placeholder="My Awesome Store">
          <div style="font-size:.7rem;color:var(--muted);margin-top:3px;">Displayed in the header &amp; used as a prefix when auto-generating listing titles.</div>
        </div>
        <div class="field">
          <label>Default Product Type ${hlp('The product (T-Shirt, Mug, Poster…) pre-selected when you open the “Publish to Printify” modal. Just a default to save clicks; you can change it per design.')}</label>
          <select id="s-default-product">${_productTypes.map(pt => `<option value="${esc(pt)}"${settings.default_product_type===pt?' selected':''}>${esc(pt)}</option>`).join('')}</select>
          <div style="font-size:.7rem;color:var(--muted);margin-top:3px;">Pre-selected when opening the Publish to Printify modal.</div>
        </div>
        <button class="btn-sm primary" id="s-save-4" style="margin-top:10px;">&#128190; Save</button>
      </div>
      <div class="settings-group" style="grid-column:1/-1;" id="trend-settings-section">
        <div class="settings-group-title">&#128200; Trend Sources</div>
        <div id="trend-body"><div style="color:var(--muted);font-size:.8rem;">Loading&#8230;</div></div>
      </div>
      <div class="settings-group" style="grid-column:1/-1;">
        <div class="settings-group-title">&#128247; Resell Preferences</div>
        <div style="font-size:.83rem;color:var(--muted);line-height:1.7;">
          Resell preferences (location, drive distance, payment methods, platform logins) have moved to the 📸 Resell tab.
        </div>
        <button class="btn-sm" style="margin-top:10px;" onclick="document.querySelector('[data-view=resell]').click()">→ Go to Resell → ⚙️ Preferences</button>
      </div>

      </div>
    </div>

    <div class="settings-tabpane" id="pane-account" style="display:none;">
      <div class="settings-grid">
      <div class="settings-group">
        <div class="settings-group-title">&#128274; Security</div>
        <div class="field"><label>Current Password ${hlp('This changes the LOGIN password for this dashboard (the one you type on the login screen). It is NOT any Etsy/Printify/Google password. You must enter the current one to set a new one; you’ll be signed out after changing it.')}</label><input type="password" id="s-pw-cur" placeholder="Current password"></div>
        <div class="field"><label>New Password</label><input type="password" id="s-pw-new" placeholder="New password (min 4 chars)"></div>
        <div class="field"><label>Confirm New Password</label><input type="password" id="s-pw-confirm" placeholder="Confirm new password"></div>
        <div style="display:flex;gap:8px;margin-top:10px;">
          <button class="btn-sm primary" id="s-pw-save">&#128274; Change Password</button>
          <a href="/store/logout" class="btn-sm danger" style="text-decoration:none;display:inline-flex;align-items:center;">&#128275; Sign Out</a>
        </div>
        <div id="s-pw-msg" style="margin-top:8px;font-size:.78rem;"></div>
      </div>
      </div>
    </div>

    <div class="settings-tabpane" id="pane-prompts" style="display:none;">
      <div class="settings-section-head">&#128221; Prompts</div>
      <div style="font-size:.8rem;color:var(--muted);margin-bottom:14px;max-width:760px;">
        Every LLM system prompt the app uses. Edit and Save to override; Reset restores the built-in default.
        Prompts marked <b style="color:var(--warn)">templated</b> contain <code>{placeholders}</code> &mdash; keep them intact.
      </div>
      <div id="prompts-list"><div style="color:var(--muted);font-size:.8rem;">Loading&#8230;</div></div>
    </div>

    <div class="settings-tabpane" id="pane-systems" style="display:none;">
      <div style="color:var(--muted);font-size:.8rem;">Loading&#8230;</div>
    </div>

    <div class="settings-tabpane" id="pane-plugins" style="display:none;">
      <div style="color:var(--muted);font-size:.8rem;">Loading&#8230;</div>
    </div>`;

  document.getElementById('main-content').innerHTML = h;
  if (window.mountAdminPanel) mountAdminPanel();
  loadUpdates();
  loadGithubSettings();
  loadPeers();

  async function saveAll() {
    if (!settingsLoaded) {
      // The initial GET failed, so the inputs rendered EMPTY — saving now would
      // overwrite real keys (Printify/Etsy credentials, store name) with ''.
      toast('Settings failed to load — refresh the page before saving.', 'error');
      return;
    }
    try {
      const patch = {
        printify_key:         document.getElementById('s-printify-key').value,
        printify_shop_id:     document.getElementById('s-printify-shop').value,
        etsy_key:             document.getElementById('s-etsy-key').value,
        etsy_shop_id:         document.getElementById('s-etsy-shop').value,
        etsy_shared_secret:   document.getElementById('s-etsy-secret').value,
        store_name:           document.getElementById('s-store-name').value,
        default_product_type: document.getElementById('s-default-product').value,
      };
      await api('/api/settings', { method: 'PATCH', body: JSON.stringify(patch) });
      try { _settings = await api('/api/settings'); } catch {}
      toast('Settings saved \u2713');
    } catch(e) { toast('Save failed: ' + e.message, 'error'); }
  }

  const pwSaveBtn = document.getElementById('s-pw-save');
  if (pwSaveBtn) pwSaveBtn.addEventListener('click', async () => {
    const cur = document.getElementById('s-pw-cur').value;
    const nw  = document.getElementById('s-pw-new').value;
    const cfm = document.getElementById('s-pw-confirm').value;
    const msg = document.getElementById('s-pw-msg');
    msg.style.color = 'var(--warn)'; msg.textContent = '';
    if (!cur || !nw)     { msg.textContent = 'Fill in current and new password.'; return; }
    if (nw !== cfm)      { msg.textContent = 'Passwords do not match.'; return; }
    if (nw.length < 4)   { msg.textContent = 'New password must be at least 4 characters.'; return; }
    try {
      await api('/api/auth/change-password', { method: 'POST', body: JSON.stringify({ current: cur, new_password: nw }) });
      msg.style.color = 'var(--green)'; msg.textContent = '\u2713 Password changed. You will be signed out.';
      document.getElementById('s-pw-cur').value = '';
      document.getElementById('s-pw-new').value = '';
      document.getElementById('s-pw-confirm').value = '';
      setTimeout(() => { window.location.href = '/store/logout'; }, 1500);
    } catch(e) { msg.textContent = 'Error: ' + e.message; }
  });

  ['s-save','s-save-2','s-save-4'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('click', saveAll);
  });

  // Load trend sources into the settings placeholder
  _loadTrendIntoSettings();

  const shopsBtn = document.getElementById('s-shops');
  if (shopsBtn) shopsBtn.addEventListener('click', async () => {
    shopsBtn.disabled = true; shopsBtn.textContent = '\u29d7\u2026';
    try {
      const shops = await api('/api/printify/shops');
      const el = document.getElementById('shops-list');
      el.innerHTML = (shops && shops.length)
        ? shops.map(s => `<div>\u2022 ${esc(s.title||s.id||JSON.stringify(s))}</div>`).join('')
        : 'No shops found';
    } catch(e) { toast('Error: ' + e.message, 'error'); }
    finally { shopsBtn.disabled = false; shopsBtn.textContent = '\u{1F3EA} List Shops'; }
  });

  _loadEtsyStatus();   // async — fills the Etsy status + connect/disconnect after paint
}

// Loads Etsy connection status (slow external API) after Settings has already rendered.
async function _loadEtsyStatus() {
  const st = document.getElementById('etsy-conn-status');
  const btn = document.getElementById('etsy-conn-btn');
  let es = {};
  try { es = await api('/api/etsy/status'); } catch {}
  if (st) st.innerHTML = es.connected
    ? `<span style="color:var(--green)">&#10003; Connected${es.shop_id ? ' &middot; Shop: ' + esc(es.shop_id) : ''}</span>`
    : `<span style="color:var(--muted)">Not connected</span>`;
  if (!btn) return;
  btn.innerHTML = es.connected
    ? `<button class="btn-sm danger" id="s-etsy-disconnect">Disconnect</button>`
    : `<button class="btn-sm" id="s-etsy-connect">&#128279; Connect Etsy</button>`;
  const c = document.getElementById('s-etsy-connect');
  if (c) c.addEventListener('click', async () => {
    try { const r = await api('/api/etsy/connect'); if (r.url) window.open(r.url, '_blank'); }
    catch (e) { toast('Error: ' + e.message, 'error'); }
  });
  const d = document.getElementById('s-etsy-disconnect');
  if (d) d.addEventListener('click', async () => {
    if (!confirm('Disconnect Etsy?')) return;
    try { await api('/api/etsy/disconnect', { method: 'DELETE' }); toast('Etsy disconnected'); renderSettings(); }
    catch (e) { toast('Error: ' + e.message, 'error'); }
  });
}
