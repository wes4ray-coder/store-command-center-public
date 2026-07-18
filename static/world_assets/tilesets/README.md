# The Company — tileset / sprite assets

Drop downloaded pixel-art packs **in this folder** and describe them in `manifest.json`.
Everything degrades gracefully: until an atlas + coords are filled in, the world uses
its built-in procedural art, so you can add pieces incrementally.

First pack: **Anokolisa — Free Pixel Art Asset Pack (Top-down RPG, 16×16)**
https://anokolisa.itch.io/free-pixel-art-asset-pack-topdown-tileset-rpg-16x16-sprites

## How to wire it up

1. **Save the PNG(s)** here, e.g. `anokolisa.png` (keep the pack's `license.txt` too).
2. **Register the atlas** in `manifest.json`:
   ```json
   "atlases": [ { "id": "anokolisa", "src": "anokolisa.png" } ]
   ```
3. **Fill the sprite coords** — open the PNG in an image editor, read the pixel x/y of
   each structure's top-left corner and its width/height, and set them:
   ```json
   "sprites": {
     "workbench":     { "atlas": "anokolisa", "x": 112, "y": 48, "w": 16, "h": 16 },
     "furnace":       { "atlas": "anokolisa", "x": 128, "y": 48, "w": 16, "h": 32 },
     "alchemy_table": { "atlas": "anokolisa", "x": 144, "y": 48, "w": 16, "h": 16 },
     "anvil":         { "atlas": "anokolisa", "x": 160, "y": 48, "w": 16, "h": 16 },
     "sawmill":       { "atlas": "anokolisa", "x": 176, "y": 48, "w": 32, "h": 32 }
   }
   ```
   *(x/y/w/h above are placeholders — read the real ones from the sheet.)*
4. Reload the Company tab. Structures appear as **department workstations**:
   Dev Lab → workbench · Image Studio → alchemy table · Video → furnace ·
   3D Studio → sawmill · Storefront → anvil (others reuse these). Mapping lives in
   `DEPT_STATION` in `static/js/tab-world.js`.

## Optional: swap the terrain too
Fill `manifest.tiles` with a 16×16 atlas cell per key to replace procedural tiles:
```json
"tiles": {
  "grass": { "atlas": "anokolisa", "x": 0, "y": 0, "w": 16, "h": 16 },
  "path":  { "atlas": "anokolisa", "x": 16, "y": 0, "w": 16, "h": 16 }
}
```
Keys: `grass path floor wall water tree plaza`. Leave a key `null` to keep procedural.

## Notes
- Anything in this folder is git-ignored (runtime assets). Keep licenses alongside.
- The loader is `static/js/world-assets.js` (`window.WA`). It only activates when at
  least one atlas image loads; otherwise the world stays procedural.
