"""tasks routes."""
from fastapi import APIRouter, HTTPException, BackgroundTasks, Request, Form, UploadFile, File
from deps import *
from services import *

router = APIRouter()


@router.get("/api/task/{task_id}")
def poll_task(task_id: int):
    return orch.poll(task_id)

@router.delete("/api/task/{task_id}")
def cancel_task(task_id: int):
    ok = orch.cancel(task_id)
    if not ok:
        raise HTTPException(400, "Task not cancellable (not pending or not found)")
    return {"ok": True}

@router.post("/api/task/{task_id}/retry")
def retry_task(task_id: int):
    info = orch.poll(task_id)
    meta = info.get("retry_meta")
    if not meta:
        raise HTTPException(400, "No retry info for this task")
    req = EnhanceRequest(prompt=meta["prompt"])
    if meta["type"] == "enhance":
        return enhance_prompt(req)
    if meta["type"] == "research":
        return research_prompt(req)
    raise HTTPException(400, "Unknown task type")
