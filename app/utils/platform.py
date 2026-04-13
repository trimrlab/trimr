"""
@Project: Trimr
@File: app/utils/platform.py
@Description: Cross-platform utility functions
"""

import sys
import platform
import socket


def get_platform() -> str:
    if sys.platform == "win32":
        return "windows"
    elif sys.platform == "darwin":
        return "macos"
    else:
        return "linux"


def get_platform_short() -> str:
    system = platform.system().lower()
    if system == "darwin":
        return "mac"
    elif system == "windows":
        return "windows"
    elif system == "linux":
        return "linux"
    return system


def get_device_name() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "Unknown Device"
