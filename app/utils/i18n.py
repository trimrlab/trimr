"""
@Project: Trimr
@File: app/utils/i18n.py
@Description: Internationalization support (Chinese / English)
"""

import json
from pathlib import Path

_current_lang = "en"

MESSAGES = {
    # ── Auth ──────────────────────────────────────
    "auth.welcome_title": {
        "en": "  Welcome to Trimr",
        "zh": "  欢迎使用 Trimr",
    },
    "auth.login_prompt": {
        "en": "  Please log in to your Trimr account",
        "zh": "  请登录您的 Trimr 账号",
    },
    "auth.phone": {
        "en": "[Auth] Phone: ",
        "zh": "[Auth] 手机号: ",
    },
    "auth.password": {
        "en": "[Auth] Password: ",
        "zh": "[Auth] 密码: ",
    },
    "auth.logging_in": {
        "en": "[Auth] Logging in...",
        "zh": "[Auth] 登录中...",
    },
    "auth.logged_in_as": {
        "en": "[Auth] Logged in as {name}",
        "zh": "[Auth] 已登录: {name}",
    },
    "auth.registering_device": {
        "en": "[Auth] Registering device...",
        "zh": "[Auth] 注册设备中...",
    },
    "auth.device_registered": {
        "en": "[Auth] Device registered: {name}",
        "zh": "[Auth] 设备注册成功: {name}",
    },
    "auth.completed": {
        "en": "[Auth] Authentication completed. Starting service...",
        "zh": "[Auth] 认证完成，启动服务...",
    },
    "auth.already_authenticated": {
        "en": "[Auth] Already authenticated as {name}",
        "zh": "[Auth] 已认证设备: {name}",
    },
    "auth.cloud_not_enabled": {
        "en": "[Auth] Cloud sync is not configured. Running in local-only mode.",
        "zh": "[Auth] 未配置云端同步，以本地模式运行。",
    },
    "auth.register_failed": {
        "en": "[Auth] Error: Failed to register device",
        "zh": "[Auth] 错误: 设备注册失败",
    },
    "auth.invalid_credentials": {
        "en": "[Auth] Invalid phone or password. {remaining} attempts remaining",
        "zh": "[Auth] 手机号或密码错误，还剩 {remaining} 次机会",
    },
    "auth.too_many_failures": {
        "en": "[Auth] Too many failed attempts. Please check your credentials and restart.",
        "zh": "[Auth] 登录失败次数过多，请确认账号密码后重启。",
    },

    # ── Data key ──────────────────────────────────
    "datakey.title": {
        "en": "  Set a data password",
        "zh": "  设置数据密码",
    },
    "datakey.desc1": {
        "en": "  Used to encrypt your activity logs (Agent operation records)",
        "zh": "  用于加密您的行为日志（Agent 操作记录）",
    },
    "datakey.desc2": {
        "en": "  This password is stored only on your device. Please remember it",
        "zh": "  此密码仅存储在您的设备上，请牢记",
    },
    "datakey.desc3": {
        "en": "  If you forget the password, historical activity logs cannot be recovered",
        "zh": "  如果忘记密码，历史行为日志将无法恢复",
    },
    "datakey.set_prompt": {
        "en": "\nPlease set a data password (at least 8 characters): ",
        "zh": "\n请设置数据密码（至少 8 个字符）: ",
    },
    "datakey.confirm_prompt": {
        "en": "Confirm again: ",
        "zh": "再次确认: ",
    },
    "datakey.too_short": {
        "en": "Password must be at least 8 characters. Please try again.",
        "zh": "密码至少 8 个字符，请重新输入。",
    },
    "datakey.mismatch": {
        "en": "The two inputs do not match. Please try again.",
        "zh": "两次输入不一致，请重新输入。",
    },
    "datakey.success": {
        "en": "Data password set successfully",
        "zh": "数据密码设置成功",
    },

    # ── Startup ───────────────────────────────────
    "startup.select_language": {
        "en": "Select language / 选择语言:",
        "zh": "Select language / 选择语言:",
    },
    "startup.started": {
        "en": "[Main] Trimr started",
        "zh": "[Main] Trimr 已启动",
    },
}


def set_language(lang: str):
    global _current_lang
    if lang in ("en", "zh"):
        _current_lang = lang
    _save_language_preference(lang)


def get_language() -> str:
    return _current_lang


def t(key: str, **kwargs) -> str:
    msg = MESSAGES.get(key, {})
    text = msg.get(_current_lang, msg.get("en", key))
    if kwargs:
        text = text.format(**kwargs)
    return text


def _lang_file() -> Path:
    return Path.home() / ".trimr" / "language.json"


def _save_language_preference(lang: str):
    path = _lang_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"language": lang}))


def load_language_preference():
    global _current_lang
    path = _lang_file()
    if path.exists():
        try:
            data = json.loads(path.read_text())
            lang = data.get("language", "en")
            if lang in ("en", "zh"):
                _current_lang = lang
        except Exception:
            pass
