async function libAddLinkForm() {
  const el = document.getElementById('lib-content');
  el.innerHTML = `
    <div class="stat-card" style="padding:24px;">
      <div style="margin-bottom:20px;">
        <h3 style="margin-bottom:8px;">Drop a Link for Review</h3>
        <p style="color:var(--muted);font-size:.85rem;">Submit a URL for the library. I'll review it and decide if we should include it.</p>
      </div>
      <form id="lib-add-link-form" style="display:flex;flex-direction:column;gap:12px;">
        <input type="text" id="lib-add-link-url" placeholder="URL (https://...)" style="padding:10px;background:var(--surface2);border:1px solid var(--border);border-radius:8px;color:var(--text);" required />
        <input type="text" id="lib-add-link-title" placeholder="Title (Optional)" style="padding:10px;background:var(--surface2);border:1px solid var(--border);border-radius:8px;color:var(--text);" />
        <textarea id="lib-add-link-desc" placeholder="Description (Optional)" style="padding:10px;background:var(--surface2);border:1px solid var(--border);border-radius:8px;color:var(--text);min-height:80px;"></textarea>
        <input type="text" id="lib-add-link-cat" placeholder="Category (Optional)" style="padding:10px;background:var(--surface2);border:1px solid var(--border);border-radius:8px;color:var(--text);" />
        <div style="display:flex;gap:10px;">
          <button type="submit" class="btn">Submit for Review</button>
          <button type="button" class="btn-sm" onclick="libShowSections()">Cancel</button>
        </div>
      </form>
    </div>
  `;

  document.getElementById('lib-add-link-form').onsubmit = async (e) => {
    e.preventDefault();
    const url = document.getElementById('lib-add-link-url').value;
    const title = document.getElementById('lib-add-link-title').value;
    const desc = document.getElementById('lib-add-link-desc').value;
    const cat = document.getElementById('lib-add-link-cat').value;

    try {
      const result = await api('/api/library/links', {
        method: 'POST',
        body: JSON.stringify({ url, title, description: desc, category: cat })
      });
      toast(`Submitted: ${title || url}`);
      libShowSections();
    } catch(err) {
      toast(err.message, 'error');
    }
  };
}

async function libReviewLinks() {
  const el = document.getElementById('lib-content');
  el.innerHTML = '<div class="empty">Loading pending links...</div>';
  try {
    const data = await api('/api/library/links?status=pending');
    const links = data.links || [];
    
    if (!links.length) {
      el.innerHTML = '<div class="empty"><div class="empty-icon">\u{1F4C2}</div>No pending links to review.</div>';
      return;
    }

    let h = `<div style="margin-bottom:14px;display:flex;align-items:center;gap:8px;">` +
      `<button class="btn-sm" onclick="libShowSections()">&larr; Back</button>` +
      `<span style="font-weight:600;font-size:1.1rem;">Pending Review</span></div>`;
    h += `<div style="display:flex;flex-direction:column;gap:12px;">`;
    for (const link of links) {
      h += `<div class="stat-card" style="padding:16px;border:1px solid var(--border);border-radius:8px;">` +
        `<div style="font-weight:600;margin-bottom:4px;">${esc(link.title || 'Untitled Link')}</div>` +
        `<div style="font-size:.85rem;color:var(--muted);margin-bottom:8px;">${esc(link.url)}</div>` +
        `<div style="font-size:.85rem;margin-bottom:12px;color:var(--text);">${esc(link.description || 'No description')}</div>` +
        `<div style="display:flex;gap:10px;">` +
        `<button class="btn-sm" style="background:var(--green);" onclick="libReviewLink(${link.id}, 'approved')">Approve</button>` +
        `<button class="btn-sm" style="background:var(--red);" onclick="libReviewLink(${link.id}, 'rejected')">Reject</button>` +
        `<button class="btn-sm" onclick="libDeleteLink(${link.id})">Delete</button>` +
        `</div></div>`;
    }
    h += `</div>`;
    el.innerHTML = h;
  } catch(err) {
    el.innerHTML = `<div class="empty"><div class="empty-icon">\u{274C}</div>${esc(err.message)}</div>`;
  }
}

async function libReviewLink(linkId, status) {
  try {
    await api(`/api/library/links/${linkId}/review`, {
      method: 'POST',
      body: JSON.stringify({ status })
    });
    toast(`Link ${status}ed`);
    libReviewLinks();
  } catch(err) {
    toast(err.message, 'error');
  }
}

async function libDeleteLink(linkId) {
  if(!confirm('Are you sure you want to delete this submission?')) return;
  try {
    await api(`/api/library/links/${linkId}`, { method: 'DELETE' });
    toast('Link deleted');
    libReviewLinks();
  } catch(err) {
    toast(err.message, 'error');
  }
}
