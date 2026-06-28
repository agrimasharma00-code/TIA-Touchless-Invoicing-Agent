from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from main import app as api_app

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIST = BASE_DIR / "tia-frontend" / "dist"
FRONTEND_INDEX = FRONTEND_DIST / "index.html"

app = FastAPI(title="TIA - Touchless Invoice Agent")
app.mount("/api", api_app)

if FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/")
    def index():
        return FileResponse(FRONTEND_INDEX)

    @app.get("/{path_name:path}")
    def spa_fallback(path_name: str):
        if path_name.startswith("api"):
            raise HTTPException(status_code=404, detail="Not found")

        candidate = FRONTEND_DIST / path_name
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_INDEX)
else:
    @app.get("/")
    def index():
        return {
            "status": "ok",
            "message": "TIA backend is running. Build tia-frontend first to serve the web app here.",
            "api": "/api",
        }
