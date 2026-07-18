/* ══ GITHUB / DEV SWARM TAB ══
   Manage your GitHub (repos, branches, PRs, issues, start new projects), see the
   dev→master→retail workflow, configure the local-model agent swarm, and propose
   jobs the swarm will work on. Phase 1 = management + config + job proposals.
   Phase 2 = the live autonomous engine (agents code/review/vote/test/promote). */

let _ghSection = 'board';
let _ghJobs = [];
let _ghJobTimer = null;   // live-refresh timer for an open, working job
const GH_WORKING = ['planning', 'coding', 'reviewing', 'testing'];

const GH_SECTIONS = [
  { key: 'board',    icon: '&#128203;', label: 'Workboard' },
  { key: 'repos',    icon: '&#128193;', label: 'Repositories' },
  { key: 'workflow', icon: '&#127807;', label: 'Workflow' },
  { key: 'swarm',    icon: '&#129302;', label: 'Dev Swarm' },
  { key: 'cron',     icon: '&#9200;',   label: 'Cron' },
  { key: 'agents',   icon: '&#9881;&#65039;', label: 'Agents & Models' },
];

const BOARD_COLS = [
  { key: 'proposed', label: 'Proposed',        statuses: ['proposed'],                             color: 'var(--muted)' },
  { key: 'working',  label: 'Working',          statuses: ['planning', 'coding', 'reviewing', 'testing', 'decomposed'], color: 'var(--accent)' },
  { key: 'needs',    label: 'Needs you',        statuses: ['awaiting_input', 'awaiting_review', 'awaiting_system'], color: 'var(--warn)' },
  { key: 'approved', label: 'Approved',         statuses: ['approved'],                             color: '#22c55e' },
  { key: 'done',     label: 'Done',             statuses: ['done'],                                 color: '#22c55e' },
  { key: 'held',     label: 'Paused / Failed',  statuses: ['paused', 'failed'],                     color: '#f87171' },
];

async function renderGithub() {
  document.getElementById('main-content').innerHTML = `
    <div class="view-header">
      <div class="view-title">&#128025; GitHub &amp; Dev Swarm</div>
      <div class="view-sub">Manage your repos and let a swarm of your <b>local models</b> propose,
        review, and vote on changes — you approve, then it promotes dev&nbsp;&rarr;&nbsp;main&nbsp;&rarr;&nbsp;retail.</div>
    </div>
    <div id="gh-status" style="margin-bottom:12px;"></div>
    <div id="gh-pills" style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px;"></div>
    <div id="gh-body"></div>`;
  renderGhPills();
  await loadGhStatus();
  await switchGhSection(_ghSection);
}
window.renderGithub = renderGithub;

function renderGhPills() {
  document.getElementById('gh-pills').innerHTML = GH_SECTIONS.map(s => `
    <button class="btn-sm ${s.key === _ghSection ? 'primary' : ''}" onclick="switchGhSection('${s.key}')">
      ${s.icon} ${s.label}</button>`).join('');
}

async function loadGhStatus() {
  const el = document.getElementById('gh-status');
  try {
    const s = await api('/api/github/status');
    if (s.authenticated) {
      el.innerHTML = `<div style="background:rgba(34,197,94,.1);border:1px solid rgba(34,197,94,.35);
        border-radius:10px;padding:10px 14px;font-size:.82rem;">
        <span style="color:#22c55e;font-weight:600;">&#9679; GitHub connected</span>
        <span style="color:var(--muted);"> &mdash; ${esc(s.login || '')}</span></div>`;
    } else {
      el.innerHTML = `<div style="background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.35);
        border-radius:10px;padding:10px 14px;font-size:.82rem;">
        <span style="color:#f87171;font-weight:600;">&#9679; GitHub not authenticated</span>
        <span style="color:var(--muted);"> &mdash; run <code>gh auth login</code> in a terminal.</span></div>`;
    }
  } catch (e) { el.innerHTML = `<div style="color:var(--warn);font-size:.82rem;">${esc(e.message)}</div>`; }
}

async function switchGhSection(sec) {
  if (_ghJobTimer) { clearTimeout(_ghJobTimer); _ghJobTimer = null; }
  _ghSection = sec; renderGhPills();
  const body = document.getElementById('gh-body');
  body.innerHTML = '<div class="loading-state">Loading…</div>';
  try {
    if (sec === 'board')    return await ghRenderBoard();
    if (sec === 'repos')    return await ghRenderRepos();
    if (sec === 'workflow') return await ghRenderWorkflow();
    if (sec === 'swarm')    return await ghRenderSwarm();
    if (sec === 'cron')     return await ghRenderCron();
    if (sec === 'agents')   return await ghRenderAgents();
  } catch (e) {
    body.innerHTML = `<div class="empty"><div class="empty-icon">&#9888;&#65039;</div>${esc(e.message)}</div>`;
  }
}
window.switchGhSection = switchGhSection;

/* ── Workboard (kanban of swarm jobs by status) ───────────────────────────── */
async function ghRenderBoard() {
  const jobs = await api('/api/github/jobs');
  const body = document.getElementById('gh-body');
  const col = (c) => {
    const items = jobs.filter(j => c.statuses.includes(j.status));
    return `<div style="flex:1;min-width:200px;background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:10px;">
      <div style="font-size:.74rem;font-weight:700;color:${c.color};text-transform:uppercase;letter-spacing:.04em;margin-bottom:8px;display:flex;justify-content:space-between;">
        <span>${c.label}</span><span style="opacity:.6;">${items.length}</span></div>
      <div style="display:flex;flex-direction:column;gap:8px;">
        ${items.map(j => `<div class="card" style="padding:9px 10px;cursor:pointer;" onclick="ghOpenJob(${j.id})">
          <div style="font-weight:600;font-size:.78rem;line-height:1.3;">${esc(j.title)}</div>
          <div style="font-size:.66rem;color:var(--muted);margin-top:4px;">${esc((j.repo || '').split('/').pop() || '')} · ${esc(j.branch || 'dev')}${j.open_questions ? ` · <span style="color:var(--warn);">${j.open_questions}?</span>` : ''}</div>
          ${GH_WORKING.includes(j.status) ? `<div style="font-size:.64rem;color:var(--accent);margin-top:3px;">⏳ ${esc(j.progress_msg || j.status)}</div>` : ''}
        </div>`).join('') || '<div style="font-size:.7rem;color:var(--muted);opacity:.5;">—</div>'}
      </div></div>`;
  };
  body.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;gap:8px;">
      <span style="color:var(--muted);font-size:.82rem;">${jobs.length} jobs across the pipeline</span>
      <button class="btn-sm primary" onclick="switchGhSection('swarm')">&#10133; New job</button>
    </div>
    <div style="display:flex;gap:12px;overflow-x:auto;align-items:flex-start;padding-bottom:8px;">
      ${BOARD_COLS.map(col).join('')}
    </div>`;
  // live-refresh the board while anything is actively working
  if (jobs.some(j => GH_WORKING.includes(j.status)) && _ghSection === 'board') {
    _ghJobTimer = setTimeout(() => { if (_ghSection === 'board') ghRenderBoard(); }, 5000);
  }
}
window.ghRenderBoard = ghRenderBoard;

/* ── Repositories ─────────────────────────────────────────────────────────── */
async function ghRenderRepos() {
  const data = await api('/api/github/repos');
  const body = document.getElementById('gh-body');
  body.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;gap:8px;">
      <span style="color:var(--muted);font-size:.82rem;">${data.count} repositories</span>
      <button class="btn-sm primary" onclick="ghNewProjectModal()">&#10133; New project</button>
    </div>
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px;">
      ${data.repos.map(r => `
        <div class="card" style="padding:14px;cursor:pointer;" onclick="ghOpenRepo('${esc(r.full)}')">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">
            <span style="font-weight:600;font-size:.9rem;">${esc(r.name)}</span>
            <span style="font-size:.62rem;padding:2px 7px;border-radius:20px;
              background:${r.private ? 'rgba(234,179,8,.15)' : 'rgba(34,197,94,.15)'};
              color:${r.private ? '#eab308' : '#22c55e'};">${r.private ? 'private' : 'public'}</span>
          </div>
          <div style="color:var(--muted);font-size:.75rem;margin-top:6px;min-height:2.2em;">${esc(r.description || '—')}</div>
          <div style="color:var(--muted);font-size:.68rem;margin-top:8px;">
            ${esc(r.default_branch || '')} · ★ ${r.stars} · ${r.pushed_at ? new Date(r.pushed_at).toLocaleDateString() : ''}
          </div>
        </div>`).join('')}
    </div>`;
}

let _ghRepo = null;   // current repo full name for the browser

async function ghOpenRepo(full) {
  _ghRepo = full;
  const body = document.getElementById('gh-body');
  body.innerHTML = '<div class="loading-state">Loading ' + esc(full) + '…</div>';
  const r = await api('/api/github/repo?full=' + encodeURIComponent(full));
  body.innerHTML = `
    <button class="btn-sm" onclick="switchGhSection('repos')">&#8592; All repos</button>
    <div class="card" style="padding:16px;margin-top:12px;">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
        <div style="font-weight:700;font-size:1.05rem;">${esc(r.full)}</div>
        <a class="btn-sm" href="${esc(r.url)}" target="_blank" rel="noopener">Open on GitHub &#8599;</a>
      </div>
      <div style="color:var(--muted);font-size:.82rem;margin-top:6px;">${esc(r.description || '')}</div>
      <div style="color:var(--muted);font-size:.72rem;margin-top:6px;">default: ${esc(r.default_branch || '')} · ${esc(r.visibility || '')}</div>
      <div style="margin-top:12px;">
        <button class="btn-sm primary" onclick="ghProposeForRepo('${esc(r.full)}')">&#129302; Propose a swarm job on this repo</button>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px;">
      <div id="gh-files" class="card" style="padding:12px;"><div class="loading-state">Loading files…</div></div>
      <div style="display:flex;flex-direction:column;gap:12px;">
        ${ghListCard('Branches (' + r.branches.length + ')', r.branches.map(b => `<div>${esc(b)}</div>`).join('') || '—')}
        ${ghListCard('Open PRs (' + r.pulls.length + ')', r.pulls.map(p => `<div><a href="${esc(p.url)}" target="_blank" rel="noopener">#${p.number} ${esc(p.title)}</a></div>`).join('') || 'none')}
        ${ghListCard('Open Issues (' + r.issues.length + ')', r.issues.map(i => `<div><a href="${esc(i.url)}" target="_blank" rel="noopener">#${i.number} ${esc(i.title)}</a></div>`).join('') || 'none')}
      </div>
    </div>
    <div id="gh-readme" class="card" style="padding:16px;margin-top:12px;"><div class="loading-state">Checking for README…</div></div>`;
  ghBrowse(full, '');
  ghLoadReadme(full);
}

async function ghBrowse(full, path) {
  const el = document.getElementById('gh-files');
  if (!el) return;
  el.innerHTML = '<div class="loading-state">Loading…</div>';
  try {
    const d = await api(`/api/github/repo/contents?full=${encodeURIComponent(full)}&path=${encodeURIComponent(path)}`);
    const up = path ? path.split('/').slice(0, -1).join('/') : null;
    el.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
        <div style="font-weight:600;font-size:.8rem;">&#128193; /${esc(path)}</div>
        <button class="btn-sm" onclick="ghScopeJob('${esc(full)}','${esc(path || '')}','folder')">Scope job here</button>
      </div>
      <div style="font-size:.78rem;line-height:1.9;max-height:340px;overflow:auto;">
        ${path !== '' ? `<div style="cursor:pointer;color:var(--muted);" onclick="ghBrowse('${esc(full)}','${esc(up)}')">&#8617; ..</div>` : ''}
        ${d.items.map(it => it.type === 'dir'
          ? `<div style="cursor:pointer;" onclick="ghBrowse('${esc(full)}','${esc(it.path)}')">&#128193; ${esc(it.name)}</div>`
          : `<div style="display:flex;justify-content:space-between;gap:8px;">
               <span style="cursor:pointer;" onclick="ghViewFile('${esc(full)}','${esc(it.path)}')">&#128196; ${esc(it.name)}</span>
               <span style="cursor:pointer;color:var(--accent2);font-size:.66rem;" title="Scope a job to this file"
                 onclick="ghScopeJob('${esc(full)}','${esc(it.path)}','file')">scope&nbsp;&#8594;</span>
             </div>`).join('') || '<span style="color:var(--muted);">empty</span>'}
      </div>`;
  } catch (e) { el.innerHTML = `<div style="color:var(--warn);font-size:.78rem;">${esc(e.message)}</div>`; }
}
window.ghBrowse = ghBrowse;

async function ghViewFile(full, path) {
  try {
    const d = await api(`/api/github/repo/file?full=${encodeURIComponent(full)}&path=${encodeURIComponent(path)}`);
    openLightbox && document.getElementById('lightbox') ? null : null;
    const w = window.open('', '_blank');
    if (w) { w.document.write('<pre style="white-space:pre-wrap;font-family:monospace;padding:16px;">' +
             esc(path) + '\n\n' + esc(d.content) + '</pre>'); w.document.title = path; }
  } catch (e) { toast('Open failed: ' + e.message, 'error'); }
}
window.ghViewFile = ghViewFile;

async function ghLoadReadme(full) {
  const el = document.getElementById('gh-readme');
  if (!el) return;
  try {
    const d = await api('/api/github/repo/readme?full=' + encodeURIComponent(full));
    if (!d.has_readme) { el.innerHTML = '<div style="color:var(--muted);font-size:.78rem;">No README in this repo.</div>'; return; }
    el.innerHTML = `<div style="font-weight:600;font-size:.82rem;margin-bottom:10px;">&#128196; ${esc(d.name)}</div>
      <div class="readme-body" style="font-size:.82rem;line-height:1.6;max-height:520px;overflow:auto;">${d.html}</div>`;
  } catch (e) { el.innerHTML = `<div style="color:var(--muted);font-size:.78rem;">README unavailable: ${esc(e.message)}</div>`; }
}

function ghScopeJob(full, path, scope) {
  _ghSection = 'swarm'; renderGhPills();
  document.getElementById('gh-body').innerHTML = '<div class="loading-state">…</div>';
  ghRenderSwarm(full).then(() => {
    const f = document.getElementById('gh-job-form'); if (f) f.open = true;
    const sc = document.getElementById('job-scope'); if (sc) { sc.value = scope; ghScopeChanged(); }
    const p = document.getElementById('job-paths'); if (p) p.value = path;
    const t = document.getElementById('job-title'); if (t) t.focus();
  });
}
window.ghScopeJob = ghScopeJob;
function ghListCard(title, html) {
  return `<div class="card" style="padding:12px;">
    <div style="font-weight:600;font-size:.8rem;margin-bottom:8px;">${title}</div>
    <div style="font-size:.74rem;line-height:1.7;color:var(--muted);max-height:220px;overflow:auto;">${html}</div>
  </div>`;
}
window.ghOpenRepo = ghOpenRepo;

function ghNewProjectModal() {
  const name = prompt('New repository name:');
  if (!name) return;
  const desc = prompt('Description (optional):') || '';
  const priv = confirm('Private repo?  OK = private, Cancel = public');
  api('/api/github/repo/create', { method: 'POST', body: JSON.stringify({
    name, description: desc, private: priv, add_readme: true, gitignore: 'Python'
  })}).then(res => { toast('✅ ' + res.message); switchGhSection('repos'); })
     .catch(e => toast('Create failed: ' + e.message, 'error'));
}
window.ghNewProjectModal = ghNewProjectModal;

/* ── Workflow (dev → master → retail) ─────────────────────────────────────── */
async function ghRenderWorkflow() {
  const data = await api('/api/github/workflow');
  const body = document.getElementById('gh-body');
  body.innerHTML = `
    <div style="color:var(--muted);font-size:.82rem;margin-bottom:12px;">
      Your three worktrees. Develop on <b>dev</b>, promote working changes to <b>master</b> (live), then <b>retail</b> (clean).
    </div>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px;">
      ${data.worktrees.map(w => `
        <div class="card" style="padding:14px;">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <span style="font-weight:700;">${esc(w.branch)}</span>
            <span style="font-size:.66rem;color:var(--muted);">${w.port ? ':' + w.port : ''} ${w.base ? esc(w.base) : ''}</span>
          </div>
          <div style="font-family:monospace;font-size:.72rem;color:var(--muted);margin-top:6px;">${esc(w.head || 'missing')} @ ${esc(w.checked_out || '')}</div>
          <div style="font-size:.74rem;margin-top:8px;">
            ${w.dirty ? `<span style="color:var(--warn);">● ${w.changed_files} uncommitted</span>` : '<span style="color:#22c55e;">● clean</span>'}
            ${w.branch !== 'master' && w.ahead != null ? `<span style="color:var(--muted);"> · ${w.ahead} ahead / ${w.behind} behind master</span>` : ''}
          </div>
        </div>`).join('')}
    </div>
    <div style="margin-top:14px;display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
      <button class="btn-sm" onclick="ghRestartLive()" title="Restart this live Store app so it loads the code already promoted to the master worktree on disk. Briefly unavailable (~10s). A promote writes the files but the running process keeps old code until this restart.">&#128260; Restart live app (load promoted code)</button>
      <span style="font-size:.72rem;color:var(--muted);">A promote writes new code to the master worktree on disk — the live app loads it on restart (no GitHub pull needed here).</span>
    </div>`;
}

/* ── Cron management ──────────────────────────────────────────────────────── */
async function ghRenderCron() {
  const jobs = await api('/api/github/jobs');
  const body = document.getElementById('gh-body');
  const active = jobs.filter(j => j.cron_enabled);
  body.innerHTML = `
    <div style="color:var(--muted);font-size:.82rem;margin-bottom:12px;">
      Cron keeps working-in-progress jobs moving on a schedule — it advances any non-gated job
      on its interval (gated jobs still wait for you). ${active.length} scheduled.
    </div>
    ${jobs.length ? `<div style="display:flex;flex-direction:column;gap:10px;">${jobs.map(j => `
      <div class="card" style="padding:12px;">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
          <span style="font-weight:600;font-size:.84rem;cursor:pointer;" onclick="ghOpenJob(${j.id})">${esc(j.title)}</span>
          <span style="font-size:.64rem;color:var(--muted);">${esc(j.status)} · updated ${j.updated_at ? new Date(j.updated_at.replace(' ','T')+'Z').toLocaleString() : ''}</span>
        </div>
        <div style="display:flex;gap:10px;align-items:center;margin-top:8px;flex-wrap:wrap;">
          <label style="font-size:.76rem;display:flex;gap:6px;align-items:center;cursor:pointer;">
            <input type="checkbox" ${j.cron_enabled ? 'checked' : ''} onchange="ghCronToggle(${j.id}, this.checked)"> scheduled ${hlp('When on, the swarm advances this job automatically on the interval below - no clicks needed. Gated jobs still pause for your input/review; only non-gated stages auto-run.')}</label>
          <label style="font-size:.76rem;color:var(--muted);display:flex;gap:6px;align-items:center;">every
            <input type="number" value="${j.cron_interval || 30}" min="1" max="1440" style="width:64px;" onchange="ghCronInterval(${j.id}, this.value)"> min ${hlp('How often the scheduler pokes this job to take its next step (1-1440 minutes). Shorter = faster progress but more GPU turns.')}</label>
          <button class="btn-sm" onclick="ghRunJob(${j.id})" title="Kick the swarm to take this job's next step right now, without waiting for the schedule.">&#9654; Run now</button>
        </div>
      </div>`).join('')}</div>`
      : '<div class="empty"><div class="empty-icon">&#9200;</div>No jobs yet — propose one in Dev Swarm, then schedule it here.</div>'}`;
}
async function ghCronToggle(jid, on) {
  try { await api('/api/github/jobs/' + jid, { method: 'PATCH', body: JSON.stringify({ cron_enabled: on ? 1 : 0 }) }); toast(on ? 'Scheduled' : 'Unscheduled'); }
  catch (e) { toast('Failed: ' + e.message, 'error'); }
}
async function ghCronInterval(jid, v) {
  const n = Math.max(1, parseInt(v) || 30);
  try { await api('/api/github/jobs/' + jid, { method: 'PATCH', body: JSON.stringify({ cron_interval: n }) }); toast('Interval set to ' + n + ' min'); }
  catch (e) { toast('Failed: ' + e.message, 'error'); }
}
window.ghRenderCron = ghRenderCron; window.ghCronToggle = ghCronToggle; window.ghCronInterval = ghCronInterval;

async function ghRestartLive() {
  if (!confirm('Restart the live app now? It will be unavailable for a few seconds while it reloads.')) return;
  try { await api('/api/github/restart-live', { method: 'POST' });
    toast('Restarting… reload the page in ~10s');
  } catch (e) { toast('Restart failed: ' + e.message, 'error'); }
}
window.ghRestartLive = ghRestartLive;

/* ── Dev Swarm: jobs ──────────────────────────────────────────────────────── */
async function ghRenderSwarm(preRepo) {
  _ghJobs = await api('/api/github/jobs');
  const ownRepo = '';   // filled in async below — never block the paint on `gh` subprocesses
  const body = document.getElementById('gh-body');
  body.innerHTML = `
    <details class="settings-group" style="margin-bottom:16px;" id="gh-job-form" ${preRepo ? 'open' : ''}>
      <summary style="cursor:pointer;font-weight:600;font-size:.9rem;">&#10133; Propose a job / fix / project</summary>
      <div style="font-size:.72rem;color:var(--muted);margin:8px 0 12px;">Describe what you want. The swarm plans it,
        asks questions if it's fuzzy or a big change, then (Phase 2) codes → reviews → votes → tests on the working branch.</div>
      <div class="field"><label>Title *</label><input type="text" id="job-title" placeholder="e.g. Add CSV export to the resell tab"></div>
      <div class="field"><label>Details / spec</label><textarea id="job-spec" rows="4" placeholder="What should change and why. Constraints, files, acceptance criteria."></textarea></div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
        <div class="field"><label>Repo (owner/name) ${hlp('Which GitHub repo the swarm works in. Defaults to this app so it can improve itself; the swarm codes on the dev branch here, never straight to main/retail.')}</label><input type="text" id="job-repo" value="${esc(preRepo || ownRepo)}" placeholder="owner/name (defaults to this install's origin)"></div>
        <div class="field"><label>Autonomy for this job ${hlp('How far the swarm runs on its own. gate = stop for your input/review at key points; auto = run straight through to the final review; step = pause after every stage. Less autonomy = more control, more clicks.')}</label>
          <select id="job-autonomy">
            <option value="">Use global default</option>
            <option value="gate">Gate the big moments</option>
            <option value="auto">Autonomous until tests pass</option>
            <option value="step">Step-by-step confirm</option>
          </select></div>
        <div class="field"><label>Direction / scope ${hlp('How wide the change may reach — the whole repo, one folder, or specific files. Narrower scope is safer: the coder agents may only edit the paths you list below.')}</label>
          <select id="job-scope" onchange="ghScopeChanged()">
            <option value="project">Whole project</option>
            <option value="folder">Specific folder</option>
            <option value="file">Specific file(s)</option>
          </select></div>
        <div class="field"><label># Agents (blank = default) ${hlp('How many coder agents work this job in parallel. Blank uses the global default (set below). More = faster on big jobs but more GPU turns and VRAM churn.')}</label>
          <input type="number" id="job-agents" min="1" max="12" placeholder="e.g. 3"></div>
        <div class="field" id="job-paths-wrap" style="grid-column:1/3;display:none;"><label>Path(s) — comma-separated ${hlp('When scope is file/folder, the exact paths the swarm is allowed to touch. Everything else is off-limits — this is the hard safety boundary for the job.')}</label>
          <input type="text" id="job-paths" placeholder="app/routers/resell.py, static/js/tab-resell.js"></div>
      </div>
      <button class="btn-sm primary" onclick="ghCreateJob()">Create job</button>
    </details>
    <div id="gh-jobs-list">${ghJobsListHtml(_ghJobs)}</div>`;
  // Default repo = the install's own origin — filled AFTER paint, and only when the
  // origin actually belongs to the signed-in user (never prefill the vendor repo).
  if (!preRepo) api('/api/github/status').then(st => {
    if (!st.owned) return;
    const m = (st.origin || '').match(/github\.com[:/]([^/]+)\/([^/.]+)/);
    const inp = document.getElementById('job-repo');
    if (m && inp && !inp.value) inp.value = m[1] + '/' + m[2];
  }).catch(() => {});
}
function ghJobsListHtml(jobs) {
  if (!jobs.length) return '<div class="empty"><div class="empty-icon">&#129302;</div>No jobs yet — propose one above.</div>';
  return `<div style="display:flex;flex-direction:column;gap:10px;">` + jobs.map(j => `
    <div class="card" style="padding:12px;cursor:pointer;" onclick="ghOpenJob(${j.id})">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">
        <span style="font-weight:600;font-size:.86rem;">${esc(j.title)}</span>
        <span style="font-size:.64rem;padding:2px 8px;border-radius:20px;background:var(--bg2);color:var(--muted);">${esc(j.status)}</span>
      </div>
      <div style="color:var(--muted);font-size:.72rem;margin-top:5px;">
        ${esc(j.repo || '')} · ${esc(j.branch || 'dev')}
        ${j.open_questions ? `· <span style="color:var(--warn);">${j.open_questions} question(s) awaiting you</span>` : ''}
      </div>
    </div>`).join('') + `</div>`;
}

function ghScopeChanged() {
  const scope = document.getElementById('job-scope').value;
  const wrap = document.getElementById('job-paths-wrap');
  if (wrap) wrap.style.display = scope === 'project' ? 'none' : 'block';
}
window.ghScopeChanged = ghScopeChanged;

async function ghCreateJob() {
  const title = document.getElementById('job-title').value.trim();
  if (!title) { toast('Title required', 'error'); return; }
  const scope = document.getElementById('job-scope').value;
  const pathsRaw = document.getElementById('job-paths').value.trim();
  const agents = parseInt(document.getElementById('job-agents').value);
  const payload = {
    title, spec: document.getElementById('job-spec').value.trim(),
    repo: document.getElementById('job-repo').value.trim(),
    autonomy: document.getElementById('job-autonomy').value || null,
    scope,
    paths: scope !== 'project' && pathsRaw ? pathsRaw.split(',').map(s => s.trim()).filter(Boolean) : [],
    agent_count: Number.isInteger(agents) ? agents : null,
  };
  try { await api('/api/github/jobs', { method: 'POST', body: JSON.stringify(payload) });
    toast('✅ Job proposed'); await ghRenderSwarm();
  } catch (e) { toast('Failed: ' + e.message, 'error'); }
}
window.ghCreateJob = ghCreateJob;
function ghProposeForRepo(full) { _ghSection = 'swarm'; renderGhPills();
  document.getElementById('gh-body').innerHTML = '<div class="loading-state">…</div>'; ghRenderSwarm(full); }
window.ghProposeForRepo = ghProposeForRepo;

async function ghOpenJob(jid) {
  if (_ghJobTimer) { clearTimeout(_ghJobTimer); _ghJobTimer = null; }
  const j = await api('/api/github/jobs/' + jid);
  const systasks = await api('/api/github/jobs/' + jid + '/system-tasks').catch(() => []);
  const body = document.getElementById('gh-body');
  const openQs = (j.questions || []).filter(q => q.status === 'open');
  body.innerHTML = `
    <button class="btn-sm" onclick="switchGhSection('swarm')">&#8592; All jobs</button>
    <div class="card" style="padding:16px;margin-top:12px;">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
        <div style="font-weight:700;font-size:1rem;">${esc(j.title)}</div>
        <span style="font-size:.66rem;padding:2px 9px;border-radius:20px;background:var(--bg2);color:var(--muted);">${esc(j.status)}</span>
      </div>
      <div style="color:var(--muted);font-size:.78rem;margin-top:8px;white-space:pre-wrap;">${esc(j.spec || '')}</div>
      ${j.enhanced_spec ? `<details style="margin-top:8px;"><summary style="cursor:pointer;font-size:.74rem;color:var(--accent2);">&#10024; Architect's enhanced spec</summary>
        <div style="font-size:.76rem;color:var(--muted);white-space:pre-wrap;margin-top:6px;padding:8px;background:var(--bg2);border-radius:8px;">${esc(j.enhanced_spec)}</div></details>` : ''}
      ${(j.children && j.children.length) ? `<div style="margin-top:10px;">
        <div style="font-size:.76rem;font-weight:600;margin-bottom:6px;">&#129513; Subtasks (${j.children.length})</div>
        ${j.children.map(c => `<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;font-size:.74rem;padding:5px 8px;background:var(--bg2);border-radius:6px;margin-bottom:5px;">
          <span style="cursor:pointer;" onclick="ghOpenJob(${c.id})">${esc(c.title)} <span style="color:var(--muted);">${esc(c.scope || '')}</span></span>
          <span style="display:flex;gap:6px;align-items:center;"><span style="font-size:.62rem;color:var(--muted);">${esc(c.status)}</span>
            ${c.status === 'proposed' ? `<button class="btn-sm" style="padding:2px 8px;" onclick="event.stopPropagation();ghRunJob(${c.id})">&#9654;</button>` : ''}</span>
        </div>`).join('')}
        ${j.children.some(c => c.status === 'proposed') ? `<button class="btn-sm primary" style="margin-top:4px;" onclick="ghRunAllSubtasks(${j.id})">&#9654; Run all subtasks</button>` : ''}
      </div>` : ''}
      <div style="color:var(--muted);font-size:.72rem;margin-top:8px;">
        ${esc(j.repo || '')} · ${esc(j.branch || 'dev')} · autonomy: ${esc(j.autonomy || 'global default')}
        · scope: ${esc(j.scope || 'project')}${ghPaths(j.paths)}
        · agents: ${j.agent_count || 'default'}
      </div>
      ${j.decision ? `<div style="margin-top:8px;font-size:.78rem;color:${j.decision === 'approved' ? '#22c55e' : '#f87171'};">
        ${j.decision === 'approved' ? '✓ Approved by you' : '✗ Rejected: ' + esc(j.decision_comment || '')}
        ${j.decision === 'approved' && j.status !== 'done' ? `<button class="btn-sm primary" style="margin-left:10px;" onclick="ghPromoteJob(${j.id})" title="Ship this approved work: merge dev into master and push, then resync retail from master, scrub it of real IPs/domains/identity/private docs, and push retail as a clean public branch. The live app keeps old code until you Restart it in Workflow.">&#128640; Promote dev &rarr; master &rarr; retail</button>` : ''}
        ${j.status === 'done' ? ' · <span style="color:var(--muted);">promoted ✓ (restart to run new code)</span>' : ''}</div>` : ''}
      <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap;">
        <button class="btn-sm primary" onclick="ghRunJob(${j.id})" title="Start (or advance) the local-model swarm on this job now: the planner/coder/reviewer agents plan, code on the dev branch, and vote. It may pause to ask you questions or wait for approval depending on the job's autonomy.">&#9654; Run swarm</button>
        <label style="font-size:.74rem;display:flex;align-items:center;gap:6px;color:var(--muted);">
          <input type="checkbox" ${j.cron_enabled ? 'checked' : ''} onchange="ghToggleCron(${j.id}, this.checked)">
          keep working on a schedule (cron) ${hlp('Let the scheduler keep advancing this job automatically on its interval, instead of you pressing Run swarm each time. Same setting as the Cron tab.')}</label>
        <button class="btn-sm" onclick="ghDeleteJob(${j.id})" title="Delete this job and its timeline from the queue. Does not touch any code already committed on the dev branch.">&#128465;&#65039; Delete</button>
      </div>
      <div style="margin-top:10px;padding-top:10px;border-top:1px solid var(--border);">
        <div style="font-size:.72rem;color:var(--muted);margin-bottom:6px;">Only you can approve or reject — models review each other's code, never their own.</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
          <button class="btn-sm" style="background:rgba(34,197,94,.15);color:#22c55e;" onclick="ghApproveJob(${j.id})" title="You are the final approver. Marks the swarm's work accepted and unlocks the Promote button - it does not push code by itself.">&#10003; Approve &rarr; promote</button>
          <input type="text" id="reject-comment" placeholder="What's wrong? (required to reject)" style="flex:1;min-width:180px;">
          <button class="btn-sm" style="background:rgba(239,68,68,.12);color:#f87171;" onclick="ghRejectJob(${j.id})" title="Send the work back to the swarm with your comment (the box to the left is required). The agents use it to revise on the dev branch; nothing is promoted.">&#10007; Reject</button>
          <button class="btn-sm" onclick="ghPeerReview(${j.id})" title="Send this job's dev-branch diff to a connected friend's Store: their local LLM reviews it and your friend can vote too. The verdict comes back as an ADVISORY vote on this job — you still make the final call.">&#129309; Peer review</button>
        </div>
        <div id="peer-votes-${j.id}" style="margin-top:6px;"></div>
      </div>
    </div>
    ${openQs.length ? `<div class="card" style="padding:14px;margin-top:12px;border-color:var(--warn);">
      <div style="font-weight:600;font-size:.84rem;color:var(--warn);margin-bottom:8px;">&#10067; The swarm needs your input</div>
      ${openQs.map(q => `<div style="margin-bottom:10px;">
        <div style="font-size:.8rem;">${esc(q.question)}</div>
        <div style="display:flex;gap:6px;margin-top:5px;">
          <input type="text" id="q-${q.id}" placeholder="Your answer…" style="flex:1;">
          <button class="btn-sm primary" onclick="ghAnswer(${q.id}, ${j.id})">Send</button>
        </div></div>`).join('')}
    </div>` : ''}
    <div class="card" style="padding:14px;margin-top:12px;">
      <div style="font-weight:600;font-size:.84rem;margin-bottom:8px;">&#128295; System agent</div>
      <div style="font-size:.72rem;color:var(--muted);margin-bottom:8px;">Installs/configures tools the swarm needs. Every command needs your approval before it runs.</div>
      ${(systasks || []).map(t => ghSysTaskHtml(t, jid)).join('') || '<div style="font-size:.74rem;color:var(--muted);margin-bottom:8px;">No system tasks.</div>'}
      <div style="display:flex;gap:6px;margin-top:8px;">
        <input type="text" id="ask-sys" placeholder="Ask the system agent to install/fix something…" style="flex:1;">
        <button class="btn-sm" onclick="ghAskSystem(${jid})" title="Ask the system agent to prepare a tool/dependency the swarm needs (e.g. install a package). It proposes the exact shell command, which you must approve before it runs on your machine.">Ask</button>
      </div>
    </div>
    <div class="card" style="padding:14px;margin-top:12px;">
      <div style="font-weight:600;font-size:.84rem;margin-bottom:8px;">Timeline</div>
      <div style="font-size:.76rem;line-height:1.7;max-height:400px;overflow:auto;">
        ${(j.events || []).map(e => `<div style="padding:4px 0;border-bottom:1px solid var(--border);">
          <span style="color:var(--accent2);font-weight:600;">${esc(e.agent || 'system')}</span>
          <span style="color:var(--muted);font-size:.68rem;"> ${esc(e.kind || '')}${e.vote ? ' · ' + esc(e.vote) : ''}${e.model ? ' · ' + esc(e.model) : ''}</span>
          <div style="white-space:pre-wrap;">${esc(e.content || '')}</div>
        </div>`).join('') || '<span style="color:var(--muted);">No activity yet.</span>'}
      </div>
    </div>`;
  ghLoadPeerVotes(jid);   // async — fills the peer-votes strip after paint
  // Live-refresh while the swarm is actively working this job (never while you're typing).
  if (GH_WORKING.includes(j.status) && _ghSection === 'swarm') {
    _ghJobTimer = setTimeout(() => ghOpenJob(jid), 4000);
  }
}
window.ghOpenJob = ghOpenJob;

/* ── Peer review: send this job's diff to a friend's Store for an advisory vote ── */
async function ghPeerReview(jid) {
  let peers = [];
  try { peers = ((await api('/api/peers')).peers || []).filter(p => p.status === 'approved'); }
  catch (e) { toast('Could not load peers: ' + e.message, 'error'); return; }
  if (!peers.length) { toast('No approved peers yet — pair with a friend in Settings → Integrations → Peers.', 'error'); return; }
  let peer = peers[0];
  if (peers.length > 1) {
    const pick = prompt('Send to which peer?\n' + peers.map((p, i) => `${i + 1}. ${p.name}`).join('\n'), '1');
    peer = peers[(parseInt(pick, 10) || 1) - 1] || peers[0];
  }
  try {
    await api(`/api/peers/${peer.id}/review-job`, { method: 'POST', body: JSON.stringify({ job_id: jid }) });
    toast(`Diff sent to ${peer.name} — their node is reviewing. Refresh the votes strip for the verdict.`);
    ghLoadPeerVotes(jid);
  } catch (e) { toast('Peer review failed: ' + e.message, 'error'); }
}
async function ghLoadPeerVotes(jid) {
  const el = document.getElementById(`peer-votes-${jid}`);
  if (!el) return;
  let reqs = [];
  try { reqs = (await api('/api/peers/review-requests?job_id=' + jid)).requests || []; }
  catch { return; }
  if (!reqs.length) { el.innerHTML = ''; return; }
  el.innerHTML = `<div style="font-size:.72rem;color:var(--muted);">
    ${reqs.map(r => {
      const vote = r.human_vote || r.llm_vote;
      const who = esc(r.peer_name) + (r.human_vote ? '' : r.llm_vote ? ' (their LLM)' : '');
      return `<span style="margin-right:10px;">&#129309; ${who}: ${r.status === 'done'
        ? `<b style="color:${vote === 'approve' ? '#22c55e' : '#f87171'}">${esc(vote || '?')}</b>`
        : `${esc(r.status)}&hellip; <a href="#" onclick="ghRefreshPeerVote(${r.id},${jid});return false;">check</a>`}</span>`;
    }).join('')}</div>`;
}
async function ghRefreshPeerVote(rid, jid) {
  try {
    await api(`/api/peers/review-requests/${rid}/refresh`, { method: 'POST' });
    ghLoadPeerVotes(jid);
  } catch (e) { toast('Refresh failed: ' + e.message, 'error'); }
}
window.ghPeerReview = ghPeerReview; window.ghLoadPeerVotes = ghLoadPeerVotes;
window.ghRefreshPeerVote = ghRefreshPeerVote;

async function ghRunJob(jid) {
  try { const r = await api('/api/github/jobs/' + jid + '/run', { method: 'POST' });
    toast(r.message || 'Run requested'); ghOpenJob(jid);
  } catch (e) { toast('Failed: ' + e.message, 'error'); }
}
async function ghToggleCron(jid, on) {
  try { await api('/api/github/jobs/' + jid, { method: 'PATCH', body: JSON.stringify({ cron_enabled: on ? 1 : 0 }) });
    toast(on ? 'Cron enabled for this job' : 'Cron disabled');
  } catch (e) { toast('Failed: ' + e.message, 'error'); }
}
async function ghAnswer(qid, jid) {
  const v = document.getElementById('q-' + qid).value.trim();
  if (!v) return;
  try { await api('/api/github/questions/' + qid + '/answer', { method: 'POST', body: JSON.stringify({ answer: v }) });
    toast('Answer sent'); ghOpenJob(jid);
  } catch (e) { toast('Failed: ' + e.message, 'error'); }
}
async function ghDeleteJob(jid) {
  if (!confirm('Delete this job?')) return;
  try { await api('/api/github/jobs/' + jid, { method: 'DELETE' }); toast('Deleted'); switchGhSection('swarm'); }
  catch (e) { toast('Failed: ' + e.message, 'error'); }
}
function ghPaths(paths) {
  try { const p = typeof paths === 'string' ? JSON.parse(paths || '[]') : (paths || []);
    return p.length ? ' (' + p.map(esc).join(', ') + ')' : ''; } catch { return ''; }
}
async function ghApproveJob(jid) {
  if (!confirm('Approve this job? You are the final approver.')) return;
  try { await api('/api/github/jobs/' + jid + '/approve', { method: 'POST' });
    toast('✅ Approved — ready to promote'); ghOpenJob(jid);
  } catch (e) { toast('Failed: ' + e.message, 'error'); }
}
async function ghRejectJob(jid) {
  const c = document.getElementById('reject-comment').value.trim();
  if (!c) { toast('Add a comment explaining the problem to reject', 'error'); return; }
  try { await api('/api/github/jobs/' + jid + '/reject', { method: 'POST', body: JSON.stringify({ comment: c }) });
    toast('Rejected with feedback'); ghOpenJob(jid);
  } catch (e) { toast('Failed: ' + e.message, 'error'); }
}
function ghSysTaskHtml(t, jid) {
  const color = { requested: 'var(--warn)', approved: 'var(--muted)', installing: 'var(--muted)',
                  done: '#22c55e', verified: '#22c55e', failed: '#f87171' }[t.status] || 'var(--muted)';
  let reason = '';
  try { reason = JSON.parse(t.report || '{}').reason || ''; } catch { reason = ''; }
  const showReport = ['done', 'verified', 'failed'].includes(t.status);
  return `<div class="card" style="padding:10px;margin-bottom:8px;">
    <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">
      <code style="font-size:.74rem;word-break:break-all;">${esc(t.command)}</code>
      <span style="font-size:.62rem;color:${color};white-space:nowrap;">${esc(t.status)}</span>
    </div>
    ${reason && !showReport ? `<div style="font-size:.7rem;color:var(--muted);margin-top:4px;">${esc(reason)}</div>` : ''}
    ${showReport ? `<pre style="font-size:.68rem;background:var(--bg2);padding:6px;border-radius:6px;margin-top:6px;max-height:160px;overflow:auto;white-space:pre-wrap;">${esc(t.report || '')}</pre>` : ''}
    ${t.status === 'requested' ? `<div style="display:flex;gap:6px;margin-top:6px;">
      <button class="btn-sm" style="background:rgba(34,197,94,.15);color:#22c55e;" onclick="ghApproveSys(${t.id}, ${jid})">&#10003; Approve &amp; run</button>
      <button class="btn-sm" style="background:rgba(239,68,68,.12);color:#f87171;" onclick="ghRejectSys(${t.id}, ${jid})">&#10007; Reject</button>
    </div>` : ''}
  </div>`;
}
async function ghApproveSys(tid, jid) {
  if (!confirm('Approve and run this command on your machine?')) return;
  try { const r = await api('/api/github/system-tasks/' + tid + '/approve', { method: 'POST' });
    toast(r.message || 'Running…'); setTimeout(() => ghOpenJob(jid), 1500);
  } catch (e) { toast('Failed: ' + e.message, 'error'); }
}
async function ghRejectSys(tid, jid) {
  try { await api('/api/github/system-tasks/' + tid + '/reject', { method: 'POST' }); toast('Rejected'); ghOpenJob(jid); }
  catch (e) { toast('Failed: ' + e.message, 'error'); }
}
async function ghAskSystem(jid) {
  const need = document.getElementById('ask-sys').value.trim();
  if (!need) return;
  try { const r = await api('/api/github/jobs/' + jid + '/ask-system', { method: 'POST', body: JSON.stringify({ need }) });
    toast(r.message || 'Asking…'); setTimeout(() => ghOpenJob(jid), 2500);
  } catch (e) { toast('Failed: ' + e.message, 'error'); }
}
window.ghApproveSys = ghApproveSys; window.ghRejectSys = ghRejectSys; window.ghAskSystem = ghAskSystem;

async function ghPromoteJob(jid) {
  if (!confirm('Promote this job dev → master → retail?\n\nThis merges to master, pushes both branches, and resyncs retail. The running app keeps old code until you restart.')) return;
  toast('Promoting… (this runs git across all three worktrees)');
  try { const r = await api('/api/github/jobs/' + jid + '/promote', { method: 'POST' });
    const failed = (r.steps || []).filter(s => !s.ok);
    toast(failed.length ? ('Promoted with issues: ' + failed.map(s => s.step).join(', ')) : '✅ Promoted — restart to run new code', failed.length ? 'error' : 'success');
    ghOpenJob(jid);
  } catch (e) { toast('Promote failed: ' + e.message, 'error'); }
}
async function ghRunAllSubtasks(jid) {
  try {
    const j = await api('/api/github/jobs/' + jid);
    const todo = (j.children || []).filter(c => c.status === 'proposed');
    for (const c of todo) { await api('/api/github/jobs/' + c.id + '/run', { method: 'POST' }); }
    toast(`Started ${todo.length} subtask(s)`); ghOpenJob(jid);
  } catch (e) { toast('Failed: ' + e.message, 'error'); }
}
window.ghRunJob = ghRunJob; window.ghToggleCron = ghToggleCron; window.ghAnswer = ghAnswer;
window.ghDeleteJob = ghDeleteJob; window.ghApproveJob = ghApproveJob; window.ghRejectJob = ghRejectJob;
window.ghPromoteJob = ghPromoteJob; window.ghRunAllSubtasks = ghRunAllSubtasks;

/* ── Agents & Models config ───────────────────────────────────────────────── */
async function ghRenderAgents() {
  const [cfg, models, loaded] = await Promise.all([
    api('/api/github/swarm-config'),
    api('/api/github/llm-models').catch(() => ({ models: [] })),
    api('/api/github/loaded-model').catch(() => ({ loaded: null, checks: [] })),
  ]);
  const body = document.getElementById('gh-body');
  const allModels = models.models || [];
  const sys = cfg.system_agent || {};
  const modelOpts = (sel) => `<option value="">— pick a local model —</option>` +
    allModels.map(m => `<option value="${esc(m)}" ${m === sel ? 'selected' : ''}>${esc(m)}</option>`).join('');
  window._ghAllModels = allModels;
  window._ghCfgAgents = cfg.agents || [];

  body.innerHTML = `
    <div style="background:rgba(108,99,255,.08);border:1px solid var(--border);border-radius:8px;padding:10px 12px;font-size:.74rem;color:var(--muted);margin-bottom:14px;line-height:1.6;">
      &#9888;&#65039; <b>Only one model loads in VRAM at a time</b>, so agent turns run <b>sequentially</b> (swapping models between turns).
      ${allModels.length ? allModels.length + ' local models detected.' : '<br>No local models detected — is LM Studio running on the GPU box?'}
    </div>

    <div class="settings-group">
      <div class="settings-group-title">&#128190; GPU model — load &amp; pin</div>
      <div id="gh-loaded" style="font-size:.8rem;margin-bottom:10px;">
        ${loaded.loaded
          ? `<span style="color:#22c55e;">&#9679; resident: <b>${esc(loaded.loaded)}</b></span> <span style="color:var(--muted);">· context ${loaded.context || '?'} tokens</span>`
          : '<span style="color:var(--warn);">&#9679; nothing resident — load a model so turns don\'t stall</span>'}
      </div>
      ${(loaded.checks || []).map(c => `<div style="font-size:.72rem;color:${c.level === 'warn' ? 'var(--warn)' : 'var(--muted)'};margin-bottom:4px;">${c.level === 'warn' ? '&#9888;&#65039;' : '&#8505;&#65039;'} ${esc(c.msg)}</div>`).join('')}
      <div style="display:grid;grid-template-columns:2fr 1fr auto;gap:8px;align-items:end;margin-top:8px;">
        <div class="field" style="margin:0;"><label>Model to pin ${hlp('Force this job to use one specific local model instead of picking from the pool. Use it to keep behaviour consistent or to run your best coder.')}</label>
          <select id="gh-pin-model">${allModels.map(m => `<option value="${esc(m)}" ${m === loaded.loaded ? 'selected' : ''}>${esc(m)}</option>`).join('')}</select></div>
        <div class="field" style="margin:0;"><label>Context length ${hlp('The token context window for the pinned model. Bigger fits more code/history per turn but uses more VRAM and runs slower.')}</label>
          <input type="number" id="sw-context" value="${cfg.context || 16384}" min="2048" max="131072" step="2048"></div>
        <button class="btn-sm primary" onclick="ghLoadPin()" title="Load the chosen model into VRAM on the GPU box at the given context and keep it resident (unloading others to fit). Do this before a run so the swarm's turns don't stall loading a model.">Load &amp; pin</button>
      </div>
      <div style="font-size:.7rem;color:var(--muted);margin-top:6px;">Pinning unloads others to fit and keeps this model resident (no auto-unload). The swarm borrows whatever's resident, so pin your coding model before a run.</div>
      <label style="font-size:.78rem;display:flex;gap:6px;align-items:center;cursor:pointer;margin-top:8px;">
        <input type="checkbox" id="sw-autopin" ${cfg.auto_pin !== false ? 'checked' : ''}>
        Auto-pin the job's coder model before each run (recommended) ${hlp('Before each run, automatically load the job coder model into VRAM so turns never stall waiting on a model swap. Leave on unless you want to manage the resident model by hand.')}</label>
      <label style="font-size:.78rem;display:flex;gap:6px;align-items:center;cursor:pointer;margin-top:6px;">
        <input type="checkbox" id="sw-restart" ${cfg.restart_after_promote ? 'checked' : ''}>
        Auto-restart the live app after a promote (so approved code goes live immediately) ${hlp('After a successful promote, restart this Store app automatically so the new master code runs at once - instead of you clicking Restart live app in Workflow. Causes a few seconds of downtime.')}</label>
    </div>

    <div class="settings-group">
      <div class="settings-group-title">Autonomy (global default — overridable per job)</div>
      <div style="display:flex;flex-direction:column;gap:6px;font-size:.82rem;">
        ${[['gate', 'Gate the big moments — ask before fuzzy work, stop before test + push'],
           ['auto', 'Autonomous until tests pass, then one review gate before push'],
           ['step', 'Step-by-step — confirm each stage']].map(([v, label]) => `
          <label style="display:flex;gap:8px;align-items:flex-start;cursor:pointer;">
            <input type="radio" name="autonomy" value="${v}" ${cfg.autonomy === v ? 'checked' : ''}>
            <span>${label}</span></label>`).join('')}
      </div>
    </div>

    <div class="settings-group" style="margin-top:14px;">
      <div class="settings-group-title">Swarm size</div>
      <div style="display:flex;gap:16px;font-size:.82rem;margin-bottom:10px;flex-wrap:wrap;">
        <label style="display:flex;gap:6px;align-items:center;cursor:pointer;">
          <input type="radio" name="sw-mode" value="dynamic" ${cfg.mode !== 'static' ? 'checked' : ''} onchange="ghModeChanged()"> Dynamic (spin up N agents) ${hlp('The swarm spins up N coder agents per job (the count below) and assigns models from your pool automatically. Simplest - good default.')}</label>
        <label style="display:flex;gap:6px;align-items:center;cursor:pointer;">
          <input type="radio" name="sw-mode" value="static" ${cfg.mode === 'static' ? 'checked' : ''} onchange="ghModeChanged()"> Static (fixed named roster) ${hlp('You define a fixed roster of named agents (planner/coder/reviewer) and hand-pick each one model and instructions in the roster below. More control, less automatic.')}</label>
      </div>
      <div id="sw-dynamic" style="display:${cfg.mode === 'static' ? 'none' : 'block'};">
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
          <div class="field"><label>Default # of agents (per job/task overridable) ${hlp('The swarm’s default parallel coder count for new jobs. Any individual job can override it in its own “# Agents” field.')}</label>
            <input type="number" id="sw-count" value="${cfg.agent_count || 3}" min="1" max="12"></div>
          <div class="field"><label>Reviewer/auditor voters (majority approves; author excluded) ${hlp('How many reviewer/auditor agents vote before a change is accepted. Majority wins and the agent that wrote the code can’t vote on it. More voters = stricter review, slower.')}</label>
            <input type="number" id="sw-voters" value="${cfg.voters || 2}" min="1" max="9"></div>
        </div>
        <div class="field"><label>Model pool the swarm draws from (your coding models etc.) ${hlp('The set of local models the swarm can assign to its roles (planner / coder / reviewer). Point it at your best coding models; pinning a model on a job overrides this.')}</label>
          <div style="display:flex;flex-wrap:wrap;gap:8px;max-height:160px;overflow:auto;padding:6px;border:1px solid var(--border);border-radius:8px;">
            ${allModels.length ? allModels.map(m => `
              <label style="font-size:.74rem;display:flex;gap:5px;align-items:center;cursor:pointer;background:var(--bg2);padding:3px 8px;border-radius:6px;">
                <input type="checkbox" class="sw-pool" value="${esc(m)}" ${(cfg.models || []).includes(m) ? 'checked' : ''}> ${esc(m)}</label>`).join('')
              : '<span style="color:var(--muted);font-size:.74rem;">no models detected</span>'}
          </div></div>
      </div>
    </div>

    <div class="settings-group" style="margin-top:14px;">
      <div class="settings-group-title">Review rules</div>
      <div style="display:flex;flex-direction:column;gap:8px;font-size:.8rem;">
        <label style="display:flex;gap:8px;align-items:flex-start;cursor:pointer;">
          <input type="checkbox" id="sw-noself" ${cfg.no_self_approval !== false ? 'checked' : ''}>
          <span>A model may <b>not</b> review or approve its <b>own</b> code — another model must review it (the author still gets a vote).</span></label>
        <label style="display:flex;gap:8px;align-items:flex-start;cursor:pointer;">
          <input type="checkbox" id="sw-solo" ${cfg.self_review_when_solo !== false ? 'checked' : ''}>
          <span>If a job runs with <b>only 1 agent</b>, that model reviews + tests its own code (no peer available).</span></label>
        <div style="font-size:.74rem;color:var(--muted);padding-left:26px;">Either way, <b>only you</b> give the final approve/reject — a reject requires a comment describing the problem.</div>
      </div>
    </div>

    <div class="settings-group" style="margin-top:14px;">
      <div class="settings-group-title">&#128295; System agent</div>
      <div style="font-size:.74rem;color:var(--muted);margin-bottom:8px;">Installs/configures tools the swarm needs on the system, verifies them, then signals the swarm to resume/test. Risky commands are proposed for your approval.</div>
      <label style="font-size:.78rem;display:flex;gap:6px;align-items:center;cursor:pointer;margin-bottom:8px;">
        <input type="checkbox" id="sys-en" ${sys.enabled !== false ? 'checked' : ''}> enabled ${hlp('Let the swarm request tool/dependency installs on this machine when a job needs them. Every command still waits for your approval before it runs. Off = the swarm cannot touch the system.')}</label>
      <div class="field"><label>Model ${hlp('Which local model plays the system agent - the one that figures out and proposes the install/fix commands.')}</label><select id="sys-model">${modelOpts(sys.model)}</select></div>
      <div class="field"><label>Task ${hlp('The system agent standing instructions (its system prompt) - what it may set up and how careful to be. Sent to the model on every system request.')}</label><textarea id="sys-task" rows="2">${esc(sys.task || '')}</textarea></div>
    </div>

    <div class="settings-group" style="margin-top:14px;display:${cfg.mode === 'static' ? 'block' : 'none'};" id="sw-roster">
      <div class="settings-group-title">Named roster (static mode)</div>
      <div id="sw-agents">
        ${(cfg.agents || []).map((a, i) => `
          <div class="card" style="padding:12px;margin-bottom:10px;">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">
              <span style="font-weight:600;text-transform:capitalize;">${esc(a.role)}</span>
              <label style="font-size:.74rem;display:flex;gap:6px;align-items:center;cursor:pointer;">
                <input type="checkbox" class="sw-en" data-i="${i}" ${a.enabled ? 'checked' : ''}> enabled</label>
            </div>
            <div class="field" style="margin-top:8px;"><label>Model ${hlp('The local model that plays this named role (planner / coder / reviewer). Give your strongest coding model to the coder role.')}</label>
              <select class="sw-model" data-i="${i}">${modelOpts(a.model)}</select></div>
            <div class="field"><label>Task ${hlp('This agent standing instructions (its system prompt) for the role - how it should plan, code, or review. Sent to its model on every turn.')}</label>
              <textarea class="sw-task" data-i="${i}" rows="2">${esc(a.task || '')}</textarea></div>
          </div>`).join('')}
      </div>
    </div>

    <div style="margin-top:14px;"><button class="btn-sm primary" onclick="ghSaveAgents()">&#128190; Save swarm config</button></div>`;
}

function ghModeChanged() {
  const mode = document.querySelector('input[name="sw-mode"]:checked')?.value;
  document.getElementById('sw-dynamic').style.display = mode === 'static' ? 'none' : 'block';
  document.getElementById('sw-roster').style.display = mode === 'static' ? 'block' : 'none';
}
window.ghModeChanged = ghModeChanged;

async function ghSaveAgents() {
  const agents = (window._ghCfgAgents || []).map((a, i) => ({
    role: a.role,
    enabled: document.querySelector(`.sw-en[data-i="${i}"]`)?.checked ?? a.enabled,
    model: document.querySelector(`.sw-model[data-i="${i}"]`)?.value ?? a.model,
    task: document.querySelector(`.sw-task[data-i="${i}"]`)?.value ?? a.task,
  }));
  const payload = {
    autonomy: document.querySelector('input[name="autonomy"]:checked')?.value || 'gate',
    mode: document.querySelector('input[name="sw-mode"]:checked')?.value || 'dynamic',
    agent_count: parseInt(document.getElementById('sw-count').value) || 3,
    context: parseInt(document.getElementById('sw-context').value) || 16384,
    auto_pin: document.getElementById('sw-autopin')?.checked ?? true,
    restart_after_promote: document.getElementById('sw-restart')?.checked ?? false,
    voters: parseInt(document.getElementById('sw-voters').value) || 2,
    models: [...document.querySelectorAll('.sw-pool:checked')].map(c => c.value),
    no_self_approval: document.getElementById('sw-noself').checked,
    self_review_when_solo: document.getElementById('sw-solo').checked,
    system_agent: {
      enabled: document.getElementById('sys-en').checked,
      model: document.getElementById('sys-model').value,
      task: document.getElementById('sys-task').value,
    },
    agents,
  };
  try {
    await api('/api/github/swarm-config', { method: 'POST', body: JSON.stringify(payload) });
    toast('✅ Swarm config saved');
  } catch (e) { toast('Save failed: ' + e.message, 'error'); }
}
window.ghSaveAgents = ghSaveAgents;

async function ghLoadPin() {
  const model = document.getElementById('gh-pin-model').value;
  const context = parseInt(document.getElementById('sw-context').value) || 16384;
  if (!model) { toast('Pick a model', 'error'); return; }
  const el = document.getElementById('gh-loaded');
  el.innerHTML = `<span style="color:var(--muted);">⏳ Loading ${esc(model)} @ ${context} ctx (unloading others to fit)…</span>`;
  try {
    const r = await api('/api/github/load-model', { method: 'POST', body: JSON.stringify({ model, context }) });
    toast('✅ Pinned ' + r.loaded + (r.note ? ' — ' + r.note : ''));
    ghRenderAgents();
  } catch (e) { toast('Load failed: ' + e.message, 'error'); el.innerHTML = `<span style="color:var(--warn);">${esc(e.message)}</span>`; }
}
window.ghLoadPin = ghLoadPin;
