"""
@Project: Trimr
@File: app/db/sync.py
@Description: Cloud synchronization client
"""

import json
import base64
from datetime import datetime
from pathlib import Path

import httpx
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.config import settings
from app.db.models import engine
from app.auth.client import load_credentials, TRIMR_DIR
from app.utils.logger import get_logger

logger = get_logger()

SYNC_STATE_FILE = TRIMR_DIR / "sync_state.json"

def load_sync_state() -> dict:
    if not SYNC_STATE_FILE.exists():
        return {
            "last_request_id": None,
            "last_action_log_id": None,
            "last_synced_at": None,
        }
    try:
        return json.loads(SYNC_STATE_FILE.read_text())
    except Exception:
        return {
            "last_request_id": None,
            "last_action_log_id": None,
            "last_synced_at": None,
        }

def save_sync_state(data: dict):
    TRIMR_DIR.mkdir(parents=True, exist_ok=True)
    SYNC_STATE_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False)
    )

    logger.debug(f"[Sync] Saved sync state to {SYNC_STATE_FILE}]")

def read_new_requests(last_id=None, limit: int = 500) -> list[dict]:
    with Session(engine) as session:
        if last_id:
            result = session.execute(
                text("""
                    SELECT id, timestamp, model, provider,
                           input_tokens_original, input_tokens_actual,
                           output_tokens, cost_original, cost_actual,
                           cost_saved, strategies_used, strategy_type, cache_hit,
                           compression_triggered, is_streaming, latency_ms, error
                    FROM requests
                    WHERE rowid > (SELECT rowid FROM requests WHERE id = :last_id)
                    ORDER BY rowid ASC LIMIT :limit
                """),
                {"last_id": last_id, "limit": limit}
            )
        else:
            result = session.execute(
                text("""
                    SELECT id, timestamp, model, provider,
                           input_tokens_original, input_tokens_actual,
                           output_tokens, cost_original, cost_actual,
                           cost_saved, strategies_used, strategy_type, cache_hit,
                           compression_triggered, is_streaming, latency_ms, error
                    FROM requests
                    ORDER BY rowid ASC LIMIT :limit
                """),
                {"limit": limit}
            )
        rows = result.fetchall()
        cols = result.keys()
        return [dict(zip(cols, row)) for row in rows]

def read_new_action_logs(last_id=None, limit: int = 500) -> list[dict]:
    with Session(engine) as session:
        if last_id:
            result = session.execute(
                text("""
                    SELECT id, request_id, timestamp, action_type, summary
                    FROM action_logs
                    WHERE rowid > (SELECT rowid FROM action_logs WHERE id = :last_id)
                    ORDER BY rowid ASC LIMIT :limit
                """),
                {"last_id": last_id, "limit": limit}
            )
        else:
            result = session.execute(
                text("""
                    SELECT id, request_id, timestamp, action_type, summary
                    FROM action_logs
                    ORDER BY rowid ASC LIMIT :limit
                """),
                {"limit": limit}
            )
        rows = result.fetchall()
        cols = result.keys()
        return [dict(zip(cols, row)) for row in rows]

def encrypt_action_logs(logs: list[dict], data_key_b64: str) -> str:
        from app.auth.crypto import encrypt

        raw = base64.b64decode(data_key_b64)
        data_key = raw[16:].hex()

        return encrypt(
            {"logs": logs, "exported_at": datetime.utcnow().isoformat()},
            data_key
        )

async def sync_to_cloud() -> dict:
    creds = load_credentials()
    if not creds:
        return {"status": "error", "message": "Not authenticated"}

    device_token = creds.get("device_token")
    device_id = creds.get("device_id")
    data_key = creds.get("data_key")

    if not device_token:
        return {"status": "error", "message": "Not authenticated"}

    if not settings.CLOUD_API_URL:
        return {"status": "error", "message": "Cloud is not enabled"}

    state = load_sync_state()
    synced_count = 0

    requests = read_new_requests(state.get("last_request_id"))
    if requests:
        logger.debug(f"[Sync] Syncing {len(requests)} requests...")

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{settings.CLOUD_API_URL}/api/sync/stats",
                    json={
                        "records": requests,
                        "device_id": device_id,
                    },
                    headers={"X-Device-Token": device_token}
                )
                if resp.status_code == 200:
                    state["last_request_id"] = requests[-1]["id"]
                    synced_count += len(requests)
                    logger.debug(f"[Sync] Synced {len(requests)} requests")

                else:
                    logger.error(f"[Sync] Error: {resp.json().get('detail', 'Unknown')}")

        except Exception as e:
            logger.error(f"[Sync] Error: {e}")

    action_logs = read_new_action_logs(state.get("last_action_log_id"))
    if action_logs and data_key:
        logger.debug(f"[Sync] Syncing {len(action_logs)} action logs...")

        try:
            encrypted = encrypt_action_logs(action_logs, data_key)
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{settings.CLOUD_API_URL}/api/sync/action_log",
                    json={
                        "encrypted_data": encrypted,
                        "records_count": len(action_logs),
                        "device_id": device_id,
                    },
                    headers={"X-Device-Token": device_token},
                )
                if resp.status_code == 200:
                    state["last_action_log_id"] = action_logs[-1]["id"]
                    synced_count += len(action_logs)
                    logger.debug(f"[Sync] Activity logs synchronized successfully")
                else:
                    logger.debug(f"[Sync] Activity log synchronization failed: {resp.status_code}")
        except Exception as e:
            logger.error(f"[Sync] Error occurred while synchronizing activity logs: {e}")

    if synced_count > 0:
        state["last_synced_at"] = datetime.utcnow().isoformat()
        save_sync_state(state)

    if synced_count == 0 and not requests and not action_logs:
        return {"success": True, "message": "No new data to synchronize", "records_count": 0}

    return {
        "success": True,
        "message": "Synchronization completed",
        "records_count": synced_count,
    }
