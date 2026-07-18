'use strict';

/* ══ TREND SOURCES ══ */
async function renderTrendSources() {
  let cfg = {}, scanStatus = {};
  try { cfg = await api('/api/trends/config'); } catch {}
  try { scanStatus = await api('/api/trends/status'); } catch {}

  const googleOn  = cfg.google_enabled !== false;
  const redditOn  = cfg.reddit_enabled !== false;
  const rssOn     = cfg.rss_enabled    !== false;
  const rssFeeds  = cfg.rss_urls ? cfg.rss_urls.split('\n').filter(Boolean) : [];
  const redditSubs = cfg.reddit_subs || '';

  const scanMsg = scanStatus.status === 'running'
    ? '&#9881; Scanning now\u2026'
    : esc(scanStatus.message || (cfg.last_run ? `Last scan: ${new Date(cfg.last_run).toLocaleString()} \u2014 ${cfg.last_count} proposals added` : 'No scans run yet'));

  let h = `
    <div class="view-header">
      <div class="view-title">&#128200; Trend Sources</div>
      <div class="view-sub">${scanMsg}</div>
    </div>
    <div class="section-header">
      <div></div>
      <button class="btn-sm primary" id="scan-now-btn">&#128269; Scan Now</button>
    </div>
    <div class="trend-grid">
      <div class="trend-card">
        <div class="trend-card-header">
          <div class="trend-card-title">&#127758; Google Trends</div>
          <div class="toggle ${googleOn?'on':''}" id="toggle-google" data-source="google"></div>
        </div>
        <div style="font-size:.78rem;color:var(--muted);margin-bottom:10px;">Scrapes trending search terms.</div>
        <div class="field">
          <label>Region</label>
          <select id="google-region">
            ${['US','GB','CA','AU','DE','FR','JP','BR','IN','MX'].map(r => `<option value="${r}"${cfg.google_region===r?' selected':''}>${r}</option>`).join('')}
          </select>
        </div>
      </div>
      <div class="trend-card">
        <div class="trend-card-header">
          <div class="trend-card-title">&#128992; Reddit</div>
          <div class="toggle ${redditOn?'on':''}" id="toggle-reddit" data-source="reddit"></div>
        </div>
        <div style="font-size:.78rem;color:var(--muted);margin-bottom:8px;">Monitors hot posts from subreddits.</div>
        <div class="field">
          <label>Subreddits (comma-separated)</label>
          <textarea id="reddit-subs" rows="4" style="font-size:.73rem;resize:vertical;">${esc(redditSubs)}</textarea>
        </div>
        <button class="btn-sm" id="save-reddit-btn" style="margin-top:6px;">&#128190; Save Subreddits</button>
      </div>
      <div class="trend-card">
        <div class="trend-card-header">
          <div class="trend-card-title">&#128225; RSS Feeds</div>
          <div class="toggle ${rssOn?'on':''}" id="toggle-rss" data-source="rss"></div>
        </div>
        <div style="font-size:.78rem;color:var(--muted);margin-bottom:10px;">Custom RSS feeds to monitor.</div>`;

  if (rssFeeds.length) {
    h += `<ul class="rss-list">`;
    for (const feed of rssFeeds)
      h += `<li class="rss-item"><span class="rss-item-url" title="${esc(feed)}">${esc(feed)}</span><button class="btn-sm" style="padding:2px 7px;font-size:.68rem;" data-action="remove-rss" data-url="${esc(feed)}">&#10005;</button></li>`;
    h += `</ul>`;
  } else {
    h += `<div style="font-size:.75rem;color:var(--muted);margin-bottom:8px;">No custom feeds added.</div>`;
  }

  h += `<div class="add-rss-row">
    <input type="text" id="rss-add-input" placeholder="https://feed.url/rss.xml">
    <button class="btn-sm primary" id="rss-add-btn">Add</button>
  </div>
      </div>
    </div>`;

  document.getElementById('main-content').innerHTML = h;

  document.getElementById('scan-now-btn').addEventListener('click', async () => {
    const btn = document.getElementById('scan-now-btn');
    btn.disabled = true; btn.textContent = '&#9203; Scanning\u2026';
    try {
      const r = await api('/api/trends/scan', { method: 'POST' });
      if (r.ok === false) { toast(r.message || 'Already scanning', 'warn'); return; }
      toast('Trend scan started! Check back in a minute.');
      // Poll for completion
      for (let i = 0; i < 120; i++) {
        await new Promise(res => setTimeout(res, 3000));
        const st = await api('/api/trends/status');
        if (st.status !== 'running') {
          toast(st.message || 'Scan complete');
          renderTrendSources();
          return;
        }
      }
    } catch(e) { toast('Scan error: ' + e.message, 'error'); }
    finally { btn.disabled = false; btn.textContent = '\u{1F50D} Scan Now'; }
  });

  document.querySelectorAll('.toggle[data-source]').forEach(el => {
    el.addEventListener('click', async () => {
      el.classList.toggle('on');
      const on = el.classList.contains('on');
      const patch = {}; patch[el.dataset.source + '_enabled'] = on;
      try {
        await api('/api/trends/config', { method: 'PATCH', body: JSON.stringify(patch) });
        toast(`${el.dataset.source} trends ${on ? 'enabled' : 'disabled'}`);
      } catch(e) {
        toast('Error: ' + e.message, 'error');
        el.classList.toggle('on');
      }
    });
  });

  document.getElementById('google-region')?.addEventListener('change', async (e) => {
    try {
      await api('/api/trends/config', { method: 'PATCH', body: JSON.stringify({ google_region: e.target.value }) });
      toast('Region saved');
    } catch(e2) { toast('Error: ' + e2.message, 'error'); }
  });

  document.getElementById('save-reddit-btn')?.addEventListener('click', async () => {
    const subs = document.getElementById('reddit-subs').value.trim();
    try {
      await api('/api/trends/config', { method: 'PATCH', body: JSON.stringify({ reddit_subs: subs }) });
      toast('Subreddits saved \u2713');
    } catch(e) { toast('Error: ' + e.message, 'error'); }
  });

  document.getElementById('rss-add-btn').addEventListener('click', async () => {
    const input = document.getElementById('rss-add-input');
    const url = input.value.trim();
    if (!url) return;
    try {
      const cfg2 = await api('/api/trends/config');
      const feeds = [...(cfg2.rss_urls ? cfg2.rss_urls.split('\n').filter(Boolean) : []), url];
      await api('/api/trends/config', { method: 'PATCH', body: JSON.stringify({ rss_urls: feeds.join('\n') }) });
      toast('Feed added'); input.value = '';
      renderTrendSources();
    } catch(e) { toast('Error: ' + e.message, 'error'); }
  });

  document.getElementById('main-content').addEventListener('click', async e => {
    const btn = e.target.closest('[data-action="remove-rss"]');
    if (!btn) return;
    try {
      const cfg2 = await api('/api/trends/config');
      const feeds = (cfg2.rss_urls ? cfg2.rss_urls.split('\n').filter(Boolean) : []).filter(f => f !== btn.dataset.url);
      await api('/api/trends/config', { method: 'PATCH', body: JSON.stringify({ rss_urls: feeds.join('\n') }) });
      toast('Feed removed'); renderTrendSources();
    } catch(e) { toast('Error: ' + e.message, 'error'); }
  }, { once: true });
}
