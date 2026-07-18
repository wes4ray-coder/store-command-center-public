"""
Printify API integration.
Docs: https://developers.printify.com/
"""
import base64, httpx
from pathlib import Path
from typing import Optional

PRINTIFY_API = "https://api.printify.com/v1"

# Blueprint IDs for common products (Printify standard catalog)
# These are for Printify's most popular print providers (Monster Digital / Printify Choice)
BLUEPRINTS = {
    "T-Shirt":    {"blueprint_id": 6,   "print_provider_id": 29},  # Unisex Jersey Short Sleeve Tee / Monster Digital
    "Hoodie":     {"blueprint_id": 77,  "print_provider_id": 66},  # Unisex Heavy Blend Hooded Sweatshirt / Prima Printing
    "Sweatshirt": {"blueprint_id": 49,  "print_provider_id": 66},  # Unisex Heavy Blend Crewneck Sweatshirt / Prima Printing
    "Tank Top":   {"blueprint_id": 39,  "print_provider_id": 29},  # Unisex Jersey Tank / Monster Digital
    "Mug":        {"blueprint_id": 68,  "print_provider_id": 1},   # White Glossy Mug / SPOKE Custom Products
    "Tumbler":    {"blueprint_id": 353, "print_provider_id": 1},   # Tumbler 20oz / SPOKE Custom Products
    "Poster":     {"blueprint_id": 446, "print_provider_id": 6},   # Poster / T Shirt and Sons
    "Sticker":    {"blueprint_id": 400, "print_provider_id": 99},  # Kiss-Cut Stickers / Printify Choice
    "Tote Bag":   {"blueprint_id": 553, "print_provider_id": 217}, # Cotton Tote Bag / Fulfill Engine
    "Phone Case": {"blueprint_id": 269, "print_provider_id": 1},   # Tough Phone Cases / SPOKE Custom Products
    "Mouse Pad":  {"blueprint_id": 582, "print_provider_id": 70},  # Mouse Pad / Printed Mint
    "Pillow":     {"blueprint_id": 220, "print_provider_id": 10},  # Spun Polyester Square Pillow / MWW On Demand
}

# Verified variant IDs from live Printify API
DEFAULT_VARIANTS = {
    "T-Shirt": [
        {"id": 12126, "price": 2500},  # S Black
        {"id": 12125, "price": 2500},  # M Black
        {"id": 12124, "price": 2500},  # L Black
        {"id": 12127, "price": 2500},  # XL Black
        {"id": 12128, "price": 2700},  # 2XL Black
    ],
    "Hoodie": [
        {"id": 32918, "price": 4000},  # S Black
        {"id": 32919, "price": 4000},  # M Black
        {"id": 32920, "price": 4000},  # L Black
        {"id": 32921, "price": 4000},  # XL Black
        {"id": 32922, "price": 4200},  # 2XL Black
        {"id": 32923, "price": 4200},  # 3XL Black
    ],
    "Sweatshirt": [
        {"id": 25397, "price": 3500},  # S Black
        {"id": 25428, "price": 3500},  # M Black
        {"id": 25459, "price": 3500},  # L Black
        {"id": 25490, "price": 3500},  # XL Black
        {"id": 25521, "price": 3700},  # 2XL Black
    ],
    "Tank Top": [
        {"id": 24641, "price": 2000},  # S Black
        {"id": 24640, "price": 2000},  # M Black
        {"id": 24639, "price": 2000},  # L Black
        {"id": 24642, "price": 2000},  # XL Black
    ],
    "Mug": [
        {"id": 33719, "price": 1800},  # 11oz
    ],
    "Tumbler": [
        {"id": 44519, "price": 2800},  # 20oz
    ],
    "Poster": [
        {"id": 62615, "price": 2000},
        {"id": 62616, "price": 2500},
        {"id": 62617, "price": 3000},
    ],
    "Sticker": [
        {"id": 45750, "price": 399},   # 3x3
        {"id": 45752, "price": 499},   # 4x4
        {"id": 45754, "price": 699},   # 6x6
    ],
    "Tote Bag": [
        {"id": 70603, "price": 1800},  # Black
        {"id": 70646, "price": 1800},  # Cream
    ],
    "Phone Case": [
        {"id": 62582, "price": 1800},  # iPhone 11
        {"id": 62583, "price": 1800},  # iPhone 11 Pro
        {"id": 62584, "price": 1800},  # iPhone 11 Pro Max
        {"id": 70871, "price": 1800},  # iPhone 12
    ],
    "Mouse Pad": [
        {"id": 71664, "price": 1200},  # Rectangle
    ],
    "Pillow": [
        {"id": 41521, "price": 2200},  # 14x14
        {"id": 41524, "price": 2500},  # 16x16
        {"id": 41527, "price": 2800},  # 18x18
    ],
}


class PrintifyClient:
    def __init__(self, api_key: str, shop_id: str):
        self.api_key = api_key
        self.shop_id = shop_id
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "StoreCommandCenter/1.0",
        }

    def _get(self, path: str) -> dict:
        r = httpx.get(f"{PRINTIFY_API}{path}", headers=self.headers, timeout=30)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, data: dict) -> dict:
        r = httpx.post(f"{PRINTIFY_API}{path}", headers=self.headers, json=data, timeout=60)
        if not r.is_success:
            try:
                detail = r.json()
            except Exception:
                detail = r.text[:400]
            raise Exception(f"Printify HTTP {r.status_code}: {detail}")
        return r.json()

    def get_shops(self) -> list:
        return self._get("/shops.json")

    def upload_image(self, image_path: str, filename: str = "design.png") -> dict:
        """Upload image to Printify media library. Returns image object with id."""
        img_bytes = Path(image_path).read_bytes()
        b64 = base64.b64encode(img_bytes).decode()
        return self._post("/uploads/images.json", {
            "file_name": filename,
            "contents": b64,
        })

    def create_product(self, title: str, description: str, image_id: str,
                       product_type: str = "T-Shirt",
                       tags: Optional[list] = None,
                       retail_price_cents: Optional[int] = None) -> dict:
        """Create a Printify product with the uploaded image.
        retail_price_cents: if provided, overrides all variant prices with this value (in cents).
        """
        bp = BLUEPRINTS.get(product_type, BLUEPRINTS["T-Shirt"])
        base_variants = DEFAULT_VARIANTS.get(product_type, DEFAULT_VARIANTS["T-Shirt"])
        # Apply retail price override if provided
        if retail_price_cents is not None:
            variants = [{**v, "price": retail_price_cents} for v in base_variants]
        else:
            variants = base_variants

        # Print areas differ by product type
        if product_type == "Mug":
            print_areas = [{"variant_ids": [v["id"] for v in variants],
                            "placeholders": [{"position": "front", "images": [
                                {"id": image_id, "x": 0.5, "y": 0.5, "scale": 1, "angle": 0}
                            ]}]}]
        else:
            print_areas = [{"variant_ids": [v["id"] for v in variants],
                            "placeholders": [{"position": "front", "images": [
                                {"id": image_id, "x": 0.5, "y": 0.5, "scale": 1, "angle": 0}
                            ]}]}]

        product = {
            "title": title,
            "description": description,
            "blueprint_id": bp["blueprint_id"],
            "print_provider_id": bp["print_provider_id"],
            "variants": variants,
            "print_areas": print_areas,
        }
        if tags:
            product["tags"] = tags

        return self._post(f"/shops/{self.shop_id}/products.json", product)

    def publish_product(self, product_id: str) -> dict:
        """Push product live (visible on connected sales channel)."""
        return self._post(f"/shops/{self.shop_id}/products/{product_id}/publish.json", {
            "title": True, "description": True, "images": True,
            "variants": True, "tags": True,
        })

    def get_products(self, limit: int = 20) -> dict:
        return self._get(f"/shops/{self.shop_id}/products.json?limit={limit}")

    def update_product(self, product_id: str, title: str = None,
                       description: str = None, tags: list = None) -> dict:
        """Update a Printify product's title, description, or tags."""
        body = {}
        if title is not None:       body["title"] = title
        if description is not None: body["description"] = description
        if tags is not None:        body["tags"] = tags
        r = httpx.put(
            f"{PRINTIFY_API}/shops/{self.shop_id}/products/{product_id}.json",
            headers=self.headers, json=body, timeout=30
        )
        if not r.is_success:
            try:    detail = r.json()
            except: detail = r.text[:400]
            raise Exception(f"Printify update HTTP {r.status_code}: {detail}")
        return r.json()

    def delete_product(self, product_id: str) -> dict:
        """Archive/delete a Printify product."""
        r = httpx.delete(
            f"{PRINTIFY_API}/shops/{self.shop_id}/products/{product_id}.json",
            headers=self.headers, timeout=30
        )
        if not r.is_success:
            try:    detail = r.json()
            except: detail = r.text[:400]
            raise Exception(f"Printify delete HTTP {r.status_code}: {detail}")
        return r.json() if r.content else {"ok": True}

    def get_uploaded_images(self, limit: int = 50, page: int = 1) -> dict:
        """List images uploaded to Printify media library."""
        return self._get(f"/uploads.json?limit={limit}&page={page}")

    def get_shop_stats(self) -> dict:
        """Return basic product + order counts."""
        products = self.get_products(limit=50)
        items    = products if isinstance(products, list) else products.get("data", [])
        live     = [p for p in items if p.get("visible", False)]
        # Try fetching orders (may not be available on all plans)
        try:
            orders_r = self._get(f"/shops/{self.shop_id}/orders.json?limit=10")
            orders   = orders_r if isinstance(orders_r, list) else orders_r.get("data", [])
            pending  = [o for o in orders if o.get("status") in ("pending", "in-production")]
            fulfilled = [o for o in orders if o.get("status") == "fulfilled"]
        except Exception:
            orders = pending = fulfilled = []
        return {
            "total_products":  len(items),
            "live_products":   len(live),
            "draft_products":  len(items) - len(live),
            "recent_orders":   len(orders),
            "pending_orders":  len(pending),
            "fulfilled_orders": len(fulfilled),
        }
