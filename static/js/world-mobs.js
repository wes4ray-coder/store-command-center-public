'use strict';
/* ══════════════════════════════════════════════════════════════════════════
   THE COMPANY — raid monsters (window.WMob).
   Real security threats (system D) are dramatized as anokolisa Skeleton/Orc mobs.
   Backend (world_raid) owns truth (kind/hp/slot); this just draws the sprite for
   each active threat with an idle animation. 32×32 frames, 4-frame Idle sheets,
   side-facing (mirrored to face the HQ). Degrades to a drawn glyph if absent.
   ══════════════════════════════════════════════════════════════════════════ */
window.WMob = (function () {
  const MOBS = "/store/static/world_assets/packs/anokolisa-pixel-crawler/Pixel Crawler - Free Pack/Entities/Mobs";
  const PATH = {
    orc_warrior:      'Orc Crew/Orc - Warrior',
    orc_rogue:        'Orc Crew/Orc - Rogue',
    orc_shaman:       'Orc Crew/Orc - Shaman',
    skeleton_warrior: 'Skeleton Crew/Skeleton - Warrior',
    skeleton_rogue:   'Skeleton Crew/Skeleton - Rogue',
    skeleton_mage:    'Skeleton Crew/Skeleton - Mage',
    skeleton_base:    'Skeleton Crew/Skeleton - Base',
  };
  const FR = 32, IFR = 4, ISPD = 200;
  const img = {};
  let ready = false;

  function _load(url) {
    return new Promise(res => { const im = new Image(); im.onload = () => { img[url] = im; res(true); }; im.onerror = () => res(false); im.src = encodeURI(url); });
  }
  async function init() {
    const oks = await Promise.all(Object.values(PATH).map(p => _load(MOBS + '/' + p + '/Idle/Idle-Sheet.png')));
    ready = oks.some(Boolean);
    if (ready) console.log('[WMob] raid monster sheets loaded');
    return ready;
  }

  // draw a monster bottom-centred at (x,y); faceLeft mirrors it toward the HQ.
  // Chain: the mob's OWN generated sheet → the pack Idle sheet → a drawn glyph.
  function draw(ctx, mobKey, x, y, size, faceLeft) {
    if (window.WSP && WSP.ready &&
        WSP.draw(ctx, 'mob_' + mobKey, 'idle', x, y, size, faceLeft ? 'left' : 'right')) return;
    const p = PATH[mobKey] || PATH.skeleton_base, im = img[MOBS + '/' + p + '/Idle/Idle-Sheet.png'];
    if (!im) {                                            // fallback glyph
      ctx.fillStyle = '#c0392b'; ctx.beginPath(); ctx.arc(x, y - size / 2, size / 3, 0, 6.283); ctx.fill();
      return;
    }
    const f = Math.floor((performance.now() + x * 7) / ISPD) % IFR;
    const dh = size, dw = size, dyp = y - dh;
    ctx.save();
    if (faceLeft) { ctx.translate(2 * x, 0); ctx.scale(-1, 1); }
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(im, f * FR, 0, FR, FR, x - dw / 2, dyp, dw, dh);
    ctx.restore();
  }

  return { init, draw, get ready() { return ready; } };
})();
