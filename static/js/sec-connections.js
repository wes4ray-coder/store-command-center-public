/* Security → 🌐 Connections: who/what/where, in & out (the live "is it working" view). */
async function secConnections() {
  const el = document.getElementById('sec-body');
  el.innerHTML = '<div class="empty">Scanning live connections…</div>';
  await _secConnLoad();
  _secConnTimer = setInterval(_secConnLoad, 20000);   // live refresh
}

async function _secConnLoad() {
  // Self-clear once we've left the security view (switchView doesn't call _secStopTimers).
  if (!document.getElementById('sec-body')) { clearInterval(_secConnTimer); _secConnTimer = null; return; }
  let d;
  try { d = await api('/api/security/connections'); }
  catch (e) { const el = document.getElementById('sec-body'); if (el) el.innerHTML = '<div class="empty">Could not read connections.</div>'; return; }
  const el = document.getElementById('sec-body');
  if (!el) return;
  const s = d.summary || {};
  const geo = g => g ? [g.city, g.country].filter(Boolean).join(', ') : '';
  const org = g => (g && (g.org || g.isp)) || '';

  const stat = (n, label, color) => `<div style="background:var(--surface,#161a22);border:1px solid var(--border,#2a2f3d);border-radius:10px;padding:12px 14px;min-width:110px">
    <div style="font-size:1.5rem;font-weight:800;color:${color||'#e2e8f0'}">${n}</div>
    <div style="font-size:.68rem;color:#7a86a0;text-transform:uppercase;letter-spacing:.04em">${label}</div></div>`;

  const warn = !d.firewall_logging ? `
    <div style="background:#2a1e12;border:1px solid #7c5a1a;border-radius:10px;padding:10px 14px;margin:12px 0;font-size:.82rem;color:#f6c76b">
      ⚠️ <b>Firewall logging is OFF</b> — that's why past inbound (your friends) wasn't recorded. Turn it on to capture who tries to connect from now on:
      <code style="background:#0b1120;padding:2px 7px;border-radius:5px;color:#a9c7e8;margin-left:4px">sudo ufw logging on</code>
      <span style="color:#8a97ad"> — run it once on the server; then blocked/attempted inbound shows here.</span>
    </div>` : '';

  // external connections (inbound first — someone reaching IN is the noteworthy case)
  const dirBadge = r => r.in ? '<span style="color:#f87171;font-weight:700">⬇ IN</span>'
    : '<span style="color:#7a86a0">⬆ out</span>';
  const extRows = (d.external || []).map(r => `<tr style="border-top:1px solid #1b2740">
      <td style="padding:5px 8px">${dirBadge(r)}</td>
      <td style="padding:5px 8px;font-family:ui-monospace,monospace;color:#e2e8f0">${esc(r.ip)}</td>
      <td style="padding:5px 8px;color:#c7d2e5">${esc(org(r.geo) || r.rdns || '—')}</td>
      <td style="padding:5px 8px;color:#9fb4d6">${esc(geo(r.geo) || '—')}</td>
      <td style="padding:5px 8px;color:#aeb9cc">${esc((r.services||[]).join(', '))}</td>
      <td style="padding:5px 8px;text-align:right;color:#7a86a0">${r.count}</td></tr>`).join('')
    || '<tr><td colspan="6" style="padding:10px;color:#54607a">No active external connections right now.</td></tr>';

  // SSH knockers
  const sshRows = (d.ssh || []).map(r => {
    const c = r.accepted ? '#f87171' : '#f59e0b';
    return `<tr style="border-top:1px solid #1b2740">
      <td style="padding:5px 8px;font-family:ui-monospace,monospace">${esc(r.ip)}</td>
      <td style="padding:5px 8px"><b style="color:${c}">${r.result === 'breached' ? '🔓 GOT IN' : '🚫 blocked'}</b></td>
      <td style="padding:5px 8px;text-align:right">${r.attempts}</td>
      <td style="padding:5px 8px;color:#9fb4d6">${esc(geo(r.geo) || org(r.geo) || '—')}</td>
      <td style="padding:5px 8px;color:#8a97ad">${esc((r.users||[]).join(', '))}</td></tr>`;
  }).join('') || '<tr><td colspan="5" style="padding:10px;color:#54607a">No external SSH attempts in 7 days — SSH isn\'t being brute-forced. 👍</td></tr>';

  // exposed surface
  const exp = (d.listening || []).map(x => `<span style="display:inline-block;margin:2px;padding:2px 8px;border-radius:6px;font-size:.72rem;background:${x.risky?'#3a1a1a':'#0e1626'};border:1px solid ${x.risky?'#7c3a3a':'#26324a'};color:${x.risky?'#f6a5a5':'#9fb4d6'}">${x.port} ${esc(x.service)}${x.risky?' ⚠️':''}</span>`).join('');

  el.innerHTML = `
    <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:6px">
      ${stat(s.inbound || 0, 'inbound now', (s.inbound?'#f87171':'#6ee7a8'))}
      ${stat(s.outbound || 0, 'outbound now', '#9fb4d6')}
      ${stat(s.ssh_breached || 0, 'ssh breaches', (s.ssh_breached?'#f87171':'#6ee7a8'))}
      ${stat(s.blocked_24h || 0, 'blocked 24h', '#f59e0b')}
      ${stat(s.exposed_services || 0, 'exposed services', '#fbbf24')}
    </div>
    <div style="font-size:.68rem;color:#54607a;margin-bottom:6px">🔄 live · updated ${esc((d.generated_at||'').slice(11))} · external IPs enriched with location + owner</div>
    ${warn}

    <div class="section-header" style="margin-top:8px"><div class="section-title">🌐 External connections (who / where / what)</div></div>
    <div style="overflow-x:auto"><table style="width:100%;font-size:.78rem;border-collapse:collapse;color:#c7d2e5">
      <thead><tr style="color:#7a86a0;text-align:left"><th style="padding:5px 8px">Dir</th><th style="padding:5px 8px">IP</th><th style="padding:5px 8px">Who (owner)</th><th style="padding:5px 8px">Where</th><th style="padding:5px 8px">Service</th><th style="padding:5px 8px;text-align:right">Conns</th></tr></thead>
      <tbody>${extRows}</tbody></table></div>

    <div class="section-header" style="margin-top:16px"><div class="section-title">🔑 SSH access attempts (who&rsquo;s knocking)</div></div>
    <div style="overflow-x:auto"><table style="width:100%;font-size:.78rem;border-collapse:collapse;color:#c7d2e5">
      <thead><tr style="color:#7a86a0;text-align:left"><th style="padding:5px 8px">Source IP</th><th style="padding:5px 8px">Result</th><th style="padding:5px 8px;text-align:right">Tries</th><th style="padding:5px 8px">Where</th><th style="padding:5px 8px">Users tried</th></tr></thead>
      <tbody>${sshRows}</tbody></table></div>

    <div class="section-header" style="margin-top:16px"><div class="section-title">🎯 Exposed services — your attack surface (${(d.listening||[]).length})</div></div>
    <div style="line-height:1.9">${exp}</div>
    <div style="font-size:.7rem;color:#7a86a0;margin-top:8px">⚠️ = remote-access / data / mail ports worth locking down to LAN-only or behind a VPN if not needed from the internet.</div>`;
}
