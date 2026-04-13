"""
@Author: Sid Woong
@Date: 2026/3/11
@Description: Request tracking and cost calculation
"""
import time
import uuid
import tiktoken
from dataclasses import dataclass, field
from typing import Optional
from sqlalchemy.orm import Session

from app.db.models import RequestLog
from app.utils.logger import get_logger

logger = get_logger()

MODEL_PRICING = {
    # OpenAI
    "gpt-5.4":               {"input": 0.003,   "output": 0.015},
    "gpt-5.4-pro":           {"input": 0.005,   "output": 0.020},
    "gpt-4o":                {"input": 0.0025,  "output": 0.010},
    "gpt-4o-mini":           {"input": 0.00015, "output": 0.0006},
    "gpt-3.5-turbo":         {"input": 0.0005,  "output": 0.0015},

    # Anthropic
    "claude-opus-4-6":       {"input": 0.015,   "output": 0.075},
    "claude-sonnet-4-6":     {"input": 0.003,   "output": 0.015},
    "claude-haiku-4-5":      {"input": 0.0008,  "output": 0.004},

    # Google Gemini
    "gemini-3.1-pro":        {"input": 0.00125, "output": 0.005},
    "gemini-3-flash":        {"input": 0.00015, "output": 0.0006},
    "gemini-2.5-flash":      {"input": 0.00015, "output": 0.0006},
    "gemini-2.5-flash-lite": {"input": 0.000075,"output": 0.0003},

    # DeepSeek
    "deepseek-chat":         {"input": 0.00014, "output": 0.00028},
    "deepseek-v3":           {"input": 0.00014, "output": 0.00028},

    # Mistral
    "mistral-large":         {"input": 0.002,   "output": 0.006},
    "mistral-small":         {"input": 0.0002,  "output": 0.0006},

    # xAI / Grok
    "grok-4":                {"input": 0.003,   "output": 0.015},
    "grok-3":                {"input": 0.003,   "output": 0.015},
    "grok-3-mini":           {"input": 0.0003,  "output": 0.0005},

    # Chinese providers (approximate, $/1K tokens)
    "glm":                   {"input": 0.0004,  "output": 0.0004},
    "qwen":                  {"input": 0.0003,  "output": 0.0006},
    "ernie":                 {"input": 0.0004,  "output": 0.0008},
    "moonshot":              {"input": 0.0008,  "output": 0.0008},
    "kimi":                  {"input": 0.0008,  "output": 0.0008},
    "minimax":               {"input": 0.0004,  "output": 0.0004},
    "doubao":                {"input": 0.0003,  "output": 0.0006},
    "step":                  {"input": 0.0004,  "output": 0.0008},

    # Groq / Cerebras (inference-as-a-service, often free tier)
    "llama":                 {"input": 0.0001,  "output": 0.0001},

    # OpenRouter (pass-through, use underlying model pricing)
    "openrouter":            {"input": 0.001,   "output": 0.002},

    "default":               {"input": 0.001,   "output": 0.002},
}

@dataclass
class RequestContext:
    model: str
    provider: str
    is_streaming: bool = False

    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    input_tokens_original: int = 0
    input_tokens_actual: int = 0
    output_tokens: int = 0

    strategies_used: list = field(default_factory=list)
    strategy_type: str = "balance"
    cache_hit: bool = False
    compression_triggered: bool = False

    saved_tokens_override: int = -1

    cost_actual: float = 0.0
    cost_original: float = 0.0
    cost_saved: float = 0.0

    # Cost of the summary LLM call used for compression
    compression_cost: float = 0.0

    skip_cost_calculation: bool = False

    start_time: float = field(default_factory=time.time)
    latency_ms: int = 0

    error: Optional[str] = None

    agent_slug: str = "openclaw"

    def mark_done(self):
        self.latency_ms = int((time.time() - self.start_time) * 1000)

    @property
    def saved_tokens(self) -> int:
        if self.saved_tokens_override >= 0:
            return self.saved_tokens_override
        return max(0, self.input_tokens_original - self.input_tokens_actual)

class TokenCounter:
    _encoders = {}

    @classmethod
    def get_encoder(cls, model: str):
        if model not in cls._encoders:
            try:
                cls._encoders[model] = tiktoken.encoding_for_model(model)
            except KeyError:
                cls._encoders[model] = tiktoken.get_encoding("cl100k_base")

        return cls._encoders[model]

    @classmethod
    def count_messages(cls, messages: list, model: str) -> int:
        total = 0
        for message in messages:
            total += 4
            for key, value in message.items():
                if isinstance(value, str):
                    chinese_chars = sum(1 for c in value if '\u4e00' <= c <= '\u9fff')
                    other_chars = len(value) - chinese_chars
                    encoder = cls.get_encoder(model)
                    total += int(chinese_chars * 1.5) + len(encoder.encode(
                        ''.join(c for c in value if not '\u4e00' <= c <= '\u9fff')
                    )) if other_chars else int(chinese_chars * 1.5)
            total += 1
        total += 3
        return total

    @classmethod
    def count_text(cls, text: str, model: str = "gpt-4o") -> int:
        encoder = cls.get_encoder(model)
        return len(encoder.encode(text))

def calculate_cost(model: str, input_token: int, output_token: int) -> float:
    pricing = None
    for model_key in MODEL_PRICING:
        if model_key in model.lower():
            pricing = MODEL_PRICING[model_key]
            break

    if pricing is None:
        pricing = MODEL_PRICING["default"]

    cost = (input_token / 1000 * pricing["input"]) + \
           (output_token / 1000 * pricing["output"])

    return round(cost, 8)

class Tracker:
    def create_context(
            self,
            model: str,
            provider: str,
            is_streaming: bool = False,
    ) -> RequestContext:
        return RequestContext(
            model=model,
            provider=provider,
            is_streaming=is_streaming,
        )

    def save(self, ctx: RequestContext, db: Session):
        ctx.mark_done()

        existing = db.query(RequestLog).filter_by(id=ctx.request_id).first()
        if existing:
            return

        if ctx.skip_cost_calculation:
            cost_actual = ctx.cost_actual
            cost_original = ctx.cost_original
            cost_saved = ctx.cost_saved
        else:
            cost_actual = calculate_cost(
                ctx.model,
                ctx.input_tokens_actual,
                ctx.output_tokens
            )
            cost_original = calculate_cost(
                ctx.model,
                ctx.input_tokens_original,
                ctx.output_tokens
            )
            # Subtract the cost of compression LLM call from savings
            cost_saved = round(cost_original - cost_actual - ctx.compression_cost, 8)
            cost_actual = round(cost_actual + ctx.compression_cost, 8)

        log = RequestLog(
            id=ctx.request_id,
            model=ctx.model,
            provider=ctx.provider,
            is_streaming=ctx.is_streaming,
            input_tokens_original=ctx.input_tokens_original,
            input_tokens_actual=ctx.input_tokens_actual,
            output_tokens=ctx.output_tokens,
            saved_tokens=ctx.saved_tokens,
            cost_actual=cost_actual,
            cost_original=cost_original,
            cost_saved=cost_saved,
            latency_ms=ctx.latency_ms,
            strategies_used=",".join(ctx.strategies_used) if ctx.strategies_used else "none",
            strategy_type=ctx.strategy_type,
            cache_hit=ctx.cache_hit,
            compression_triggered=ctx.compression_triggered,
            error=ctx.error,
            agent_slug=ctx.agent_slug,
        )

        try:
            db.add(log)
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"Error saving log: {e}")


tracker = Tracker()
