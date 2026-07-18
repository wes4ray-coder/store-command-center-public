/* ══ CULTS3D TAB ══
   Account + a live dashboard: your listings, sales/download stats, and shortcuts
   into 3D Studio (where the review → publish → pricing pipeline actually lives). */
async function renderCults3D() {
  let settings = {};
  try { settings = await api('/api/settings'); } catch {}
  const apiKey   = settings.cults3d_api_key  || '';
  const username = settings.cults3d_username || '';
  const connected = !!(apiKey && username);

  document.getElementById('main-content').innerHTML = `
    <div class="view-header">
      <div class="view-title">&#128424;&#65039; Cults3D</div>
      <div class="view-sub">Your Cults3D storefront &mdash; listings, sales, and one-click into the 3D publishing pipeline.</div>
    </div>

    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px;max-width:1040px;">
      <div class="settings-group">
        <div class="settings-group-title">&#128279; Account</div>
        <div class="field"><label>Username ${hlp('Your Cults3D account username. Paired with the API key (HTTP Basic auth) to reach the Cults3D GraphQL API, and used to build your public profile link.')}</label>
          <input type="text" id="c3d-username" value="${esc(username)}" placeholder="your-username"></div>
        <div class="field"><label>API Key <span style="font-size:.66rem;color:var(--warn);">(long token &mdash; NOT your password)</span> ${hlp('The API token from cults3d.com/en/api (works even with Google login) — not your password. Saved to app settings and used to authenticate every Cults3D call: listing your creations and publishing new ones.')}</label>
          <input type="password" id="c3d-apikey" value="${esc(apiKey)}" placeholder="Token from cults3d.com/en/api"></div>
        <div style="font-size:.72rem;color:var(--muted);line-height:1.6;background:rgba(108,99,255,.08);border:1px solid var(--border);border-radius:8px;padding:8px 10px;margin-top:4px;">
          &#128161; Connect with an <b>API key</b>, not your password (works even with Google login).
          <a href="https://cults3d.com/en/api" target="_blank" rel="noopener" style="color:var(--accent2);">cults3d.com/en/api &#8599;</a>
        </div>
        <div style="margin-top:12px;display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
          <button class="btn-sm primary" id="c3d-save">&#128190; Save</button>
          <button class="btn-sm" id="c3d-test" onclick="cults3dTest()" title="Save the username and API key, then call the Cults3D API to confirm they work (fetches your account nickname). Shows connected or an error below.">&#128268; Test</button>
          ${username ? `<a href="https://cults3d.com/en/users/${esc(username)}" target="_blank" rel="noopener" class="btn-sm">&#8599; Profile</a>` : ''}
        </div>
        <div id="c3d-status" style="font-size:.78rem;margin-top:8px;"></div>
      </div>

      <div class="settings-group">
        <div class="settings-group-title">&#128640; Publishing pipeline</div>
        <div style="font-size:.8rem;color:var(--muted);line-height:1.7;margin-bottom:10px;">
          Uploading, AI listings, pricing &amp; licensing all live in <b>3D Studio</b> &mdash; review your
          backlog, generate images, and publish to Cults3D via the API.
        </div>
        <div style="display:flex;flex-direction:column;gap:6px;">
          <button class="btn-sm primary" onclick="switchView('models3d')" title="Go to 3D Studio to review your model backlog and publish a model to Cults3D via its API (createCreation) — this is where the actual upload happens.">&#128230; Review &amp; publish 3D models &rarr;</button>
          <button class="btn-sm" onclick="switchView('models3d')" title="Go to 3D Studio to turn an image into a 3D model (TripoSR) before listing it.">&#10024; Generate a 3D model from an image &rarr;</button>
          <button class="btn-sm" onclick="switchView('models3d')" title="Go to 3D Studio to set each listing price and license before publishing to Cults3D.">&#127991;&#65039; Manage pricing &amp; licensing &rarr;</button>
        </div>
      </div>
    </div>

    <div id="c3d-stats" style="margin-top:20px;"></div>
    <div id="c3d-creations" style="margin-top:16px;">${connected ? '<div class="loading-state">Loading your Cults3D listings…</div>' : ''}</div>`;

  document.getElementById('c3d-save')?.addEventListener('click', async () => {
    const btn = document.getElementById('c3d-save');
    btn.disabled = true; btn.textContent = '⏳ Saving…';
    try {
      await api('/api/settings', { method:'PATCH', body: JSON.stringify({
        cults3d_username: document.getElementById('c3d-username').value.trim(),
        cults3d_api_key:  document.getElementById('c3d-apikey').value.trim(),
      }) });
      toast('✅ Cults3D settings saved!');
      cults3dLoadCreations();
    } catch(e) { toast('Save failed: ' + e.message, 'error'); }
    finally { btn.disabled = false; btn.textContent = '\u{1F4BE} Save'; }
  });

  if (connected) cults3dLoadCreations();
}
window.renderCults3D = renderCults3D;

async function cults3dTest() {
  const st = document.getElementById('c3d-status');
  const btn = document.getElementById('c3d-test');
  try {
    await api('/api/settings', { method: 'PATCH', body: JSON.stringify({
      cults3d_username: document.getElementById('c3d-username').value.trim(),
      cults3d_api_key:  document.getElementById('c3d-apikey').value.trim(),
    }) });
  } catch {}
  btn.disabled = true; btn.textContent = '⏳ Testing…';
  st.style.color = 'var(--muted)'; st.textContent = 'Connecting to Cults3D…';
  try {
    const r = await api('/api/cults3d/test', { method: 'POST' });
    st.style.color = 'var(--green)';
    st.innerHTML = `✅ Connected as <b>${esc(r.nick || 'unknown')}</b>.`;
    toast('Cults3D connected!');
    cults3dLoadCreations();
  } catch (e) {
    st.style.color = 'var(--warn)';
    st.textContent = '❌ ' + e.message;
  } finally { btn.disabled = false; btn.textContent = '🔌 Test'; }
}
window.cults3dTest = cults3dTest;

async function cults3dLoadCreations() {
  const box = document.getElementById('c3d-creations');
  const statsBox = document.getElementById('c3d-stats');
  if (!box) return;
  box.innerHTML = '<div class="loading-state">Loading your listings…</div>';
  try {
    const r = await api('/api/cults3d/creations');
    const items = r.creations || [];
    // Derived stats (Cults' API exposes downloadsCount + price per creation).
    const totalDownloads = items.reduce((s,c)=> s + (c.downloadsCount||0), 0);
    const priced = items.filter(c => c.price && c.price.cents);
    const avgPrice = priced.length ? (priced.reduce((s,c)=>s+c.price.cents,0)/priced.length/100) : 0;
    if (statsBox) statsBox.innerHTML = `
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;max-width:640px;">
        ${cults3dStat('🖨️', items.length, 'Live listings')}
        ${cults3dStat('⬇️', totalDownloads.toLocaleString(), 'Total downloads')}
        ${cults3dStat('💲', priced.length ? '$'+avgPrice.toFixed(2) : 'Free', 'Avg price')}
      </div>`;
    const hidden = r.hidden_count || 0;
    const hiddenBanner = hidden > 0 ? `<div style="background:#2a1005;border:1px solid #f59e0b80;border-radius:8px;padding:8px 10px;color:#fcd34d;font-size:.8rem;margin-bottom:10px;">&#128286; <b>${hidden} listing(s) hidden</b> — you have <b>${r.total_count}</b> total but Cults3D's API only returns the ${items.length} non-adult ones. Those ${hidden} are your <b>mature/NSFW items</b>. Cults3D provides no way to fetch them via the API, so manage them on <a href="https://cults3d.com" target="_blank" rel="noopener" style="color:#fcd34d;text-decoration:underline;">cults3d.com</a>. (They still sell — they're just not listable here.)</div>` : '';
    if (!items.length && !hidden) { box.innerHTML = '<div class="empty" style="padding:16px;">No listings yet. Publish from <b>3D Studio</b>.</div>'; return; }
    if (!items.length) { box.innerHTML = hiddenBanner; return; }
    box.innerHTML = hiddenBanner + `<div class="section-header"><div class="section-title">🖨️ Your Cults3D Listings (${items.length}${hidden?` of ${r.total_count}`:''})</div>
        <button class="btn-sm" onclick="cults3dLoadCreations()" title="Reload your live listings and stats straight from the Cults3D API.">↻ Refresh</button></div>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px;">
      ${items.map(c => `
        <a href="${esc(c.url || '#')}" target="_blank" rel="noopener" class="stat-card" style="text-decoration:none;color:inherit;padding:0;overflow:hidden;">
          ${c.illustrationImageUrl ? `<img src="${esc(c.illustrationImageUrl)}" loading="lazy" decoding="async" style="width:100%;height:130px;object-fit:cover;">` : ''}
          <div style="padding:8px 10px;">
            <div style="font-weight:600;font-size:.8rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(c.name || 'Untitled')}</div>
            <div style="font-size:.72rem;color:var(--muted);">${c.price ? (c.price.cents/100).toFixed(2) + ' ' + (c.price.currency || '') : 'Free'} ${c.downloadsCount != null ? '· ⬇ ' + c.downloadsCount : ''}</div>
          </div>
        </a>`).join('')}
      </div>`;
  } catch (e) {
    box.innerHTML = `<div style="color:var(--warn);padding:12px;font-size:.8rem;">Couldn't load listings: ${esc(e.message)}<br><span style="color:var(--muted)">Hit <b>Test</b> above to check your connection.</span></div>`;
    if (statsBox) statsBox.innerHTML = '';
  }
}
window.cults3dLoadCreations = cults3dLoadCreations;

function cults3dStat(icon, value, label) {
  return `<div class="stat-card" style="text-align:center;padding:14px 10px;">
    <div style="font-size:1.4rem;">${icon}</div>
    <div style="font-size:1.3rem;font-weight:700;margin-top:2px;">${esc(String(value))}</div>
    <div style="font-size:.72rem;color:var(--muted);">${esc(label)}</div>
  </div>`;
}
