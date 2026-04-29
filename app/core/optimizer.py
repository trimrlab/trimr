"""
@Author: Sid Woong
@Date: 2026/3/13
@Description: Context Compression Core Engine
"""
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Optional

import httpx

from app.core.tracker import TokenCounter
from app.agent.strategy import load_agent_config, PROVIDER_BASE_URLS
from app.utils.logger import get_logger

logger = get_logger()

@dataclass
class CompressionResult:
    compressed_messages: list
    original_tokens: int
    compressed_tokens: int
    saved_tokens: int
    saving_pct: float
    summary_text: str
    from_cache: bool = False
    summary_input_tokens: int = 0
    summary_output_tokens: int = 0
    summary_model: str = ""

_summary_cache: dict[str, dict] = {}
MAX_SUMMARY_CACHE_SIZE = 50

def _get_session_id(messages: list) -> str:
    """Generate a cache key based on system prompt + message count + last message content.
    This ensures:
    - Different conversations (different system prompts) get different IDs
    - Same conversation at different lengths gets different IDs (cache invalidation)
    """
    parts = []
    for m in messages:
        if m.get("role") == "system":
            parts.append(m.get("content", ""))
            break
    parts.append(str(len(messages)))
    if messages:
        last = messages[-1]
        parts.append(f"{last.get('role', '')}:{str(last.get('content', ''))[:100]}")
    raw = "|".join(parts)
    return hashlib.md5(raw.encode()).hexdigest()[:16]

def _get_cached_summary(session_id: str) -> Optional[str]:
    if session_id not in _summary_cache:
        return None

    cached = _summary_cache[session_id]

    if time.time() - cached["created_at"] > 3600:
        del _summary_cache[session_id]
        return None

    return cached["summary"]

def _set_cached_summary(session_id: str, summary: str):
    # Evict oldest entry if cache is full
    if len(_summary_cache) >= MAX_SUMMARY_CACHE_SIZE:
        oldest_key = min(_summary_cache, key=lambda k: _summary_cache[k]["created_at"])
        del _summary_cache[oldest_key]

    _summary_cache[session_id] = {
        "summary": summary,
        "created_at": time.time(),
    }


def _build_summary_prompt(conversation: str, compression_ratio: int = 70) -> str:
    retain_pct = 100 - compression_ratio
    return f"""You are a conversation compression assistant.

Please compress the following multi-turn conversation into a concise summary:
1. Retain all key decisions, technical choices, and important conclusions
2. Retain the user's background information and core requirements
3. Remove duplicate content, greetings, and transition statements
4. Control the summary length to approximately {retain_pct}% of the original
5. Use third person, format as plain text

Conversation content:
{conversation}

Please output the summary directly without any prefix or explanation."""

def _resolve_summary_config(agent_slug: str = "openclaw") -> tuple[str, str, str]:
    """
    Resolve the API key, base_url, and model for summary generation.
    Uses the agent's own API key and the REAL upstream URL (bypassing Trimr proxy).
    """
    agent_config = load_agent_config(agent_slug)
    api_key = agent_config.relay_api_key or agent_config.api_key
    if api_key:
        provider = agent_config.provider_slug or "gemini"

        # Priority: relay baseUrl > PROVIDER_BASE_URLS (direct)
        upstream_base_url = agent_config.relay_base_url or PROVIDER_BASE_URLS.get(provider)
        if not upstream_base_url:
            return "", "", ""

        # Pick the cheapest/fastest model per provider for summary generation
        provider_summary_models = {
            # Major providers
            "openai":           "gpt-4o-mini",
            "anthropic":        "claude-haiku-4-5-20251001",
            "gemini":           "gemini-2.5-flash-lite",
            "google":           "gemini-2.5-flash-lite",
            "google-gemini-cli":"gemini-2.5-flash-lite",
            "deepseek":         "deepseek-chat",
            "openai-codex":     "gpt-4o-mini",

            # Aggregators
            "openrouter":       "google/gemini-2.5-flash-lite",

            # Chinese providers
            "moonshot":         "moonshot-v1-8k",
            "kimi":             "moonshot-v1-8k",
            "qwen":             "qwen-turbo",
            "qianfan":          "ernie-speed",
            "minimax":          "MiniMax-Text-01",
            "zai":              "glm-4-flash",
            "stepfun":          "step-1-flash",
            "volcengine":       "doubao-lite-32k",
            "byteplus":         "doubao-lite-32k",
            "xiaomi":           "xiaomi-chat",

            # International providers
            "mistral":          "mistral-small-latest",
            "xai":              "grok-3-mini",
            "groq":             "llama-3.1-8b-instant",
            "cerebras":         "llama3.1-8b",
            "together":         "meta-llama/Llama-3-8b-chat-hf",
            "nvidia":           "meta/llama-3.1-8b-instruct",
            "venice":           "llama-3.1-8b",
            "huggingface":      "meta-llama/Llama-3.1-8B-Instruct",
        }
        model = agent_config.summary_model or provider_summary_models.get(provider, "gpt-4o-mini")
        return api_key, upstream_base_url, model

    return "", "", ""

@dataclass
class SummaryResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""

async def _generate_summary(messages: list, compression_ratio: int = 70, agent_slug: str = "openclaw") -> SummaryResult:
    api_key, base_url, model = _resolve_summary_config(agent_slug)

    if not api_key:
        return SummaryResult(text="[Summary generation failed: API Key not configured]")

    conversation_text = "\n".join(
        f"[{m['role'].upper()}]: {m.get('content', '')}"
        for m in messages
        if isinstance(m.get('content'), str)
    )
    prompt = _build_summary_prompt(conversation_text, compression_ratio)

    url = f"{base_url}/chat/completions"

    payload = {
        "model":       model,
        "messages":    [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens":  1024,
    }

    logger.debug(f"[Summary] url={url} model={model}")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type":  "application/json",
                },
                json=payload,
            )
            logger.debug(f"[Summary] status={response.status_code}")
            if response.status_code != 200:
                return SummaryResult(text=f"[Summary generation failed: {response.status_code}]")
            data = response.json()
            text = data["choices"][0]["message"]["content"].strip()
            usage = data.get("usage", {})
            return SummaryResult(
                text=text,
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                model=model,
            )
    except Exception as e:
        return SummaryResult(text=f"[Summary generation failed: {str(e)}]")

TOOL_RESULT_COMPRESS_THRESHOLD = 500  # tokens

def _build_tool_summary_prompt(tool_content: str) -> str:
    return f"""You are a tool output compression assistant.

Compress the following tool output into a concise summary:
1. Retain key information: file names, function names, error messages, important values
2. Retain structural information: what type of content this is (code, search results, file listing, etc.)
3. Remove redundant details, boilerplate code, and repetitive content
4. Keep the summary under 20% of the original length
5. Output as plain text, no markdown

Tool output:
{tool_content}

Output the summary directly without any prefix or explanation."""


async def _compress_tool_result(content: str, agent_slug: str = "openclaw") -> SummaryResult:
    """Compress a single tool result content string."""
    api_key, base_url, model = _resolve_summary_config(agent_slug)

    if not api_key:
        return SummaryResult(text=content)

    prompt = _build_tool_summary_prompt(content)
    url = f"{base_url}/chat/completions"

    payload = {
        "model":       model,
        "messages":    [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens":  512,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type":  "application/json",
                },
                json=payload,
            )
            if response.status_code != 200:
                return SummaryResult(text=content)
            data = response.json()
            text = data["choices"][0]["message"]["content"].strip()
            usage = data.get("usage", {})
            return SummaryResult(
                text=f"[Trimr Summary] {text}",
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                model=model,
            )
    except Exception as e:
        logger.debug(f"[ToolCompress] Error: {e}")
        return SummaryResult(text=content)


def _is_failed_summary(text: str) -> bool:
    if not text:
        return True
    failed_prefixes = [
        "[Summary generation failed",
        "[GEMINI API Error",
        "[GEMINI_API_KEY",
    ]
    return any(text.startswith(p) for p in failed_prefixes)

class CompressionEngine:
    def __init__(self):
        # Default values, only used when caller doesn't pass strategy
        self._default_threshold = 2000
        self._default_window_size = 3
        self._default_compression_ratio = 70

    def should_compress(
        self,
        messages: list,
        model: str = "gpt-4o",
        threshold: Optional[int] = None,
        window_size: Optional[int] = None,
    ) -> bool:
        threshold = threshold or self._default_threshold

        total_tokens = TokenCounter.count_messages(messages, model)
        logger.debug(f"[Compression] total_tokens={total_tokens}")

        return total_tokens > threshold

    async def compress(
            self,
            messages: list,
            model: str = "gpt-4o",
            agent_slug: str = "openclaw",
            session_id: Optional[str] = None,
            window_size: Optional[int] = None,
            compression_ratio: Optional[int] = None,
            compression_threshold: Optional[int] = None,
    ) -> CompressionResult:
        window_size = window_size or self._default_window_size
        compression_ratio = compression_ratio or self._default_compression_ratio
        compression_threshold = compression_threshold or self._default_threshold

        logger.debug(f"[Compression] window_size={window_size}")
        original_tokens = TokenCounter.count_messages(messages, model)

        system_msgs = [m for m in messages if m.get("role") == "system"]

        non_system = [m for m in messages if m.get("role") != "system"]

        window_count = window_size * 2
        split_idx = max(0, len(non_system) - window_count)

        # Adjust split point to avoid breaking tool_call/tool pairs
        # If the split lands on a "tool" message, move it back so the
        # corresponding assistant(tool_calls) + tool(result) stay together in window
        while split_idx > 0 and non_system[split_idx].get("role") == "tool":
            split_idx -= 1

        window_msgs = non_system[split_idx:]
        history_msgs = non_system[:split_idx]

        logger.debug(f"[Compression] total_msgs={len(messages)} history={len(history_msgs)} window={len(window_msgs)}")

        history_tool_msgs = [
            m for m in history_msgs
            if m.get("role") == "tool"
            or (m.get("role") == "assistant" and m.get("tool_calls"))
        ]

        history_chat_msgs = [
            m for m in history_msgs
            if m not in history_tool_msgs
        ]

        # ── Step 1: Compress long tool results (parallel) ──────────
        import asyncio as _asyncio
        tool_compress_input_tokens = 0
        tool_compress_output_tokens = 0
        tool_compressed_count = 0
        tool_skipped_roi = 0

        # Resolve summary model pricing for ROI check
        from app.core.tracker import calculate_cost
        _, _, summary_model_name = _resolve_summary_config(agent_slug)

        # Phase 1: identify which tool msgs need compression, launch tasks in parallel
        compress_tasks = {}  # index -> asyncio.Task
        for i, msg in enumerate(history_tool_msgs):
            if msg.get("role") == "tool" and isinstance(msg.get("content"), str):
                content = msg["content"]
                msg_tokens = TokenCounter.count_text(content, model)
                if msg_tokens > TOOL_RESULT_COMPRESS_THRESHOLD:
                    estimated_compressed_tokens = int(msg_tokens * 0.2)
                    estimated_saved = msg_tokens - estimated_compressed_tokens
                    savings_value = calculate_cost(model, estimated_saved, 0)

                    estimated_summary_output = int(msg_tokens * 0.2)
                    compress_cost = calculate_cost(summary_model_name, msg_tokens, estimated_summary_output)

                    if compress_cost >= savings_value:
                        logger.debug(f"[ToolCompress] ROI skip: {msg_tokens} tokens, compress_cost=${compress_cost:.6f} >= savings=${savings_value:.6f}")
                        tool_skipped_roi += 1
                        continue

                    compress_tasks[i] = _asyncio.create_task(
                        _compress_tool_result(content, agent_slug)
                    )

        # Phase 2: await all compression tasks in parallel
        if compress_tasks:
            results = await _asyncio.gather(*compress_tasks.values())
            task_results = dict(zip(compress_tasks.keys(), results))
        else:
            task_results = {}

        # Phase 3: assemble compressed tool messages in original order
        compressed_tool_msgs = []
        for i, msg in enumerate(history_tool_msgs):
            if i in task_results:
                result = task_results[i]
                content = msg["content"]
                if result.text != content:
                    compressed_msg = dict(msg)
                    compressed_msg["content"] = result.text
                    compressed_tool_msgs.append(compressed_msg)
                    tool_compress_input_tokens += result.input_tokens
                    tool_compress_output_tokens += result.output_tokens
                    tool_compressed_count += 1
                    logger.debug(f"[ToolCompress] {TokenCounter.count_text(content, model)} -> ~{TokenCounter.count_text(result.text, model)} tokens")
                    continue
            compressed_tool_msgs.append(msg)

        logger.debug(f"[ToolCompress] compressed={tool_compressed_count} skipped_roi={tool_skipped_roi} total={len(history_tool_msgs)}")

        # ── Step 2: Compress chat history ────────────────────────
        MAX_SUMMARY_INPUT_TOKENS = 4000
        if history_chat_msgs:
            trimmed = []
            token_budget = 0
            for msg in reversed(history_chat_msgs):
                msg_tokens = TokenCounter.count_messages([msg], model)
                if token_budget + msg_tokens > MAX_SUMMARY_INPUT_TOKENS and trimmed:
                    break
                trimmed.append(msg)
                token_budget += msg_tokens
            history_chat_msgs = list(reversed(trimmed))
            logger.debug(f"[Compression] summary input: {len(history_chat_msgs)} msgs, ~{token_budget} tokens (capped at {MAX_SUMMARY_INPUT_TOKENS})")

        if not session_id:
            session_id = _get_session_id(messages)

        from_cache = False
        summary_text = _get_cached_summary(session_id)
        summary_input_tokens = 0
        summary_output_tokens = 0
        summary_model = ""

        if summary_text:
            from_cache = True
        elif history_chat_msgs:
            # ROI pre-check for chat summary: only summarize if history exceeds threshold
            history_chat_tokens = TokenCounter.count_messages(history_chat_msgs, model)
            if history_chat_tokens > compression_threshold:
                summary_result = await _generate_summary(history_chat_msgs, compression_ratio, agent_slug)
                summary_text = summary_result.text
                summary_input_tokens = summary_result.input_tokens
                summary_output_tokens = summary_result.output_tokens
                summary_model = summary_result.model

                if not summary_text:
                    summary_text = "[Summary generation failed: empty response]"

                if not _is_failed_summary(summary_text):
                    _set_cached_summary(session_id, summary_text)
            else:
                logger.debug(f"[Compression] Chat history too small to summarize: {history_chat_tokens} tokens")
                summary_text = ""
        else:
            summary_text = ""

        # ── Step 3: Assemble compressed messages ─────────────────
        # Build candidate with compressed tool msgs + chat summary
        if summary_text and not _is_failed_summary(summary_text):
            summary_msg = {
                "role": "assistant",
                "content": f"[History Summary]\n{summary_text}",
            }
            candidate = (
                system_msgs +
                compressed_tool_msgs +
                [summary_msg] +
                window_msgs
            )
        else:
            candidate = (
                system_msgs +
                compressed_tool_msgs +
                history_chat_msgs +
                window_msgs
            )

        candidate_tokens = TokenCounter.count_messages(candidate, model)
        if candidate_tokens < original_tokens:
            logger.debug(f"[Compression] Using compressed, candidate_tokens={candidate_tokens} original_tokens={original_tokens}")
            compressed_messages = candidate
            # Accumulate compression cost from tool result compression
            summary_input_tokens += tool_compress_input_tokens
            summary_output_tokens += tool_compress_output_tokens
        else:
            logger.debug(f"[Compression] Skipping, candidate_tokens={candidate_tokens} >= original_tokens={original_tokens}")
            compressed_messages = messages
            # Compression didn't help, zero out costs so user isn't charged for nothing
            summary_input_tokens = 0
            summary_output_tokens = 0
            summary_model = ""

        compressed_tokens = TokenCounter.count_messages(compressed_messages, model)
        saved_tokens = max(0, original_tokens - compressed_tokens)
        saving_pct = (saved_tokens / original_tokens * 100) if original_tokens > 0 else 0.0


        return CompressionResult(
            compressed_messages=compressed_messages,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            saved_tokens=saved_tokens,
            saving_pct=round(saving_pct, 2),
            summary_text=summary_text,
            from_cache=from_cache,
            summary_input_tokens=summary_input_tokens,
            summary_output_tokens=summary_output_tokens,
            summary_model=summary_model,
        )

compression_engine = CompressionEngine()
