"""
@Project: Trimr
@File: app/utils/i18n.py
@Description: User-facing message strings (English only)
"""

MESSAGES = {
    # ── Auth ──────────────────────────────────────
    "auth.welcome_title":       "  Welcome to Trimr",
    "auth.login_prompt":        "  Please log in to your Trimr account",
    "auth.email":               "[Auth] Email: ",
    "auth.password":            "[Auth] Password: ",
    "auth.logging_in":          "[Auth] Logging in...",
    "auth.logged_in_as":        "[Auth] Logged in as {name}",
    "auth.registering_device":  "[Auth] Registering device...",
    "auth.device_registered":   "[Auth] Device registered: {name}",
    "auth.completed":           "[Auth] Authentication completed. Starting service...",
    "auth.already_authenticated": "[Auth] Already authenticated as {name}",
    "auth.cloud_not_enabled":   "[Auth] Cloud sync is not configured. Running in local-only mode.",
    "auth.device_token_title":  "  Your Device Token (copy it to Trimr Cloud):",
    "auth.device_token_hint":   "  Please save this token. You will need it for cloud configuration.",
    "auth.register_failed":     "[Auth] Error: Failed to register device",
    "auth.invalid_credentials": "[Auth] Invalid email or password. {remaining} attempts remaining",
    "auth.too_many_failures":   "[Auth] Too many failed attempts. Please check your credentials and restart.",

    # ── Data key ──────────────────────────────────
    "datakey.title":            "  Set a data password",
    "datakey.desc1":            "  Used to encrypt your activity logs (Agent operation records)",
    "datakey.desc2":            "  This password is stored only on your device. Please remember it",
    "datakey.desc3":            "  If you forget the password, historical activity logs cannot be recovered",
    "datakey.set_prompt":       "\nPlease set a data password (at least 8 characters): ",
    "datakey.confirm_prompt":   "Confirm again: ",
    "datakey.too_short":        "Password must be at least 8 characters. Please try again.",
    "datakey.mismatch":         "The two inputs do not match. Please try again.",
    "datakey.success":          "Data password set successfully",

    # ── Startup ───────────────────────────────────
    "startup.started":          "[Main] Trimr started",
}


def t(key: str, **kwargs) -> str:
    text = MESSAGES.get(key, key)
    if kwargs:
        text = text.format(**kwargs)
    return text
