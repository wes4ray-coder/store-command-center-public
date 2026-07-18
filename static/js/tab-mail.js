/* ══ MAIL / QUOTES TAB ══
   Read customer email from the self-hosted Mailcow mailbox (support@example.com),
   draft a labor quote with the local LLM (Acme Carpentry terms), and send the reply. */

let _mailMsgs = [];
let _mailCur = null;

async function renderMail() {
  document.getElementById('main-content').innerHTML = `
    <div class="view-header">
      <div class="view-title">&#9993;&#65039; Mail &amp; Quotes</div>
      <div class="view-sub">Customer email from <b>support@example.com</b> &mdash; read it, let the AI draft a
        labor quote (your $40/hr, 4-hr-min, materials-by-customer terms), tweak, and reply.</div>
    </div>
    <div style="display:flex;gap:10px;align-items:center;margin-bottom:12px;">
      <button class="btn-sm primary" onclick="loadMailInbox()" title="Re-read the support@example.com inbox over IMAP from the self-hosted Mailcow server. Read-only: nothing is sent. Opening a message marks it seen on the server.">&#128260; Refresh inbox</button>
      <span id="mail-status" style="font-size:.8rem;color:var(--muted);"></span>
    </div>
    <div style="display:grid;grid-template-columns:360px 1fr;gap:16px;align-items:start;">
      <div id="mail-list"></div>
      <div id="mail-detail"><div class="empty"><div class="empty-icon">&#128231;</div>Select a message to read &amp; quote.</div></div>
    </div>`;
  await loadMailInbox();
}
window.renderMail = renderMail;

async function loadMailInbox() {
  const list = document.getElementById('mail-list');
  const st = document.getElementById('mail-status');
  list.innerHTML = '<div class="loading-state">Loading inbox…</div>';
  try {
    const d = await api('/api/mail/inbox');
    _mailMsgs = d.messages || [];
    if (st) st.textContent = `${d.count} message${d.count === 1 ? '' : 's'}`;
    if (!_mailMsgs.length) { list.innerHTML = '<div class="empty"><div class="empty-icon">&#128231;</div>Inbox empty.</div>'; return; }
    list.innerHTML = _mailMsgs.map((m, i) => `
      <div class="card" style="padding:11px 13px;cursor:pointer;margin-bottom:8px;${m.seen ? '' : 'border-left:3px solid var(--accent);'}"
        onclick="openMailMsg('${esc(m.uid)}')">
        <div style="display:flex;justify-content:space-between;gap:8px;">
          <b style="font-size:.84rem;">${esc(m.from_name || m.from_email)}</b>
          <span style="font-size:.66rem;color:var(--muted);white-space:nowrap;">${esc((m.date || '').replace(/\s*\(.*\)/, '').slice(0, 22))}</span>
        </div>
        <div style="font-size:.8rem;margin-top:3px;${m.seen ? 'color:var(--muted);' : 'font-weight:600;'}">${esc(m.subject)}</div>
      </div>`).join('');
  } catch (e) {
    list.innerHTML = `<div class="empty"><div class="empty-icon">&#9888;&#65039;</div>${esc(e.message)}</div>`;
  }
}

async function openMailMsg(uid) {
  const det = document.getElementById('mail-detail');
  det.innerHTML = '<div class="loading-state">Opening…</div>';
  try {
    const m = await api(`/api/mail/message/${encodeURIComponent(uid)}`);
    _mailCur = m;
    const imgs = (m.images || []).map(u => `<img src="${API + u}" loading="lazy" onclick="openLightbox('${API + u}','')"
        style="width:130px;height:130px;object-fit:cover;border-radius:8px;cursor:pointer;">`).join('');
    det.innerHTML = `
      <div class="card" style="padding:16px 18px;">
        <div style="font-weight:700;font-size:1rem;">${esc(m.subject || '(no subject)')}</div>
        <div style="font-size:.78rem;color:var(--muted);margin:2px 0 12px;">
          From <b>${esc(m.from_name || '')}</b> &lt;${esc(m.from_email)}&gt; &middot; ${esc(m.date || '')}</div>
        <div style="font-size:.86rem;line-height:1.6;white-space:pre-wrap;max-height:300px;overflow:auto;
          background:var(--bg2);border-radius:8px;padding:12px;">${esc(m.body || '(no text)')}</div>
        ${imgs ? `<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px;">${imgs}</div>
          <div style="font-size:.7rem;color:var(--muted);margin-top:4px;">${(m.images || []).length} photo(s) attached</div>` : ''}
      </div>
      <div class="card" style="padding:16px 18px;margin-top:14px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
          <b style="font-size:.92rem;">&#9997;&#65039; Reply</b>
          <button class="btn-sm primary" id="mail-draft-btn" onclick="mailDraftQuote()" title="Send this email plus any attached photos to the local LLM on the GPU box. It writes a labor-quote reply using the fixed Acme Carpentry terms ($40/hr, 4-hr minimum, customer buys materials) and fills the Message box below. Draft only - nothing sends until you press Send reply.">&#10024; Draft AI quote</button>
        </div>
        <div class="field" style="margin-bottom:8px;"><label>To ${hlp('Where the reply goes - prefilled to the sender. The message is sent from support@example.com through the Mailcow SMTP server.')}</label>
          <input type="text" id="mail-to" value="${esc(m.from_email)}"></div>
        <div class="field" style="margin-bottom:8px;"><label>Subject</label>
          <input type="text" id="mail-subject" value="Re: ${esc(m.subject || 'your project')}"></div>
        <div class="field" style="margin-bottom:10px;"><label>Message ${hlp('Your reply body. Draft AI quote writes a first draft here; edit it freely. Nothing leaves your machine until you press Send reply.')}</label>
          <textarea id="mail-reply-body" rows="12" placeholder="Write a reply, or hit ✨ Draft AI quote…"></textarea></div>
        <button class="btn-sm primary" onclick="mailSend()" title="Send this reply now from support@example.com through the Mailcow SMTP server (port 587). It threads onto the original email. This really emails the customer - there is no undo.">&#128233; Send reply</button>
      </div>`;
    loadMailInbox();  // refresh seen state
  } catch (e) {
    det.innerHTML = `<div class="empty"><div class="empty-icon">&#9888;&#65039;</div>${esc(e.message)}</div>`;
  }
}

async function mailDraftQuote() {
  if (!_mailCur) return;
  const btn = document.getElementById('mail-draft-btn'); const orig = btn.innerHTML;
  btn.disabled = true; btn.innerHTML = '⏳ Drafting…';
  try {
    const { task_id } = await api('/api/mail/draft-quote', { method: 'POST', body: JSON.stringify({ uid: _mailCur.uid }) });
    const r = await pollTask(task_id, 90);
    if (r && r.quote) {
      document.getElementById('mail-reply-body').value = r.quote;
      toast('✨ Quote drafted — review & tweak before sending');
    } else toast('No draft returned', 'error');
  } catch (e) { toast('Draft failed: ' + e.message, 'error'); }
  btn.disabled = false; btn.innerHTML = orig;
}

async function mailSend() {
  const to = document.getElementById('mail-to').value.trim();
  const subject = document.getElementById('mail-subject').value.trim();
  const body = document.getElementById('mail-reply-body').value.trim();
  if (!to || !body) { toast('Need a recipient and a message', 'error'); return; }
  try {
    await api('/api/mail/send', { method: 'POST', body: JSON.stringify({
      to, subject, body, in_reply_to: _mailCur ? _mailCur.message_id : '' }) });
    toast('📨 Reply sent to ' + to);
  } catch (e) { toast('Send failed: ' + e.message, 'error'); }
}

window.loadMailInbox = loadMailInbox;
window.openMailMsg = openMailMsg;
window.mailDraftQuote = mailDraftQuote;
window.mailSend = mailSend;
