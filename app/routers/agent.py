"""AI Assistant routes.

The assistant runs through the Store's own orchestrator + LM Studio, which BORROWS
whatever model is already loaded (e.g. your OpenClaw model) instead of forcing a
specific one. This makes it reliable regardless of OpenClaw's agent_store config or
which model happens to be loaded.

(The full OpenClaw agent_store — with web/browser/memory tools — can still be driven
from the CLI; it just needs a capable model in ~/.openclaw/openclaw.json. See BOOK.md.)
"""
import time
from fastapi import APIRouter, HTTPException
from deps import *
from services import *

router = APIRouter()

_ASSISTANT_SYSTEM = (
    "You are agent_store, the built-in assistant for a self-hosted store dashboard that "
    "handles print-on-demand (Printify/Etsy), local resale, AI image/video generation, a "
    "knowledge library, and Pi-hole network security. Be concise, practical, and friendly. "
    "Answer the user's question directly. If they ask you to perform an action you can't do "
    "from chat, explain which tab/button in the dashboard does it. You also hold a JellyCoin "
    "(JLY) wallet named 'assistant' — the store's own GPU-mined token — and may tip users or "
    "Company agents small JLY amounts via POST /api/jelly/tip (Crypto → JellyCoin tab)."
)


class AgentChatRequest(BaseModel):
    message: str
    session_key: Optional[str] = "store-dashboard"


@router.post("/api/agent/chat")
def agent_chat(req: AgentChatRequest):
    """Answer via the local model (borrowed through the orchestrator)."""
    msg = (req.message or "").strip()
    if not msg:
        raise HTTPException(400, "message required")

    def _work():
        return {"reply": _call_lmstudio(get_prompt('assistant'), msg, max_tokens=1500)}

    tid = orch.submit_llm(_work, desc=f"Assistant: {msg[:40]}", priority=0, task="assistant")   # user waiting on chat
    # Chat is interactive — wait for the queued job to finish (big reasoning models are slow).
    for _ in range(180):          # up to ~6 min
        t = orch.poll(tid)
        if t["status"] == "done":
            reply = (t.get("result") or {}).get("reply", "").strip()
            return {"ok": True, "reply": reply or "(the model returned an empty reply)"}
        if t["status"] == "error":
            raise HTTPException(502, f"Assistant error: {t.get('error')}")
        if t["status"] == "cancelled":
            raise HTTPException(499, "Cancelled")
        time.sleep(2)
    raise HTTPException(504, "Assistant timed out — the model may be busy or very slow.")
