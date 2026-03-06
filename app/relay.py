from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import HTTPException

from .schemas import AppConfig, LocalKeyRecord, ProviderConfig, ProviderModel


def _build_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


async def test_provider_connection(provider: ProviderConfig) -> dict[str, Any]:
    """向上游发送最小请求验证 api_key 有效性。返回 {"ok": bool, "detail": str}"""
    if not provider.api_key:
        return {"ok": False, "detail": "api_key 未配置"}

    try:
        if provider.protocol == "openai":
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    _build_url(provider.base_url, "/v1/models"),
                    headers={"Authorization": f"Bearer {provider.api_key}"},
                )
            if resp.status_code < 400:
                return {"ok": True, "detail": f"连接成功 (HTTP {resp.status_code})"}
            try:
                err = resp.json()
                msg = err.get("error", {}).get("message") or str(err)
            except Exception:
                msg = resp.text[:200]
            return {"ok": False, "detail": f"HTTP {resp.status_code}: {msg}"}

        else:  # anthropic
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    _build_url(provider.base_url, "/v1/messages"),
                    headers={
                        "x-api-key": provider.api_key,
                        "anthropic-version": "2023-06-01",
                    },
                    json={
                        "model": (provider.models[0].upstream_name if provider.models else "claude-3-haiku-20240307"),
                        "max_tokens": 1,
                        "messages": [{"role": "user", "content": "hi"}],
                    },
                )
            if resp.status_code < 400:
                return {"ok": True, "detail": f"连接成功 (HTTP {resp.status_code})"}
            try:
                err = resp.json()
                msg = err.get("error", {}).get("message") or str(err)
            except Exception:
                msg = resp.text[:200]
            return {"ok": False, "detail": f"HTTP {resp.status_code}: {msg}"}

    except httpx.RequestError as exc:
        return {"ok": False, "detail": f"网络错误: {exc}"}


async def fetch_upstream_models(provider: ProviderConfig) -> list[str]:
    """从上游 /v1/models 拉取模型 ID 列表（仅 OpenAI 协议支持）。"""
    if provider.protocol != "openai":
        return []
    if not provider.api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                _build_url(provider.base_url, "/v1/models"),
                headers={"Authorization": f"Bearer {provider.api_key}"},
            )
        if resp.status_code >= 400:
            return []
        data = resp.json()
        models = data.get("data") or []
        return sorted(m["id"] for m in models if isinstance(m, dict) and m.get("id"))
    except Exception:
        return []


def list_all_model_aliases(config: AppConfig) -> list[str]:
    aliases = {model.alias for provider in config.providers for model in provider.models}
    return sorted(aliases)


def resolve_provider_and_model(
    config: AppConfig, model_alias: str
) -> tuple[ProviderConfig, ProviderModel]:
    for provider in config.providers:
        for model in provider.models:
            if model.alias == model_alias:
                if not model.enabled:
                    raise HTTPException(
                        status_code=403,
                        detail=f"Model '{model_alias}' is currently disabled.",
                    )
                if not provider.api_key:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Provider '{provider.id}' has no api_key configured. "
                            "Set it in /api/config first."
                        ),
                    )
                return provider, model
    raise HTTPException(status_code=404, detail=f"Unknown model '{model_alias}'.")


def assert_key_can_use_model(local_key: LocalKeyRecord, model_alias: str) -> None:
    if local_key.allowed_models and model_alias not in local_key.allowed_models:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Local key '{local_key.id}' is not allowed to use model '{model_alias}'."
            ),
        )


def _openai_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        maybe_text = content.get("text")
        if isinstance(maybe_text, str):
            return maybe_text
        return str(content)
    if isinstance(content, list):
        chunks: list[str] = []
        for block in content:
            if isinstance(block, str):
                chunks.append(block)
                continue
            if isinstance(block, dict):
                block_type = block.get("type")
                if block_type in ("text", "input_text", "output_text") and isinstance(
                    block.get("text"), str
                ):
                    chunks.append(block["text"])
                elif isinstance(block.get("content"), str):
                    chunks.append(block["content"])
        return "\n".join(chunks)
    return ""


def _anthropic_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    texts.append(text)
        return "\n".join(texts)
    if isinstance(content, dict):
        maybe_text = content.get("text")
        if isinstance(maybe_text, str):
            return maybe_text
    return ""


def _normalize_role(value: str | None) -> str:
    if value in ("assistant", "system", "user"):
        return value
    return "user"


def _responses_input_to_messages(input_value: Any) -> list[dict[str, str]]:
    if isinstance(input_value, str):
        return [{"role": "user", "content": input_value}]

    if not isinstance(input_value, list):
        raise HTTPException(status_code=400, detail="input must be a string or list.")

    messages: list[dict[str, str]] = []
    for item in input_value:
        if isinstance(item, str):
            messages.append({"role": "user", "content": item})
            continue

        if not isinstance(item, dict):
            continue

        role = _normalize_role(item.get("role"))

        if "content" in item:
            content_text = _openai_content_to_text(item.get("content"))
            messages.append({"role": role, "content": content_text})
            continue

        if item.get("type") in ("input_text", "output_text") and isinstance(
            item.get("text"), str
        ):
            messages.append({"role": role, "content": item["text"]})

    if not messages:
        raise HTTPException(status_code=400, detail="No usable messages in input.")

    return messages


def normalize_openai_chat_payload(payload: dict[str, Any]) -> dict[str, Any]:
    model = payload.get("model")
    if not isinstance(model, str) or not model:
        raise HTTPException(status_code=400, detail="Request body requires model.")

    messages: Any = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        if "input" in payload:
            messages = _responses_input_to_messages(payload.get("input"))
        elif "prompt" in payload:
            prompt = payload.get("prompt")
            if isinstance(prompt, str) and prompt:
                messages = [{"role": "user", "content": prompt}]
            else:
                raise HTTPException(status_code=400, detail="prompt must be a string.")
        else:
            raise HTTPException(
                status_code=400,
                detail="Request requires messages, input, or prompt.",
            )

    normalized: dict[str, Any] = {"model": model, "messages": messages}

    max_tokens = (
        payload.get("max_tokens")
        or payload.get("max_completion_tokens")
        or payload.get("max_output_tokens")
    )
    if max_tokens is not None:
        normalized["max_tokens"] = max_tokens

    for field in (
        "temperature",
        "top_p",
        "stop",
        "stream",
        "presence_penalty",
        "frequency_penalty",
        "seed",
        "n",
        "user",
    ):
        if field in payload:
            normalized[field] = payload[field]

    return normalized


def openai_chat_response_to_responses_api(response: dict[str, Any]) -> dict[str, Any]:
    choices = response.get("choices")
    first = choices[0] if isinstance(choices, list) and choices else {}
    message = first.get("message") if isinstance(first, dict) else {}
    if not isinstance(message, dict):
        message = {}

    output_text = _openai_content_to_text(message.get("content", ""))

    usage = response.get("usage")
    if not isinstance(usage, dict):
        usage = {}

    return {
        "id": response.get("id", "resp-local"),
        "object": "response",
        "created_at": response.get("created", int(time.time())),
        "status": "completed",
        "model": response.get("model", ""),
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": output_text,
                        "annotations": [],
                    }
                ],
            }
        ],
        "output_text": output_text,
        "usage": {
            "input_tokens": int(usage.get("prompt_tokens") or 0),
            "output_tokens": int(usage.get("completion_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
        },
    }


def openai_chat_response_to_completions(response: dict[str, Any]) -> dict[str, Any]:
    choices = response.get("choices")
    first = choices[0] if isinstance(choices, list) and choices else {}
    message = first.get("message") if isinstance(first, dict) else {}
    if not isinstance(message, dict):
        message = {}

    completion_text = _openai_content_to_text(message.get("content", ""))

    return {
        "id": response.get("id", "cmpl-local"),
        "object": "text_completion",
        "created": response.get("created", int(time.time())),
        "model": response.get("model", ""),
        "choices": [
            {
                "text": completion_text,
                "index": 0,
                "logprobs": None,
                "finish_reason": first.get("finish_reason") if isinstance(first, dict) else "stop",
            }
        ],
        "usage": response.get("usage", {}),
    }


def legacy_anthropic_complete_to_messages_request(
    payload: dict[str, Any]
) -> dict[str, Any]:
    model = payload.get("model")
    if not isinstance(model, str) or not model:
        raise HTTPException(status_code=400, detail="Request body requires model.")

    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise HTTPException(status_code=400, detail="prompt must be a non-empty string.")

    normalized_prompt = prompt.replace("\r\n", "\n")
    normalized_prompt = normalized_prompt.replace("\n\nHuman:", "")
    normalized_prompt = normalized_prompt.replace("\n\nAssistant:", "")
    normalized_prompt = normalized_prompt.strip()

    converted: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": normalized_prompt}],
        "max_tokens": payload.get("max_tokens_to_sample") or 1024,
    }

    for source, target in (
        ("temperature", "temperature"),
        ("top_p", "top_p"),
        ("stop_sequences", "stop_sequences"),
    ):
        if source in payload:
            converted[target] = payload[source]

    return converted


def anthropic_message_response_to_legacy_complete(
    response: dict[str, Any]
) -> dict[str, Any]:
    return {
        "id": response.get("id", "compl-local"),
        "type": "completion",
        "model": response.get("model", ""),
        "completion": _anthropic_content_to_text(response.get("content", [])),
        "stop_reason": response.get("stop_reason"),
    }


def _map_anthropic_stop_reason(value: str | None) -> str:
    mapping = {
        "end_turn": "stop",
        "max_tokens": "length",
        "tool_use": "tool_calls",
    }
    return mapping.get(value or "", "stop")


def _map_openai_finish_reason(value: str | None) -> str:
    mapping = {
        "stop": "end_turn",
        "length": "max_tokens",
        "tool_calls": "tool_use",
    }
    return mapping.get(value or "", "end_turn")


def openai_chat_request_to_anthropic(
    payload: dict[str, Any], upstream_model: str
) -> dict[str, Any]:
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise HTTPException(status_code=400, detail="messages must be a non-empty list.")

    system_parts: list[str] = []
    anthropic_messages: list[dict[str, str]] = []

    for message in messages:
        if not isinstance(message, dict):
            continue

        role = message.get("role")
        content = _openai_content_to_text(message.get("content", ""))

        if role == "system":
            if content:
                system_parts.append(content)
            continue

        if role not in ("user", "assistant"):
            role = "user"
            content = f"[{message.get('role', 'unknown')}] {content}".strip()

        anthropic_messages.append({"role": role, "content": content})

    if not anthropic_messages:
        raise HTTPException(status_code=400, detail="No usable user/assistant messages.")

    converted: dict[str, Any] = {
        "model": upstream_model,
        "messages": anthropic_messages,
        "max_tokens": payload.get("max_tokens")
        or payload.get("max_completion_tokens")
        or 1024,
    }

    if system_parts:
        converted["system"] = "\n\n".join(system_parts)

    for field in ("temperature", "top_p", "stop"):
        if field in payload:
            converted[field] = payload[field]

    return converted


def anthropic_messages_request_to_openai_chat(
    payload: dict[str, Any], upstream_model: str
) -> dict[str, Any]:
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise HTTPException(status_code=400, detail="messages must be a non-empty list.")

    openai_messages: list[dict[str, str]] = []

    system_content = payload.get("system")
    if isinstance(system_content, str) and system_content.strip():
        openai_messages.append({"role": "system", "content": system_content})
    elif isinstance(system_content, list):
        system_text = _anthropic_content_to_text(system_content)
        if system_text:
            openai_messages.append({"role": "system", "content": system_text})

    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role not in ("user", "assistant"):
            continue
        openai_messages.append(
            {
                "role": role,
                "content": _anthropic_content_to_text(message.get("content", "")),
            }
        )

    if not openai_messages:
        raise HTTPException(
            status_code=400,
            detail="No usable messages after conversion to OpenAI format.",
        )

    converted: dict[str, Any] = {
        "model": upstream_model,
        "messages": openai_messages,
        "max_tokens": payload.get("max_tokens") or 1024,
    }

    for field in ("temperature", "top_p"):
        if field in payload:
            converted[field] = payload[field]

    if "stop_sequences" in payload:
        converted["stop"] = payload["stop_sequences"]

    return converted


def anthropic_response_to_openai_chat(
    response: dict[str, Any], local_model: str
) -> dict[str, Any]:
    usage = response.get("usage")
    if not isinstance(usage, dict):
        usage = {}

    prompt_tokens = int(usage.get("input_tokens") or 0)
    completion_tokens = int(usage.get("output_tokens") or 0)

    return {
        "id": response.get("id", "chatcmpl-local"),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": local_model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": _anthropic_content_to_text(response.get("content", [])),
                },
                "finish_reason": _map_anthropic_stop_reason(
                    response.get("stop_reason")
                ),
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def openai_response_to_anthropic_message(
    response: dict[str, Any], local_model: str
) -> dict[str, Any]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise HTTPException(
            status_code=502,
            detail="Upstream OpenAI response has no choices to convert.",
        )

    first = choices[0]
    if not isinstance(first, dict):
        first = {}

    message = first.get("message")
    if not isinstance(message, dict):
        message = {}

    usage = response.get("usage")
    if not isinstance(usage, dict):
        usage = {}

    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)

    assistant_text = _openai_content_to_text(message.get("content", ""))

    return {
        "id": response.get("id", "msg-local"),
        "type": "message",
        "role": "assistant",
        "model": local_model,
        "content": [{"type": "text", "text": assistant_text}],
        "stop_reason": _map_openai_finish_reason(first.get("finish_reason")),
        "stop_sequence": None,
        "usage": {
            "input_tokens": prompt_tokens,
            "output_tokens": completion_tokens,
        },
    }


async def _post_json(
    url: str, headers: dict[str, str], payload: dict[str, Any]
) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to reach upstream provider: {exc}",
        ) from exc

    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type.lower():
        try:
            data: Any = response.json()
        except ValueError:
            data = {"raw": response.text}
    else:
        data = {"raw": response.text}

    if response.status_code >= 400:
        raise HTTPException(
            status_code=response.status_code,
            detail={
                "upstream_url": url,
                "upstream_status": response.status_code,
                "upstream_error": data,
            },
        )

    if not isinstance(data, dict):
        raise HTTPException(
            status_code=502,
            detail="Upstream response must be a JSON object.",
        )

    return data


async def _stream_upstream(
    url: str, headers: dict[str, str], payload: dict[str, Any]
) -> AsyncIterator[bytes]:
    """逐行转发上游 SSE 流，不做内容解析。"""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    try:
                        err = json.loads(body)
                    except ValueError:
                        err = {"raw": body.decode("utf-8", errors="replace")}
                    raise HTTPException(
                        status_code=response.status_code,
                        detail={
                            "upstream_url": url,
                            "upstream_status": response.status_code,
                            "upstream_error": err,
                        },
                    )
                async for line in response.aiter_lines():
                    yield (line + "\n").encode()
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to reach upstream provider: {exc}",
        ) from exc


def _openai_stream_to_anthropic_stream(
    local_model: str,
) -> "type[_OpenAIToAnthropicStreamAdapter]":
    """返回一个适配器类，用于在 relay_messages 的跨协议 streaming 场景中使用。"""
    return _OpenAIToAnthropicStreamAdapter(local_model)


class _OpenAIToAnthropicStreamAdapter:
    """把 OpenAI chat.completion SSE 流转换为 Anthropic messages SSE 流。"""

    def __init__(self, local_model: str) -> None:
        self._local_model = local_model
        self._msg_id = f"msg-{int(time.time())}"
        self._input_tokens = 0
        self._output_tokens = 0
        self._sent_start = False
        self._sent_delta = False

    def _make_event(self, event: str, data: dict[str, Any]) -> bytes:
        return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()

    def start_block(self) -> bytes:
        self._sent_start = True
        return (
            self._make_event("message_start", {
                "type": "message_start",
                "message": {
                    "id": self._msg_id,
                    "type": "message",
                    "role": "assistant",
                    "model": self._local_model,
                    "content": [],
                    "stop_reason": None,
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                },
            })
            + self._make_event("content_block_start", {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            })
            + b"event: ping\ndata: {\"type\":\"ping\"}\n\n"
        )

    def convert_chunk(self, raw_line: bytes) -> bytes | None:
        """把一行 OpenAI SSE data 转换为 Anthropic SSE 格式，返回 None 表示跳过。"""
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line.startswith("data:"):
            return None
        payload_str = line[5:].strip()
        if payload_str == "[DONE]":
            return None
        try:
            chunk = json.loads(payload_str)
        except ValueError:
            return None

        choice = (chunk.get("choices") or [{}])[0]
        delta = choice.get("delta") or {}
        text = delta.get("content") or ""
        finish_reason = choice.get("finish_reason")

        usage = chunk.get("usage") or {}
        if usage.get("prompt_tokens"):
            self._input_tokens = int(usage["prompt_tokens"])
        if usage.get("completion_tokens"):
            self._output_tokens = int(usage["completion_tokens"])

        out = b""
        if not self._sent_start:
            out += self.start_block()

        if text:
            out += self._make_event("content_block_delta", {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": text},
            })

        if finish_reason is not None:
            stop_reason = _map_openai_finish_reason(finish_reason)
            out += (
                self._make_event("content_block_stop", {"type": "content_block_stop", "index": 0})
                + self._make_event("message_delta", {
                    "type": "message_delta",
                    "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                    "usage": {"output_tokens": self._output_tokens},
                })
                + self._make_event("message_stop", {"type": "message_stop"})
            )

        return out if out else None


class _AnthropicToOpenAIStreamAdapter:
    """把 Anthropic messages SSE 流转换为 OpenAI chat.completion SSE 流。"""

    def __init__(self, local_model: str) -> None:
        self._local_model = local_model
        self._cmpl_id = f"chatcmpl-{int(time.time())}"
        self._input_tokens = 0
        self._output_tokens = 0
        self._sent_role = False

    def _make_chunk(self, delta: dict[str, Any], finish_reason: str | None = None) -> bytes:
        chunk = {
            "id": self._cmpl_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": self._local_model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }
        return f"data: {json.dumps(chunk)}\n\n".encode()

    def convert_chunk(self, raw_line: bytes) -> bytes | None:
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line.startswith("data:"):
            return None
        payload_str = line[5:].strip()
        try:
            event_data = json.loads(payload_str)
        except ValueError:
            return None

        event_type = event_data.get("type")
        out = b""

        if event_type == "message_start":
            usage = (event_data.get("message") or {}).get("usage") or {}
            self._input_tokens = int(usage.get("input_tokens") or 0)
            if not self._sent_role:
                self._sent_role = True
                out += self._make_chunk({"role": "assistant", "content": ""})

        elif event_type == "content_block_delta":
            delta = event_data.get("delta") or {}
            text = delta.get("text") or ""
            if text:
                out += self._make_chunk({"content": text})

        elif event_type == "message_delta":
            delta = event_data.get("delta") or {}
            stop_reason = _map_anthropic_stop_reason(delta.get("stop_reason"))
            usage = event_data.get("usage") or {}
            self._output_tokens = int(usage.get("output_tokens") or 0)
            out += self._make_chunk({}, finish_reason=stop_reason)

        elif event_type == "message_stop":
            out += b"data: [DONE]\n\n"

        return out if out else None


async def relay_chat_completion(
    payload: dict[str, Any],
    provider: ProviderConfig,
    provider_model: ProviderModel,
    local_model: str,
) -> dict[str, Any]:
    if provider.protocol == "openai":
        forward_payload = dict(payload)
        forward_payload["model"] = provider_model.upstream_name

        upstream = await _post_json(
            url=_build_url(provider.base_url, "/v1/chat/completions"),
            headers={"Authorization": f"Bearer {provider.api_key}"},
            payload=forward_payload,
        )
        upstream["model"] = local_model
        return upstream

    converted = openai_chat_request_to_anthropic(payload, provider_model.upstream_name)
    upstream = await _post_json(
        url=_build_url(provider.base_url, "/v1/messages"),
        headers={
            "x-api-key": provider.api_key,
            "anthropic-version": "2023-06-01",
        },
        payload=converted,
    )
    return anthropic_response_to_openai_chat(upstream, local_model)


async def stream_chat_completion(
    payload: dict[str, Any],
    provider: ProviderConfig,
    provider_model: ProviderModel,
    local_model: str,
) -> AsyncIterator[bytes]:
    """Streaming 版本的 chat completion 转发，返回 OpenAI SSE 格式字节流。"""
    if provider.protocol == "openai":
        forward_payload = {**payload, "model": provider_model.upstream_name, "stream": True}
        async for chunk in _stream_upstream(
            url=_build_url(provider.base_url, "/v1/chat/completions"),
            headers={"Authorization": f"Bearer {provider.api_key}"},
            payload=forward_payload,
        ):
            yield chunk
        return

    # openai -> anthropic 跨协议 streaming
    converted = openai_chat_request_to_anthropic(
        {**payload, "stream": False}, provider_model.upstream_name
    )
    converted["stream"] = True
    adapter = _AnthropicToOpenAIStreamAdapter(local_model)
    async for raw in _stream_upstream(
        url=_build_url(provider.base_url, "/v1/messages"),
        headers={
            "x-api-key": provider.api_key,
            "anthropic-version": "2023-06-01",
        },
        payload=converted,
    ):
        result = adapter.convert_chunk(raw)
        if result:
            yield result


async def relay_messages(
    payload: dict[str, Any],
    provider: ProviderConfig,
    provider_model: ProviderModel,
    local_model: str,
) -> dict[str, Any]:
    if provider.protocol == "anthropic":
        forward_payload = dict(payload)
        forward_payload["model"] = provider_model.upstream_name

        upstream = await _post_json(
            url=_build_url(provider.base_url, "/v1/messages"),
            headers={
                "x-api-key": provider.api_key,
                "anthropic-version": "2023-06-01",
            },
            payload=forward_payload,
        )
        upstream["model"] = local_model
        return upstream

    converted = anthropic_messages_request_to_openai_chat(
        payload, provider_model.upstream_name
    )
    upstream = await _post_json(
        url=_build_url(provider.base_url, "/v1/chat/completions"),
        headers={"Authorization": f"Bearer {provider.api_key}"},
        payload=converted,
    )
    return openai_response_to_anthropic_message(upstream, local_model)


async def stream_messages(
    payload: dict[str, Any],
    provider: ProviderConfig,
    provider_model: ProviderModel,
    local_model: str,
) -> AsyncIterator[bytes]:
    """Streaming 版本的 messages 转发，返回 Anthropic SSE 格式字节流。"""
    if provider.protocol == "anthropic":
        forward_payload = {**payload, "model": provider_model.upstream_name, "stream": True}
        async for chunk in _stream_upstream(
            url=_build_url(provider.base_url, "/v1/messages"),
            headers={
                "x-api-key": provider.api_key,
                "anthropic-version": "2023-06-01",
            },
            payload=forward_payload,
        ):
            yield chunk
        return

    # anthropic -> openai 跨协议 streaming
    converted = anthropic_messages_request_to_openai_chat(
        {k: v for k, v in payload.items() if k != "stream"},
        provider_model.upstream_name,
    )
    converted["stream"] = True
    adapter = _OpenAIToAnthropicStreamAdapter(local_model)
    async for raw in _stream_upstream(
        url=_build_url(provider.base_url, "/v1/chat/completions"),
        headers={"Authorization": f"Bearer {provider.api_key}"},
        payload=converted,
    ):
        result = adapter.convert_chunk(raw)
        if result:
            yield result
