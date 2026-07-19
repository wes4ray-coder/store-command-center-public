"""AI Assistant — settings endpoints (per-category auto-approve toggles, max iters)."""
from deps import *
import assistant_tools

from ._base import router, _ensure


# ─── Assistant settings (approval toggles etc.) ──────────────────────────────
@router.get("/api/agent/settings")
def agent_settings():
    _ensure()
    return {"ok": True, "categories": assistant_tools.category_states(),
            "max_iters": int(get_setting("assistant_max_iters", 8) or 8),
            "model": get_setting("assistant_model", "") or ""}


class AgentSettingsRequest(BaseModel):
    toggles: Optional[dict] = None      # {category: bool} — per-category auto-approve
    max_iters: Optional[int] = None


@router.post("/api/agent/settings")
def agent_settings_save(req: AgentSettingsRequest):
    _ensure()
    conn = get_conn()
    if req.toggles:
        valid = {c["key"] for c in assistant_tools.CATEGORIES if not c.get("locked")}
        for cat, on in req.toggles.items():
            if cat in valid:
                conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
                             (f"assistant_auto_{cat}", "1" if on else "0"))
    if req.max_iters is not None:
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
                     ("assistant_max_iters", str(max(1, min(int(req.max_iters), 25)))))
    conn.commit()
    conn.close()
    return {"ok": True, "categories": assistant_tools.category_states()}
