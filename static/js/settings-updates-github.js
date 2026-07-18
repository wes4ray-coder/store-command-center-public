/* ── UPDATES (GitHub) ── */
async function loadUpdates(fetch) {
  const el = document.getElementById('updates-slot');
  if (!el) return;
  let s;
  try { s = await api('/api/system/update-status' + (fetch ? '?fetch=true' : '')); }
  catch (e) { el.innerHTML = `<div class="settings-group-title">&#128260; Updates</div><div style="font-size:.76rem;color:var(--warn);">${esc(e.message)}</div>`; return; }
  const chanOpts = (s.channels || []).map(c => `<option value="${esc(c)}" ${c === s.channel ? 'selected' : ''}>${esc(c)}</option>`).join('')
    + (s.channels.includes(s.channel) ? '' : `<option value="${esc(s.channel)}" selected>${esc(s.channel)} (current)</option>`);
  const behindTxt = !s.has_remote ? '<span style="color:var(--muted)">no git remote</span>'
    : (s.behind == null ? '<span style="color:var(--muted)">unknown — Check</span>'
      : (s.behind > 0 ? `<span style="color:var(--warn)">${s.behind} update(s) available</span>`
        : '<span style="color:var(--green)">&#10003; up to date</span>'));
  el.innerHTML = `
    <div class="settings-group-title">&#128260; Updates</div>
    <div style="font-size:.76rem;color:var(--muted);line-height:1.7;margin-bottom:8px;">
      Version: <b>${esc(s.branch)}</b> @ <code>${esc(s.commit)}</code><br>${esc(s.subject || '')}
      <br>Status: ${behindTxt}${s.dirty ? ' · <span style="color:var(--warn)">local changes present</span>' : ''}
      ${s.has_remote ? ` · updates from <b>${esc(s.remote || 'origin')}</b>` : ''}
    </div>
    <div class="field"><label>Update channel (branch) ${hlp('Which git branch this install pulls updates from. retail = stable/tested, master = latest features, dev = experimental (may break). Changing it + Update & restart switches your running code to that branch. Updates come from YOUR install’s own git remote (origin) using the GitHub account signed in below — nothing is hard-wired to a vendor repo.')}</label>
      <select id="upd-channel">${chanOpts}</select>
      <div style="font-size:.68rem;color:var(--muted);margin-top:3px;">retail = stable · master = latest · dev = experimental</div></div>
    <label style="font-size:.78rem;display:flex;gap:6px;align-items:center;cursor:pointer;margin:6px 0;">
      <input type="checkbox" id="upd-enabled" ${s.enabled ? 'checked' : ''}> Updates enabled (uncheck to pin this version) ${hlp('When unchecked, the “Update & restart” button is disabled so this install stays pinned to its current version — nothing auto-changes your code. Check it to allow pulling updates.')}</label>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:6px;">
      <button class="btn-sm" onclick="updSaveConfig()">&#128190; Save</button>
      <button class="btn-sm" onclick="loadUpdates(true)">&#128269; Check for updates</button>
      <button class="btn-sm primary" onclick="updApply()" ${(!s.enabled || !s.has_remote || s.behind === 0) ? 'disabled' : ''}>&#11015;&#65039; Update &amp; restart</button>
    </div>`;
}
async function updSaveConfig() {
  try {
    await api('/api/system/update-config', { method: 'POST', body: JSON.stringify({
      channel: document.getElementById('upd-channel').value,
      enabled: document.getElementById('upd-enabled').checked,
    })});
    toast('Update settings saved'); loadUpdates(true);
  } catch (e) { toast('Save failed: ' + e.message, 'error'); }
}
async function updApply() {
  if (!confirm('Update this install to the latest ' + document.getElementById('upd-channel').value + ' and restart?')) return;
  try {
    await api('/api/system/update-config', { method: 'POST', body: JSON.stringify({ channel: document.getElementById('upd-channel').value }) });
    const r = await api('/api/system/update-apply', { method: 'POST' });
    toast(r.message || 'Updating… reload in ~10s');
  } catch (e) { toast('Update failed: ' + e.message, 'error'); }
}
window.loadUpdates = loadUpdates; window.updSaveConfig = updSaveConfig; window.updApply = updApply;

/* ── GITHUB (the account the whole app acts as) ── */
async function loadGithubSettings() {
  const el = document.getElementById('github-slot');
  if (!el) return;
  let s;
  try { s = await api('/api/github/status'); }
  catch (e) { el.innerHTML = `<div class="settings-group-title">&#128025; GitHub</div><div style="font-size:.76rem;color:var(--warn);">${esc(e.message)}</div>`; return; }
  const status = s.authenticated
    ? `<span style="color:var(--green)">&#10003; signed in as <b>${esc(s.login || '?')}</b></span>`
    : `<span style="color:var(--warn)">not signed in</span>`;
  const repoBlock = !s.authenticated ? '' : (s.owned
    ? `<div style="font-size:.72rem;color:var(--green);margin:6px 0;">&#10003; This install pushes to <b>your</b> repo: <code style="word-break:break-all;">${esc(s.origin || '')}</code>${s.has_upstream ? ' · updates flow from <b>upstream</b>' : ''}</div>
       <button class="btn-sm" onclick="ghAddCollab()">&#129309; Add collaborator</button>
       ${hlp('Invite a GitHub user (e.g. your buddy) to this repo. GitHub emails them an invite; once they accept, they can clone/pull/push it — the easy way to share a private repo.')}`
    : (s.origin ? `
      <div style="font-size:.72rem;color:var(--muted);margin:6px 0;line-height:1.6;">
        This install still points at the repo it was cloned from:<br><code style="word-break:break-all;">${esc(s.origin)}</code>
      </div>
      <button class="btn-sm" onclick="ghSetupOwn()">&#128230; Make this install yours</button>
      ${hlp('One-time onboarding: creates a private repo under YOUR GitHub account, pushes this install’s code there, and makes it the push target (origin). The repo you cloned from becomes “upstream”, so the Updates panel keeps pulling new releases from it while your own changes stay in your repo.')}`
      : `<div style="font-size:.72rem;color:var(--muted);margin:6px 0;">No git remote configured yet.</div>`));
  el.innerHTML = `
    <div class="settings-group-title">&#128025; GitHub</div>
    <div style="font-size:.76rem;color:var(--muted);line-height:1.7;margin-bottom:8px;">
      The GitHub account this app acts as — the Dev tab (repos, PRs, swarm promote) and
      the Updates panel all use whoever is signed in here, against your own repos and
      this install's own git remote. Status: ${status}
    </div>
    ${repoBlock}
    ${s.authenticated ? `
      <div style="margin-top:8px;"><button class="btn-sm danger" onclick="ghLogout()">&#128275; Sign out</button></div>
    ` : `
      <div class="field"><label>Personal Access Token ${hlp('Create one at github.com → Settings → Developer settings → Tokens (classic: repo + workflow + read:org scopes). It signs the GitHub CLI (gh) in and also wires git push/pull to the same account. gh keeps it in your system keyring — this app never stores it.')}</label>
        <input type="password" id="gh-token" placeholder="ghp_&hellip; or github_pat_&hellip;"></div>
      <button class="btn-sm primary" onclick="ghLogin()">&#128273; Sign in to GitHub</button>
      ${(s.detail && s.detail.length) ? `<div style="font-size:.68rem;color:var(--muted);margin-top:6px;">${s.detail.map(esc).join('<br>')}</div>` : ''}
    `}`;
}
async function ghLogin() {
  const tok = (document.getElementById('gh-token').value || '').trim();
  if (!tok) { toast('Paste a GitHub token first', 'error'); return; }
  try {
    const r = await api('/api/github/auth/login', { method: 'POST', body: JSON.stringify({ token: tok }) });
    toast('GitHub: signed in as ' + (r.login || 'ok'));
    loadGithubSettings(); loadUpdates();
  } catch (e) { toast('GitHub sign-in failed: ' + e.message, 'error'); }
}
async function ghLogout() {
  if (!confirm('Sign the GitHub CLI out? The Dev tab and Updates will lose GitHub access until you sign in again.')) return;
  try { await api('/api/github/auth/logout', { method: 'POST' }); toast('GitHub signed out'); loadGithubSettings(); }
  catch (e) { toast('Error: ' + e.message, 'error'); }
}
async function ghAddCollab() {
  const username = prompt('GitHub username to invite as a collaborator on your repo:');
  if (!username) return;
  try {
    const r = await api('/api/github/repo/collaborator', { method: 'POST', body: JSON.stringify({ username }) });
    toast(r.message || 'Invited ✓');
  } catch (e) { toast('Invite failed: ' + e.message, 'error'); }
}
async function ghSetupOwn() {
  const name = prompt('Name for YOUR repo (created private under your GitHub account).\n\nThe repo you cloned from stays connected as "upstream" so updates keep flowing; your own changes will push to the new repo.', 'store-command-center');
  if (!name) return;
  toast('Creating your repo & pushing — this can take a minute…');
  try {
    const r = await api('/api/github/repo/setup-own', { method: 'POST', body: JSON.stringify({ name }) });
    toast(r.message || 'Repo created ✓');
    loadGithubSettings(); loadUpdates();
  } catch (e) { toast('Repo setup failed: ' + e.message, 'error'); }
}
window.loadGithubSettings = loadGithubSettings; window.ghLogin = ghLogin;
window.ghLogout = ghLogout; window.ghSetupOwn = ghSetupOwn;
window.ghAddCollab = ghAddCollab;
