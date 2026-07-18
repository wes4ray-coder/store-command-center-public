"""Cults3D integration — GraphQL API (username + generated API key, HTTP Basic auth).

Docs: https://cults3d.com/en/api  — generate an API key in your Cults3D account settings
(works even if you sign in with Google), then Test Connection here.
"""
from fastapi import APIRouter, HTTPException
from deps import *
from cults import cults_query, CultsError

router = APIRouter()


def _cults_query(query: str, variables: dict = None) -> dict:
    """Router wrapper — translate CultsError into an HTTP error for the UI."""
    try:
        return cults_query(query, variables)
    except CultsError as e:
        raise HTTPException(getattr(e, "status", 502), str(e))


@router.post("/api/cults3d/test")
def cults3d_test():
    """Verify the saved credentials by fetching the authenticated user."""
    data = _cults_query("{ me { nick } }")
    me = data.get("me") or {}
    return {"ok": True, "nick": me.get("nick"), "raw": data}


@router.get("/api/cults3d/creations")
def cults3d_creations(limit: int = 100):
    """List the authenticated user's own creations (best-effort — surfaces schema errors).

    Fetch a high limit so `hidden_count` reflects only Cults3D's silent adult-item
    exclusion (total vs. returned), not simple pagination truncation."""
    q = """
    query($limit: Int) {
      me {
        nick
        creationsCount
        creations(limit: $limit) {
          name
          url
          price { cents currency }
          illustrationImageUrl
          downloadsCount
        }
      }
    }"""
    data = _cults_query(q, {"limit": limit})
    me = data.get("me") or {}
    creations = me.get("creations") or []
    total = me.get("creationsCount")
    # Cults3D's `me.creations` API silently excludes mature/adult items (no include-adult
    # param exists), so surface the gap: total vs. returned = your hidden NSFW listings.
    hidden = (total - len(creations)) if isinstance(total, int) and total > len(creations) else 0
    return {"nick": me.get("nick"), "creations": creations,
            "total_count": total, "hidden_count": hidden}
