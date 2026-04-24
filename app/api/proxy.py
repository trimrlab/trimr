"""
@Project: Trimr
@File: app/api/proxy.py
@Description: Core proxy module
"""
import json
import asyncio
import httpx
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.orm import Session
from datetime import datetime

from app.config import settings
from app.core.tracker import tracker, TokenCounter
from app.db.models import get_db, ActionLog
from app.core.optimizer import compression_engine
from app.core.dedup import dedup_engine
from app.agent.strategy import load_strategy, load_agent_config
from app.utils.logger import get_logger

logger = get_logger()

router = APIRouter()


def _build_streaming_from_cache(response_body: dict, request_id: str) -> StreamingResponse:
    """Convert a cached non-streaming response into SSE format for streaming clients."""
    content = ""
    choices = response_body.get("choices", [])
    if choices:
        content = choices[0].get("message", {}).get("content", "")

    async def stream_cached():
        # Send content as a single chunk in SSE format
        chunk = {
            "id": request_id,
            "object": "chat.completion.chunk",
            "choices": [{
                "index": 0,
                "delta": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }],
        }
        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        stream_cached(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Trimr-Request-Id": request_id,
            "X-Trimr-Cache-Hit": "true",
        },
    )


_sync_lock = asyncio.Lock()

async def _background_sync():
    if _sync_lock.locked():
        return
    async with _sync_lock:
        try:
            from app.db.sync import sync_to_cloud
            result = await sync_to_cloud()
            if result.get("records_count", 0) > 0:
                logger.debug(f"[Sync] {result['message']} count={result['records_count']}")
        except Exception as e:
            logger.debug(f"[Sync] Background sync error: {e}")

def extract_action_logs(messages: list, request_id: str, db: Session):
    last_tool_msg = None
    for msg in reversed(messages):
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            last_tool_msg = msg
            break

    if not last_tool_msg:
        return

    for call in last_tool_msg.get("tool_calls", []):
        try:
            func = call.get("function", {})
            name = func.get("name", "unknown")
            args_str = func.get("arguments", "{}")

            try:
                args = json.loads(args_str) if isinstance(args_str, str) else args_str
            except Exception:
                args = {}

            summary = _extract_summary(name, args)

            log = ActionLog(
                request_id=request_id,
                timestamp=datetime.utcnow(),
                action_type=name,
                summary=json.dumps(summary, ensure_ascii=False),
                synced=False,
            )
            db.add(log)

        except Exception as e:
            logger.debug(f"[ActionLog] Parse error: {e}")

    try:
        db.commit()
    except Exception:
        db.rollback()

def _extract_summary(action_name: str, args: dict) -> dict:
    name = action_name.lower()

    if "read" in name or "file" in name:
        return {
            "file": args.get("path") or args.get("file_path") or args.get("file") or "unknown"
        }
    elif "write" in name or "edit" in name:
        return {
            "file": args.get("path") or args.get("file_path") or "unknown"
        }
    elif "exec" in name or "command" in name or "run" in name:
        cmd = args.get("command", "")
        return {"command": cmd[:50] if cmd else "unknown"}
    elif "search" in name:
        return {"query": args.get("query", "unknown")}
    elif "fetch" in name or "url" in name:
        return {"url": args.get("url", "unknown")}
    elif "memory" in name:
        return {"action": action_name}
    else:
        return {"action": action_name}

# ─────────────────────────────────────────
# LLM Provider Configuration
# ─────────────────────────────────────────
def get_upstream_url(agent_slug: str = "openclaw") -> str:
    agent_config = load_agent_config(agent_slug)
    if agent_config.base_url:
        return f"{agent_config.base_url}/chat/completions"

    return "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"

def detect_provider(modle: str):
    model_lower = modle.lower()
    if "gemini" in model_lower:
        return "gemini"
    elif "deepseek" in model_lower:
        return "deepseek"
    else:
        return "openai"

def build_upstream_headers(agent_slug) -> dict:
    agent_config = load_agent_config(agent_slug)

    api_key = agent_config.api_key

    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="API key not found. Please configure the Agent's API key in the cloud.",
        )
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

# ─────────────────────────────────────────
# Core endpoint: POST /v1/chat/completions
# ─────────────────────────────────────────
@router.post("/chat/completions")
async def chat_completions(request: Request, db: Session = Depends(get_db)):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid JSON body",
        )

    for key in ["store", "prompt_cache_key", "max_output_tokens"]:
        body.pop(key, None)

    if "messages" in body:
        body["messages"] = _fix_messages(body["messages"])

    if "tools" in body:
        for tool in body.get("tools", []):
            if isinstance(tool, dict):
                tool.pop("strict", None)
                if "function" in tool:
                    tool["function"].pop("strict", None)

    agent_slug = request.headers.get("X-Agent-Slug", "openclaw")
    agent_config = load_agent_config(agent_slug)
    upstream_url = get_upstream_url(agent_slug)
    headers = build_upstream_headers(agent_slug)
    is_streaming = body.get("stream", False)
    provider = agent_config.provider_slug

    model = agent_config.model or body.get("model", "gemini-2.5-flash")
    body["model"] = model

    ctx = tracker.create_context(
        model=model,
        provider=provider,
        is_streaming=is_streaming,
    )

    messages = body.get("messages", [])
    original_messages = messages
    input_tokens = TokenCounter.count_messages(messages, model)

    logger.debug(f"\n{'='*60}")
    logger.debug(f"[1/6 Request] id={ctx.request_id[:8]} agent={agent_slug} model={model} provider={provider} streaming={is_streaming}")
    logger.debug(f"[1/6 Request] messages={len(messages)} tools={len(body.get('tools', []))} input_tokens={input_tokens}")
    logger.debug(f"[1/6 Request] upstream={upstream_url}")

    ctx.input_tokens_original = input_tokens
    ctx.input_tokens_actual = input_tokens

    extract_action_logs(messages, ctx.request_id, db)

    strategy = load_strategy(agent_slug)
    ctx.strategy_type = strategy.type
    ctx.agent_slug = agent_slug
    logger.debug(f"[2/6 Strategy] type={strategy.type} threshold={strategy.compression_threshold} window={strategy.window_size} ratio={strategy.compression_ratio} dedup={strategy.dedup_enabled} ttl={strategy.dedup_ttl}")

    if strategy.dedup_enabled and dedup_engine.should_use_dedup(body):
        logger.debug(f"[3/6 Dedup] checking cache... ttl={strategy.dedup_ttl}s cache_size={dedup_engine.cache_size()}")
        dedup_engine.ttl_seconds = strategy.dedup_ttl
        cache_entry = dedup_engine.get(model, messages)
        if cache_entry:
            logger.debug(f"[3/6 Dedup] HIT! hit_count={cache_entry.hit_count} streaming={is_streaming} saved_tokens={cache_entry.input_tokens}")
            from app.core.tracker import calculate_cost

            original_cost = calculate_cost(
                model,
                cache_entry.input_tokens,
                cache_entry.output_tokens,
            )

            ctx.input_tokens_original = cache_entry.input_tokens
            ctx.input_tokens_actual = 0
            ctx.output_tokens = cache_entry.output_tokens
            ctx.saved_tokens_override = cache_entry.input_tokens
            ctx.cost_original = original_cost
            ctx.cost_actual = 0.0
            ctx.cost_saved = original_cost
            ctx.skip_cost_calculation = True
            ctx.cache_hit = True
            ctx.strategies_used.append("dedup")
            tracker.save(ctx, db)

            if is_streaming:
                return _build_streaming_from_cache(cache_entry.response_body, ctx.request_id)
            return JSONResponse(
                content=cache_entry.response_body,
                headers={"X-Trimr-Request-Id": ctx.request_id},
            )
        else:
            logger.debug(f"[3/6 Dedup] MISS")
    else:
        reason = "disabled" if not strategy.dedup_enabled else "not applicable (temperature>0.7 or no messages)"
        logger.debug(f"[3/6 Dedup] skipped: {reason}")


    should_compress = compression_engine.should_compress(
        messages, model,
        threshold=strategy.compression_threshold,
        window_size=strategy.window_size,
    )
    logger.debug(f"[4/6 Compression] should_compress={should_compress} tokens={input_tokens} threshold={strategy.compression_threshold}")

    if should_compress:
        result = await compression_engine.compress(
            messages, model, agent_slug,
            window_size=strategy.window_size,
            compression_ratio=strategy.compression_ratio,
        )
        body["messages"] = result.compressed_messages
        ctx.input_tokens_original = result.original_tokens
        ctx.input_tokens_actual = result.compressed_tokens
        ctx.compression_triggered = True
        ctx.strategies_used.append("compression")

        logger.debug(f"[4/6 Compression] original={result.original_tokens} -> compressed={result.compressed_tokens} saved={result.saved_tokens} ({result.saving_pct}%) from_cache={result.from_cache}")

        # Factor in the cost of the summary LLM call
        if result.summary_model and not result.from_cache:
            from app.core.tracker import calculate_cost
            ctx.compression_cost = calculate_cost(
                result.summary_model,
                result.summary_input_tokens,
                result.summary_output_tokens,
            )
            logger.debug(f"[4/6 Compression] summary_cost=${ctx.compression_cost:.6f} summary_model={result.summary_model} summary_tokens={result.summary_input_tokens}+{result.summary_output_tokens}")

    logger.debug(f"[5/6 Forward] mode={'streaming' if is_streaming else 'normal'} url={upstream_url}")
    if is_streaming:
        return await _handle_streaming(upstream_url, headers, body, ctx, db)
    else:
        return await _handle_normal(upstream_url, headers, body, ctx, db, original_messages)

def _to_content_parts(content) -> list:
    if isinstance(content, list):
        return list(content)
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    return []


def _merge_content(prev, curr):
    if isinstance(prev, str) and isinstance(curr, str):
        if not prev:
            return curr
        if not curr:
            return prev
        return prev + "\n" + curr
    return _to_content_parts(prev) + _to_content_parts(curr)


def _fix_messages(messages: list) -> list:
    if not messages:
        return messages

    cleaned = []
    for msg in messages:
        msg = dict(msg)
        if msg.get("content") is None:
            msg["content"] = ""
        cleaned.append(msg)

    fixed = []
    for msg in cleaned:
        role = msg.get("role")
        content = msg.get("content", "")

        if msg.get("tool_calls"):
            fixed.append(msg)
            continue

        if fixed and fixed[-1].get("role") == role and not fixed[-1].get("tool_calls"):
            fixed[-1]["content"] = _merge_content(fixed[-1].get("content", ""), content)
        else:
            fixed.append(msg)

    return fixed

# Handle normal requests
async def _handle_normal(
        url: str,
        headers: dict,
        body: dict,
        ctx,
        db: Session,
        original_messages: list = None,
) -> JSONResponse:
    if original_messages is None:
        original_messages = []

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(
                url,
                headers=headers,
                json=body
            )

            logger.debug(f"[5/6 Response] status={response.status_code}")

            if response.status_code != 200:
                ctx.error = f"Upstream error {response.status_code}"
                logger.debug(f"[5/6 Response] ERROR: {response.text[:200]}")
                tracker.save(ctx, db)
                return JSONResponse(
                    status_code=response.status_code,
                    content=response.json()
                )

            resp_data = response.json()
            usage = resp_data.get("usage", {})
            logger.debug(f"[5/6 Response] usage={usage}")
            if usage:
                if not ctx.compression_triggered:
                    ctx.input_tokens_actual = usage.get("prompt_tokens", ctx.input_tokens_actual)
                    ctx.input_tokens_original = usage.get("prompt_tokens", ctx.input_tokens_original)
                    ctx.output_tokens = usage.get("completion_tokens", 0)

            dedup_engine.set(
                model=ctx.model,
                messages=original_messages,
                response_body=resp_data,
                input_tokens=ctx.input_tokens_actual,
                output_tokens=ctx.output_tokens,
            )

            tracker.save(ctx, db)

            from app.core.tracker import calculate_cost
            final_cost = calculate_cost(ctx.model, ctx.input_tokens_actual, ctx.output_tokens)
            final_original = calculate_cost(ctx.model, ctx.input_tokens_original, ctx.output_tokens)
            print(f"[200 OK] model={ctx.model} in={ctx.input_tokens_original}->{ctx.input_tokens_actual} out={ctx.output_tokens} saved={ctx.saved_tokens} ${final_original - final_cost - ctx.compression_cost:.6f} latency={ctx.latency_ms}ms")
            logger.debug(f"[6/6 Done] id={ctx.request_id[:8]} input={ctx.input_tokens_original}->{ctx.input_tokens_actual} output={ctx.output_tokens} saved={ctx.saved_tokens}")
            logger.debug(f"[6/6 Done] cost_original=${final_original:.6f} cost_actual=${final_cost:.6f} compression_cost=${ctx.compression_cost:.6f} net_saved=${final_original - final_cost - ctx.compression_cost:.6f}")
            logger.debug(f"[6/6 Done] strategies={ctx.strategies_used} latency={ctx.latency_ms}ms")
            logger.debug(f"{'='*60}\n")

            asyncio.create_task(_background_sync())

            return JSONResponse(
                content=resp_data,
                headers={"X-Trimr-Request-Id": ctx.request_id},
            )

        except httpx.TimeoutException:
            ctx.error = "Upstream request timed out"
            tracker.save(ctx, db)
            raise HTTPException(status_code=500, detail="Upstream request timed out")
        except httpx.HTTPError as e:
            ctx.error = f"Request forwarding failed: {str(e)}"
            tracker.save(ctx, db)
            raise HTTPException(status_code=502, detail=f"Request forwarding failed: {str(e)}")

# Handle streaming requests
async def _handle_streaming(url: str, headers: dict, body: dict, ctx, db: Session) -> StreamingResponse:
    async def stream_generator():
        logger.debug(f"[5/6 Streaming] started")
        output_text = ""

        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                async with client.stream(
                    "POST",
                    url,
                    headers=headers,
                    json=body
                ) as response:
                    if response.status_code != 200:
                        error_body = await response.aread()
                        error_msg = f"Upstream error {response.status_code}: {error_body.decode()}"
                        ctx.error = error_msg
                        tracker.save(ctx, db)
                        yield f"data: {json.dumps({'error': error_msg}, ensure_ascii=False)}\n\n"
                        return

                    chunk_count = 0
                    async for line in response.aiter_lines():
                        if not line:
                            continue

                        yield f"{line}\n\n"

                        # Parse SSE data lines to extract output text
                        data_line = None
                        if line.startswith("data: ") and line != "data: [DONE]":
                            data_line = line[6:]
                        elif line.startswith("data:") and line != "data:[DONE]":
                            data_line = line[5:]

                        if data_line:
                            try:
                                chunk_data = json.loads(data_line)
                                choices = chunk_data.get("choices", [])
                                if choices:
                                    delta = choices[0].get("delta", {})
                                    content = delta.get("content", "")
                                    if content:
                                        output_text += content
                                chunk_count += 1
                                if chunk_count == 1:
                                    logger.debug(f"[5/6 Streaming] first chunk: {json.dumps(chunk_data, ensure_ascii=False)[:200]}")
                            except json.JSONDecodeError:
                                if chunk_count == 0:
                                    logger.debug(f"[5/6 Streaming] parse failed, raw line: {line[:150]}")

                    logger.debug(f"[5/6 Streaming] finished, chunks={chunk_count} output_chars={len(output_text)}")

            except httpx.TimeoutException:
                ctx.error = "Upstream request timeout"
                tracker.save(ctx, db)

                yield f"data: {json.dumps({'error': 'Upstream request timeout'}, ensure_ascii=False)}\n\n"
            except httpx.HTTPError as e:
                ctx.error = str(e)
                yield f"data: {json.dumps({'error': f'Connection failed: {str(e)}'}, ensure_ascii=False)}\n\n"
            finally:
                if output_text:
                    ctx.output_tokens = TokenCounter.count_text(output_text, ctx.model)
                tracker.save(ctx, db)

                from app.core.tracker import calculate_cost
                final_cost = calculate_cost(ctx.model, ctx.input_tokens_actual, ctx.output_tokens)
                final_original = calculate_cost(ctx.model, ctx.input_tokens_original, ctx.output_tokens)
                print(f"[200 OK] model={ctx.model} in={ctx.input_tokens_original}->{ctx.input_tokens_actual} out={ctx.output_tokens} saved={ctx.saved_tokens} ${final_original - final_cost - ctx.compression_cost:.6f} latency={ctx.latency_ms}ms")
                logger.debug(f"[6/6 Done] id={ctx.request_id[:8]} input={ctx.input_tokens_original}->{ctx.input_tokens_actual} output={ctx.output_tokens} saved={ctx.saved_tokens}")
                logger.debug(f"[6/6 Done] cost_original=${final_original:.6f} cost_actual=${final_cost:.6f} compression_cost=${ctx.compression_cost:.6f} net_saved=${final_original - final_cost - ctx.compression_cost:.6f}")
                logger.debug(f"[6/6 Done] strategies={ctx.strategies_used} latency={ctx.latency_ms}ms output_chars={len(output_text)}")
                logger.debug(f"{'='*60}\n")

                asyncio.create_task(_background_sync())

    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        }
    )
