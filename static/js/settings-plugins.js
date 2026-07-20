'use strict';

/* ── Settings → 🔌 Plugins ──────────────────────────────────────────────────
   Management pane for the drop-in plugin system (app/plugin_host.py +
   plugin-loader.js). Lists every discovered plugin with its status, lets you
   enable/disable each one (persisted; backend change applies on the next
   restart), and links the author contract (plugins/README.md).

   Tolerant by design: against a pre-restart v1 backend the entries have no
   status/enabled fields — rows degrade to "loaded" with the toggle still shown
   (toggling then errors with a friendly toast). All symbols are IIFE-scoped
   except the entry point window.renderPluginsPane (settings-systems.js pattern). */
(function () {

  function statusChip(p) {
    const st = p.status || 'loaded';   // v1 backend: no status field → loaded
    const S = {
      loaded:   { icon: '✅', color: 'var(--green)', bg: 'rgba(34,197,94,.14)'  },
      failed:   { icon: '❌', color: 'var(--red)',   bg: 'rgba(239,68,68,.14)'  },
      disabled: { icon: '⏸', color: 'var(--muted)', bg: 'rgba(100,116,139,.16)' },
    }[st] || { icon: '?', color: 'var(--muted)', bg: 'rgba(100,116,139,.16)' };
    return `<span style="font-size:.66rem;font-weight:700;padding:2px 8px;border-radius:9px;white-space:nowrap;
      color:${S.color};background:${S.bg};text-transform:uppercase;letter-spacing:.03em">${S.icon} ${esc(st)}</span>`;
  }

  function row(p) {
    const enabled = p.enabled !== false;              // tolerant: missing → enabled
    const err = p.error
      ? `<details style="margin-top:5px;"><summary style="cursor:pointer;font-size:.7rem;color:var(--red);">error details</summary>
           <pre style="margin:6px 0 0;padding:8px;background:var(--surface);border:1px solid var(--border);border-radius:6px;
             font-size:.68rem;white-space:pre-wrap;overflow-x:auto;color:var(--red);">${esc(p.error)}</pre></details>`
      : '';
    const restart = p.pending_restart
      ? `<span style="font-size:.62rem;font-weight:700;padding:2px 7px;border-radius:9px;color:var(--warn);
           background:rgba(245,158,11,.15);white-space:nowrap;">&#8635; applies on restart</span>`
      : '';
    const desc = p.description
      ? `<div style="font-size:.7rem;color:var(--muted);margin-top:3px;line-height:1.4;">${esc(p.description)}</div>`
      : '';
    return `<div style="display:grid;grid-template-columns:minmax(200px,2fr) 110px 60px 100px 150px;gap:10px;
        align-items:start;padding:11px 12px;border-bottom:1px solid var(--border);">
      <div>
        <div style="display:flex;align-items:center;gap:7px;flex-wrap:wrap;">
          <span style="font-size:1rem;">${esc(p.icon || '\u{1F9E9}')}</span>
          <b style="font-size:.82rem;">${esc(p.name || p.id)}</b>
          <span style="font-size:.68rem;color:var(--muted);">v${esc(p.version || '?')}</span>
        </div>
        ${desc}${err}
      </div>
      <div>${statusChip(p)}</div>
      <div style="text-align:center;font-size:.78rem;color:var(--muted);" title="Backend routes this plugin registered">${p.routes != null ? p.routes : '—'}</div>
      <div style="font-size:.7rem;color:#9fb4d8;align-self:center;">${esc(p.nav_group || 'Plugins')}</div>
      <div style="display:flex;align-items:center;gap:8px;">
        <div class="toggle ${enabled ? 'on' : ''}" data-plugin="${esc(p.id || '')}"
          title="Enable/disable this plugin. Off = no sidebar entry immediately (next refresh); its backend routes unload on the next restart."></div>
        ${restart}
      </div>
    </div>`;
  }

  async function renderPluginsPane() {
    const pane = document.getElementById('pane-plugins');
    if (!pane) return;
    let plugins = [];
    try {
      const r = await api('/api/plugins');
      plugins = (r && r.plugins) || [];
    } catch (e) {
      pane.innerHTML = `<div style="color:var(--muted);font-size:.8rem;">Couldn't load plugins: ${esc(e.message)}</div>`;
      return;
    }

    const rows = plugins.length
      ? `<div style="display:grid;grid-template-columns:minmax(200px,2fr) 110px 60px 100px 150px;gap:10px;padding:7px 12px;
           border-bottom:2px solid var(--border);font-size:.64rem;font-weight:700;text-transform:uppercase;
           letter-spacing:.04em;color:var(--muted);">
           <div>Plugin</div><div>Status</div><div style="text-align:center;">Routes</div><div>Nav group</div><div>Enabled</div>
         </div>` + plugins.map(row).join('')
      : `<div style="padding:14px 12px;color:var(--muted);font-size:.8rem;">No plugins installed yet.</div>`;

    pane.innerHTML = `
      <div class="settings-group" style="max-width:960px;">
        <div class="settings-group-title">&#128268; Plugins ${typeof hlp === 'function' ? hlp('Drop-in add-ons discovered from the plugins/ folder at boot. Disabling takes a plugin out of the sidebar immediately (next refresh); its backend routes stay mounted until the next restart. A failed plugin never affects the rest of the store.') : ''}</div>
        <div style="border:1px solid var(--border);border-radius:10px;overflow:hidden;">${rows}</div>
        <div style="margin-top:14px;padding:10px;background:var(--surface);border-radius:8px;border:1px solid var(--border);
            font-size:.75rem;color:var(--muted);line-height:1.6;">
          <b style="color:var(--text);">&#9432; Installing a plugin:</b> drop a folder into <code>plugins/&lt;name&gt;/</code>
          (a <code>plugin.json</code> manifest + optional <code>backend.py</code> router + optional <code>static/frontend.js</code>
          view), then restart the store. Plugins are gitignored, so they survive every store update.
          A plugin with missing <code>requires</code> deps, a route collision, or a crashing import shows here as
          <b>failed</b> — the store itself is never affected.
          <a href="${API}/api/plugins/readme" target="_blank" style="color:var(--accent);">&#128214; Full author contract (plugins/README.md)</a>
        </div>
      </div>`;

    pane.querySelectorAll('.toggle[data-plugin]').forEach(el => {
      el.addEventListener('click', async () => {
        const id = el.dataset.plugin;
        const enable = !el.classList.contains('on');
        el.classList.toggle('on');
        try {
          const r = await api(`/api/plugins/${encodeURIComponent(id)}/toggle`,
                              { method: 'POST', body: JSON.stringify({ enabled: enable }) });
          toast(`${id} ${enable ? 'enabled' : 'disabled'}` +
                (r && r.pending_restart ? ' — applies on restart' : ''));
          renderPluginsPane();
        } catch (e) {
          el.classList.toggle('on');   // revert
          toast(`Couldn't toggle ${id}: ${e.message} (an older backend needs a restart first)`, 'error');
        }
      });
    });
  }

  window.renderPluginsPane = renderPluginsPane;
})();
