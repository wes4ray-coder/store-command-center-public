/* ── PEERS (friend Store installs: shared reviews + lent compute) ── */
async function loadPeers() {
  const el = document.getElementById('peers-slot');
  if (!el) return;
  let d;
  try { d = await api('/api/peers'); }
  catch (e) { el.innerHTML = `<div class="settings-group-title">&#129309; Peers</div><div style="font-size:.76rem;color:var(--warn);">${esc(e.message)}</div>`; return; }
  const peerRows = (d.peers || []).map(p => `
    <tr>
      <td style="padding:4px 8px;"><b>${esc(p.name)}</b><br><span style="font-size:.66rem;color:var(--muted);word-break:break-all;">${esc(p.base_url || 'no URL')}</span></td>
      <td style="padding:4px 8px;">${p.status === 'approved'
        ? '<span style="color:var(--green)">&#10003; approved</span>'
        : `<span style="color:var(--warn)">pending</span> <button class="btn-sm primary" onclick="peerApprove(${p.id})">Approve</button>`}
        <br><span style="font-size:.64rem;color:var(--muted);">last seen: ${esc(p.last_seen || 'never')}</span></td>
      <td style="padding:4px 8px;font-size:.72rem;">
        <label style="display:flex;gap:4px;align-items:center;cursor:pointer;"><input type="checkbox" ${p.accept_reviews ? 'checked' : ''} onchange="peerCfg(${p.id},'accept_reviews',this.checked)"> code reviews ${hlp('Let this peer send diffs for YOUR node to review: your local LLM reviews them and you can vote. They only ever see their own diff + the verdict.')}</label>
        <label style="display:flex;gap:4px;align-items:center;cursor:pointer;"><input type="checkbox" id="pw-llm-${p.id}" ${(p.accept_work && (p.work_kinds || 'llm,embedding').includes('llm')) ? 'checked' : ''} onchange="peerCfgWork(${p.id})"> LLM work ${hlp('Let this peer run text-generation jobs on YOUR unified queue at background priority — your own jobs always come first, and their jobs borrow whatever model you already have loaded (they can never swap your models). Their jobs carry THEIR prompts; they can never see or change your settings, prompts, or code.')}</label>
        <label style="display:flex;gap:4px;align-items:center;cursor:pointer;"><input type="checkbox" id="pw-emb-${p.id}" ${(p.accept_work && (p.work_kinds || 'llm,embedding').includes('embedding')) ? 'checked' : ''} onchange="peerCfgWork(${p.id})"> embeddings ${hlp('Let this peer run embedding jobs. These ride the LM Studio passthrough alongside your loaded chat model — cheap, and they never swap models.')}</label>
      </td>
      <td style="padding:4px 8px;white-space:nowrap;">
        <button class="btn-sm" onclick="peerPing(${p.id})" title="Ping — shows their branch/commit + recently promoted work">&#128246;</button>
        <button class="btn-sm" onclick="peerTestJob(${p.id})" title="Send a tiny test job to their queue">&#129514;</button>
        <button class="btn-sm danger" onclick="peerRevoke(${p.id})" title="Revoke — their key stops working immediately">&#10060;</button>
      </td>
    </tr>`).join('');
  const reviews = (d.incoming_reviews || []).filter(r => r.status !== 'error');
  const reviewRows = reviews.map(r => `
    <tr>
      <td style="padding:4px 8px;">#${r.id} <b>${esc(r.title || '')}</b><br><span style="font-size:.64rem;color:var(--muted);">${esc(r.created_at || '')}</span></td>
      <td style="padding:4px 8px;font-size:.72rem;">${r.status === 'done'
        ? `LLM: <b style="color:${r.llm_vote === 'approve' ? 'var(--green)' : 'var(--warn)'}">${esc(r.llm_vote || '?')}</b>`
        : esc(r.status)}</td>
      <td style="padding:4px 8px;">${r.human_vote
        ? `you: <b style="color:${r.human_vote === 'approve' ? 'var(--green)' : 'var(--warn)'}">${esc(r.human_vote)}</b>`
        : `<button class="btn-sm" onclick="peerReviewVote(${r.id},'approve')">&#128077;</button>
           <button class="btn-sm" onclick="peerReviewVote(${r.id},'reject')">&#128078;</button>`}</td>
    </tr>`).join('');
  el.innerHTML = `
    <div class="settings-group-title">&#129309; Peers ${hlp('Connect your Store to a friend’s Store: you review each other’s swarm changes (their local LLM + their human vote lands on your job as an advisory vote), share coarse progress, and — only if you allow it per-peer — lend each other queue compute. Peers can NEVER change anything on your node: no settings, prompts, code, or pushes. Pair: one side makes an invite key, the other Connects with it, then the first side Approves.')}</div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px;">
      <button class="btn-sm primary" onclick="peerInvite()">&#128273; New invite key</button>
      <button class="btn-sm" onclick="peerConnectForm()">&#128279; Connect to a friend</button>
      <button class="btn-sm" onclick="peerConnInfo()">&#127760; My connection info</button>
      <button class="btn-sm" onclick="loadPeers()">&#8635; Refresh</button>
      ${d.open_invites ? `<span style="font-size:.72rem;color:var(--muted);align-self:center;">${d.open_invites} unused invite key(s)</span>` : ''}
    </div>
    <div id="peer-connect-slot"></div>
    ${(d.peers || []).length
      ? `<table style="width:100%;border-collapse:collapse;font-size:.78rem;"><tr style="color:var(--muted);text-align:left;"><th style="padding:4px 8px;">Peer</th><th style="padding:4px 8px;">Status</th><th style="padding:4px 8px;">Allow</th><th style="padding:4px 8px;"></th></tr>${peerRows}</table>`
      : '<div style="font-size:.76rem;color:var(--muted);">No peers yet. Make an invite key and send it to your friend, or Connect with one they sent you.</div>'}
    ${reviews.length ? `<div style="margin-top:12px;font-size:.8rem;"><b>&#128269; Reviews friends sent you</b>
      <table style="width:100%;border-collapse:collapse;font-size:.76rem;">${reviewRows}</table></div>` : ''}
    <div id="peer-out" style="margin-top:8px;font-size:.74rem;color:var(--muted);white-space:pre-wrap;"></div>`;
}
async function peerInvite() {
  const note = prompt('Note for this invite (who is it for)?', '') ?? '';
  try {
    const r = await api('/api/peers/invite', { method: 'POST', body: JSON.stringify({ note }) });
    prompt('Copy this ONE-TIME invite key and send it to your friend\n(along with this install\'s URL):', r.invite_key);
    loadPeers();
  } catch (e) { toast('Invite failed: ' + e.message, 'error'); }
}
function peerConnectForm() {
  document.getElementById('peer-connect-slot').innerHTML = `
    <div style="border:1px solid var(--border);border-radius:8px;padding:10px;margin-bottom:10px;">
      <div class="field"><label>Friend's name</label><input type="text" id="pc-name" placeholder="Buddy"></div>
      <div class="field"><label>Friend's Store URL ${hlp('The public URL of their install, INCLUDING any path prefix their reverse proxy uses — e.g. https://friend.example.com/store')}</label><input type="text" id="pc-url" placeholder="https://friend.example.com/store"></div>
      <div class="field"><label>Invite key (from your friend)</label><input type="password" id="pc-key" placeholder="pinv_&hellip;"></div>
      <button class="btn-sm primary" onclick="peerConnect()">&#128279; Connect</button>
    </div>`;
}
async function peerConnect() {
  const name = document.getElementById('pc-name').value.trim();
  const url = document.getElementById('pc-url').value.trim();
  const key = document.getElementById('pc-key').value.trim();
  if (!url || !key) { toast('URL and invite key are required', 'error'); return; }
  try {
    const r = await api('/api/peers/connect', { method: 'POST', body: JSON.stringify({ name, url, invite_key: key }) });
    toast(r.message || 'Paired ✓');
    loadPeers();
  } catch (e) { toast('Pairing failed: ' + e.message, 'error'); }
}
async function peerConnInfo() {
  const out = document.getElementById('peer-out');
  try {
    const c = await api('/api/peers/connection-info');
    out.innerHTML = `<div style="border:1px solid var(--border);border-radius:8px;padding:10px;line-height:1.8;">
      <b>&#127760; What your friend needs to reach this node</b><br>
      Public URL: <code>${esc(c.public_url || '(not set — see STORE_PUBLIC_URL in .env)')}</code><br>
      App port: <code>${esc(String(c.port))}</code>${c.lan_ip ? ` · LAN IP: <code>${esc(c.lan_ip)}</code>` : ''}<br>
      <span style="color:var(--muted);font-size:.72rem;">
        &bull; <b>Same network / VPN:</b> they can use <code>http://${esc(c.lan_ip || 'your-lan-ip')}:${esc(String(c.port))}</code> directly — easiest is a free mesh VPN (Tailscale/ZeroTier) so no router changes are needed.<br>
        &bull; <b>Over the internet:</b> either forward TCP port ${esc(String(c.port))} on your router to this machine (then give them http://your-public-ip:${esc(String(c.port))}), or better, put it behind your reverse proxy with HTTPS and give them the public URL above <b>including any /store path prefix</b>.<br>
        &bull; Peer traffic is key-authenticated either way, but prefer VPN or HTTPS so the keys aren't sent in the clear.
      </span></div>`;
  } catch (e) { toast('Error: ' + e.message, 'error'); }
}
async function peerCfgWork(id) {
  const llm = document.getElementById('pw-llm-' + id).checked;
  const emb = document.getElementById('pw-emb-' + id).checked;
  const kinds = [llm ? 'llm' : null, emb ? 'embedding' : null].filter(Boolean).join(',');
  try {
    await api(`/api/peers/${id}/config`, { method: 'POST',
      body: JSON.stringify({ accept_work: !!kinds, work_kinds: kinds || 'llm,embedding' }) });
    toast('Saved');
  } catch (e) { toast('Error: ' + e.message, 'error'); loadPeers(); }
}
async function peerApprove(id) {
  try { await api(`/api/peers/${id}/approve`, { method: 'POST' }); toast('Peer approved ✓'); loadPeers(); }
  catch (e) { toast('Error: ' + e.message, 'error'); }
}
async function peerCfg(id, field, val) {
  try { await api(`/api/peers/${id}/config`, { method: 'POST', body: JSON.stringify({ [field]: val }) }); toast('Saved'); }
  catch (e) { toast('Error: ' + e.message, 'error'); loadPeers(); }
}
async function peerRevoke(id) {
  if (!confirm('Revoke this peer? Their key stops working immediately.')) return;
  try { await api(`/api/peers/${id}`, { method: 'DELETE' }); toast('Peer revoked'); loadPeers(); }
  catch (e) { toast('Error: ' + e.message, 'error'); }
}
async function peerPing(id) {
  const out = document.getElementById('peer-out');
  out.textContent = 'Pinging…';
  try {
    const r = await api(`/api/peers/${id}/status`);
    const rem = r.remote || {};
    out.textContent = `${rem.name || r.peer}: ${rem.branch || '?'} @ ${rem.commit || '?'}\n`
      + ((rem.recently_promoted || []).map(p => `  • promoted: ${p.title} (${p.when})`).join('\n') || '  (no promoted work yet)');
  } catch (e) { out.textContent = ''; toast('Ping failed: ' + e.message, 'error'); }
}
async function peerTestJob(id) {
  const out = document.getElementById('peer-out');
  out.textContent = 'Sending test job to their queue… (can take a minute)';
  try {
    const r = await api(`/api/peers/${id}/test-job`, { method: 'POST', body: JSON.stringify({}) });
    out.textContent = 'Their node replied: ' + (r.output || '(empty)');
  } catch (e) { out.textContent = ''; toast('Test job failed: ' + e.message, 'error'); }
}
async function peerReviewVote(rid, vote) {
  const comments = prompt('Optional comment to send back with your ' + vote + ' vote:', '') ?? '';
  try {
    await api(`/api/peers/reviews/${rid}/vote`, { method: 'POST', body: JSON.stringify({ vote, comments }) });
    toast('Vote recorded — your friend sees it next time they refresh the review.');
    loadPeers();
  } catch (e) { toast('Error: ' + e.message, 'error'); }
}
window.loadPeers = loadPeers; window.peerInvite = peerInvite; window.peerConnectForm = peerConnectForm;
window.peerConnect = peerConnect; window.peerApprove = peerApprove; window.peerCfg = peerCfg;
window.peerRevoke = peerRevoke; window.peerPing = peerPing; window.peerTestJob = peerTestJob;
window.peerReviewVote = peerReviewVote; window.peerConnInfo = peerConnInfo;
window.peerCfgWork = peerCfgWork;
