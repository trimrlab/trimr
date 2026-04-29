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
from app.utils.i18n import t

logger = setup_logger(debug=settings.DEBUG)


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
    init_db()
    init_connector()
    await ensure_authenticated()
    task = asyncio.create_task(start_polling())
    print(t("startup.started"))
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

def _cmd_restore(args):
    from app.agent.connector import AGENT_HANDLERS
    if not args:
        print("Usage: trimr restore <agent_slug>")
        print(f"Available agents: {', '.join(AGENT_HANDLERS.keys())}")
        return 1
    slug = args[0]
    handler = AGENT_HANDLERS.get(slug)
    if not handler:
        print(f"Unknown agent: {slug}")
        print(f"Available agents: {', '.join(AGENT_HANDLERS.keys())}")
        return 1
    success = handler.restore_original_config()
    if success:
        print(f"Restored {slug} to original config.")
        return 0
    print(f"Failed: no original config saved for {slug}.")
    print("(Trimr only saves the original on its first modification.)")
    return 1


def _cmd_status(args):
    from app.agent.connector import AGENT_HANDLERS, ORIGINAL_DIR
    print("Trimr managed agents:")
    for slug, handler in AGENT_HANDLERS.items():
        original = ORIGINAL_DIR / f"{slug}.original.json"
        config = handler.get_config_path()
        marker = "✓" if original.exists() else "—"
        print(f"  {marker} {slug}: config={config} original={'saved' if original.exists() else 'not saved'}")
    return 0


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if args:
        cmd = args[0]
        rest = args[1:]
        if cmd == "restore":
            sys.exit(_cmd_restore(rest))
        elif cmd == "status":
            sys.exit(_cmd_status(rest))
        elif cmd in ("-h", "--help", "help"):
            print("Usage:")
            print("  trimr                  Start Trimr proxy service")
            print("  trimr restore <agent>  Restore agent config to pre-Trimr original")
            print("  trimr status           Show managed agents and original-config status")
            sys.exit(0)

    log_level = "debug" if settings.DEBUG else "warning"
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
        log_level=log_level,
    )
