/* ══ THE COMPANY — The Bible ══
   The nation's scripture. The Word is the store's BOOK.md; the Teachings are
   what the agents study and record (via blessed research/scout strategies).
   Uses _worldModal + api()/esc()/toast(). Global-scope classic script. */

let _bibleData = { word: null, teachings: [], tab: 'word', chapter: 0 };

/* tiny, safe-enough markdown → html (content is our own BOOK.md) */
function _md(src) {
  if (!src) return '';
  const parts = String(src).split(/```/);
  let out = '';
  parts.forEach((seg, i) => {
    if (i % 2 === 1) {   // fenced code block
      out += `<pre style="background:#0b1120;border:1px solid #1b2740;border-radius:6px;padding:8px;overflow-x:auto;font-size:.72rem;color:#a9c7e8;white-space:pre">${esc(seg.replace(/^\w*\n/, ''))}</pre>`;
      return;
    }
    let t = esc(seg);
    t = t.replace(/`([^`]+)`/g, '<code style="background:#0b1120;padding:1px 4px;border-radius:4px;color:#a9c7e8">$1</code>');
    t = t.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>').replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" style="color:#7dd3fc">$1</a>');
    // block elements, line by line
    const lines = t.split('\n');
    let html = '', inList = false;
    for (let ln of lines) {
      const h = ln.match(/^(#{3,6})\s+(.*)$/);
      const li = ln.match(/^\s*[-*]\s+(.*)$/);
      if (h) { if (inList) { html += '</ul>'; inList = false; } html += `<div style="font-weight:700;color:#e8eefc;margin:8px 0 3px">${h[2]}</div>`; }
      else if (li) { if (!inList) { html += '<ul style="margin:2px 0 6px 16px">'; inList = true; } html += `<li style="margin:1px 0">${li[1]}</li>`; }
      else if (/^\s*---+\s*$/.test(ln)) { if (inList) { html += '</ul>'; inList = false; } html += '<hr style="border:none;border-top:1px solid #1b2740;margin:8px 0">'; }
      else if (ln.trim() === '') { if (inList) { html += '</ul>'; inList = false; } html += '<div style="height:6px"></div>'; }
      else { if (inList) { html += '</ul>'; inList = false; } html += `<div>${ln}</div>`; }
    }
    if (inList) html += '</ul>';
    out += html;
  });
  return out;
}

async function worldBible() {
  try {
    const [w, t] = await Promise.all([
      api('/api/world/bible/word'),
      api('/api/world/bible/teachings?limit=100'),
    ]);
    _bibleData = { word: w, teachings: t.teachings || [], tab: 'word', chapter: 0 };
  } catch (e) { toast?.('The Bible failed to load'); return; }
  _renderBible();
}

function _renderBible() {
  const d = _bibleData, w = d.word || {}, chs = w.chapters || [];
  const tab = (id, label) => `<button class="btn" style="padding:4px 12px;font-size:.76rem;${d.tab === id ? 'background:#2a1f4a;border-color:#6d5aff;color:#c4b5fd' : ''}" onclick="bibleTab('${id}')">${label}</button>`;
  const tabs = `<div style="display:flex;gap:6px;margin-bottom:12px">${tab('word', '📜 The Word')}${tab('teachings', `✍️ Teachings${d.teachings.length ? ` (${d.teachings.length})` : ''}`)}</div>`;

  let body;
  if (d.tab === 'word') {
    const opts = [`<option value="-1">✦ ${esc(w.title || 'The Book')} — preface</option>`]
      .concat(chs.map((c, i) => `<option value="${i}" ${i === d.chapter ? 'selected' : ''}>${esc(c.title)}</option>`)).join('');
    const content = d.chapter < 0 ? _md(w.intro) : _md((chs[d.chapter] || {}).md);
    body = `
      <select onchange="bibleChapter(this.value)" style="width:100%;padding:7px 10px;background:#0b1120;border:1px solid #26324a;border-radius:8px;color:#e8eefc;font-size:.8rem;margin-bottom:10px">${opts}</select>
      <div style="font-size:.8rem;color:#c7d2e5;line-height:1.55;max-height:52vh;overflow:auto;padding-right:6px">${content || '<span style="color:#54607a">—</span>'}</div>`;
  } else {
    const KIND = { study: '📘', law: '⚖️', lesson: '🎓', revelation: '✨' };
    body = d.teachings.length
      ? `<div style="max-height:56vh;overflow:auto;padding-right:6px">${d.teachings.map(t => `
        <div style="border:1px solid #26324a;border-radius:9px;padding:10px 12px;margin-bottom:8px;background:#0e1626">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
            <b style="color:#e8eefc">${KIND[t.kind] || '📘'} ${esc(t.title)}</b>
            <span style="font-size:.66rem;color:#54607a;flex-shrink:0">${(t.created_at || '').slice(0, 10)}</span>
          </div>
          <div style="font-size:.8rem;color:#c7d2e5;line-height:1.5;margin:4px 0">${esc(t.verse)}</div>
          <div style="font-size:.66rem;color:#7a86a0">— ${esc(t.author || 'a scholar')}${t.book ? ` · on <span style="color:#9fb4d6">${esc(t.book)}</span>` : ''}</div>
        </div>`).join('')}</div>`
      : `<div style="color:#54607a;font-size:.82rem;padding:12px 0">No teachings yet. When the Republic's research or scout strategies are blessed, scholars study the topic and record what they learn here — the Bible grows from the nation's work.</div>`;
  }

  _worldModal('📖 The Company Bible', tabs + body);
}

function bibleTab(t) { _bibleData.tab = t; _renderBible(); }
function bibleChapter(i) { _bibleData.chapter = parseInt(i, 10); _renderBible(); }

window.worldBible = worldBible;
window.bibleTab = bibleTab;
window.bibleChapter = bibleChapter;
