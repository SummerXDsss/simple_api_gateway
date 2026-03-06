from __future__ import annotations

import time
from typing import Any

import httpx
from fastapi import HTTPException

from .schemas import AppConfig, LocalKeyRecord, ProviderConfig, ProviderModel


def _build_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


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
                if block_type == "text" and isinstance(block.get("text"), str):
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
    if payload.get("stream"):
        raise HTTPException(
            status_code=400,
            detail="stream=true is not supported in this MVP.",
        )

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
    if payload.get("stream"):
        raise HTTPException(
            status_code=400,
            detail="stream=true is not supported in this MVP.",
        )

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
