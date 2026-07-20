'use strict';

/* ── PLUGIN LOADER ── frontend half of the drop-in plugin system.
   The backend (app/plugin_host.py) discovers plugins/<name>/ folders at boot and
   lists them at /api/plugins; here we inject one sidebar nav item per LOADED
   plugin (grouped under its nav_group, default "Plugins") and <script>-load each
   plugin's frontend. Each frontend calls registerView(view, fn); the injected
   nav item carries data-view=<view>, so the EXISTING delegated #main-nav click
   handler and renderView's default: case dispatch to PLUGIN_VIEWS[view] — no
   core edits per plugin, ever. Author contract: plugins/README.md.

   Hardening (a plugin can never break the app):
   - plugins with status "disabled" or "failed" get NO nav item and NO script
     (manage them in Settings → 🔌 Plugins); v1 backends without a status field
     are treated as loaded.
   - a frontend script that fails to load marks its nav item with ⚠ + tooltip.
   - registerView refuses to overwrite a core view or another plugin's view. */

window.PLUGIN_VIEWS = window.PLUGIN_VIEWS || {};

/* Core view ids owned by app-nav.js renderView — a plugin may never shadow one. */
const _CORE_VIEWS = new Set([
  'dashboard', 'world', 'finance', 'treasury', 'etsy-printify', 'cults3d',
  'portal', 'social', 'money', 'mail', 'github', 'resell', 'settings', 'agent',
  'library', 'graph', 'network-security', 'homelab', 'crypto', 'oracle',
  'research', 'wallets', 'nsfw', 'studio', 'image-gen', 'videos', 'audio',
  'models3d', 'models', 'proposals', 'review', 'approved', 'published',
  'store-stats', 'products',
]);

/* Called by each plugin's frontend.js: registerView('myview', renderMyView).
   renderView() falls through to PLUGIN_VIEWS[view]() for any unknown view.
   First registration wins — a core id or an already-taken view is refused. */
function registerView(view, fn) {
  if (_CORE_VIEWS.has(view)) {
    console.warn(`[plugins] registerView('${view}') ignored — collides with a core view`);
    return;
  }
  if (window.PLUGIN_VIEWS[view]) {
    console.warn(`[plugins] registerView('${view}') ignored — already registered by another plugin`);
    return;
  }
  window.PLUGIN_VIEWS[view] = fn;
}
window.registerView = registerView;

/* Run once on boot (from the DOMContentLoaded handler in index.html).
   Tolerant by design: no plugins dir, an empty list, or a failed fetch → the
   app boots exactly as before, silently. */
async function initPlugins() {
  let plugins = [];
  try {
    const r = await api('/api/plugins');
    plugins = (r && r.plugins) || [];
  } catch { return; }   // endpoint missing / erroring → no plugins, no noise
  if (!plugins.length) return;

  const nav = document.getElementById('main-nav');
  if (!nav) return;
  const groups = {};   // nav_group name → its .nav-group-items container
  for (const p of plugins) {
    if (!p || !p.view) continue;
    // Disabled/failed plugins stay out of the nav entirely (see Settings →
    // Plugins). Tolerant: a v1 backend sends no status → treat as loaded.
    if (p.status && p.status !== 'loaded') continue;
    const gname = p.nav_group || 'Plugins';
    if (!groups[gname]) {
      const g = document.createElement('div');
      g.className = 'nav-group';
      // Stable data-group id so collapse state persists (saveNavGroups/restoreNavGroups).
      g.dataset.group = 'plugin-' + gname.toLowerCase().replace(/[^a-z0-9]+/g, '-');
      g.innerHTML = `<div class="nav-group-title">${esc(gname)} <span class="nav-group-chev">&#9662;</span></div>
        <div class="nav-group-items"></div>`;
      nav.appendChild(g);
      groups[gname] = g.querySelector('.nav-group-items');
    }
    const item = document.createElement('div');
    item.className = 'nav-item';
    item.dataset.view = p.view;
    item.innerHTML = `<span class="nav-icon">${esc(p.icon || '\u{1F9E9}')}</span><span>${esc(p.name || p.id)}</span>`;
    groups[gname].appendChild(item);
    // Load the plugin's frontend — it registers its render fn via registerView().
    // Plain script tag on purpose: NO ?v= (a manual ?v disables the app's own
    // cache-busting, and /plugins/* already ships a short max-age).
    if (p.frontend_url) {
      const s = document.createElement('script');
      s.src = API + p.frontend_url;
      s.onerror = () => {
        // Script 404/parse-load failure → flag the nav item, don't break anything.
        const warn = document.createElement('span');
        warn.textContent = '⚠';
        warn.title = `${p.name || p.id}: frontend script failed to load (${p.frontend_url})`;
        warn.style.cssText = 'margin-left:auto;color:var(--warn,#f59e0b);';
        item.appendChild(warn);
      };
      document.body.appendChild(s);
    }
  }
  // Re-apply saved collapsed state to the freshly injected plugin groups.
  if (typeof restoreNavGroups === 'function') restoreNavGroups();
}
window.initPlugins = initPlugins;
