"""FastAPI application for the Lumina AI video generator."""
from __future__ import annotations

import base64
import io
import logging
import os
from pathlib import Path

import qrcode
from fastapi import FastAPI, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .config import settings
from .task_manager import (
    S_EXPIRED,
    S_FAILED,
    S_SUCCEEDED,
    task_manager,
)
from .video_client import (
    DEFAULT_DURATION,
    DEFAULT_RATIO,
    DEFAULT_RESOLUTION,
    VALID_GENDERS,
)

# Ensure our app loggers (e.g. the video model's full HTTP request/response
# dumps in aiday.video) reach stdout/server.log at INFO even under uvicorn,
# whose default root handler is WARNING.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("aiday").setLevel(logging.INFO)

PKG_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PKG_DIR.parents[1]
STATIC_DIR = PROJECT_ROOT / "app" / "static"
ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}

app = FastAPI(title="Lumina · Dreamina Seedance 2.5")


# ---- optional cloud access password -----------------------------------------
@app.middleware("http")
async def access_gate(request: Request, call_next):
    pwd = settings.ACCESS_PASSWORD.strip()
    if pwd:
        # Allow the auth endpoints & static assets to load; gate everything else.
        path = request.url.path
        open_paths = ("/api/auth", "/health")
        if not (path in open_paths):
            token = request.cookies.get("access_token") or request.headers.get("x-access-token")
            if token != pwd:
                if path.startswith("/api/"):
                    return JSONResponse({"detail": "unauthorized"}, status_code=401)
                # else fall through to serve the page; frontend prompts for password
    return await call_next(request)


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/config")
def api_config() -> dict:
    return {"require_password": bool(settings.ACCESS_PASSWORD.strip())}


@app.post("/api/auth")
def api_auth(password: str = Form(...)) -> JSONResponse:
    pwd = settings.ACCESS_PASSWORD.strip()
    if not pwd or password == pwd:
        resp = JSONResponse({"ok": True})
        resp.set_cookie("access_token", pwd, httponly=True, samesite="lax")
        return resp
    raise HTTPException(status_code=401, detail="wrong password")


@app.post("/api/task")
def create_task() -> dict:
    state = task_manager.create()
    return {"task_id": state["task_id"], "status": state["status"]}


@app.post("/api/task/{task_id}/generate")
async def generate(
    task_id: str,
    gender: str = Form(...),
    ratio: str = Form(DEFAULT_RATIO),
    duration: int = Form(DEFAULT_DURATION),
    resolution: str = Form(DEFAULT_RESOLUTION),
    image: UploadFile = File(...),
) -> dict:
    if gender not in VALID_GENDERS:
        raise HTTPException(status_code=400, detail="gender must be male or female")
    ext = os.path.splitext(image.filename or "")[1].lower()
    if ext not in ALLOWED_IMAGE_EXT:
        raise HTTPException(status_code=400, detail=f"unsupported image type {ext}")
    data = await image.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty image")
    try:
        # submit() does synchronous image normalization + TOS upload; run it in
        # a threadpool so the event loop is never blocked under concurrency
        # (prevents gateway timeouts / lock-ups when many windows submit at once).
        state = await run_in_threadpool(
            task_manager.submit,
            task_id,
            data,
            ext,
            ratio,
            int(duration),
            resolution,
            gender,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"task_id": task_id, "status": state["status"]}


@app.get("/api/task/{task_id}")
def get_task(task_id: str) -> dict:
    state = task_manager.load(task_id)
    if state is None:
        raise HTTPException(status_code=404, detail="task not found")
    # Self-heal: if the task stalled because its owning instance was recycled,
    # any polling instance transparently resumes it (lease-guarded).
    task_manager.maybe_resume(state)
    return {
        "task_id": state["task_id"],
        "status": state["status"],
        "ratio": state.get("ratio"),
        "duration": state.get("duration"),
        "resolution": state.get("resolution"),
        "gender": state.get("gender"),
        "video_url": state.get("video_url"),
        "attempts": state.get("attempts"),
        "error": state.get("error"),
        "created_at": state.get("created_at"),
    }


@app.get("/api/qrcode")
def qrcode_png(url: str) -> JSONResponse:
    """Return a data-URI PNG QR code for the given URL."""
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return JSONResponse({"data_uri": f"data:image/png;base64,{b64}"})


# Serve SPA / task page. Static mount last so API routes take priority.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
