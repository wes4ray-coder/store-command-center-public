'use strict';
/* ══ THE COMPANY — 🔊 sound-mixer popover + generated-soundscape controls (split from tab-world.js) ══ */

function worldSndToggle() {
  const on = window.WAU ? WAU.toggle() : false;
  const b = document.getElementById('world-snd-btn');
  if (b) b.textContent = on ? '🔊' : '🔇';
  const t = document.getElementById('world-snd-onoff');
  if (t) t.textContent = on ? 'On' : 'Off';
  toast?.(on ? 'Sound on' : 'Sound off');
}
window.worldSndToggle = worldSndToggle;

/* the 🔊 mixer popover — master / ambient / effects sliders */
function worldSndPanel() {
  const old = document.getElementById('world-snd-pop');
  if (old) { old.remove(); return; }
  const btn = document.getElementById('world-snd-btn');
  if (!btn || !window.WAU) return;
  const r = btn.getBoundingClientRect();
  const p = document.createElement('div');
  p.id = 'world-snd-pop';
  p.style.cssText = `position:fixed;top:${r.bottom + 6}px;left:${Math.max(8, r.left - 130)}px;z-index:950;` +
    'background:#0f1626;border:1px solid #2a3752;border-radius:10px;padding:12px;width:238px;box-shadow:0 8px 30px rgba(0,0,0,.5)';
  const row = (k, lbl) => `<div style="display:flex;align-items:center;gap:8px;margin:6px 0">
    <span style="font-size:.72rem;color:#c7d2e5;width:60px">${lbl}</span>
    <input type="range" min="0" max="100" value="${Math.round(WAU.vol(k) * 100)}" style="flex:1"
      oninput="WAU.setVol('${k}', this.value/100)"></div>`;
  p.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
      <b style="font-size:.8rem;color:#e8eefc">🔊 Sound</b>
      <button class="btn" id="world-snd-onoff" style="padding:2px 10px;font-size:.7rem" onclick="worldSndToggle()">${WAU.on ? 'On' : 'Off'}</button>
    </div>
    ${row('master', 'Master')}${row('amb', 'Ambient')}${row('sfx', 'Effects')}
    <div style="display:flex;align-items:center;gap:8px;margin:8px 0 2px">
      <span style="font-size:.72rem;color:#c7d2e5;width:60px">Generated</span>
      <button class="btn" id="world-snd-gen" style="padding:2px 10px;font-size:.7rem" onclick="worldSndGenToggle()">${WAU.genPref ? 'On' : 'Off'}</button>
      <button class="btn" style="padding:2px 10px;font-size:.7rem" onclick="worldSndGenerate()">🎛 Generate</button>
    </div>
    <div id="world-snd-gen-stat" style="font-size:.62rem;color:#8fa3c8;margin:2px 0 4px">checking generated clips…</div>
    <div style="font-size:.62rem;color:#54607a;margin-top:4px">Birdsong, wind, hammering and crowd murmur follow the live world — season, time, raids, who's working. "Generated" swaps the synth for real ambience + effects rendered by the store's own audio models (Stable Audio / MusicGen) — hit 🎛 Generate once to render them on the GPU node.</div>`;
  document.body.appendChild(p);
  _worldSndGenStat();
}
window.worldSndPanel = worldSndPanel;

/* generated-soundscape controls (the "Generated" row in the 🔊 mixer) */
async function _worldSndGenStat() {
  const el = document.getElementById('world-snd-gen-stat');
  if (!el) return;
  try {
    const j = await api('/api/world/audio/assets');
    const ready = (j.assets || []).filter(a => a.ready).length, total = (j.assets || []).length;
    let s = ready ? `${ready}/${total} clips generated` : `no clips yet — 🎛 Generate renders ${total} (synth plays meanwhile)`;
    if (j.job?.status === 'running') s = `⏳ generating ${j.job.done}/${j.job.total} — ${j.job.current || '…'}`;
    else if (j.job?.status === 'error') s = `⚠️ ${j.job.error || 'generation failed'} — synth fallback active`;
    el.textContent = s;
    if (j.job?.status === 'running' && document.getElementById('world-snd-pop'))
      setTimeout(_worldSndGenStat, 4000);
  } catch { el.textContent = 'generated-clip status unavailable'; }
}
function worldSndGenToggle() {
  const on = window.WAU ? WAU.genToggle() : false;
  const b = document.getElementById('world-snd-gen');
  if (b) b.textContent = on ? 'On' : 'Off';
  toast?.(on ? 'Generated soundscape on' : 'Generated soundscape off — synth only');
}
window.worldSndGenToggle = worldSndGenToggle;
async function worldSndGenerate() {
  try {
    const j = await api('/api/world/audio/generate', { method: 'POST', body: JSON.stringify({}) });
    if (j.status === 'already_running') toast?.('Already generating — hang tight');
    else if (j.status === 'nothing_to_do') toast?.('All world sounds are already generated');
    else toast?.(`Rendering ${j.queued} world sounds on the GPU node (${j.engine})…`);
    _worldSndGenStat();
  } catch (e) { toast?.(e.message, 'error'); }
}
window.worldSndGenerate = worldSndGenerate;
