'use strict';

/* ── STUDIO HUB view root ── (falls back to #main-content when standalone) */
function viewRoot() {
  return document.getElementById('studio-content') || document.getElementById('main-content');
}

/* ── NAV ── */
document.getElementById('main-nav').addEventListener('click', e => {
  // collapse/expand a group when its title is clicked
  const title = e.target.closest('.nav-group-title');
  if (title) {
    const g = title.parentElement;
    g.classList.toggle('collapsed');
    saveNavGroups();
    return;
  }
  const item = e.target.closest('[data-view]');
  if (!item) return;
  switchView(item.dataset.view);
});

function saveNavGroups() {
  try {
    const collapsed = [...document.querySelectorAll('.nav-group.collapsed')].map(g => g.dataset.group);
    localStorage.setItem('navCollapsed', JSON.stringify(collapsed));
  } catch {}
}
function restoreNavGroups() {
  try {
    const collapsed = JSON.parse(localStorage.getItem('navCollapsed') || '[]');
    collapsed.forEach(name => {
      const g = document.querySelector(`.nav-group[data-group="${name}"]`);
      if (g) g.classList.add('collapsed');
    });
  } catch {}
}
restoreNavGroups();

// Legacy money views now live as panes inside the 💰 Finance tab. The old ids
// stay valid switchView targets (dashboard cards etc. deep-link to them) — they
// highlight the Finance nav item and open Finance on the right pane.
const _FIN_VIEW_ALIASES = { treasury: 'finance', money: 'finance', crypto: 'finance', wallets: 'finance' };

function switchView(view) {
  _currentView = view;
  const navView = _FIN_VIEW_ALIASES[view] || view;
  document.querySelectorAll('.nav-item').forEach(n => n.classList.toggle('active', n.dataset.view === navView));
  // update the header title from the matching nav item's label
  const active = document.querySelector(`.nav-item[data-view="${navView}"] span:not(.nav-icon):not(.nav-badge)`);
  const tt = document.getElementById('topbar-title');
  if (tt && active) tt.textContent = active.textContent;
  renderView(view);
}

async function renderView(view) {
  const main = document.getElementById('main-content');
  main.innerHTML = '<div class="empty"><div class="empty-icon">&#9203;</div>Loading&#8230;</div>';
  // NOTE: do NOT reset _cardsBound here — bindCards attaches a single permanent
  // delegated listener that handles all views; resetting causes listener accumulation.
  try {
    switch (view) {
      case 'dashboard':     await renderDashboard();       break;
      case 'world':         await renderWorld();           break;
      // Finance hub — Overview / Treasury / Missions & Earn / Wallets / Markets
      // as sub-tab panes. Legacy view names deep-link straight to their pane.
      case 'finance':       await renderFinance();             break;
      case 'treasury':      await renderFinance('treasury');   break;
      case 'etsy-printify': await renderEtsyPrintify();    break;
      case 'cults3d':       await renderCults3D();         break;
      case 'portal':        await renderPortal();          break;
      case 'social':        await renderSocial();          break;
      case 'money':         await renderFinance('money');      break;
      case 'mail':          await renderMail();            break;
      case 'github':        await renderGithub();          break;
      case 'resell':        await renderResell();          break;
      case 'settings':      await renderSettings();        break;
      case 'agent':         await renderAgent();           break;
      case 'library':       await renderLibrary();         break;
      case 'graph':         await renderGraph();           break;
      case 'network-security': await renderNetworkSecurity(); break;
      case 'homelab':       await renderHomelab();         break;
      case 'crypto':        await renderFinance('crypto');     break;
      case 'oracle':        await renderOracle();          break;
      case 'research':      await renderResearch();        break;
      case 'games':         await renderGames();           break;
      case 'wallets':       await renderFinance('wallets');    break;
      case 'nsfw':          await renderNsfw();            break;
      // Studio hub — Image / Video / Audio / 3D / Models / Queue as sub-tabs.
      // Legacy view names deep-link straight to the matching sub-tab.
      case 'studio':        await renderStudio();          break;
      case 'image-gen':     await renderStudio('image');   break;
      case 'videos':        await renderStudio('video');   break;
      case 'audio':         await renderStudio('audio');   break;
      case 'models3d':      await renderStudio('3d');       break;
      case 'models':        await renderStudio('models');  break;
      // Legacy direct views (still accessible, redirect into E/P subtab)
      case 'proposals':     _etsySubTab='proposals';  await switchView('etsy-printify'); break;
      case 'review':        _etsySubTab='review';     await switchView('etsy-printify'); break;
      case 'approved':      _etsySubTab='approved';   await switchView('etsy-printify'); break;
      case 'published':     _etsySubTab='published';  await switchView('etsy-printify'); break;
      case 'store-stats':   _etsySubTab='store-stats';await switchView('etsy-printify'); break;
      case 'products':      _etsySubTab='products';   await switchView('etsy-printify'); break;
      // Drop-in plugins: any view registered via registerView() (plugin-loader.js).
      // A crashing plugin render paints an in-view error card — never breaks nav.
      default:
        if (window.PLUGIN_VIEWS && PLUGIN_VIEWS[view]) {
          try { await PLUGIN_VIEWS[view](); }
          catch (pe) {
            main.innerHTML = `<div class="card" style="padding:18px;max-width:620px;">
              <h3 style="margin:0 0 8px;">&#9888;&#65039; Plugin view failed</h3>
              <div style="font-size:.85rem;">The <b>${esc(view)}</b> plugin threw while rendering:</div>
              <pre style="margin:10px 0;padding:10px;background:var(--surface);border:1px solid var(--border);border-radius:8px;font-size:.75rem;white-space:pre-wrap;overflow-x:auto;">${esc(pe && pe.message ? pe.message : String(pe))}</pre>
              <div style="font-size:.78rem;color:var(--muted);">The rest of the store is unaffected. You can disable this plugin in Settings &rarr; &#128268; Plugins.</div>
            </div>`;
          }
        }
        break;
    }
  } catch(e) {
    main.innerHTML = `<div class="empty"><div class="empty-icon">&#10060;</div>${esc(e.message)}</div>`;
  }
  bindCards();
}
