/* Restored from pre_unification_backup (Jul 9) — real tab implementation.
   Part of the modular frontend: one file per tab. */
// Card action handler (bindCards) + pipeline modals (approve/publish/regen/etsy/edit).

/* ══ GENERAL THUMBNAIL HELPERS ══
   thumbUrl() (app-main.js) only covers pipeline designs. These target the general
   /api/thumb?path=&w= route, which serves cached WebP thumbs for ANY local image
   under an allowlisted server root. External CDN urls (Printify/Cults/Woo) and
   base64 data: URIs CANNOT be thumbnailed — callers must skip those. */
// relPath is relative to the app root, e.g. "static/resell_uploads/x.jpg" or "models3d/hero/x.png".
window.thumbAny = function (relPath, w) {
  if (!relPath) return relPath;
  return `${API}/api/thumb?path=${encodeURIComponent(relPath)}&w=${w || 400}`;
};
// Convert a token-guarded models3d image URL (/api/public/m3d/<t>/<id>/img/<file>) into a
// thumbnail URL. On-disk naming decides the dir: hero PNGs are "gensrc_*"/"*_hero_*", the
// rest are turntable renders ("m<id>_v<n>"). Returns the original url if it can't be parsed.
window.thumbM3d = function (pubUrl, w) {
  if (!pubUrl || pubUrl.indexOf('/img/') < 0) return pubUrl;
  const fn = pubUrl.split('/img/')[1].split('?')[0];
  const dir = (fn.indexOf('gensrc_') === 0 || fn.indexOf('_hero_') >= 0) ? 'models3d/hero' : 'models3d/renders';
  return window.thumbAny(`${dir}/${fn}`, w);
};

/* ── BIND CARDS (event delegation on #main-content) ── */
function bindCards() {
  const content = document.getElementById('main-content');
  if (content._cardsBound) return;
  content._cardsBound = true;

  content.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    const { action, id } = btn.dataset;
    const card = btn.closest('[data-id]');

    if (action === 'approve-proposal') {
      openApproveProposalModal(id, card);
    }

    if (action === 'reject-proposal') {
      btn.disabled = true;
      try {
        await api(`/api/proposals/${id}/reject`, { method: 'PATCH' });
        card?.remove(); toast('Skipped'); loadStats();
      } catch(e) { toast('Error: ' + e.message, 'error'); btn.disabled = false; }
    }

    if (action === 'approve-design') {
      // DIRECT ONE-CLICK APPROVE — no modal
      btn.disabled = true;
      const origText = btn.textContent;
      btn.textContent = '\u23F3';
      try {
        const designId = parseInt(id, 10);
        if (!designId) { toast('Invalid design ID', 'error'); return; }
        await api(`/api/designs/${designId}/approve`, { method: 'PATCH', body: JSON.stringify({ product_types: ['T-Shirt'] }) });
        if (card) { card.style.borderColor = 'var(--green)'; card.style.opacity = '.4'; setTimeout(() => card?.remove(), 400); }
        toast('\u2713 Approved \u2014 choose product types when publishing to Printify');
        loadStats();
      } catch(e) {
        toast('Error: ' + e.message, 'error');
        btn.textContent = origText; btn.disabled = false;
      }
    }

    if (action === 'publish-printify') { openPublishModal(btn); }

    if (action === 'reject-design') {
      btn.disabled = true;
      try {
        await api(`/api/designs/${id}/reject`, { method: 'PATCH' });
        card?.remove(); toast('Rejected'); loadStats();
      } catch(e) { toast('Error: ' + e.message, 'error'); btn.disabled = false; }
    }

    if (action === 'delete-design') {
      if (!confirm('Delete permanently?')) return;
      btn.disabled = true;
      try {
        await api(`/api/designs/${id}`, { method: 'DELETE' });
        card?.remove(); toast('Deleted'); loadStats();
      } catch(e) { toast('Error: ' + e.message, 'error'); btn.disabled = false; }
    }

    if (action === 'regen-design') { openRegenModal(id, btn.dataset.prompt || ''); }
    if (action === 'make-collection') {
      const themes = window.prompt('Matching collection — theme variations, comma-separated\n(e.g. winter snow scene, summer beach, neon cyberpunk, autumn leaves):', '');
      if (themes && themes.trim()) {
        const variants = themes.split(',').map(t => t.trim()).filter(Boolean)
          .map(t => `the same subject and composition, but ${t}`);
        api('/api/collection', { method: 'POST', body: JSON.stringify({ design_id: parseInt(id, 10), variants }) })
          .then(r => toast(`🎨 Collection queued — ${r.queued} variant(s) generating; they'll appear in Review`))
          .catch(e => toast(e.message || 'Collection failed', 'error'));
      }
    }
    if (action === 'publish-etsy') { openEtsyModal(btn); }
    if (action === 'edit-listing') { openEditListingModal(btn); }

    // Image Generator tab actions
    if (action === 'ig-send-review') {
      btn.disabled = true; btn.textContent = '\u23F3';
      try {
        await api(`/api/designs/${id}/send-to-review`, { method: 'PATCH' });
        document.getElementById(`ig-card-${id}`)?.remove();
        toast('\u2713 Sent to Review Queue');
        loadStats();
      } catch(e) { toast('Failed: ' + e.message, 'error'); btn.disabled = false; btn.textContent = '\u2192 Review'; }
    }
    if (action === 'ig-discard') {
      if (!confirm('Discard this image permanently?')) return;
      btn.disabled = true;
      try {
        await api(`/api/designs/${id}`, { method: 'DELETE' });
        document.getElementById(`ig-card-${id}`)?.remove();
        toast('Discarded');
      } catch(e) { toast('Failed: ' + e.message, 'error'); btn.disabled = false; }
    }

    if (action === 'unpublish-design') {
      if (!confirm('Archive this design on Printify?\n\nNote: Printify API can only archive products — they will be hidden from your store but will still appear under Archived in your Printify dashboard. The design will be marked as approved (unpublished) here.')) return;
      btn.disabled = true;
      const orig = btn.textContent; btn.textContent = '⏳';
      try {
        await api(`/api/designs/${id}/unpublish`, { method: 'DELETE' });
        card?.remove();
        toast('✓ Archived on Printify (still visible under Archived in Printify dashboard)');
        loadStats();
      } catch(e) { toast('Remove failed: ' + e.message, 'error'); btn.disabled = false; btn.textContent = orig; }
    }

    // ── Model download/cancel (Models view) ──────────────────────────────────
    if (action === 'dl-model') {
      const filename = btn.dataset.filename;
      const safeId2  = btn.dataset.safeid || (filename||'').replace(/[^a-zA-Z0-9_-]/g, '_');
      btn.disabled = true; btn.innerHTML = '&#8987; Starting&#8230;';
      try {
        await api(`/api/models/${encodeURIComponent(filename)}/download`, { method: 'POST' });
        btn.style.display = 'none';
        const prog = document.getElementById(`dl-prog-${safeId2}`);
        if (prog) prog.style.removeProperty('display');
        pollDownload(filename, safeId2);
      } catch(e2) {
        toast('Download failed: ' + e2.message, 'error');
        btn.disabled = false; btn.innerHTML = '&#11015; Download';
      }
    }

    if (action === 'cancel-dl') {
      const filename = btn.dataset.filename;
      const safeId2  = btn.dataset.safeid || (filename||'').replace(/[^a-zA-Z0-9_-]/g, '_');
      try {
        await api(`/api/models/${encodeURIComponent(filename)}/download`, { method: 'DELETE' });
        toast('Download cancelled');
        setTimeout(() => renderModels(), 500);
      } catch(e2) { toast('Cancel failed: ' + e2.message, 'error'); }
    }

    // ── Video model download/cancel ──────────────────────────────────────────
    if (action === 'dl-video-model') {
      const key     = btn.dataset.key;
      const safeVid = (key||'').replace(/[^a-zA-Z0-9_-]/g, '_');
      btn.disabled = true; btn.innerHTML = '&#8987; Starting&hellip;';
      try {
        await api(`/api/video-models/${encodeURIComponent(key)}/download`, { method: 'POST' });
        btn.style.display = 'none';
        const prog = document.getElementById(`vdl-prog-${safeVid}`);
        if (prog) prog.style.removeProperty('display');
        pollVideoDownload(key, safeVid);
      } catch(e2) {
        toast('Download failed: ' + e2.message, 'error');
        btn.disabled = false; btn.innerHTML = '&#11015; Download';
      }
    }

    if (action === 'cancel-vdl') {
      const key     = btn.dataset.key;
      const safeVid = btn.dataset.safeid || (key||'').replace(/[^a-zA-Z0-9_-]/g, '_');
      try {
        await api(`/api/video-models/${encodeURIComponent(key)}/download`, { method: 'DELETE' });
        toast('Download cancelled');
        setTimeout(() => renderModels(), 500);
      } catch(e2) { toast('Cancel failed: ' + e2.message, 'error'); }
    }

    // ── Audio model download/install + cancel ────────────────────────────────
    if (action === 'dl-audio-model') {
      const key  = btn.dataset.key;
      const safe = (key||'').replace(/[^a-zA-Z0-9_-]/g, '_');
      const isInstall = btn.dataset.install === '1';
      btn.disabled = true; btn.innerHTML = '&#8987; Starting&hellip;';
      try {
        await api(`/api/audio-models/${encodeURIComponent(key)}/download`, { method: 'POST' });
        btn.style.display = 'none';
        const prog = document.getElementById(`adl-prog-${safe}`);
        if (prog) prog.style.removeProperty('display');
        const st = document.getElementById(`adl-status-${safe}`);
        if (st) st.textContent = isInstall ? 'Installing (venv + model, several minutes)…' : 'Downloading model…';
        pollAudioDownload(key, safe);
      } catch(e2) {
        toast('Failed: ' + e2.message, 'error');
        btn.disabled = false; btn.innerHTML = '&#11015; ' + (isInstall ? 'Install' : 'Download');
      }
    }

    if (action === 'cancel-adl') {
      const key  = btn.dataset.key;
      try {
        await api(`/api/audio-models/${encodeURIComponent(key)}/download`, { method: 'DELETE' });
        toast('Cancelled');
        setTimeout(() => renderModels(), 500);
      } catch(e2) { toast('Cancel failed: ' + e2.message, 'error'); }
    }
  });

  content.addEventListener('click', (e) => {
    const img = e.target.closest('img[data-lb]');
    if (!img) return;
    openLightbox(img.dataset.lb, decodeURIComponent(img.dataset.lbCaption || ''));
  });
}
