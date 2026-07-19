'use strict';
/* ══════════════════════════════════════════════════════════════════════════
   THE COMPANY — external asset registry.
   Two things:
   (1) Named sprites/tiles from a manifest (static/world_assets/tilesets/manifest.json)
       for terrain + department structures (WA.has/draw/tile) — optional, fallback if absent.
   (2) Animated CHARACTER sheets from the downloaded packs (anokolisa 64×64 Walk/Idle,
       Down/Up/Side, Side mirrored for left/right) → WA.drawActor(). This turns the agents
       into real animated pixel villagers.
   Everything degrades gracefully: if files are missing, the world keeps its procedural art.
   ══════════════════════════════════════════════════════════════════════════ */
window.WA = (function () {
  const PACKS = '/store/static/world_assets/packs';
  const ANO = PACKS + '/anokolisa-pixel-crawler/Pixel Crawler - Free Pack';
  const FR = 64;                                   // character frame size (px)
  const CHAR = {
    walk: { frames: 6, spd: 110, base: ANO + '/Entities/Characters/Body_A/Animations/Walk_Base/Walk_' },
    idle: { frames: 4, spd: 200, base: ANO + '/Entities/Characters/Body_A/Animations/Idle_Base/Idle_' },
    work: { frames: 8, spd: 90,  base: ANO + '/Entities/Characters/Body_A/Animations/Crush_Base/Crush_' },
  };
  // extracted single-sprite props (name → filename in packs/_extracted/)
  const EXTRACT = {
    workbench: 'station_workbench.png', anvil: 'station_anvil.png', furnace: 'station_furnace.png',
    sawmill: 'station_sawmill.png', alchemy: 'station_alchemy.png',
    tree_green: 'tree_green.png', tree_autumn: 'tree_autumn.png', tree_yellow: 'tree_yellow.png',
    // scatter/identity props (anokolisa Environment/Props)
    barrel: 'prop_barrel.png', crate: 'prop_crate.png', crate_produce: 'prop_crate_produce.png',
    well: 'prop_well.png', banner_red: 'prop_banner_red.png', banner_blue: 'prop_banner_blue.png',
    banner_green: 'prop_banner_green.png',
    // per-department workstation gear (extracted from the Kenney packs — optional, fallback to emoji)
    gear_storefront: 'gear_storefront.png', gear_image: 'gear_image.png', gear_video: 'gear_video.png',
    gear_audio: 'gear_audio.png', gear_models3d: 'gear_models3d.png', gear_publishing: 'gear_publishing.png',
    gear_devlab: 'gear_devlab.png', gear_resell: 'gear_resell.png', gear_trends: 'gear_trends.png',
    // town building sprites (multi-tile; drawn as whole-building images)
    bld_house_1: 'bld_house_1.png', bld_house_2: 'bld_house_2.png', bld_shop_1: 'bld_shop_1.png',
    bld_shop_2: 'bld_shop_2.png', bld_tavern: 'bld_tavern.png', bld_cafe: 'bld_cafe.png',
    bld_arcade: 'bld_arcade.png', bld_library: 'bld_library.png', bld_church: 'bld_church.png',
    bld_townhall: 'bld_townhall.png',
  };
  const exUrl = n => PACKS + '/_extracted/' + EXTRACT[n];
  const img = {};                 // url → HTMLImageElement
  let manifest = null, ready = false, charsReady = false;

  function _load(url) {
    return new Promise(res => { const im = new Image(); im.onload = () => { img[url] = im; res(true); }; im.onerror = () => res(false); im.src = encodeURI(url); });
  }

  async function init(base) {
    // (1) optional tileset/structure manifest
    try {
      const r = await fetch((base || '/store/static/world_assets/tilesets') + '/manifest.json', { cache: 'no-cache' });
      if (r.ok) {
        manifest = await r.json();
        // key by the RESOLVED url — _load stores img[url], so the old img[a.src]
        // (bare filename) lookup never matched and atlases could never go ready.
        // ?v= busts the browser/proxy cache: regenerating a tileset reuses the
        // SAME filename, and a stale cached atlas rendered the whole map wrong.
        const ver = manifest.v || 0;
        await Promise.all((manifest.atlases || []).map(a => {
          let url = a.src && a.src.startsWith('/') ? a.src : (base || '/store/static/world_assets/tilesets') + '/' + a.src;
          if (ver) url += (url.includes('?') ? '&' : '?') + 'v=' + ver;
          return _load(url).then(ok => { if (ok) manifest.__atlas = Object.assign(manifest.__atlas || {}, { [a.id]: img[url] }); });
        }));
        ready = !!(manifest && (manifest.atlases || []).length && manifest.__atlas && Object.keys(manifest.__atlas).length);
        if (ready) _vetTiles();     // drop broken/black cells → procedural fallback
      }
    } catch (e) { /* no manifest → procedural terrain/structures */ }

    // (2) animated character sheets (the important part)
    const urls = [];
    for (const act of ['walk', 'idle', 'work']) for (const d of ['Down', 'Up', 'Side']) urls.push(CHAR[act].base + d + '-Sheet.png');
    const oks = await Promise.all(urls.map(_load));
    charsReady = oks.every(Boolean);
    if (charsReady) console.log('[WA] animated character sheets loaded');
    // (3) extracted single-sprite props (stations + landmark trees)
    await Promise.all(Object.keys(EXTRACT).map(n => _load(exUrl(n))));
    return { ready, charsReady };
  }

  // draw an extracted sprite (station/tree) bottom-centred at (x,y), height ≈ targetH
  function hasSprite(name) { return !!(EXTRACT[name] && img[exUrl(name)]); }
  function drawSprite(ctx, name, x, y, targetH) {
    const im = img[exUrl(name)]; if (!im) return false;
    const sc = targetH / im.height, w = im.width * sc;
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(im, x - w / 2, y - targetH, w, targetH);
    return true;
  }

  // ── manifest sprites/tiles (terrain + structures; used only if mapped) ──
  function _spr(name) { return ready && manifest && manifest.sprites && manifest.sprites[name]; }
  function _atlas(id) { return (manifest && manifest.__atlas && manifest.__atlas[id]) || img[id]; }
  function has(name) { const s = _spr(name); return !!(s && _atlas(s.atlas)); }
  function draw(ctx, name, dx, dy, targetH) {
    const s = _spr(name), a = s && _atlas(s.atlas); if (!a) return false;
    const sc = (targetH || s.h) / s.h; ctx.drawImage(a, s.x, s.y, s.w, s.h, dx - s.w * sc / 2, dy - s.h * sc, s.w * sc, s.h * sc); return true;
  }

  // Validate the mapped terrain cells once per init: a stale/failed generation can
  // leave a cell that is near-black or a single flat colour, which painted the
  // WHOLE terrain black/red. Any bad cell is unmapped → procedural art returns.
  // The generated atlas ('gen') also never overrides FLOOR/WALL — those are
  // structural tiles with crafted interior art (insets, bevels, wood floors);
  // user-supplied packs (other atlas ids) keep full control.
  function _vetTiles() {
    const tiles = (manifest && manifest.tiles) || {};
    for (const key in tiles) {
      const t = tiles[key];
      if (!t || typeof t !== 'object') continue;
      const a = _atlas(t.atlas); if (!a) continue;
      if (t.atlas === 'gen' && (key === 'floor' || key === 'wall')) { tiles[key] = null; continue; }
      try {
        const w = t.w || 16, h = t.h || 16, cv = document.createElement('canvas');
        cv.width = w; cv.height = h;
        const cx = cv.getContext('2d');
        cx.drawImage(a, t.x, t.y, w, h, 0, 0, w, h);
        const d = cx.getImageData(0, 0, w, h).data;
        let sum = 0, sum2 = 0, n = 0;
        for (let i = 0; i < d.length; i += 16) {          // sample every 4th px
          const l = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
          sum += l; sum2 += l * l; n++;
        }
        const mean = sum / n, sd = Math.sqrt(Math.max(0, sum2 / n - mean * mean));
        if (mean < 26 || sd < 6) { tiles[key] = null; console.warn('[WA] tile "' + key + '" failed QA (mean ' + mean.toFixed(0) + ', sd ' + sd.toFixed(0) + ') — using procedural art'); }
      } catch (e) { tiles[key] = null; }
    }
    _scaled = {};                                          // any prior prescales are stale
  }

  // Prescale an atlas cell to the on-map tile size ONCE with smoothing — blitting
  // 64px art into a 20px tile with nearest-neighbour every bake produced
  // salt-and-pepper noise ("broken" terrain). Area-averaged it reads as texture.
  let _scaled = {};
  function _scaledTile(t, size) {
    const k = t.atlas + ':' + t.x + ':' + t.y + '@' + size;
    let cv = _scaled[k];
    if (cv === undefined) {
      const a = _atlas(t.atlas); if (!a) return null;
      cv = document.createElement('canvas'); cv.width = size; cv.height = size;
      const cx = cv.getContext('2d');
      cx.imageSmoothingEnabled = true; cx.imageSmoothingQuality = 'high';
      cx.drawImage(a, t.x, t.y, t.w || 16, t.h || 16, 0, 0, size, size);
      _scaled[k] = cv;
    }
    return cv;
  }
  function tile(ctx, key, dx, dy, size) {
    const t = ready && manifest && manifest.tiles && manifest.tiles[key], a = t && typeof t === 'object' && _atlas(t.atlas); if (!a) return false;
    const sw = t.w || 16;
    if (size < sw) {                                       // downscale → use the smooth prescale
      const cv = _scaledTile(t, Math.round(size)); if (!cv) return false;
      ctx.drawImage(cv, dx, dy, size, size); return true;
    }
    ctx.drawImage(a, t.x, t.y, sw, t.h || 16, dx, dy, size, size); return true;
  }

  // ── animated character: draw a villager facing `dir` in mode walk|idle|work ──
  function drawActor(ctx, dir, mode, x, y, size) {
    if (!charsReady) return false;
    const spec = CHAR[mode] || CHAR.idle;
    const sheetDir = (dir === 'left' || dir === 'right') ? 'Side' : (dir === 'up' ? 'Up' : 'Down');
    const im = img[spec.base + sheetDir + '-Sheet.png']; if (!im) return false;
    const f = Math.floor(performance.now() / spec.spd) % spec.frames;
    const dw = size, dh = size, dyp = y - dh * 0.86;
    ctx.save();
    if (dir === 'left') { ctx.translate(2 * x, 0); ctx.scale(-1, 1); }   // mirror Side → left
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(im, f * FR, 0, FR, FR, x - dw / 2, dyp, dw, dh);
    ctx.restore();
    return true;
  }

  return { init, has, draw, tile, drawActor, hasSprite, drawSprite, get ready() { return ready; }, get charsReady() { return charsReady; }, get manifest() { return manifest; } };
})();
