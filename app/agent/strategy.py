"""
@Project: Trimr
@File: app/agent/strategy.py
@Description: Agent strategy and configuration loader
"""

import json
import os
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from app.utils.platform import get_platform
from app.utils.logger import get_logger

logger = get_logger()

TRIMR_DIR = Path.home() / ".trimr"

DEFAULT_STRATEGY = {
    "type":                  "balance",
    "compression_threshold": 2000,
    "window_size":           3,
    "compression_ratio":     70,
    "dedup_enabled":         True,
    "dedup_ttl":             3600,
}

PROVIDER_BASE_URLS = {
    # Major providers
    "openai":           "https://api.openai.com/v1",
    "anthropic":        "https://api.anthropic.com/v1",
    "gemini":           "https://generativelanguage.googleapis.com/v1beta/openai",
    "google":           "https://generativelanguage.googleapis.com/v1beta/openai",
    "google-gemini-cli":"https://generativelanguage.googleapis.com/v1beta/openai",
    "deepseek":         "https://api.deepseek.com/v1",

    # OpenAI compatible
    "openai-codex":     "https://api.openai.com/v1",

    # Aggregators
    "openrouter":       "https://openrouter.ai/api/v1",

    # Chinese providers
    "moonshot":         "https://api.moonshot.cn/v1",
    "kimi":             "https://api.moonshot.cn/v1",
    "qwen":             "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "qianfan":          "https://qianfan.baidubce.com/v2",
    "minimax":          "https://api.minimax.chat/v1",
    "zai":              "https://open.bigmodel.cn/api/paas/v4",
    "stepfun":          "https://api.stepfun.com/v1",
    "volcengine":       "https://ark.cn-beijing.volces.com/api/v3",
    "byteplus":         "https://ark.ap-southeast.bytepluses.com/api/v3",
    "xiaomi":           "https://api.xiaomi.com/v1",

    # International providers
    "mistral":          "https://api.mistral.ai/v1",
    "xai":              "https://api.x.ai/v1",
    "groq":             "https://api.groq.com/openai/v1",
    "cerebras":         "https://api.cerebras.ai/v1",
    "together":         "https://api.together.xyz/v1",
    "nvidia":           "https://integrate.api.nvidia.com/v1",
    "venice":           "https://api.venice.ai/api/v1",
    "huggingface":      "https://api-inference.huggingface.co/v1",
}

def _xdg_config_home() -> Path:
    """XDG_CONFIG_HOME, defaults to ~/.config on Linux"""
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))

def _localappdata() -> Path:
    """Windows %LOCALAPPDATA%, defaults to ~/AppData/Local"""
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))

def _appdata() -> Path:
    """Windows %APPDATA%, defaults to ~/AppData/Roaming"""
    return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))

AGENT_CONFIG_PATHS_BY_PLATFORM: dict[str, dict[str, list[Path]]] = {
    "openclaw": {
        "macos": [
            Path.home() / ".openclaw" / "openclaw.json",
            Path.home() / "Library" / "Application Support" / "OpenClaw" / "openclaw.json",
        ],
        "linux": [
            Path.home() / ".openclaw" / "openclaw.json",
            _xdg_config_home() / "openclaw" / "openclaw.json",
        ],
        "windows": [
            _appdata() / "OpenClaw" / "openclaw.json",
            _localappdata() / "OpenClaw" / "openclaw.json",
            Path.home() / ".openclaw" / "openclaw.json",
        ],
    },
    "codebuddy": {
        "macos": [
            Path.home() / ".codebuddy" / "config.json",
            Path.home() / "Library" / "Application Support" / "CodeBuddy" / "config.json",
            Path("/Applications/CodeBuddy.app") / "Contents" / "Resources" / "config.json",
        ],
        "linux": [
            Path.home() / ".codebuddy" / "config.json",
            _xdg_config_home() / "codebuddy" / "config.json",
        ],
        "windows": [
            _appdata() / "CodeBuddy" / "config.json",
            _localappdata() / "CodeBuddy" / "config.json",
            Path.home() / ".codebuddy" / "config.json",
        ],
    },
}

@dataclass
class StrategyConfig:
    type:                  str
    compression_threshold: int
    window_size:           int
    compression_ratio:     int
    dedup_enabled:         bool
    dedup_ttl:             int

@dataclass
class AgentConfig:
    api_key:      Optional[str]
    provider_slug: Optional[str]
    base_url:     Optional[str]
    model:        Optional[str]
    installed: bool = False
    config_path: Optional[Path] = None

def _get_agent_config_path(agent_slug: str) -> Optional[Path]:
    # Step 1: check env override
    env_key = f"TRIMR_{agent_slug.upper()}_CONFIG"
    env_val = os.environ.get(env_key)
    if env_val:
        custom_path = Path(env_val)
        if custom_path.exists():
            logger.debug(f"[AgentConfig] {agent_slug} using custom path: {custom_path}")
            return custom_path
        else:
            logger.debug(f"[AgentConfig] env {env_key} path not found: {env_val}")

    # Step 2: scan platform-specific config paths
    # Config file exists = agent is installed (no executable check needed)
    platform = get_platform()
    paths = AGENT_CONFIG_PATHS_BY_PLATFORM.get(agent_slug, {}).get(platform, [])

    for path in paths:
        if path.exists():
            return path

    return None

def detect_installed_agents() -> list[str]:
    installed = []
    for slug in AGENT_CONFIG_PATHS_BY_PLATFORM.keys():
        config_path = _get_agent_config_path(slug)
        if config_path:
            logger.debug(f"[Connector] Detected installed Agent: {slug} -> {config_path}")
            installed.append(slug)
    if not installed:
        logger.debug("[Connector] No installed AI Agent detected")
    return installed

def is_agent_installed(agent_slug: str) -> bool:
    return _get_agent_config_path(agent_slug) is not None

def load_strategy(agent_slug: str = "openclaw") -> StrategyConfig:
    strategy_path = TRIMR_DIR / f"{agent_slug}_strategy.json"

    if strategy_path.exists():
        try:
            data = json.loads(strategy_path.read_text())
            return StrategyConfig(
                type=data.get("type", DEFAULT_STRATEGY["type"]),
                compression_threshold=data.get("compression_threshold", DEFAULT_STRATEGY["compression_threshold"]),
                window_size=data.get("window_size", DEFAULT_STRATEGY["window_size"]),
                compression_ratio=data.get("compression_ratio", DEFAULT_STRATEGY["compression_ratio"]),
                dedup_enabled=data.get("dedup_enabled", DEFAULT_STRATEGY["dedup_enabled"]),
                dedup_ttl=data.get("dedup_ttl", DEFAULT_STRATEGY["dedup_ttl"]),
            )
        except Exception as e:
            logger.error(f"[Strategy] Error reading strategy file: {e}, using default")

    return StrategyConfig(
        type=DEFAULT_STRATEGY["type"],
        compression_threshold=DEFAULT_STRATEGY["compression_threshold"],
        window_size=DEFAULT_STRATEGY["window_size"],
        compression_ratio=DEFAULT_STRATEGY["compression_ratio"],
        dedup_enabled=DEFAULT_STRATEGY["dedup_enabled"],
        dedup_ttl=DEFAULT_STRATEGY["dedup_ttl"],
    )

def load_agent_config(agent_slug: str = "openclaw") -> AgentConfig:
    if agent_slug == "openclaw":
        config_path = Path.home() / ".openclaw" / "openclaw.json"
    elif agent_slug == "codebuddy":
        config_path = Path.home() / ".codebuddy" / "config.json"
    else:
        return AgentConfig(api_key=None, provider_slug=None, base_url=None, model=None)

    if not config_path.exists():
        return AgentConfig(api_key=None, provider_slug=None, base_url=None, model=None)

    try:
        data = json.loads(config_path.read_text())

        api_key = (
            data.get("models", {})
            .get("providers", {})
            .get("openai", {})
            .get("apiKey")
        )

        provider_slug = data.get("providerSlug")

        base_url = PROVIDER_BASE_URLS.get(provider_slug) if provider_slug else None

        primary_model = (
            data.get("agents", {})
            .get("defaults", {})
            .get("model", {})
            .get("primary", "")
        )
        model = primary_model.split("/")[-1] if primary_model else None

        return AgentConfig(
            api_key=api_key,
            provider_slug=provider_slug,
            base_url=base_url,
            model=model,
        )

    except Exception as e:
        logger.error(f"[AgentConfig] Error reading config: {e}")
        return AgentConfig(api_key=None, provider_slug=None, base_url=None, model=None)
