// ── Prompts editor (Settings → Prompts) ──
async function loadPromptsEditor() {
  const root = document.getElementById('prompts-list');
  if (!root) return;
  root.innerHTML = '<div style="color:var(--muted);font-size:.8rem;">Loading&#8230;</div>';
  try {
    const data = await api('/api/prompts');
    const prompts = data.prompts || [];
    const byCat = {};
    prompts.forEach(p => { (byCat[p.category] = byCat[p.category] || []).push(p); });
    const order = (data.categories && data.categories.length) ? data.categories : Object.keys(byCat);
    const edCount = prompts.filter(p => p.overridden).length;
    let h = `<div class="prompt-toolbar">
      <input type="text" id="prompt-search" placeholder="&#128269; Search ${prompts.length} prompts&hellip;" oninput="filterPrompts()">
      <label class="prompt-filter"><input type="checkbox" id="prompt-edited-only" onchange="filterPrompts()"> Edited only (${edCount})</label>
    </div>`;
    for (const cat of order) {
      const list = byCat[cat];
      if (!list || !list.length) continue;
      h += `<div class="prompt-cat" data-cat="${esc(cat)}">${esc(cat)} <span class="prompt-cat-n">${list.length}</span></div>`;
      for (const p of list) {
        const edited = p.overridden ? `<span class="prompt-badge edited">edited</span>` : '';
        const tmpl   = p.templated ? `<span class="prompt-badge tmpl">templated</span>` : '';
        const hay = (p.label + ' ' + p.category + ' ' + (p.help || '') + ' ' + p.key).toLowerCase();
        h += `<details class="settings-group prompt-item" data-cat="${esc(cat)}" data-edited="${p.overridden ? 1 : 0}" data-hay="${esc(hay)}">
          <summary><span class="prompt-title">${esc(p.label)}</span>${edited}${tmpl}</summary>
          ${p.help ? `<div class="prompt-help">${esc(p.help)}</div>` : ''}
          <textarea class="prompt-ta" id="pt-${esc(p.key)}" spellcheck="false">${esc(p.value || '')}</textarea>
          <div class="prompt-actions">
            <button class="btn-sm primary" onclick="savePrompt('${esc(p.key)}')">&#128190; Save</button>
            <button class="btn-sm" onclick="resetPrompt('${esc(p.key)}')">&#8635; Reset to default</button>
            <span class="prompt-msg" id="pm-${esc(p.key)}"></span>
          </div>
          <div class="prompt-test">
            <input type="text" class="prompt-test-in" id="pti-${esc(p.key)}" placeholder="Try a sample input&hellip; (tests the text above, even unsaved)">
            <button class="btn-sm" onclick="testPrompt('${esc(p.key)}')">&#9654; Test</button>
          </div>
          <div class="prompt-test-out" id="pto-${esc(p.key)}" style="display:none;"></div>
        </details>`;
      }
    }
    root.innerHTML = h || '<div style="color:var(--muted)">No prompts registered.</div>';
  } catch (e) {
    root.innerHTML = `<div style="color:var(--red);font-size:.82rem;">Failed to load prompts: ${esc(e.message)}</div>`;
  }
}
function filterPrompts() {
  const q = (document.getElementById('prompt-search')?.value || '').trim().toLowerCase();
  const editedOnly = document.getElementById('prompt-edited-only')?.checked;
  document.querySelectorAll('#prompts-list .prompt-item').forEach(el => {
    const hay = el.getAttribute('data-hay') || '';
    const show = (!q || hay.includes(q)) && (!editedOnly || el.getAttribute('data-edited') === '1');
    el.style.display = show ? '' : 'none';
  });
  // hide category headers with no visible items
  document.querySelectorAll('#prompts-list .prompt-cat').forEach(head => {
    const cat = head.getAttribute('data-cat');
    const any = [...document.querySelectorAll(`#prompts-list .prompt-item[data-cat="${cat}"]`)]
      .some(el => el.style.display !== 'none');
    head.style.display = any ? '' : 'none';
  });
}
async function testPrompt(key) {
  const inEl = document.getElementById('pti-' + key);
  const taEl = document.getElementById('pt-' + key);
  const out = document.getElementById('pto-' + key);
  if (!out) return;
  out.style.display = 'block';
  out.style.color = 'var(--muted)';
  out.textContent = '⏳ Running against the LLM…';
  try {
    const { task_id } = await api('/api/prompts/' + encodeURIComponent(key) + '/test', {
      method: 'POST',
      body: JSON.stringify({ input: inEl ? inEl.value : '', system: taEl ? taEl.value : '' })
    });
    const r = await pollTask(task_id, 90);
    const o = r && (r.output || '');
    out.style.color = 'var(--text)';
    out.textContent = (o && o.trim()) ? o.trim() : '(empty response — the model returned nothing)';
  } catch (e) {
    out.style.color = 'var(--red)';
    out.textContent = 'Error: ' + e.message;
  }
}
async function savePrompt(key) {
  const ta = document.getElementById('pt-' + key);
  const msg = document.getElementById('pm-' + key);
  if (!ta) return;
  try {
    await api('/api/prompts/' + encodeURIComponent(key),
              { method: 'PATCH', body: JSON.stringify({ value: ta.value }) });
    if (msg) { msg.style.color = 'var(--green)'; msg.textContent = '✓ Saved'; }
    toast('Prompt saved ✓');
    setTimeout(loadPromptsEditor, 500);
  } catch (e) { if (msg) { msg.style.color = 'var(--red)'; msg.textContent = e.message; } }
}
async function resetPrompt(key) {
  const msg = document.getElementById('pm-' + key);
  try {
    const r = await api('/api/prompts/' + encodeURIComponent(key) + '/reset', { method: 'POST' });
    const ta = document.getElementById('pt-' + key);
    if (ta && r && r.value != null) ta.value = r.value;
    if (msg) { msg.style.color = 'var(--muted)'; msg.textContent = 'Reset to default'; }
    toast('Prompt reset to default');
    setTimeout(loadPromptsEditor, 500);
  } catch (e) { if (msg) { msg.style.color = 'var(--red)'; msg.textContent = e.message; } }
}
