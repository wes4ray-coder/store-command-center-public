# Local Marketplace / Resell Feature — Implementation Plan

> **Goal:** Snap a photo of something (or point at a folder of images), let AI identify it, suggest a price, and help post it to Facebook Marketplace, OfferUp, Craigslist, eBay, or Mercari.

---

## Status (as of 2026-07-07, session 2)

| Component | Status |
|---|---|
| RESELL_PLAN.md | ✅ Written + updated |
| DB: resell_listings, resell_listing_images, resell_offers, resell_auto_tasks | ✅ Done |
| Backend: analyze, multi-photo, research (eBay scrape + AI), listings CRUD, offers, browser-auto posting, monitoring status | ✅ Done |
| Frontend: 📸 Resell tab — multi-photo upload, vision AI, price research, shipping policy, price mode, offers view | ✅ Done |
| Settings → Resell Preferences (location, max drive miles, gas cost, payment info) | ✅ Done |
| Monitoring cron (every 30 min, no-ops if no active listings) | ✅ Active — cron ID: aeaf0559 |
| Browser automation posting (FB/OfferUp/CL/Mercari) | ✅ Framework done — **needs platform login credentials** |
| eBay — removed (no shipping preference) | ❌ Dropped per Wesley |
| Distance calculation (haversine + Nominatim geocode) | ✅ Done in offer recording |
| Offer filtering (qualified/lowball/pending) | ✅ Done |
| Wesley notification on qualified offer | ✅ Monitoring cron handles this |
| Directory batch scan auto-analyze | ⏳ Phase 2 |
| Credential storage for FB/OfferUp | ⏳ Wesley providing creds next session |

---

## Platform Reality Check

| Platform | API Available | Strategy |
|---|---|---|
| **eBay** | ✅ Full official API (free dev program) | Auto-post via API |
| **Facebook Marketplace** | ❌ No public API | AI-generated content → copy/paste; or Playwright automation (Phase 2) |
| **OfferUp** (absorbed LetGo + 5Miles) | ❌ No public API | Same: copy/paste or Playwright |
| **Craigslist** | ❌ No public API | Copy/paste + mailto: link |
| **Mercari** | ❌ No public API | Copy/paste |

**Recommended posting workflow:**
1. AI analyzes image, generates title/description/price
2. User edits details
3. **eBay** → click "Post to eBay" → done automatically
4. **Others** → "Copy for Facebook", "Copy for OfferUp" buttons copy a pre-formatted listing block → user pastes into their phone/browser
5. Phase 2: Playwright headless browser automation for FB Marketplace and OfferUp

---

## Core Flow

```
[Upload image OR scan directory]
        ↓
[AI Vision: Gemma 4 QAT on RTX 3060]
  → item name, category, condition estimate
  → description paragraph
  → price range (low / fair / high)
        ↓
[User reviews + edits fields]
        ↓
[Save as Resell Listing]
        ↓
[Post Actions]
  ├── eBay → API call → listing URL returned
  ├── Facebook → copy button → formatted text for paste
  ├── OfferUp → copy button → formatted text
  ├── Craigslist → copy button + mailto link
  └── Mercari → copy button
```

---

## DB Schema — `resell_listings` table

```sql
CREATE TABLE IF NOT EXISTS resell_listings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    image_path      TEXT,                    -- relative path under store/static/resell_uploads/
    title           TEXT NOT NULL,
    description     TEXT,
    condition       TEXT DEFAULT 'Good',     -- New/Like New/Good/Fair/Poor
    category        TEXT,                    -- AI-suggested category
    asking_price    REAL,                    -- final price in dollars (user-set)
    ai_price_min    REAL,                    -- AI suggested low
    ai_price_max    REAL,                    -- AI suggested high
    ai_analysis     TEXT,                    -- raw JSON from AI response
    status          TEXT DEFAULT 'draft',    -- draft / listed / sold / archived
    platforms       TEXT DEFAULT '{}',       -- JSON: {ebay: {id, url, listed_at}, ...}
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);
```

---

## Backend Endpoints — `/api/resell/*`

### `POST /api/resell/analyze`
- **Input:** multipart file upload (image)
- **Flow:** save image → encode base64 → send to Gemma 4 vision via LM Studio → parse JSON response
- **Gemma prompt:** _"You are a resale pricing expert. Look at this item photo. Return JSON with: title (short product name), category (eBay category string), condition_guess (New/Like New/Good/Fair/Poor), description (2-3 sentence listing description), price_low (USD, conservative), price_fair (USD, fair market), price_high (USD, optimistic), key_features (array of strings)"_
- **Output:** `{title, category, condition_guess, description, price_low, price_fair, price_high, key_features, image_path}`

### `POST /api/resell/scan-directory`
- **Input:** `{path: "/some/local/dir"}`
- **Flow:** list image files in dir → return list of paths for user to select
- **Output:** `{images: [{path, filename, size_kb, thumb_url}]}`
- ⚠️ Phase 2: auto-analyze all images in batch

### `POST /api/resell/listings` — create/save listing
### `GET /api/resell/listings` — list all (filter by status)
### `GET /api/resell/listings/{id}` — single listing
### `PATCH /api/resell/listings/{id}` — update fields
### `DELETE /api/resell/listings/{id}` — delete

### `POST /api/resell/listings/{id}/post-ebay`
- **Requires:** eBay OAuth token (stored in settings)
- **Flow:**
  1. Read listing fields
  2. Call eBay Browse API / Trading API → create draft listing
  3. Return `{listing_url, ebay_item_id}`
- **eBay API setup:** Register at developer.ebay.com → get AppID/CertID → OAuth 2.0 flow
- **Settings keys needed:** `ebay_app_id`, `ebay_cert_id`, `ebay_access_token`, `ebay_refresh_token`, `ebay_sandbox_mode`

### `POST /api/resell/listings/{id}/generate-content`
- **Input:** `{platform: "facebook"|"offerup"|"craigslist"|"mercari"}`
- **Returns:** platform-optimized text block for copy/paste
- **Facebook format:** title + price + condition + description + "DM for details"
- **OfferUp:** same, shorter
- **Craigslist:** includes location placeholder, formatting
- **Mercari:** title + bullet features + description

---

## eBay API Setup (One-Time)

1. Register at https://developer.ebay.com (free)
2. Create a production application → get `App ID (Client ID)` and `Cert ID (Client Secret)`
3. Add to store Settings → "eBay Developer" section
4. OAuth flow: user clicks "Connect eBay Account" → redirect to eBay auth → callback saves token
5. Token refresh: eBay tokens expire in 2h; use refresh_token (18 months) to auto-renew
6. Sandbox available for testing before going live

**API used:** eBay Sell API — `POST https://api.ebay.com/sell/inventory/v1/offer`

---

## Frontend: 📦 Resell Tab

```
Nav: 📦 Resell

Subtabs:
  [🆕 New Listing] [📋 My Listings] [✅ Posted]

New Listing subtab:
  ┌─────────────────────────────────────────┐
  │  Drop an image or click to upload        │
  │  ──── or ────                            │
  │  [Scan Directory]  /path/to/folder       │
  └─────────────────────────────────────────┘
  
  [Analyze with AI] button → spinner → results card:
  
  ┌ AI Analysis ──────────────────────────┐
  │ [image thumb]  Title: Xbox 360 Controller  │
  │                Category: Video Games       │
  │                Condition: Good             │
  │                Price range: $8 – $18       │
  │ Description: [editable textarea]           │
  │ Your price: [$ input]                      │
  │                                            │
  │ [Save Listing]                             │
  └────────────────────────────────────────┘

My Listings subtab:
  - Cards showing image thumb, title, price, status
  - Actions: Edit | Post to eBay | Copy for Facebook | Copy for OfferUp | Delete

Posted subtab:
  - Listings with platform badges (eBay ✅, FB ✅, etc.)
  - Link to live listing on eBay
```

---

## Phase 2 Roadmap

1. **Directory batch scan** — point at folder, AI analyzes all images, queue for review
2. **Browser automation (Playwright)** — auto-post to Facebook Marketplace and OfferUp
   - Install: `pip install playwright && playwright install chromium`
   - FB Marketplace flow: login → Marketplace → Create listing → fill fields → post
   - Risk: TOS violation / account ban (use with caution; user's risk)
3. **eBay sold price lookup** — scrape eBay sold listings to calibrate AI price suggestion
4. **Price history tracking** — record what sold, at what price, on what platform
5. **Condition wizard** — guided condition assessment (photos of wear points)
6. **Shipping calculator** — weight/dimensions → shipping cost → factor into price
7. **Bulk CSV export** — export listings for multi-channel tools like Vendoo or List Perfectly

---

## Files Touched / To Create

| File | Change |
|---|---|
| `app/db.py` | Add `resell_listings` table to `init_db()` |
| `app/main.py` | Add `/api/resell/*` endpoints (~200 lines) |
| `static/index.html` | Add nav item + `renderResell()` + subtab views (~300 lines) |
| `static/resell_uploads/` | Directory for uploaded item photos (create, mount as StaticFiles) |
| `app/ebay_client.py` | eBay API wrapper (OAuth, create listing, get status) |

---

## eBay Listing Template (API payload skeleton)

```json
{
  "sku": "resell-{listing_id}",
  "product": {
    "title": "...",
    "description": "...",
    "aspects": {},
    "imageUrls": ["https://your-server/static/resell_uploads/{image}"]
  },
  "condition": "USED_GOOD",
  "categoryId": "...",
  "format": "FIXED_PRICE",
  "pricingSummary": {
    "price": { "value": "12.99", "currency": "USD" }
  },
  "listingPolicies": {
    "fulfillmentPolicyId": "...",
    "paymentPolicyId": "...",
    "returnPolicyId": "..."
  },
  "merchantLocationKey": "default"
}
```

eBay requires business policies set up in eBay Seller Hub before listing via API.

---

_Last updated: 2026-07-07 by agent_claude_
