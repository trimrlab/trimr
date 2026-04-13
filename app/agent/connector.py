"""
@Project: Trimr
@File: app/agent/connector.py
@Description: Local Connector for agent configuration management
"""

import asyncio
import json
import shutil
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter

from app.config import settings
from app.utils.platform import get_platform
from app.utils.logger import get_logger
from app.agent.strategy import (
    _get_agent_config_path,
    AGENT_CONFIG_PATHS_BY_PLATFORM,
    detect_installed_agents,
)

logger = get_logger()

TRIMR_DIR = Path.home() / ".trimr"

PENDING_COMMANDS_FILE = TRIMR_DIR / "pending_commands.json"

EXECUTED_COMMANDS_FILE = TRIMR_DIR / "executed_commands.json"

OPENCLAW_CONFIG_PATH = Path.home() / ".openclaw" / "openclaw.json"

CODEBUDDY_CONFIG_PATH = Path.home() / ".codebuddy" / "config.json"

BACKUP_DIR = TRIMR_DIR / "backups"

POLL_INTERVAL = 5

class BaseAgentHandler(ABC):
    @property
    @abstractmethod
    def agent_slug(self) -> str:
        ...

    @abstractmethod
    def get_config_path(self) -> Path:
        ...

    def read_config(self) -> Optional[dict]:
        path = self.get_config_path()
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except Exception as e:
            logger.debug(f"[{self.agent_slug}] Error reading config: {e}")
            return None

    def write_config(self, new_config: dict) -> bool:
        path = self.get_config_path()
        try:
            self._backup_config(path)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(new_config, indent=2, ensure_ascii=False))
            tmp.rename(path)
            logger.debug(f"[{self.agent_slug}] Config written to {path}")
            return True
        except Exception as e:
            logger.debug(f"[{self.agent_slug}] Error writing config: {e}")
            return False

    def _backup_config(self, path: Path) -> Optional[str]:
        if not path.exists():
            return None
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        backup_path = BACKUP_DIR / f"{self.agent_slug}_{timestamp}.json.bak"
        shutil.copy2(path, backup_path)
        logger.debug(f"[{self.agent_slug}] Backed up config to {backup_path}")
        return str(backup_path)

    def rollback_config(self) -> bool:
        backups = sorted(
            BACKUP_DIR.glob(f"{self.agent_slug}_*.json.bak"), reverse=True
        )
        if not backups:
            logger.debug(f"[{self.agent_slug}] No backups found")
            return False
        shutil.copy2(backups[0], self.get_config_path())
        logger.debug(f"[{self.agent_slug}] Rolled back to {backups[0]}")
        return True

    @abstractmethod
    def build_new_config(self, old_config: dict, payload: dict) -> dict:
        ...

    def apply(self, command: dict) -> dict:
        payload = command.get("payload", {})
        old_config = self.read_config() or {}
        new_config = self.build_new_config(old_config, payload)
        diffs = compute_diff(old_config, new_config)

        return {
            "old_config": old_config,
            "new_config": new_config,
            "diffs": diffs,
            "diff_display": format_diff_display(diffs),
        }

    def get_strategy_path(self) -> Path:
        return TRIMR_DIR / f"{self.agent_slug}_strategy.json"

    def apply_strategy(self, payload: dict) -> bool:
        try:
            strategy_path = self.get_strategy_path()
            strategy_path.parent.mkdir(parents=True, exist_ok=True)
            strategy_data = {k: v for k, v in payload.items() if k != "agent_slug"}
            strategy_path.write_text(json.dumps(strategy_data, indent=2, ensure_ascii=False))
            logger.debug(f"[{self.agent_slug}] Strategy updated: {strategy_data}")
            return True
        except Exception as e:
            logger.debug(f"[{self.agent_slug}] Error applying strategy: {e}")
            return False

class OpenClawAgentHandler(BaseAgentHandler):
    @property
    def agent_slug(self) -> str:
        return "openclaw"

    def get_config_path(self) -> Path:
        path = _get_agent_config_path("openclaw")
        if path:
            return path
        platform = get_platform()
        defaults = AGENT_CONFIG_PATHS_BY_PLATFORM.get("openclaw", {}).get(platform, [])
        return defaults[0] if defaults else Path.home() / ".openclaw" / "openclaw.json"

    def build_new_config(self, old_config: dict, payload: dict) -> dict:
        return _deep_merge(old_config, payload)

class CodeBuddyAgentHandler(BaseAgentHandler):
    @property
    def agent_slug(self) -> str:
        return "codebuddy"

    def get_config_path(self) -> Path:
        path = _get_agent_config_path("codebuddy")
        if path:
            return path
        platform = get_platform()
        defaults = AGENT_CONFIG_PATHS_BY_PLATFORM.get("codebuddy", {}).get(platform, [])
        return defaults[0] if defaults else Path.home() / ".codebuddy" / "config.json"

    def build_new_config(self, old_config: dict, payload: dict) -> dict:
        return _deep_merge(old_config, payload)

AGENT_HANDLERS: dict[str, BaseAgentHandler] = {
    "openclaw": OpenClawAgentHandler(),
    "codebuddy": CodeBuddyAgentHandler(),
}

def init_connector():
    TRIMR_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    if not PENDING_COMMANDS_FILE.exists():
        PENDING_COMMANDS_FILE.write_text(json.dumps([], indent=2))

    if not EXECUTED_COMMANDS_FILE.exists():
        EXECUTED_COMMANDS_FILE.write_text(json.dumps([], indent=2))

    installed = detect_installed_agents()
    if not installed:
        logger.debug("[Connector] No installed AI Agent detected")
    else:
        active = [slug for slug in installed if slug in AGENT_HANDLERS]
        logger.debug(f"[Connector] Registered handlers: {active}")

_pending_confirmations: dict[str, dict] = {}
_processed_command_ids: set[str] = set()

async def start_polling():
    logger.debug(f"[Connector] start polling {POLL_INTERVAL}s")

    while True:
        try:
            commands = await _fetch_from_cloud()
            for command in commands:
                await handle_command(command)
        except Exception as e:
            logger.error(f"[Connector] Error polling: {e}")

        await asyncio.sleep(POLL_INTERVAL)

async def handle_command(command: dict):
    cmd_id = command.get("id")
    cmd_type = command.get("type")
    agent_slug = command.get("agent_slug")

    if cmd_id in _pending_confirmations or cmd_id in _processed_command_ids:
        return

    if cmd_type == "update_strategy":
        slug = agent_slug or command.get("payload", {}).get("agent_slug")
        handler = AGENT_HANDLERS.get(slug)
        if not handler:
            logger.debug(f"[Connector] No handler for update_strategy agent_slug={slug}")
            await notify_cloud_confirmed(cmd_id)
            return
        success = handler.apply_strategy(command.get("payload", {}))
        if success:
            logger.debug(f"[Connector] [{slug}] Strategy applied silently")
        await notify_cloud_confirmed(cmd_id)
        return

    if cmd_type == "configure_openclaw":
        handler = AGENT_HANDLERS.get(agent_slug)

        if not handler:
            logger.debug(f"[Connector] Unknown agent: {agent_slug}")
            return

        result = handler.apply(command)
        diffs = result.get("diffs", [])

        if not diffs:
            logger.debug(f"[Connector] [{handler.agent_slug}] No changes to apply")
            await notify_cloud_confirmed(cmd_id)
            return

        logger.debug("\n" + "=" * 50)
        logger.debug(f"[{handler.agent_slug}] Configuration change preview")
        logger.debug("=" * 50)
        logger.debug(result["diff_display"])
        logger.debug("=" * 50)

        _pending_confirmations[cmd_id] = {
            "command": command,
            "result": result,
            "handler": handler,
        }
        asyncio.create_task(_terminal_confirm(cmd_id, result, handler))

async def _terminal_confirm(cmd_id: str, result: dict, handler: BaseAgentHandler):
    try:
        loop = asyncio.get_running_loop()
        answer = await loop.run_in_executor(
            None,
            lambda: input(f"[Connector] [{handler.agent_slug}] Confirm? (y/n): ")
        )

        if answer.strip().lower() == "y":
            success = handler.write_config(result["new_config"])
            if success:
                logger.info(f"[Connector] [{handler.agent_slug}] Configuration updated")
                await notify_cloud_confirmed(cmd_id)
        else:
            logger.debug(f"[Connector] [{handler.agent_slug}] Command cancelled")
            await notify_cloud_cancelled(cmd_id)

    except Exception as e:
        logger.error(f"[Connector] Error: {e}")
        await notify_cloud_cancelled(cmd_id)

    finally:
        _pending_confirmations.pop(cmd_id, None)
        _processed_command_ids.add(cmd_id)

def _load_device_token() -> Optional[str]:
    credentials_file = TRIMR_DIR / "credentials.json"
    if not credentials_file.exists():
        return None
    try:
        return json.loads(credentials_file.read_text()).get("device_token")
    except Exception:
        return None

async def _fetch_from_cloud() -> list[dict]:
    if not settings.CLOUD_API_URL:
        return []
    device_token = _load_device_token()
    if not device_token:
        return []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{settings.CLOUD_API_URL}/api/commands/pending",
                headers={"X-Device-Token": device_token},
            )
            if resp.status_code == 200:
                body = resp.json()
                return body.get("data", [])
            logger.debug(f"[Connector] Fetch error: {resp.status_code}")
            return []
    except Exception as e:
        logger.debug(f"[Connector] Fetch error: {e}")
        return []

async def notify_cloud_confirmed(command_id: str):
    logger.info(f"[Connector] Confirming command {command_id}...")
    if not settings.CLOUD_API_URL:
        logger.info(f"[Connector] Skipped: CLOUD_API_URL is empty")
        return
    device_token = _load_device_token()
    if not device_token:
        logger.info(f"[Connector] Skipped: no device token")
        return
    try:
        url = f"{settings.CLOUD_API_URL}/api/commands/{command_id}/confirm"
        logger.info(f"[Connector] POST {url}")
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                headers={"X-Device-Token": device_token},
            )
            logger.info(f"[Connector] Command {command_id} confirmed, status={resp.status_code}")
    except Exception as e:
        logger.error(f"[Connector] Error confirming: {e}")

async def notify_cloud_cancelled(command_id: str):
    if not settings.CLOUD_API_URL:
        return
    device_token = _load_device_token()
    if not device_token:
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"{settings.CLOUD_API_URL}/api/commands/{command_id}/cancel",
                headers={"X-Device-Token": device_token},
            )
            logger.info(f"[Connector] Command {command_id} cancelled")
    except Exception as e:
        logger.error(f"[Connector] Error cancelling: {e}")

def compute_diff(old_config: dict, new_config: dict) -> list[dict]:
    diffs = []
    _diff_recursive(old_config, new_config, "", diffs)
    return diffs

def _diff_recursive(old, new, path: str, diffs: list):
    if isinstance(old, dict) and isinstance(new, dict):
        for key in set(old.keys()) | set(new.keys()):
            full_path = f"{path}.{key}" if path else key
            if key not in old:
                diffs.append({"field": full_path, "action": "added", "old": None, "new": new[key]})
            elif key not in new:
                diffs.append({"field": full_path, "action": "removed", "old": old[key], "new": None})
            else:
                _diff_recursive(old[key], new[key], full_path, diffs)
    else:
        if old != new:
            diffs.append({"field": path, "action": "changed", "old": old, "new": new})

def format_diff_display(diffs: list[dict]) -> str:
    if not diffs:
        return "No changes"
    lines = []
    for d in diffs:
        if d["action"] == "changed":
            lines += [f" ~ {d['field']}", f"   old: {d['old']}", f"   new: {d['new']}"]
        elif d["action"] == "added":
            lines += [f" + {d['field']}", f"   new: {d['new']}"]
        elif d["action"] == "removed":
            lines += [f" - {d['field']}", f"   deleted: {d['old']}"]
    return "\n".join(lines)

def _deep_merge(base: dict, patch: dict) -> dict:
    result = base.copy()
    for key, value in patch.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result

def mark_command_executed(command_id: str):
    if not PENDING_COMMANDS_FILE.exists():
        return

    commands = json.loads(PENDING_COMMANDS_FILE.read_text())
    for cmd in commands:
        if cmd.get("id") == command_id:
            cmd["status"] = "executed"
            cmd["executed_at"] = datetime.now().isoformat()
    PENDING_COMMANDS_FILE.write_text(json.dumps(commands, indent=2))


# ── API Routes ──────────────────────────────────

connector_router = APIRouter()

@connector_router.get("/status")
async def connector_status():
    return {
        "status":              "running",
        "pending_confirmations": len(_pending_confirmations),
        "openclaw_config_exists": OPENCLAW_CONFIG_PATH.exists(),
        "backup_count":        len(list(BACKUP_DIR.glob("*.bak"))),
    }

@connector_router.get("/pending")
async def get_pending_confirmations():
    return {
        "pending": [
            {
                "id": cmd_id,
                "type": data["command"].get("type"),
                "agent_slug": data["handler"].agent_slug,
                "diffs": data["result"]["diffs"],
                "diff_display": data["result"]["diff_display"],
            }
            for cmd_id, data in _pending_confirmations.items()
        ]
    }

@connector_router.post("/confirm/{command_id}")
async def confirm_command(command_id: str):
    if command_id not in _pending_confirmations:
        return {"status": "error", "message": "Command not found"}

    data = _pending_confirmations[command_id]
    handler = data["handler"]
    success = handler.write_config(data["result"]["new_config"])

    if success:
        await notify_cloud_confirmed(command_id)
        del _pending_confirmations[command_id]
        return {"status": "ok"}
    return {"status": "error", "message": "Failed to write config"}

@connector_router.post("/cancel/{command_id}")
async def cancel_command(command_id: str):
    if command_id not in _pending_confirmations:
        return {"status": "error", "message": "Command not found"}

    del _pending_confirmations[command_id]
    mark_command_executed(command_id)
    return {"status": "ok"}

@connector_router.post("/rollback/{agent_slug}")
async def rollback(agent_slug: str):
    handler = AGENT_HANDLERS.get(agent_slug)
    if not handler:
        return {"status": "error", "message": f"Unknown agent: {agent_slug}"}
    success = handler.rollback_config()
    return {"status": "ok" if success else "error"}

@connector_router.get("/backups")
async def list_backups():
    backups = sorted(BACKUP_DIR.glob("*.bak"), reverse=True)
    return {
        "backups": [
            {
                "filename": b.name,
                "agent_slug": b.name.split("_")[0],
                "created_at": datetime.fromtimestamp(b.stat().st_mtime).isoformat(),
                "size": b.stat().st_size,
            }
            for b in backups
        ]
    }
