"""
@Project: Trimr
@File: app/core/dedup.py
@Description: Call Deduplication Strategy (Request De-duplication Cache)
"""
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Optional
from app.utils.logger import get_logger

logger = get_logger()

@dataclass
class CacheEntry:
    response_body: dict
    input_tokens: int
    output_tokens: int
    created_at: float
    hit_count: int = 0

_cache: dict[str, CacheEntry] = {}

MAX_CACHE_SIZE = 100

class DedupEngine:
    def __init__(self, ttl_seconds: int = 3600):
        self.ttl_seconds = ttl_seconds

    def _make_cache_key(self, model: str, messages: list) -> str:
        messages_str = json.dumps(messages, ensure_ascii=False, sort_keys=True)
        raw = f"{model}{messages_str}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def should_use_dedup(self, body: dict) -> bool:
        messages = body.get("messages", [])
        if not messages:
            return False

        temperature = body.get("temperature", 0)
        if temperature > 0.7:
            return False

        return True

    def get(self, model: str, messages: list) -> Optional[CacheEntry]:
        key = self._make_cache_key(model, messages)

        if key not in _cache:
            return None

        entry = _cache[key]

        if time.time() - entry.created_at > self.ttl_seconds:
            del _cache[key]
            return None

        entry.hit_count += 1
        return entry

    def set(
            self,
            model: str,
            messages: list,
            response_body: dict,
            input_tokens: int,
            output_tokens: int,
    ):
        key = self._make_cache_key(model, messages)

        # Evict oldest entries if cache is full
        if len(_cache) >= MAX_CACHE_SIZE:
            oldest_key = min(_cache, key=lambda k: _cache[k].created_at)
            del _cache[oldest_key]

        _cache[key] = CacheEntry(
            response_body=response_body,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            created_at=time.time(),
        )

    def cache_size(self) -> int:
        return len(_cache)

    def clear_expired(self):
        now = time.time()
        expired_keys = [
            k for k, v in _cache.items()
            if now - v.created_at > self.ttl_seconds
        ]

        for k in expired_keys:
            del _cache[k]

        if expired_keys:
            logger.debug(f"[Dedup] Cleared {len(expired_keys)} expired cache entries, {len(_cache)} remaining")


dedup_engine = DedupEngine(ttl_seconds=3600)
