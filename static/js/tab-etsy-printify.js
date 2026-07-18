/* Restored from pre_unification_backup (Jul 9) — real tab implementation.
   Part of the modular frontend: one file per tab. */
/* ══ ETSY / PRINTIFY (tabbed view) ══ */
async function renderEtsyPrintify(subtab) {
  if (subtab) _etsySubTab = subtab;
  if (!_etsySubTab) _etsySubTab = 'proposals';

  // Fetch stats for subtab badges
  let s = {};
  try { s = await api('/api/stats'); } catch {}

  const tabs = [
    { id:'proposals',  icon:'&#128161;', label:'Proposals',   badge: s.proposals_pending||0, bc:'warn'  },
    { id:'review',     icon:'&#128269;', label:'Review',      badge: s.review_count||0                   },
    { id:'approved',   icon:'&#9989;',   label:'Approved',    badge: s.approved_count||0,    bc:'green' },
    { id:'published',  icon:'&#128717;', label:'Published',   badge: s.published_count||0,   bc:'teal'  },
    { id:'store-stats',icon:'&#128200;', label:'Stats'                                                   },
    { id:'products',   icon:'&#128176;', label:'Products'                                                },
  ];

  const tabBarHtml = `<div class="subtab-bar">
    ${tabs.map(t => {
      const active = _etsySubTab === t.id ? ' active' : '';
      const badge  = t.badge ? `<span class="subtab-badge ${t.bc||'blue'}">${t.badge}</span>` : '';
      return `<div class="subtab${active}" data-ep-tab="${t.id}">${t.icon} ${t.label}${badge}</div>`;
    }).join('')}
  </div>`;

  const main = document.getElementById('main-content');
  main.innerHTML = `
    <div class="view-header">
      <div class="view-title">&#128717; Etsy / Printify</div>
      <div class="view-sub">Your print-on-demand pipeline &mdash; proposals through to published</div>
    </div>
    ${tabBarHtml}
    <div id="ep-subtab-content"><div class="empty"><div class="empty-icon">&#9203;</div>Loading&hellip;</div></div>`;

  // Bind subtab clicks
  main.querySelectorAll('[data-ep-tab]').forEach(el => {
    el.addEventListener('click', async () => {
      _etsySubTab = el.dataset.epTab;
      main.querySelectorAll('[data-ep-tab]').forEach(x => x.classList.toggle('active', x.dataset.epTab === _etsySubTab));
      const sub = document.getElementById('ep-subtab-content');
      if (sub) sub.innerHTML = '<div class="empty"><div class="empty-icon">&#9203;</div>Loading&hellip;</div>';
      await _renderEpSubtab(_etsySubTab);
      bindCards();
    });
  });

  await _renderEpSubtab(_etsySubTab);
  bindCards();
}

async function _renderEpSubtab(id) {
  switch (id) {
    case 'proposals':   await renderProposals();  break;
    case 'review':      await renderReview();     break;
    case 'approved':    await renderApproved();   break;
    case 'published':   await renderPublished();  break;
    case 'store-stats': await renderStoreStats(); break;
    case 'products':    await renderProducts();   break;
  }
}
