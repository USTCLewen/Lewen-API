"""Standalone admin panel/API server.

Run this process separately from `main.py` when you want to update or restart
the admin panel without interrupting the Paper Search API service.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

import uvicorn
from fastapi import FastAPI

import config
from api.admin import router as admin_router

LOG_DIR = config.PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

_log_handler = RotatingFileHandler(
    LOG_DIR / "admin.log",
    maxBytes=20 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8",
)
_log_handler.setFormatter(
    logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
)
logging.basicConfig(level=logging.INFO, handlers=[_log_handler, logging.StreamHandler()])
logging.getLogger("uvicorn.access").handlers = [_log_handler, logging.StreamHandler()]
logging.getLogger("uvicorn.error").handlers = [_log_handler, logging.StreamHandler()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    from auth.database import init_auth_db

    init_auth_db()
    app.state.target_api_base_url = config.ADMIN_TARGET_API_BASE_URL.rstrip("/")
    panel_host = "localhost" if config.ADMIN_HOST in ("0.0.0.0", "::") else config.ADMIN_HOST
    panel_url = f"http://{panel_host}:{config.ADMIN_PORT}/admin/panel"
    print("✅ Admin auth.db ready.")
    print(f"✅ Admin target Paper API: {app.state.target_api_base_url}")
    print(f"✅ Admin panel: {panel_url}")
    yield
    print("👋 Admin server shutting down.")


app = FastAPI(
    title="Paper Search Admin",
    description="Standalone admin panel and operations API.",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(admin_router)


if __name__ == "__main__":
    uvicorn.run(
        "admin_main:app",
        host=config.ADMIN_HOST,
        port=config.ADMIN_PORT,
        workers=1,
        reload=False,
        timeout_keep_alive=60,
    )
