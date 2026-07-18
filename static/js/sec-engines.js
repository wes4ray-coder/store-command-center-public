/* ── AI Shield: attack surface + prompt-injection + bots + agent watch ──────── */
async function secAIShield() {
  const el = document.getElementById('sec-body');
  el.innerHTML = '<div class="empty">Checking your AI attack surface…</div>';
  let surf, bots, anom;
  try { [surf, bots, anom] = await Promise.all([api('/api/security/ai/surface'), api('/api/security/ai/bots'), api('/api/security/ai/anomalies')]); }
  catch (e) { el.innerHTML = '<div class="empty">AI Shield failed to load.</div>'; return; }

  const chk = (surf.checks || []).map(c => { const a = _AUD[c.status] || _AUD.info; return `
    <div style="display:flex;gap:9px;align-items:flex-start;padding:7px 10px;margin-bottom:5px;background:var(--surface,#161a22);border:1px solid var(--border);border-left:3px solid ${a[1]};border-radius:8px">
      <span>${a[0]}</span><div style="flex:1"><div style="font-size:.82rem;color:#e2e8f0;font-weight:600">${esc(c.title)}</div>
      <div style="font-size:.75rem;color:#aeb9cc">${esc(c.detail)}</div>${c.fix?`<div style="font-size:.7rem;color:#7dd3fc;margin-top:2px">🔧 ${esc(c.fix)}</div>`:''}</div>
      <span style="font-size:.6rem;color:${a[1]};font-weight:700;text-transform:uppercase">${c.status}</span></div>`; }).join('');

  const anomHtml = (anom.alerts || []).length
    ? anom.alerts.map(a => `<div style="font-size:.78rem;padding:3px 0;color:#f6a5a5">${a.severity==='high'?'🔴':'🟡'} <b>${esc(a.agent)}</b> — ${esc(a.text)}</div>`).join('')
    : `<div style="font-size:.78rem;color:#6ee7a8">✓ No rogue agent behaviour — ${anom.prayers_24h||0} agent actions in 24h across ${anom.agents||0} agents, all normal.</div>`;

  const botRow = (arr, col) => arr.length ? arr.map(b => `<span style="display:inline-block;margin:2px;padding:2px 9px;border-radius:6px;font-size:.72rem;background:#0e1626;border:1px solid ${col}44;color:${col}">${esc(b.name)} <b>${b.hits}</b></span>`).join('') : '<span style="font-size:.72rem;color:#54607a">none</span>';

  el.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
      <div class="section-title">🤖 AI Shield</div><button class="btn-sm" onclick="secAIShield()">↻ Rescan</button></div>
    <div style="font-size:.74rem;color:#7a86a0;margin-bottom:10px">Defenses for your AI stack: exposed model/tool endpoints, prompt-injection, bot governance, and rogue-agent watch. Enable the agent watch in 🎛️ Control → Infra.</div>

    <div class="section-header"><div class="section-title">🎯 AI attack surface</div></div>
    ${chk}

    <div class="section-header" style="margin-top:14px"><div class="section-title">🧪 Prompt-injection tester</div></div>
    <div style="font-size:.72rem;color:#7a86a0;margin-bottom:5px">Paste any suspicious text, file content, or webpage — see if it would try to hijack your agents.</div>
    <textarea id="ai-inj" rows="3" placeholder="Paste content agents might read…" style="width:100%;background:#0b1120;border:1px solid #26324a;border-radius:8px;color:#e8eefc;font-size:.8rem;padding:8px"></textarea>
    <div style="margin-top:6px"><button class="btn-sm primary" onclick="aiScan()">🧪 Scan for injection</button> <span id="ai-inj-res" style="font-size:.8rem;margin-left:8px"></span></div>

    <div class="section-header" style="margin-top:16px"><div class="section-title">🤖 Bot governance</div></div>
    <div style="font-size:.72rem;color:#6ee7a8;margin-bottom:4px">✅ Good AI crawlers (welcome — they recommend example.com):</div>
    <div>${botRow(bots.good, '#6ee7a8')}</div>
    <div style="font-size:.72rem;color:#f87171;margin:8px 0 4px">🚫 Bad scrapers (block these):</div>
    <div>${botRow(bots.bad, '#f87171')}</div>
    <div style="font-size:.72rem;color:#fbbf24;margin:8px 0 4px">⚙️ Raw clients (review — could be scripts or your own):</div>
    <div>${botRow(bots.raw || [], '#fbbf24')}</div>
    ${(bots.unknown||[]).length?`<div style="font-size:.72rem;color:#8a97ad;margin:8px 0 4px">❓ Other bots:</div><div>${botRow(bots.unknown,'#8a97ad')}</div>`:''}
    <details style="margin-top:10px"><summary style="cursor:pointer;font-size:.76rem;color:#7dd3fc">📄 robots.txt + nginx block snippet (allow good, block bad)</summary>
      <div style="font-size:.68rem;color:#7a86a0;margin-top:4px">robots.txt for example.com:</div>
      <pre style="background:#0b1120;border:1px solid #1b2740;border-radius:6px;padding:8px;overflow-x:auto;font-size:.68rem;color:#a9c7e8;max-height:200px">${esc(bots.robots||'')}</pre>
      <div style="font-size:.68rem;color:#7a86a0">nginx-proxy-manager rule to 403 the bad scrapers:</div>
      <pre style="background:#0b1120;border:1px solid #1b2740;border-radius:6px;padding:8px;overflow-x:auto;font-size:.68rem;color:#a9c7e8">${esc(bots.nginx_block||'')}</pre>
    </details>

    <div class="section-header" style="margin-top:16px"><div class="section-title">👁️ Agent-action watch (rogue-agent detection)</div></div>
    ${anomHtml}`;
}
async function aiScan() {
  const text = document.getElementById('ai-inj')?.value || '';
  const res = document.getElementById('ai-inj-res');
  if (!text.trim()) { res.textContent = 'paste something first'; return; }
  try {
    const r = await api('/api/security/ai/scan', { method: 'POST', body: JSON.stringify({ text }) });
    const col = r.risk === 'high' ? '#f87171' : r.risk === 'medium' ? '#fbbf24' : '#6ee7a8';
    res.innerHTML = `<b style="color:${col}">${r.risk === 'clean' ? '✓ CLEAN — no injection' : '⚠️ ' + r.risk.toUpperCase() + ' RISK'}</b>${r.tags.length ? ` · <span style="color:#aeb9cc">${r.tags.map(esc).join(', ')}</span>` : ''}`;
  } catch (e) { res.textContent = 'scan failed'; }
}
window.secAIShield = secAIShield; window.aiScan = aiScan;

/* ── Guardian: auto-named devices + surgical tracker blocking ───────────────── */
const _CAT_COL = { functional: '#6ee7a8', local: '#7dd3fc', ads: '#f87171', tracking: '#fb923c', unknown: '#7a86a0' };
let _guardData = null;
async function secGuardian() {
  const el = document.getElementById('sec-body');
  el.innerHTML = '<div class="empty">Fingerprinting devices + reading their traffic…</div>';
  let d, acts;
  try { [d, acts] = await Promise.all([api('/api/security/guardian'), api('/api/security/guardian/actions')]); }
  catch (e) { el.innerHTML = '<div class="empty">Guardian failed to load.</div>'; return; }
  _guardData = d;
  if (!d.available) { el.innerHTML = `<div class="empty">${esc(d.note || 'No Pi-hole data.')}</div>`; return; }

  const bar = (cats, total) => {
    total = total || 1;
    return `<div style="display:flex;height:7px;border-radius:4px;overflow:hidden;background:#0b1120;margin:4px 0">${['functional','local','unknown','ads','tracking'].map(c => { const n = cats[c] || 0; return n ? `<div title="${c}: ${n}" style="width:${Math.max(1, n / total * 100)}%;background:${_CAT_COL[c]}"></div>` : ''; }).join('')}</div>`;
  };
  const devs = (d.devices || []).map(v => {
    const rec = v.recommend || [];
    return `<div style="border:1px solid ${v.flags.length?'#5a3a2a':'#26324a'};border-radius:10px;padding:11px 13px;margin-bottom:8px;background:var(--surface,#161a22)">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">
        <div><span style="font-size:1.1rem">${v.icon}</span>
          <b style="color:#e2e8f0">${esc(v.name)}</b>
          <span style="font-size:.7rem;color:#7a86a0">· ${esc(v.ip)}${v.vendor?` · ${esc(v.vendor)}`:''}${v.mac?` · ${esc(v.mac)}`:''}</span>
          ${v.user_named ? '' : `<button class="btn-sm" style="padding:1px 7px;font-size:.64rem;margin-left:6px" onclick="guardRename('${v.mac||v.ip}','${esc(v.name)}')">✎ name</button>`}
        </div>
        ${v.flags.map(f => `<span style="font-size:.64rem;font-weight:700;color:#fb923c;background:#2a1e12;border:1px solid #7c5a1a;border-radius:5px;padding:1px 7px">⚠️ ${esc(f)}</span>`).join('')}
      </div>
      ${bar(v.categories, v.total)}
      <div style="font-size:.68rem;color:#7a86a0">${v.total} queries · ${Object.entries(v.categories||{}).map(([c,n])=>`<span style="color:${_CAT_COL[c]}">${c} ${n}</span>`).join(' · ')}</div>
      ${v.loops && v.loops.length ? `<div style="font-size:.72rem;color:#fb923c;margin-top:4px">🔁 retry loop: ${v.loops.map(l=>`${esc(l.domain)} (${l.hits}×)`).join(', ')}</div>` : ''}
      ${rec.length ? `<div style="margin-top:6px;display:flex;gap:6px;align-items:center;flex-wrap:wrap">
        <span style="font-size:.72rem;color:#f6a5a5">Bad actors:</span>
        ${rec.slice(0,8).map(r=>`<code style="background:#0b1120;padding:1px 6px;border-radius:4px;font-size:.7rem;color:#f6a5a5">${esc(r.domain)}</code>`).join('')}
        <button class="btn-sm danger" style="padding:2px 10px;font-size:.72rem" onclick='guardBlock(${JSON.stringify(rec.map(r=>r.domain))},${JSON.stringify(v.name)})'>🛡️ Block ${rec.length} tracker${rec.length>1?'s':''}</button>
      </div>` : '<div style="font-size:.72rem;color:#6ee7a8;margin-top:4px">✓ clean — no ad/tracking to block</div>'}
    </div>`;
  }).join('');

  const log = (acts.actions || []).slice(0, 12).map(a => `<div style="font-size:.72rem;padding:2px 0;color:#aeb9cc">${a.action==='block'?'🛡️ blocked':'↩️ unblocked'} <code style="color:#c7d2e5">${esc(a.domain)}</code> ${a.device?`<span style="color:#7a86a0">(${esc(a.device)})</span>`:''}<span style="color:#54607a;float:right">${(a.created_at||'').slice(5,16)}</span> <button class="btn-sm" style="padding:0 6px;font-size:.6rem" onclick="guardUnblock('${esc(a.domain)}')">undo</button></div>`).join('') || '<div style="color:#54607a;font-size:.76rem">No blocks yet.</div>';

  el.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:8px">
      <div class="section-title">🛡️ Network Guardian — ${(d.devices||[]).length} devices</div>
      <button class="btn-sm" onclick="secGuardian()">↻ Rescan</button>
    </div>
    <div style="font-size:.74rem;color:#7a86a0;margin-bottom:10px">Every device auto-identified by hardware + behaviour. It flags ad/tracker/ACR domains and can block them surgically — <b style="color:#6ee7a8">functional traffic (streaming, DNS, updates) and your local network are never touched.</b> Enable auto-mode in 🎛️ Control → Infra.</div>
    ${devs}
    <div class="section-header" style="margin-top:14px"><div class="section-title">📋 Block actions (reversible)</div></div>
    ${log}`;
}
async function guardBlock(domains, device) {
  if (!confirm(`Block ${domains.length} tracker/ad domain(s) for ${device}?\n\nThis is network-wide, surgical, and reversible. Streaming/DNS/updates are protected.`)) return;
  try { const r = await api('/api/security/guardian/block', { method: 'POST', body: JSON.stringify({ domains, device }) }); toast?.(`🛡️ Blocked ${r.blocked.length}${r.skipped.length?`, protected ${r.skipped.length}`:''}`); secGuardian(); }
  catch (e) { toast?.('Block failed'); }
}
async function guardUnblock(domain) {
  try { await api('/api/security/guardian/unblock', { method: 'POST', body: JSON.stringify({ domain }) }); toast?.('↩️ Unblocked'); secGuardian(); }
  catch (e) { toast?.('Failed'); }
}
async function guardRename(mac, cur) {
  const name = prompt('Name this device:', cur); if (name == null) return;
  try { await api('/api/security/guardian/name', { method: 'POST', body: JSON.stringify({ mac, name }) }); toast?.('Named'); secGuardian(); }
  catch (e) { toast?.('Failed'); }
}
window.secGuardian = secGuardian; window.guardBlock = guardBlock; window.guardUnblock = guardUnblock; window.guardRename = guardRename;

/* ── Threats: ranked attackers + block commands + fail2ban + audit alerts ───── */
async function secThreats() {
  const el = document.getElementById('sec-body');
  el.innerHTML = '<div class="empty">Hunting threats…</div>';
  let t, ev;
  try { [t, ev] = await Promise.all([api('/api/security/threats'), api('/api/security/events')]); }
  catch (e) { el.innerHTML = '<div class="empty">Threat scan failed.</div>'; return; }
  const geo = g => g ? [g.city, g.country].filter(Boolean).join(', ') : '';
  const f2b = t.fail2ban || {};

  const thr = (t.threats || []).map(x => `
    <div style="border:1px solid #26324a;border-left:3px solid ${_SEV[x.severity]||'#7a86a0'};border-radius:8px;padding:9px 11px;margin-bottom:6px;background:var(--surface,#161a22)">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
        <div><b style="color:#e2e8f0;font-family:ui-monospace,monospace">${esc(x.ip)}</b>
          <span style="font-size:.66rem;color:${_SEV[x.severity]};font-weight:700;text-transform:uppercase;margin-left:6px">${esc(x.severity)}</span>
          <span style="font-size:.7rem;color:#9fb4d6;margin-left:4px">${esc(x.type)}</span></div>
        <span style="font-size:.7rem;color:#8a97ad">${esc(geo(x.geo) || (x.geo&&x.geo.org) || '')}</span>
      </div>
      <div style="font-size:.76rem;color:#aeb9cc;margin-top:2px">${esc(x.detail)}</div>
      <div style="font-size:.72rem;margin-top:4px;color:${x.bannable?'#7dd3fc':'#f59e0b'}">🔧 <code style="background:#0b1120;padding:1px 6px;border-radius:4px">${esc(x.block)}</code></div>
    </div>`).join('') || '<div style="color:#54607a;font-size:.82rem;padding:8px 0">No active threats detected — no SSH brute-force, no web probes. 🕊️</div>';

  const f2bHtml = f2b.installed
    ? `<div style="background:#12251b;border:1px solid #2a5a3a;border-radius:8px;padding:9px 12px;font-size:.8rem;color:#c7d2e5">🛡️ <b style="color:#6ee7a8">fail2ban active</b> — ${f2b.total_banned} IP(s) banned across ${(f2b.jails||[]).length} jail(s): ${(f2b.jails||[]).map(j=>`${esc(j.name)} (${j.total_banned})`).join(', ')}</div>`
    : `<div style="background:#2a1e12;border:1px solid #7c5a1a;border-radius:8px;padding:9px 12px;font-size:.8rem;color:#f6c76b">🛡️ ${esc(f2b.hint||'fail2ban not installed')}</div>`;

  const evs = (ev.events || []).map(e => `<div style="font-size:.76rem;padding:3px 0;display:flex;gap:6px">
      <span style="color:${_SEV[e.severity]||'#7a86a0'};font-weight:700;text-transform:uppercase;font-size:.62rem;width:56px">${esc(e.severity)}</span>
      <span style="color:#c7d2e5">${esc(e.text)}</span>
      <span style="color:#54607a;margin-left:auto">${(e.created_at||'').slice(5,16)}</span></div>`).join('')
    || '<div style="color:#54607a;font-size:.78rem">No alerts yet. Enable the nightly audit in 🎛️ Control → Infra, or hit Run now.</div>';

  const hist = ev.history || [];
  const trend = hist.length > 1 ? `<span style="font-size:.72rem;color:#7a86a0">trend: ${hist.slice(0,10).reverse().map(h=>h.grade).join(' → ')}</span>` : '';

  el.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:8px">
      <div class="section-title">🚨 Active threats (${t.count||0})</div>
      <button class="btn-sm" onclick="secThreats()">↻ Rescan</button>
    </div>
    ${f2bHtml}
    <div style="margin-top:10px">${thr}</div>
    <div style="font-size:.7rem;color:#7a86a0;margin-top:8px">Behind Cloudflare, web-scanner IPs are CF edges — block those at the Cloudflare WAF, not by IP. SSH attackers are real IPs and directly bannable.</div>

    <div class="section-header" style="margin-top:18px"><div class="section-title">🗓️ Scheduled audit &amp; alerts</div>
      <button class="btn-sm" onclick="secAuditRun()">▶ Run audit now</button></div>
    <div style="font-size:.72rem;color:#7a86a0;margin-bottom:6px">Nightly snapshot compares against the last and alerts on regressions (new failures, newly-exposed risky ports, new SSH logins) into the God Console. ${trend}</div>
    ${evs}`;
}
async function secAuditRun() {
  toast?.('Running audit snapshot…');
  try { const r = await api('/api/security/audit/run', { method: 'POST', body: JSON.stringify({}) }); toast?.(`Audit ${r.grade} (${r.score}) · ${r.alerts} alert(s)`); secThreats(); }
  catch (e) { toast?.('Audit failed'); }
}
window.secThreats = secThreats;
window.secAuditRun = secAuditRun;

/* ── Audit: hardening report (Lynis/CIS-style) ──────────────────────────────── */
const _AUD = { pass: ['✅', '#6ee7a8'], warn: ['⚠️', '#f59e0b'], fail: ['❌', '#f87171'], info: ['ℹ️', '#7dd3fc'], skip: ['⏭️', '#7a86a0'] };
async function secAudit() {
  const el = document.getElementById('sec-body');
  el.innerHTML = '<div class="empty">Running hardening audit…</div>';
  let d;
  try { d = await api('/api/security/audit'); }
  catch (e) { el.innerHTML = '<div class="empty">Audit failed.</div>'; return; }
  const gc = d.grade === 'A' ? '#6ee7a8' : d.grade === 'B' ? '#a3e635' : d.grade === 'C' ? '#fbbf24' : d.grade === 'D' ? '#fb923c' : '#f87171';
  const cc = d.counts || {};
  const groups = (d.groups || []).map(g => `
    <div class="section-header" style="margin-top:14px"><div class="section-title">${esc(g.name)}</div></div>
    ${g.checks.map(c => { const a = _AUD[c.status] || _AUD.info; return `
      <div style="display:flex;gap:10px;align-items:flex-start;padding:8px 10px;margin-bottom:5px;background:var(--surface,#161a22);border:1px solid var(--border,#2a2f3d);border-left:3px solid ${a[1]};border-radius:8px">
        <span style="font-size:1rem">${a[0]}</span>
        <div style="flex:1;min-width:0">
          <div style="font-size:.84rem;color:#e2e8f0;font-weight:600">${esc(c.title)}</div>
          <div style="font-size:.76rem;color:#aeb9cc">${esc(c.detail)}</div>
          ${c.fix ? `<div style="font-size:.72rem;color:#7dd3fc;margin-top:2px">🔧 <code style="background:#0b1120;padding:1px 6px;border-radius:4px">${esc(c.fix)}</code></div>` : ''}
        </div>
        <span style="font-size:.62rem;color:${a[1]};font-weight:700;text-transform:uppercase">${c.status}</span>
      </div>`; }).join('')}`).join('');
  el.innerHTML = `
    <div style="display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin-bottom:6px">
      <div style="width:92px;height:92px;border-radius:16px;background:${gc}22;border:2px solid ${gc};display:flex;flex-direction:column;align-items:center;justify-content:center">
        <div style="font-size:2.2rem;font-weight:900;color:${gc};line-height:1">${d.grade}</div>
        <div style="font-size:.7rem;color:${gc}">${d.score}/100</div>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        ${['fail','warn','pass','info','skip'].map(k => `<div style="background:var(--surface,#161a22);border:1px solid var(--border);border-radius:8px;padding:8px 12px;text-align:center"><div style="font-size:1.3rem;font-weight:800;color:${_AUD[k][1]}">${cc[k]||0}</div><div style="font-size:.62rem;color:#7a86a0;text-transform:uppercase">${k}</div></div>`).join('')}
      </div>
      <button class="btn-sm" style="margin-left:auto" onclick="secAudit()">↻ Re-audit</button>
    </div>
    <div style="font-size:.7rem;color:#7a86a0;margin-bottom:6px">Native hardening audit — patches, SSH, accounts, network exposure, containers, firewall.</div>
    ${groups}`;
}

/* ── Web Traffic: who's hitting the public services ─────────────────────────── */
async function secWebTraffic() {
  const el = document.getElementById('sec-body');
  el.innerHTML = '<div class="empty">Reading web access logs…</div>';
  let d;
  try { d = await api('/api/security/web-traffic'); }
  catch (e) { el.innerHTML = '<div class="empty">Web logs unavailable.</div>'; return; }
  if (!d.available) { el.innerHTML = `<div class="empty">${esc(d.note || 'No web access logs readable.')}</div>`; return; }
  const geo = g => g ? [g.city, g.country].filter(Boolean).join(', ') : '';
  const cf = d.cloudflare_note ? `<div style="background:#12203a;border:1px solid #2a4a7a;border-radius:10px;padding:9px 13px;margin:10px 0;font-size:.8rem;color:#9fd0ff">☁️ <b>Behind Cloudflare</b> — the visitor IPs below are Cloudflare's edge servers, not your visitors' real IPs. To see real IPs, log the <code style="background:#0b1120;padding:1px 5px;border-radius:4px">CF-Connecting-IP</code> header in nginx-proxy-manager's log format.</div>` : '';
  const vis = (d.visitors || []).map(v => `<tr style="border-top:1px solid #1b2740">
      <td style="padding:5px 8px;font-family:ui-monospace,monospace">${esc(v.ip)}</td>
      <td style="padding:5px 8px;text-align:right;font-weight:700">${v.hits}</td>
      <td style="padding:5px 8px">${Object.entries(v.statuses||{}).map(([k,n])=>`<span style="color:${k[0]==='2'?'#6ee7a8':k[0]==='4'?'#f59e0b':k[0]==='5'?'#f87171':'#9fb4d6'}">${k}:${n}</span>`).join(' ')}</td>
      <td style="padding:5px 8px;color:#9fb4d6">${esc((v.hosts||[]).join(', '))}</td>
      <td style="padding:5px 8px;color:${v.suspicious?'#f87171':'#54607a'}">${v.suspicious||''}</td>
      <td style="padding:5px 8px;color:#8a97ad">${esc(geo(v.geo))}</td></tr>`).join('');
  const sus = (d.suspicious || []).map(s => `<tr style="border-top:1px solid #1b2740">
      <td style="padding:4px 8px;font-family:ui-monospace,monospace">${esc(s.ip)}</td>
      <td style="padding:4px 8px;color:#f59e0b">${esc(s.status)}</td>
      <td style="padding:4px 8px;color:#f6a5a5">${esc(s.path)}</td>
      <td style="padding:4px 8px;color:#8a97ad">${esc(s.host)}</td></tr>`).join('')
    || '<tr><td colspan="4" style="padding:10px;color:#54607a">No obvious scanner/probe requests. 👍</td></tr>';
  el.innerHTML = `
    <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:4px">
      <div style="background:var(--surface,#161a22);border:1px solid var(--border);border-radius:10px;padding:12px 14px"><div style="font-size:1.5rem;font-weight:800">${d.total}</div><div style="font-size:.66rem;color:#7a86a0">REQUESTS</div></div>
      <div style="background:var(--surface,#161a22);border:1px solid var(--border);border-radius:10px;padding:12px 14px"><div style="font-size:1.5rem;font-weight:800">${d.unique_visitors}</div><div style="font-size:.66rem;color:#7a86a0">UNIQUE IPS</div></div>
      <div style="background:var(--surface,#161a22);border:1px solid var(--border);border-radius:10px;padding:12px 14px"><div style="font-size:1.5rem;font-weight:800;color:${d.suspicious.length?'#f87171':'#6ee7a8'}">${d.suspicious.length}</div><div style="font-size:.66rem;color:#7a86a0">PROBES</div></div>
      <button class="btn-sm" style="margin-left:auto" onclick="secWebTraffic()">↻ Refresh</button>
    </div>${cf}
    <div class="section-header" style="margin-top:8px"><div class="section-title">🎯 Services being hit</div></div>
    <div style="line-height:1.9">${(d.vhosts||[]).map(v=>`<span style="display:inline-block;margin:2px;padding:2px 9px;border-radius:6px;background:#0e1626;border:1px solid #26324a;font-size:.74rem;color:#c7d2e5">${esc(v.host)} <b style="color:#7dd3fc">${v.hits}</b></span>`).join('')}</div>
    <div class="section-header" style="margin-top:14px"><div class="section-title">👥 Top visitors</div></div>
    <div style="overflow-x:auto"><table style="width:100%;font-size:.78rem;border-collapse:collapse;color:#c7d2e5">
      <thead><tr style="color:#7a86a0;text-align:left"><th style="padding:5px 8px">IP</th><th style="padding:5px 8px;text-align:right">Hits</th><th style="padding:5px 8px">Status</th><th style="padding:5px 8px">Services</th><th style="padding:5px 8px">Probes</th><th style="padding:5px 8px">Where</th></tr></thead>
      <tbody>${vis}</tbody></table></div>
    <div class="section-header" style="margin-top:16px"><div class="section-title">🚨 Scanner / probe attempts (${(d.suspicious||[]).length})</div></div>
    <div style="overflow-x:auto"><table style="width:100%;font-size:.76rem;border-collapse:collapse;color:#c7d2e5">
      <thead><tr style="color:#7a86a0;text-align:left"><th style="padding:4px 8px">IP</th><th style="padding:4px 8px">Status</th><th style="padding:4px 8px">Path probed</th><th style="padding:4px 8px">Host</th></tr></thead>
      <tbody>${sus}</tbody></table></div>`;
}
