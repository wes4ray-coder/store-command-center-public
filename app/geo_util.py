"""Geo helpers (haversine distance + Nominatim geocode).
Split out of services.py; re-exported by it (from geo_util import *)."""
from deps import *


def haversine_miles(lat1, lon1, lat2, lon2):
    R = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return R * 2 * math.asin(math.sqrt(a))

async def geocode(address: str) -> tuple[float, float] | None:
    """Free geocode via Nominatim."""
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://nominatim.openstreetmap.org/search",
                params={"q": address, "format": "json", "limit": 1},
                headers={"User-Agent": "StoreCC-ResellBot/1.0"})
            data = r.json()
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        pass
    return None


# Export everything (incl. single-underscore helpers used across modules).
__all__ = [n for n in dir() if not n.startswith('__')]
