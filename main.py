"""
@Project: Trimr
@File: main.py
@Description: Service entry file
"""
import asyncio

import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.proxy import router as proxy_router
from app.api.dashboard import router as dashboard_router
from app.agent.connector import connector_router, init_connector, start_polling
from app.auth.client import ensure_authenticated
from app.config import settings
from app.db.models import init_db
from app.utils.logger import setup_logger, get_logger
from app.utils.i18n import load_language_preference, set_language, t

logger = setup_logger(debug=settings.DEBUG)


def _select_language():
    """Prompt user to select language on first run, or load saved preference."""
    load_language_preference()

    lang_file = __import__("pathlib").Path.home() / ".trimr" / "language.json"
    if lang_file.exists():
        return

    print("\n" + "=" * 40)
    print("  Select language / 选择语言")
    print("=" * 40)
    print("  1. English")
    print("  2. 中文")
    print("=" * 40)

    choice = input("  Enter 1 or 2 / 输入 1 或 2: ").strip()

    if choice == "2":
        set_language("zh")
    else:
        set_language("en")


def _print_banner():
    RED = '\033[0;31m'
    NC = '\033[0m'
    print(f"""
{RED}  ████████╗██████╗ ██╗███╗   ███╗██████╗
  ╚══██╔══╝██╔══██╗██║████╗ ████║██╔══██╗
     ██║   ██████╔╝██║██╔████╔██║██████╔╝
     ██║   ██╔══██╗██║██║╚██╔╝██║██╔══██╗
     ██║   ██║  ██║██║██║ ╚═╝ ██║██║  ██║
     ╚═╝   ╚═╝  ╚═╝╚═╝╚═╝     ╚═╝╚═╝  ╚═╝{NC}
     AI Agent Cost Control Engine  v0.1.0
""")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _print_banner()
    _select_language()
    init_db()
    init_connector()
    await ensure_authenticated()
    task = asyncio.create_task(start_polling())
    logger.info(t("startup.started"))
    yield

    task.cancel()

app = FastAPI(
    title="Trimr",
    description="AI Agent Cost Control Engine — Optimize tokens, preserve intelligence.",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API Routes
app.include_router(proxy_router, prefix="/v1")
app.include_router(dashboard_router, prefix="/dashboard")
app.include_router(connector_router, prefix="/connector")

@app.get("/health")
async def health_check():
    from app.auth.client import is_authenticated, load_credentials
    from app.core.dedup import dedup_engine
    from app.core.optimizer import _summary_cache
    from app.agent.strategy import detect_installed_agents

    creds = load_credentials()

    return {
        "status": "ok",
        "version": "0.1.0",
        "service": "Trimr",
        "authenticated": is_authenticated(),
        "device_name": creds.get("device_name") if creds else None,
        "agents": detect_installed_agents(),
        "cache": {
            "dedup_size": dedup_engine.cache_size(),
            "summary_size": len(_summary_cache),
        },
    }

@app.get("/")
async def root():
    return {
        "service": "Trimr",
        "slogan": "Trimr your Agent's tokens, not its intelligence.",
        "docs": "/docs",
        "health": "/health",
    }

if __name__ == "__main__":
    log_level = "debug" if settings.DEBUG else "warning"
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
        log_level=log_level,
    )
