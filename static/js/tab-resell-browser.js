/* Resale browser-posting UI — headed Chrome launch/post/fill, AI reply, inbox,
   activity panel. Split from tab-resell.js; loaded right after it. */
/* ── Store-native browser posting (headed Chrome, no OpenClaw) ── */
async function rsBrowserLaunch(platform) {
  const st = document.getElementById('rs-browser-status');
  if (st) { st.style.color = 'var(--muted)'; st.textContent = 'Launching browser…'; }
  try {
    const r = await api('/api/resell/browser/launch', { method: 'POST', body: JSON.stringify({ platform }) });
    if (st) { st.style.color = 'var(--green)'; st.textContent = r.running ? '✅ Browser open — log in there once.' : 'Launched.'; }
    toast('Store browser opened');
  } catch (e) {
    if (st) { st.style.color = 'var(--warn)'; st.textContent = '❌ ' + e.message; }
  }
}
window.rsBrowserLaunch = rsBrowserLaunch;

async function rsBrowserPost(platform) {
  if (!_savedLid) { toast('Save the listing first.'); return; }
  const status = document.getElementById('rs-post-status');
  const shotBox = document.getElementById('rs-browser-shot');
  status.style.color = 'var(--muted)';
  status.textContent = `Opening ${platform} in the Store browser and attaching photos…`;
  let text = '';
  try {
    // grab the generated copy so the user can paste it
    try {
      const c = await api(`/api/resell/listings/${_savedLid}/generate-content`, { method: 'POST', body: JSON.stringify({ platform }) });
      text = c.content || c.text || '';
    } catch {}
    const r = await api(`/api/resell/listings/${_savedLid}/browser-post`, { method: 'POST', body: JSON.stringify({ platform, overrides: _rsDraftOverrides() }) });
    rsRefreshActivity();
    if (r.needs_login) { _rsShowLogin(status, r, platform); if (r.screenshot) shotBox.innerHTML = _rsShot(r.screenshot, platform); return; }
    if (r.ok === false) {
      status.style.color = 'var(--warn)';
      status.textContent = r.note || '⚠️ Nothing could be filled — check the browser window.';
      if (r.screenshot) shotBox.innerHTML = _rsShot(r.screenshot, platform);
      return;
    }
    status.style.color = 'var(--green)';
    status.innerHTML = `✅ ${esc(r.note)} (${r.photos_uploaded ? r.photo_count + ' photo(s) attached' : 'no photo field found — attach manually'})`;
    shotBox.innerHTML = `
      ${text ? `<div style="margin-bottom:8px;"><div style="font-size:.75rem;color:var(--muted);margin-bottom:4px;">Listing text (click to copy):</div>
        <textarea readonly onclick="this.select();document.execCommand('copy');toast('Copied');" style="width:100%;min-height:120px;padding:8px;background:var(--surface2);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:.78rem;">${esc(text)}</textarea></div>` : ''}
      ${r.screenshot ? `<div style="font-size:.75rem;color:var(--muted);margin-bottom:4px;">Browser view (in the ${esc(platform)} window on your desktop):</div>
        <img src="data:image/png;base64,${r.screenshot}" style="width:100%;border:1px solid var(--border);border-radius:8px;">
        <button class="btn-sm" style="margin-top:6px;" onclick="rsBrowserShot()">🔄 Refresh view</button>` : ''}`;
  } catch (e) {
    status.style.color = 'var(--warn)';
    status.textContent = '❌ ' + e.message;
  }
}
window.rsBrowserPost = rsBrowserPost;

async function rsBrowserShot() {
  const shotBox = document.getElementById('rs-browser-shot');
  try {
    const r = await api('/api/resell/browser/screenshot');
    const img = shotBox.querySelector('img');
    if (img && r.png_b64) img.src = 'data:image/png;base64,' + r.png_b64;
  } catch (e) { toast('Error: ' + e.message, 'error'); }
}
window.rsBrowserShot = rsBrowserShot;

async function rsBrowserFill() {
  if (!_savedLid) { toast('Save the listing first.'); return; }
  const status = document.getElementById('rs-post-status');
  const shotBox = document.getElementById('rs-browser-shot');
  status.style.color = 'var(--muted)';
  status.textContent = 'Filling the current browser page…';
  try {
    const r = await api(`/api/resell/listings/${_savedLid}/browser-fill`, { method: 'POST', body: JSON.stringify({ overrides: _rsDraftOverrides() }) });
    rsRefreshActivity();
    status.style.color = r.n_filled ? 'var(--green)' : 'var(--warn)';
    status.textContent = r.n_filled ? `✅ Filled ${r.n_filled} field(s)${r.photos_uploaded ? ' + photos' : ''}. Review & submit.`
                                     : (r.note || '⚠️ No matching fields found on this page — is the create form open?');
    if (r.screenshot) shotBox.innerHTML = _rsShot(r.screenshot, 'current page');
  } catch (e) { status.style.color = 'var(--warn)'; status.textContent = '❌ ' + e.message; }
}
window.rsBrowserFill = rsBrowserFill;

async function rsOfferAiReply(offerId) {
  const box = document.getElementById('rs-ai-reply-' + offerId);
  if (!box) return;
  box.style.color = 'var(--muted)';
  box.textContent = '🧠 Drafting reply (local model, can take a minute)…';
  try {
    const { task_id } = await api(`/api/resell/offers/${offerId}/ai-reply`, { method: 'POST' });
    const r = await pollTask(task_id, 90);   // reasoning models are slow
    const badge = { accept: '✅ Accept', counter: '↔️ Counter', decline: '🚫 Decline' }[r.decision] || r.decision;
    box.style.color = 'var(--text)';
    box.innerHTML = `
      <div style="background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:8px 10px;">
        <div style="font-size:.72rem;color:var(--muted);margin-bottom:4px;">${esc(badge)}${r.counter_price ? ' at $' + r.counter_price : ''}</div>
        <textarea id="rs-reply-text-${offerId}" style="width:100%;min-height:80px;background:var(--surface2);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:.78rem;padding:6px;">${esc(r.reply)}</textarea>
        <div style="display:flex;gap:6px;margin-top:4px;">
          <button class="btn-sm" onclick="document.getElementById('rs-reply-text-${offerId}').select();document.execCommand('copy');toast('Copied');">📋 Copy</button>
          <button class="btn-sm primary" onclick="rsSendReply(${offerId})" title="Open the conversation in the Store browser first, then this fills the chat box">📤 Put in chat box</button>
        </div>
        <div style="font-size:.66rem;color:var(--muted);margin-top:3px;">Edit above · review before sending · you press Enter to send</div>
      </div>`;
  } catch (e) { box.style.color = 'var(--warn)'; box.textContent = '❌ ' + e.message; }
}
window.rsOfferAiReply = rsOfferAiReply;

function _rsDraftOverrides() {
  return {
    title: document.getElementById('rs-draft-title')?.value.trim() || '',
    price: document.getElementById('rs-draft-price')?.value.trim() || '',
    description: document.getElementById('rs-draft-desc')?.value.trim() || '',
  };
}
async function rsLoadDraft() {
  if (!_savedLid) return;
  try {
    const l = await api(`/api/resell/listings/${_savedLid}`);
    const t = document.getElementById('rs-draft-title'), p = document.getElementById('rs-draft-price'), d = document.getElementById('rs-draft-desc');
    if (t) t.value = l.title || '';
    if (p) p.value = (l.asking_price != null ? l.asking_price : (l.ai_price_max || ''));
    if (d) d.value = l.description || '';
  } catch {}
}
window.rsLoadDraft = rsLoadDraft;
function rsCopyDraft() {
  const o = _rsDraftOverrides();
  const text = `${o.title}\n$${o.price}\n\n${o.description}`;
  navigator.clipboard?.writeText(text).then(() => toast('Draft copied')).catch(() => {
    const ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove(); toast('Draft copied');
  });
}
window.rsCopyDraft = rsCopyDraft;

async function rsSendReply(offerId) {
  const ta = document.getElementById('rs-reply-text-' + offerId);
  const reply = ta ? ta.value.trim() : '';
  if (!reply) { toast('No reply text'); return; }
  try {
    const r = await api(`/api/resell/offers/${offerId}/send-reply`, { method: 'POST', body: JSON.stringify({ reply }) });
    toast(r.ok ? '📤 Typed into the chat box — press Enter to send' : (r.note || 'No message box found'), r.ok ? 'success' : 'error');
  } catch (e) { toast('❌ ' + e.message, 'error'); }
}
window.rsSendReply = rsSendReply;

function _rsInboxBar() {
  return `<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:12px;">
    <button class="btn-sm primary" onclick="rsReadInbox('facebook')">📥 Read FB Inbox</button>
    <span id="rs-inbox-status" style="font-size:.76rem;color:var(--muted);"></span>
  </div>`;
}
async function rsReadInbox(platform) {
  const st = document.getElementById('rs-inbox-status');
  if (st) { st.style.color = 'var(--muted)'; st.textContent = '⏳ Opening inbox + reading messages (local model, ~1 min)…'; }
  try {
    const r = await api('/api/resell/inbox/read', { method: 'POST', body: JSON.stringify({ platform }) });
    rsRefreshActivity();
    if (r.needs_login) { if (st) _rsShowLogin(st, r, platform); return; }
    if (r.empty) { if (st) { st.style.color = 'var(--muted)'; st.textContent = '📭 No messages in the inbox right now.'; } return; }
    const res = await pollTask(r.task_id, 90);
    rsRefreshActivity();
    if (st) { st.style.color = 'var(--green)'; st.textContent = `✅ Read ${res.conversations?.length || 0} conversation(s), created ${res.created} new offer(s).`; }
    toast(`Imported ${res.created} offer(s) from inbox`);
    const ct = document.getElementById('rs-content'); if (ct) await renderResellOffers(ct);
  } catch (e) { if (st) { st.style.color = 'var(--warn)'; st.textContent = '❌ ' + e.message; } }
}
window.rsReadInbox = rsReadInbox;

// ─── Shared status helpers: keep automation out of "black box" territory ─────
function _rsShot(b64, label) {
  return `<div style="font-size:.72rem;color:var(--muted);margin:6px 0 4px;">Browser view${label ? ' — ' + esc(label) : ''}:</div>
    <img src="data:image/png;base64,${b64}" style="width:100%;border:1px solid var(--border);border-radius:8px;">
    <button class="btn-sm" style="margin-top:6px;" onclick="rsBrowserShot()">🔄 Refresh view</button>`;
}
function _rsShowLogin(el, r, platform) {
  el.style.color = 'var(--warn)';
  el.innerHTML = `${esc(r.note || 'Not logged in.')} <button class="btn-sm" style="margin-left:6px;" onclick="rsBrowserLaunch('${esc(platform || '')}')">🌐 Launch &amp; log in</button>`;
}

const _RS_ACT_ICON = { done: '✅', running: '⏳', failed: '❌', needs_login: '🔐' };
async function rsRefreshActivity() {
  const el = document.getElementById('rs-activity');
  if (!el) return;
  try {
    const r = await api('/api/resell/browser/activity?limit=12');
    const evs = r.events || [];
    if (!evs.length) { el.innerHTML = '<div style="color:var(--muted);font-size:.72rem;">No automation activity yet.</div>'; return; }
    el.innerHTML = evs.map(e => {
      const icon = _RS_ACT_ICON[e.status] || '•';
      const col = e.status === 'failed' ? 'var(--warn)' : e.status === 'needs_login' ? '#f59e0b' : e.status === 'running' ? 'var(--muted)' : 'var(--text)';
      const when = (e.created_at || '').replace('T', ' ').slice(5, 16);
      return `<div style="display:flex;gap:6px;padding:3px 0;border-bottom:1px solid var(--border);font-size:.72rem;">
        <span>${icon}</span>
        <span style="color:var(--muted);min-width:74px;">${esc(when)}</span>
        <span style="color:${col};font-weight:600;min-width:56px;">${esc(e.action)}</span>
        <span style="color:var(--muted);flex:1;">${esc(e.detail || e.target || '')}</span>
      </div>`;
    }).join('');
  } catch { el.innerHTML = '<div style="color:var(--muted);font-size:.72rem;">Activity unavailable.</div>'; }
}
window.rsRefreshActivity = rsRefreshActivity;

function _rsActivityPanel() {
  return `<details style="margin-top:12px;border:1px solid var(--border);border-radius:8px;padding:8px 10px;" ontoggle="if(this.open)rsRefreshActivity()">
    <summary style="cursor:pointer;font-size:.78rem;font-weight:600;color:var(--muted);">📋 Recent automation activity</summary>
    <div style="display:flex;justify-content:flex-end;margin:4px 0;"><button class="btn-sm" onclick="rsRefreshActivity()">🔄 Refresh</button></div>
    <div id="rs-activity" style="max-height:220px;overflow:auto;">Loading…</div>
  </details>`;
}
window._rsActivityPanel = _rsActivityPanel;
