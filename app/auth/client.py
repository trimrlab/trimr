"""
@Project: Trimr
@File: app/auth/client.py
@Description: Authentication client
"""

import json
from pathlib import Path
from typing import Optional

from app.config import settings
from app.utils.platform import get_device_name, get_platform_short
from app.utils.logger import get_logger
from app.utils.i18n import t
import httpx

logger = get_logger()

TRIMR_DIR = Path.home() / ".trimr"
CREDENTIALS_FILE = TRIMR_DIR / "credentials.json"

def load_credentials() -> Optional[dict]:
    if not CREDENTIALS_FILE.exists():
        return None

    try:
        return json.loads(CREDENTIALS_FILE.read_text())
    except Exception:
        return None

def save_credentials(data: dict):
    TRIMR_DIR.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False)
    )

def is_authenticated() -> bool:
    creds = load_credentials()
    if not creds:
        return False

    return bool(creds.get("device_token"))

async def login(phone: str, password: str) -> Optional[dict]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{settings.CLOUD_API_URL}/api/auth/login/password",
                json={"phone": phone, "password": password},
            )

            if resp.status_code != 200:
                logger.error(f"[Auth] Error: {resp.json().get('message', 'Unknown')}")
                return None

            return (resp.json()).get("data", {})

    except Exception as e:
        logger.error(f"[Auth] Error: {e}")
        return None

async def register_device(jwt_token: str) -> Optional[dict]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{settings.CLOUD_API_URL}/api/devices/register",
                json={
                    "device_name": get_device_name(),
                    "platform": get_platform_short(),
                    "trimr_version": "0.0.1",
                },
                headers={"Authorization": f"Bearer {jwt_token}"},
            )
            if resp.status_code != 200:
                logger.error(f"[Auth] Device register failed: status={resp.status_code} body={resp.text}")
                return None

            return (resp.json()).get("data", {})

    except Exception as e:
        logger.error(f"[Auth] Error: {e}")
        return None

def _setup_data_key() -> str:
    import hashlib
    import os
    import base64

    print("\n" + "=" * 50)
    print(f"  {t('datakey.title')}")
    print(f"  {t('datakey.desc1')}")
    print(f"  {t('datakey.desc2')}")
    print(f"  {t('datakey.desc3')}")
    print("=" * 50)

    while True:
        password = input(t("datakey.set_prompt")).strip()
        password2 = input(t("datakey.confirm_prompt")).strip()

        if len(password) < 8:
            print(t("datakey.too_short"))
            continue

        if password != password2:
            print(t("datakey.mismatch"))
            continue

        salt = os.urandom(16)
        data_key = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt,
            100000,
            dklen=32
        )

        result = base64.b64encode(salt + data_key).decode("utf-8")
        print(t("datakey.success"))
        return result

async def ensure_authenticated() -> bool:
    if is_authenticated():
        creds = load_credentials()
        print(t("auth.already_authenticated", name=creds.get("device_name", "Unknown")))
        return True

    if not settings.CLOUD_API_URL:
        print(t("auth.cloud_not_enabled"))
        return True

    print("\n" + "=" * 50)
    print(f"  {t('auth.welcome_title')}")
    print(f"  {t('auth.login_prompt')}")
    print("=" * 50)

    for attempt in range(3):
        phone = input(t("auth.phone"))
        password = input(t("auth.password"))

        print(t("auth.logging_in"))

        result = await login(phone, password)

        if result:
            jwt_token = result.get("token")
            user = result.get("user", {})
            print(t("auth.logged_in_as", name=user.get("nickname", phone)))

            print(t("auth.registering_device"))

            device_result = await register_device(jwt_token)
            if device_result:

                data_key = _setup_data_key()
                save_credentials({
                    "jwt_token": jwt_token,
                    "device_token": device_result.get("device_token"),
                    "device_id": device_result.get("id"),
                    "device_name": device_result.get("device_name"),
                    "user_id": user.get("id"),
                    "phone": phone,
                    "data_key": data_key
                })

                print(t("auth.device_registered", name=device_result.get("device_name")))

                token = device_result.get("device_token")
                print("\n" + "=" * 50)
                print(t("auth.device_token_title"))
                print(f"\n  {token}\n")
                print(t("auth.device_token_hint"))
                print("=" * 50)

                print(t("auth.completed"))

                return True

            else:
                print(t("auth.register_failed"))
                return False

        else:
            remaining = 2 - attempt
            if remaining > 0:
                print(t("auth.invalid_credentials", remaining=remaining))

    print(t("auth.too_many_failures"))
    return False
