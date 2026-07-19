/* Video CHAIN-BUILDER — split out of tab-videos.js (loads AFTER it).
   Classic non-module script: shares the one global lexical scope with
   tab-videos.js. Core (tab-videos.js) calls into these (showChainBuilder /
   refreshChainGallery) via hoisted function declarations. */
/* ── VIDEO CHAIN ── */
let _chainPollTimer = null;

function showChainBuilder() {
  const modal = document.getElementById('chain-modal');
  if (modal) { modal.style.display = 'flex'; return; }
  // Create modal
  const m = document.createElement('div');
  m.id = 'chain-modal';
  m.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:2000;display:flex;align-items:center;justify-content:center;padding:16px';
  m.innerHTML = `
    <div style="background:var(--card);border:1px solid var(--border);border-radius:16px;padding:28px;width:100%;max-width:700px;max-height:90vh;overflow-y:auto">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px">
        <div style="font-size:1.1rem;font-weight:700">&#128279; Video Chain Builder</div>
        <button onclick="closeChainModal()" style="background:none;border:none;color:var(--muted);font-size:1.3rem;cursor:pointer;padding:4px">&times;</button>
      </div>

      <div style="margin-bottom:16px">
        <label style="font-size:.8rem;color:var(--muted);font-weight:600">CONCEPT / STORY (optional — for AI prompt generation)</label>
        <textarea id="chain-concept" placeholder="e.g. A lone astronaut discovers an alien garden on Mars and grows a plant that changes everything"
          style="width:100%;min-height:70px;margin-top:6px;padding:10px 12px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:8px;resize:vertical;font-family:inherit;font-size:.9rem;box-sizing:border-box"></textarea>
      </div>

      <div style="display:flex;gap:10px;margin-bottom:16px;flex-wrap:wrap;align-items:flex-end">
        <label style="font-size:.8rem;color:var(--muted);font-weight:600">SEGMENTS
          <div style="display:flex;align-items:center;gap:4px;margin-top:6px">
            <button type="button" onclick="_adjSegs(-1)" style="width:28px;height:34px;background:var(--bg);border:1px solid var(--border);border-radius:6px 0 0 6px;color:var(--text);font-size:1.1rem;cursor:pointer;padding:0">&#8722;</button>
            <input type="number" id="chain-seg-count" min="1" max="999" value="3"
              style="width:54px;height:34px;text-align:center;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:0;font-size:.95rem;padding:0 4px;-moz-appearance:textfield">
            <button type="button" onclick="_adjSegs(1)" style="width:28px;height:34px;background:var(--bg);border:1px solid var(--border);border-radius:0 6px 6px 0;color:var(--text);font-size:1.1rem;cursor:pointer;padding:0">&#43;</button>
          </div>
          <div style="font-size:.7rem;color:var(--muted);margin-top:3px" id="chain-seg-hint">3 segments &bull; ~15s</div>
        </label>
        <label style="font-size:.8rem;color:var(--muted);font-weight:600">STYLE / MOOD (optional)
          <input id="chain-style" type="text" placeholder="e.g. cinematic, epic, dreamy, funny"
            style="display:block;margin-top:6px;padding:7px 10px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px;min-width:200px" />
        </label>
        <button id="chain-gen-prompts-btn" onclick="generateChainPrompts()" title="Uses the local LLM to draft one scene prompt per segment from your concept, then fills the boxes below (you can still edit each)." style="padding:7px 18px;background:#a855f7;border:none;border-radius:6px;color:#fff;font-weight:600;cursor:pointer;font-size:.85rem">&#10024; Generate Prompts</button>
      </div>

      <div id="chain-prompts-list" style="margin-bottom:16px">
        <!-- Prompt rows injected here -->
      </div>

      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:16px">
        <label style="font-size:.78rem;color:var(--muted)">Model ${hlp('Which text-to-video model renders every segment. Wan 2.1 is the fast default; CogVideoX and LTX trade speed for quality. The model must be installed (download it in the Models tab) or the first run fetches it (~5-10 min).')}
          <select id="chain-model" style="width:100%;margin-top:4px;padding:7px 8px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px">
            <option value="Wan-AI/Wan2.1-T2V-1.3B-Diffusers">Wan2.1 T2V 1.3B</option>
            <option value="THUDM/CogVideoX-2b">CogVideoX 2B</option>
            <option value="Lightricks/LTX-Video">LTX-Video</option>
          </select>
        </label>
        <label style="font-size:.78rem;color:var(--muted)">Resolution ${hlp('Frame size and aspect ratio for every segment. 832x480 = landscape (YouTube/desktop), 480x832 = portrait (Reels/TikTok), 512x512 = square. Higher = slower and more VRAM.')}
          <select id="chain-res" style="width:100%;margin-top:4px;padding:7px 8px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px">
            <option value="832x480">832&times;480 (16:9)</option>
            <option value="480x832">480&times;832 (9:16)</option>
            <option value="512x512">512&times;512 (sq)</option>
          </select>
        </label>
        <label style="font-size:.78rem;color:var(--muted)">Duration/seg ${hlp('Length of EACH segment as a frame count (~16 fps). The finished chain runs this length times the number of segments, so more frames per segment means a much longer, slower render.')}
          <select id="chain-frames" style="width:100%;margin-top:4px;padding:7px 8px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px">
            <option value="25">&sim;1.5s (25f, fast)</option>
            <option value="49">&sim;3s (49f)</option>
            <option value="81" selected>&sim;5s (81f, default)</option>
            <option value="121">&sim;7.5s (121f, slow)</option>
          </select>
        </label>
        <label style="font-size:.78rem;color:var(--muted)">Steps ${hlp('Denoising steps per frame. More = cleaner, more coherent motion but slower. 20 is a good balance; 30 for final quality.')}
          <select id="chain-steps" style="width:100%;margin-top:4px;padding:7px 8px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px">
            <option value="15">15 &mdash; fast</option>
            <option value="20" selected>20 &mdash; balanced</option>
            <option value="30">30 &mdash; quality</option>
          </select>
        </label>
        <label style="font-size:.78rem;color:var(--muted)">Continuity strength ${hlp('How strongly each new segment carries over the last frame of the previous one. Low (0.3) = tight continuity, scenes flow smoothly; high (0.9) = more creative but jumpier. 0.7 is a good default.')}
          <div style="display:flex;align-items:center;gap:6px;margin-top:4px">
            <input type="range" id="chain-strength" min="0.3" max="0.9" step="0.05" value="0.7"
              style="flex:1" oninput="document.getElementById('chain-strength-val').textContent=this.value">
            <span id="chain-strength-val" style="font-size:.85rem;font-weight:600;color:var(--accent);min-width:30px">0.7</span>
          </div>
          <div style="font-size:.72rem;color:var(--muted);margin-top:2px">Low = tighter continuity &bull; High = more creative</div>
        </label>
      </div>

      <div style="display:flex;gap:10px;justify-content:flex-end">
        <button onclick="closeChainModal()" style="padding:9px 22px;background:none;border:1px solid var(--border);border-radius:8px;color:var(--text);cursor:pointer">Cancel</button>
        <button id="chain-submit-btn" onclick="submitChain()" style="padding:9px 22px;background:#6c63ff;border:none;border-radius:8px;color:#fff;font-weight:600;cursor:pointer">&#128279; Generate Chain</button>
      </div>
    </div>
  `;
  document.body.appendChild(m);
  m.addEventListener('click', e => { if (e.target === m) closeChainModal(); });
  // Update prompt rows when segment count changes
  const segInput = document.getElementById('chain-seg-count');
  function _syncSegs() {
    const n = Math.max(1, parseInt(segInput.value) || 1);
    const existing = [];
    for (let i = 0; i < existing.length + 1 || document.getElementById(`chain-prompt-${i}`); i++) {
      const el = document.getElementById(`chain-prompt-${i}`);
      if (!el) break;
      existing.push(el.value);
    }
    const hint = document.getElementById('chain-seg-hint');
    if (hint) hint.textContent = `${n} segment${n===1?'':'s'} \u2022 ~${Math.round(n*5)}s`;
    renderChainPromptRows(n, existing);
  }
  segInput.addEventListener('input', _syncSegs);
  window._adjSegs = function(d) {
    const el = document.getElementById('chain-seg-count');
    if (!el) return;
    el.value = Math.max(1, (parseInt(el.value)||3) + d);
    _syncSegs();
  };
  // Init prompt rows
  renderChainPromptRows(3);
}

function closeChainModal() {
  const m = document.getElementById('chain-modal');
  if (m) m.style.display = 'none';
}

function renderChainPromptRows(n, prompts = []) {
  const container = document.getElementById('chain-prompts-list');
  if (!container) return;
  let html = `<div style="font-size:.8rem;color:var(--muted);font-weight:600;margin-bottom:8px">SCENE PROMPTS <span style="font-weight:400">(edit freely)</span></div>`;
  for (let i = 0; i < n; i++) {
    html += `
      <div style="display:flex;gap:8px;align-items:flex-start;margin-bottom:8px">
        <div style="min-width:28px;height:28px;border-radius:50%;background:#6c63ff;display:flex;align-items:center;justify-content:center;font-size:.78rem;font-weight:700;color:#fff;margin-top:8px">${i+1}</div>
        <textarea id="chain-prompt-${i}" placeholder="Scene ${i+1} description&hellip;"
          style="flex:1;min-height:64px;padding:8px 10px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:8px;resize:vertical;font-family:inherit;font-size:.85rem;box-sizing:border-box">${esc(prompts[i] || '')}</textarea>
      </div>`;
  }
  container.innerHTML = html;
}

function _chainSegCount() {
  return Math.max(1, parseInt(document.getElementById('chain-seg-count')?.value) || 3);
}

async function generateChainPrompts() {
  const concept = document.getElementById('chain-concept')?.value.trim();
  if (!concept) { toast('Enter a concept first', 'warn'); return; }
  const n     = _chainSegCount();
  const style = document.getElementById('chain-style')?.value.trim() || '';
  const btn   = document.getElementById('chain-gen-prompts-btn');
  btn.disabled = true; btn.textContent = '\u23F3 Generating\u2026';
  try {
    const r = await fetch(API + '/api/videos/chain-prompts', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({concept, num_segments: n, style})
    });
    if (!r.ok) throw new Error(await r.text());
    const {task_id} = await r.json();
    // Poll for result
    let prompts = null;
    for (let i = 0; i < 60; i++) {
      await new Promise(res => setTimeout(res, 2000));
      const pr = await fetch(`${API}/api/task/${task_id}`);
      const pt = await pr.json();
      if (pt.status === 'done' && pt.result?.prompts) { prompts = pt.result.prompts; break; }
      if (pt.status === 'failed') { toast('LLM failed to generate prompts', 'error'); break; }
    }
    if (prompts) {
      renderChainPromptRows(n, prompts);
      toast(`Generated ${prompts.length} scene prompts!`);
    } else {
      toast('Timeout waiting for prompts — try again', 'warn');
    }
  } catch(e) {
    toast('Error: ' + e.message, 'error');
  } finally {
    btn.disabled = false; btn.textContent = '\u2728 Generate Prompts';
  }
}

async function submitChain() {
  const n = _chainSegCount();
  const prompts = [];
  for (let i = 0; i < n; i++) {
    const v = document.getElementById(`chain-prompt-${i}`)?.value.trim();
    if (!v) { toast(`Scene ${i+1} prompt is empty`, 'warn'); return; }
    prompts.push(v);
  }
  const res      = document.getElementById('chain-res').value;
  const [w, h]   = res.split('x').map(Number);
  const frames   = parseInt(document.getElementById('chain-frames').value);
  const steps    = parseInt(document.getElementById('chain-steps').value);
  const model_id = document.getElementById('chain-model').value;
  const strength = parseFloat(document.getElementById('chain-strength').value);
  const concept  = document.getElementById('chain-concept')?.value.trim() || '';
  const btn      = document.getElementById('chain-submit-btn');
  btn.disabled = true; btn.textContent = '\u23F3 Starting\u2026';
  try {
    const r = await fetch(API + '/api/video-chains', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({concept, prompts, model_id, width: w, height: h,
                            num_frames: frames, steps, strength})
    });
    if (!r.ok) throw new Error(await r.text());
    const {chain_id} = await r.json();
    toast(`Chain started! ${n} segments queued \u2014 generating sequentially\u2026`);
    closeChainModal();
    await refreshChainGallery();
  } catch(e) {
    toast('Error: ' + e.message, 'error');
    btn.disabled = false; btn.textContent = '\u128279 Generate Chain';
  }
}

async function refreshChainGallery() {
  const el = document.getElementById('chain-gallery');
  if (!el) return;
  if (_chainPollTimer) { clearTimeout(_chainPollTimer); _chainPollTimer = null; }
  let chains = [];
  try { chains = await api('/api/video-chains'); } catch { return; }
  if (!chains.length) { el.innerHTML = ''; return; }
  const hasActive = chains.some(c => ['pending','generating'].includes(c.status));
  el.innerHTML = `
    <div style="font-size:1rem;font-weight:700;margin:24px 0 12px">&#128279; Video Chains</div>
    <div style="display:flex;flex-direction:column;gap:16px">${chains.map(chainCard).join('')}</div>
  `;
  if (hasActive) _chainPollTimer = setTimeout(refreshChainGallery, 2500);
}

function chainCard(c) {
  const created = new Date(c.created_at + 'Z').toLocaleString();
  const total   = c.total_segments || c.prompts?.length || 0;
  const done    = c.completed_segments || 0;
  const pct     = total ? Math.round(done / total * 100) : 0;
  const statusBadge = {
    pending:    '<span style="background:var(--warn);color:#000;padding:2px 8px;border-radius:12px;font-size:.75rem">&#9203; Pending</span>',
    generating: '<span style="background:#6c63ff;color:#fff;padding:2px 8px;border-radius:12px;font-size:.75rem">&#127916; Generating&hellip;</span>',
    done:       '<span style="background:var(--green);color:#000;padding:2px 8px;border-radius:12px;font-size:.75rem">&#10003; Done</span>',
    failed:     '<span style="background:#ef4444;color:#fff;padding:2px 8px;border-radius:12px;font-size:.75rem">&#10060; Failed</span>',
  }[c.status] || c.status;

  // Progress bar
  const progressBar = (c.status === 'generating' || (c.status === 'done' && done < total)) ? `
    <div style="margin:10px 0;background:#1e1e2e;border-radius:4px;height:6px;overflow:hidden">
      <div style="height:100%;background:#6c63ff;transition:width .5s;width:${pct}%"></div>
    </div>
    <div style="font-size:.75rem;color:var(--muted)">Segment ${done}/${total} complete</div>` : '';

  // Compiled video player
  const compiledFilename = c.compiled_path ? c.compiled_path.split('/').pop() : null;
  const compiledSrc      = compiledFilename ? `${API}/videos/${encodeURIComponent(compiledFilename)}` : null;
  const compiledPlayer   = compiledSrc ? `
    <div style="margin-top:12px">
      <div style="font-size:.8rem;color:var(--muted);margin-bottom:6px">&#127902; Compiled video:</div>
      <video controls loop muted preload="metadata" style="width:100%;border-radius:8px;background:#000;max-height:200px;display:block">
        <source src="${compiledSrc}" type="video/mp4">
      </video>
      <a href="${compiledSrc}" download style="text-decoration:none">
        <button style="margin-top:6px;width:auto;padding:5px 12px;font-size:.8rem;background:var(--accent2,#0ea5e9)">&#11015; Download Compiled</button>
      </a>
    </div>` : '';

  // Segments list
  const segsHtml = (c.segments || []).map(s => {
    const segFilename = s.video_path ? s.video_path.split('/').pop() : null;
    const segSrc      = segFilename ? `${API}/videos/${encodeURIComponent(segFilename)}` : null;
    const segBadge    = {done:'&#10003;',failed:'&#10060;',generating:'&#8987;',queued:'&#9203;'}[s.status] || '?';
    const segProg = s.status === 'generating'
      ? `<span style="color:#a855f7;font-size:.72rem;min-width:34px;text-align:right">${Math.max(2,Math.min(100,s.progress||0))}%</span>` : '';
    return `<div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--border);font-size:.82rem">
      <span style="min-width:20px;font-weight:700;color:#6c63ff">${(s.chain_index||0)+1}</span>
      <span>${segBadge}</span>
      <span style="flex:1;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(s.prompt||'')}">${ s.status==='generating' && s.progress_msg ? esc(s.progress_msg) : esc((s.prompt||'').substring(0,80)) }</span>
      ${segProg}
      ${segSrc ? `<a href="${segSrc}" download title="Download segment"><button style="padding:3px 8px;font-size:.75rem;background:#1e1e2e;border:1px solid var(--border);border-radius:4px;color:var(--text);cursor:pointer">&#11015;</button></a>` : ''}
    </div>`;
  }).join('');

  const compileBtn = c.status === 'done' && !compiledSrc
    ? `<button onclick="compileChain(${c.id})" title="Stitch all finished segments into one MP4 with crossfade transitions, ready to download." style="width:auto;padding:5px 14px;font-size:.8rem;background:#0ea5e9;color:#fff;border:none;border-radius:6px;cursor:pointer">&#127902; Compile Video</button>`
    : '';
  const cancelChainBtn = ['pending','generating'].includes(c.status)
    ? `<button onclick="cancelChain(${c.id})" style="width:auto;padding:5px 12px;font-size:.8rem;background:#f59e0b20;color:#f59e0b;border:1px solid #f59e0b50;border-radius:6px;cursor:pointer">&#9209;&#65039; Cancel</button>`
    : '';

  return `
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;flex-wrap:wrap">
        <div>
          <div style="font-weight:700;font-size:.95rem;margin-bottom:4px">${esc(c.title||'Untitled Chain')}</div>
          ${c.concept ? `<div style="font-size:.78rem;color:var(--muted);margin-bottom:4px">Concept: ${esc(c.concept.substring(0,80))}</div>` : ''}
        </div>
        <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
          ${statusBadge}
          <span style="font-size:.72rem;color:var(--muted)">${total} segments &bull; ${c.model_id ? c.model_id.split('/').pop() : 'Wan'}</span>
        </div>
      </div>
      ${progressBar}
      ${c.error ? `<div style="font-size:.8rem;color:#ef4444;margin:8px 0">${esc(c.error)}</div>` : ''}
      ${compiledPlayer}
      <div style="margin-top:12px;border:1px solid var(--border);border-radius:8px;overflow:hidden">
        ${segsHtml}
      </div>
      <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">
        ${compileBtn}${cancelChainBtn}
        <button onclick="deleteChain(${c.id})" style="width:auto;padding:5px 12px;font-size:.8rem;background:#ef444420;color:#ef4444;border:1px solid #ef444450;border-radius:6px;cursor:pointer">&#128465; Delete Chain</button>
      </div>
      <div style="margin-top:5px;font-size:.73rem;color:var(--muted)">${created}</div>
    </div>`;
}

async function cancelChain(id) {
  if (!confirm('Cancel this chain? The current segment will be stopped.')) return;
  try {
    const r = await fetch(`${API}/api/video-chains/${id}/cancel`, {method:'POST'});
    if (!r.ok) throw new Error(await r.text());
    toast('Chain cancelled'); refreshChainGallery();
  } catch(e) { toast('Cancel failed: ' + e.message, 'error'); }
}
window.cancelChain = cancelChain;

async function compileChain(id) {
  const r = await fetch(`${API}/api/video-chains/${id}/compile`, {method:'POST'});
  if (r.ok) { toast('Compiling chain video with xfade transitions\u2026'); setTimeout(refreshChainGallery, 3000); }
  else toast('Compile failed: ' + await r.text(), 'error');
}

async function deleteChain(id) {
  if (!confirm('Delete this chain and all its segments?')) return;
  const r = await fetch(`${API}/api/video-chains/${id}`, {method:'DELETE'});
  if (r.ok) { toast('Chain deleted'); refreshChainGallery(); }
  else toast('Delete failed', 'error');
}
