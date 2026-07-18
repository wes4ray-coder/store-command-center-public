"""WordPress / WooCommerce client for the Portal bridge.

Two transports, because WordPress splits the surface across two auth systems:

  • WooCommerce products  → WooCommerce REST API (`/wp-json/wc/v3`) over HTTPS with
    Basic Auth (consumer key = user, secret = pass). WooCommerce only honours Basic /
    query-param auth over SSL, so this MUST hit the public https URL (example.com),
    not http://localhost:8090 (there it demands OAuth-1.0a signing).

  • Media upload + Pages  → the easy-mcp-ai MCP endpoint (`/wp-json/easy-mcp-ai/v1/mcp`)
    over http://localhost:8090 with a `wpmcp_…` Bearer token. This lets us push LOCAL
    generated files (base64) with no public URL, and build the portfolio Gallery page.

All credentials live in the `settings` key-value table (same convention as Etsy /
Printify / Cults3D). See routers/portal.py for how they are read.
"""
from __future__ import annotations
import base64
from pathlib import Path
from typing import Optional
import httpx


class WCError(Exception):
    """WooCommerce / WordPress API error, carrying an HTTP-ish status for the router."""
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


# ─────────────────────────────────────────────────────────────────────────────
# WooCommerce REST (products) — Basic Auth over HTTPS
# ─────────────────────────────────────────────────────────────────────────────
class WooClient:
    def __init__(self, base_url: str, consumer_key: str, consumer_secret: str):
        # base_url like "https://example.com" (no trailing slash, no /wp-json)
        self.base = base_url.rstrip("/")
        self.api = f"{self.base}/wp-json/wc/v3"
        self.auth = (consumer_key, consumer_secret)

    def _req(self, method: str, path: str, *, params: dict = None, json: dict = None) -> dict | list:
        url = f"{self.api}{path}"
        try:
            r = httpx.request(method, url, params=params, json=json,
                              auth=self.auth, timeout=60,
                              headers={"User-Agent": "StoreCommandCenter-Portal/1.0"})
        except httpx.HTTPError as e:
            raise WCError(f"Could not reach WooCommerce at {self.base}: {e}", 502)
        if not r.is_success:
            detail = None
            try:
                detail = r.json().get("message")
            except Exception:
                detail = r.text[:300]
            raise WCError(f"WooCommerce HTTP {r.status_code}: {detail}", r.status_code)
        if r.status_code == 204 or not r.content:
            return {}
        return r.json()

    # --- connection / metadata -------------------------------------------------
    def ping(self) -> dict:
        """Cheap authenticated read. Returns {ok, total_products}."""
        try:
            r = httpx.get(f"{self.api}/products", params={"per_page": 1},
                          auth=self.auth, timeout=30,
                          headers={"User-Agent": "StoreCommandCenter-Portal/1.0"})
        except httpx.HTTPError as e:
            raise WCError(f"Could not reach WooCommerce at {self.base}: {e}", 502)
        if r.status_code in (401, 403):
            raise WCError("WooCommerce rejected the API key (check consumer key/secret "
                          "and that the store is HTTPS).", r.status_code)
        if not r.is_success:
            raise WCError(f"WooCommerce HTTP {r.status_code}: {r.text[:200]}", r.status_code)
        total = r.headers.get("x-wp-total")
        return {"ok": True, "total_products": int(total) if total and total.isdigit() else None}

    def list_products(self, per_page: int = 50, page: int = 1, **params) -> list:
        return self._req("GET", "/products",
                         params={"per_page": per_page, "page": page, **params})

    def get_product(self, pid: int) -> dict:
        return self._req("GET", f"/products/{pid}")

    def delete_product(self, pid: int, force: bool = True) -> dict:
        return self._req("DELETE", f"/products/{pid}", params={"force": str(force).lower()})

    # --- categories ------------------------------------------------------------
    def list_categories(self, per_page: int = 100) -> list:
        return self._req("GET", "/products/categories", params={"per_page": per_page})

    def ensure_category(self, name: str) -> int:
        """Return the id of a product category, creating it if missing."""
        name = (name or "").strip()
        if not name:
            return 0
        for c in self.list_categories():
            if c.get("name", "").lower() == name.lower():
                return c["id"]
        created = self._req("POST", "/products/categories", json={"name": name})
        return created.get("id", 0)

    # --- the core write: external / affiliate product --------------------------
    def create_external_product(self, *, name: str, external_url: str,
                                regular_price: str = "", description: str = "",
                                short_description: str = "", button_text: str = "Buy now",
                                image_urls: list[str] = None, category_ids: list[int] = None,
                                tags: list[str] = None, status: str = "publish",
                                sku: str = "") -> dict:
        """Create a WooCommerce 'external/affiliate' product: real product page whose
        Buy button links OUT to external_url (Amazon, Etsy, Cults3D, a software page…)."""
        payload: dict = {
            "name": name,
            "type": "external",
            "status": status,
            "external_url": external_url,
            "button_text": button_text or "Buy now",
            "description": description or "",
            "short_description": short_description or "",
        }
        if regular_price not in (None, ""):
            payload["regular_price"] = str(regular_price)
        if sku:
            payload["sku"] = sku
        if image_urls:
            payload["images"] = [{"src": u} for u in image_urls if u]
        if category_ids:
            payload["categories"] = [{"id": i} for i in category_ids if i]
        if tags:
            payload["tags"] = [{"name": t} for t in tags if t]
        return self._req("POST", "/products", json=payload)


# ─────────────────────────────────────────────────────────────────────────────
# WordPress MCP (media + pages) — Bearer token over http://localhost:8090
# ─────────────────────────────────────────────────────────────────────────────
class WPMcpClient:
    def __init__(self, endpoint: str, token: str):
        self.endpoint = endpoint
        self.token = token
        self._id = 0

    def _call(self, method: str, params: dict = None) -> dict:
        self._id += 1
        body = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            body["params"] = params
        try:
            r = httpx.post(self.endpoint, json=body, timeout=120, headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            })
        except httpx.HTTPError as e:
            raise WCError(f"Could not reach WordPress MCP: {e}", 502)
        if not r.is_success:
            raise WCError(f"WordPress MCP HTTP {r.status_code}: {r.text[:200]}", r.status_code)
        data = r.json()
        if "error" in data:
            raise WCError(f"WordPress MCP error: {data['error'].get('message', data['error'])}", 502)
        return data.get("result", {})

    def _tool(self, name: str, arguments: dict) -> dict:
        """Call an MCP tool and return the parsed JSON payload from its text content."""
        res = self._call("tools/call", {"name": name, "arguments": arguments})
        # MCP returns {content:[{type:text,text:"<json or message>"}], isError?}
        if res.get("isError"):
            txt = _first_text(res)
            raise WCError(f"WordPress tool '{name}' failed: {txt}", 502)
        txt = _first_text(res)
        import json as _json
        try:
            return _json.loads(txt) if txt else {}
        except Exception:
            return {"raw": txt}

    def upload_media_base64(self, filename: str, file_bytes: bytes,
                            title: str = "", alt_text: str = "", caption: str = "") -> dict:
        """Upload a LOCAL file to the WP media library. Returns the attachment (id, source_url…)."""
        b64 = base64.b64encode(file_bytes).decode("ascii")
        return self._tool("wp_upload_media", {
            "filename": filename, "content_base64": b64,
            "title": title or filename, "alt_text": alt_text, "caption": caption,
        })

    def upload_media_from_url(self, url: str, title: str = "", alt_text: str = "") -> dict:
        return self._tool("wp_upload_media_from_url",
                          {"url": url, "title": title, "alt_text": alt_text})

    def find_page_by_slug(self, slug: str) -> Optional[dict]:
        res = self._tool("wp_list_pages", {"slug": slug}) if True else {}
        pages = res.get("pages") or res.get("posts") or (res if isinstance(res, list) else [])
        if isinstance(pages, dict):
            pages = pages.get("items", [])
        for p in pages or []:
            if str(p.get("slug")) == slug:
                return p
        return None

    def create_page(self, title: str, content: str, slug: str = "", status: str = "publish") -> dict:
        args = {"title": title, "content": content, "status": status}
        if slug:
            args["slug"] = slug
        return self._tool("wp_create_page", args)

    def update_page(self, page_id: int, content: str, title: str = None) -> dict:
        args = {"page_id": page_id, "content": content}
        if title:
            args["title"] = title
        return self._tool("wp_update_page", args)


def _first_text(result: dict) -> str:
    content = result.get("content") or []
    for c in content:
        if isinstance(c, dict) and c.get("type") == "text":
            return c.get("text", "")
    return ""
