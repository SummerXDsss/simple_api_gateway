from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config_store import ConfigStore
from .relay import (
    anthropic_message_response_to_legacy_complete,
    assert_key_can_use_model,
    fetch_upstream_models,
    legacy_anthropic_complete_to_messages_request,
    list_all_model_aliases,
    normalize_openai_chat_payload,
    openai_chat_response_to_completions,
    openai_chat_response_to_responses_api,
    relay_chat_completion,
    relay_messages,
    resolve_provider_and_model,
    stream_chat_completion,
    stream_messages,
    test_provider_connection,
)
from .schemas import (
    AppConfig,
    CreateLocalKeyRequest,
    CreateLocalKeyResponse,
    LocalKeyPublic,
    LocalKeyRecord,
    UpdateLocalKeyRequest,
)
from .security import generate_local_api_key, verify_local_api_key

STORE = ConfigStore(Path("data/config.json"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    STORE.ensure_exists()
    yield


app = FastAPI(title="Local AI API Aggregator", version="0.3.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


def _to_public_local_key(record: LocalKeyRecord) -> LocalKeyPublic:
    return LocalKeyPublic(
        id=record.id,
        name=record.name,
        key_prefix=record.key_prefix,
        enabled=record.enabled,
        allowed_models=record.allowed_models,
        created_at=record.created_at,
    )


def _validate_allowed_models(config: AppConfig, allowed_models: list[str]) -> None:
    existing = set(list_all_model_aliases(config))
    invalid = sorted(set(allowed_models) - existing)
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown models in allowed_models: {', '.join(invalid)}",
        )


def _extract_local_api_key(request: Request) -> str:
    authorization = request.headers.get("Authorization", "")
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing local API key. Use Authorization: Bearer <local_key>",
        )

    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Empty local API key.")
    return token


def _authenticate_local_key(request: Request, config: AppConfig) -> LocalKeyRecord:
    plain_key = _extract_local_api_key(request)
    record = verify_local_api_key(plain_key, config.local_keys)
    if not record:
        raise HTTPException(status_code=401, detail="Invalid or disabled local API key.")
    return record


async def _relay_openai_compatible(
    payload: dict[str, Any], request: Request
) -> dict[str, Any] | StreamingResponse:
    config = STORE.load()
    local_key = _authenticate_local_key(request, config)

    normalized_payload = normalize_openai_chat_payload(payload)
    model_alias = normalized_payload["model"]

    provider, provider_model = resolve_provider_and_model(config, model_alias)
    assert_key_can_use_model(local_key, model_alias)

    if normalized_payload.get("stream"):
        return StreamingResponse(
            stream_chat_completion(normalized_payload, provider, provider_model, model_alias),
            media_type="text/event-stream",
        )

    return await relay_chat_completion(
        normalized_payload,
        provider,
        provider_model,
        model_alias,
    )


async def _relay_anthropic_messages_compatible(
    payload: dict[str, Any], request: Request
) -> dict[str, Any] | StreamingResponse:
    config = STORE.load()
    local_key = _authenticate_local_key(request, config)

    model_alias = payload.get("model")
    if not isinstance(model_alias, str) or not model_alias:
        raise HTTPException(status_code=400, detail="Request body requires model.")

    provider, provider_model = resolve_provider_and_model(config, model_alias)
    assert_key_can_use_model(local_key, model_alias)

    if payload.get("stream"):
        return StreamingResponse(
            stream_messages(payload, provider, provider_model, model_alias),
            media_type="text/event-stream",
        )

    return await relay_messages(payload, provider, provider_model, model_alias)


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(Path("static/index.html"))


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config", response_model=AppConfig)
def get_config() -> AppConfig:
    return STORE.load()


@app.put("/api/config", response_model=AppConfig)
def put_config(config: AppConfig) -> AppConfig:
    try:
        return STORE.save(config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/models")
def get_models() -> dict[str, list[dict[str, Any]]]:
    config = STORE.load()
    models: list[dict[str, Any]] = []

    for provider in config.providers:
        for model in provider.models:
            models.append(
                {
                    "alias": model.alias,
                    "upstream_name": model.upstream_name,
                    "enabled": model.enabled,
                    "provider_id": provider.id,
                    "provider_protocol": provider.protocol,
                }
            )

    return {"models": models}


@app.get("/v1/models")
def list_models_openai_compat() -> dict[str, Any]:
    """Standard OpenAI-compatible GET /v1/models endpoint.

    Returns all enabled models as OpenAI model objects so that clients
    like Cherry Studio, Cursor, and the OpenAI SDK can enumerate them.
    """
    import time as _time

    config = STORE.load()
    data: list[dict[str, Any]] = []

    for provider in config.providers:
        for model in provider.models:
            if not model.enabled:
                continue
            data.append(
                {
                    "id": model.alias,
                    "object": "model",
                    "created": int(_time.time()),
                    "owned_by": provider.name or provider.id,
                }
            )

    return {"object": "list", "data": data}


@app.get("/api/local-keys", response_model=list[LocalKeyPublic])
def list_local_keys() -> list[LocalKeyPublic]:
    config = STORE.load()
    return [_to_public_local_key(record) for record in config.local_keys]


@app.post("/api/local-keys", response_model=CreateLocalKeyResponse)
def create_local_key(request: CreateLocalKeyRequest) -> CreateLocalKeyResponse:
    config = STORE.load()
    _validate_allowed_models(config, request.allowed_models)

    plain_key, key_hash, key_prefix = generate_local_api_key()
    record = LocalKeyRecord(
        id=f"lk_{uuid4().hex[:12]}",
        name=request.name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        enabled=True,
        allowed_models=request.allowed_models,
    )

    config.local_keys.append(record)
    try:
        STORE.save(config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    public = _to_public_local_key(record)
    return CreateLocalKeyResponse(**public.model_dump(), plain_key=plain_key)


@app.patch("/api/local-keys/{key_id}", response_model=LocalKeyPublic)
def update_local_key(key_id: str, request: UpdateLocalKeyRequest) -> LocalKeyPublic:
    config = STORE.load()

    target: LocalKeyRecord | None = None
    for record in config.local_keys:
        if record.id == key_id:
            target = record
            break

    if target is None:
        raise HTTPException(status_code=404, detail=f"Local key '{key_id}' not found.")

    if request.name is not None:
        target.name = request.name
    if request.enabled is not None:
        target.enabled = request.enabled
    if request.allowed_models is not None:
        _validate_allowed_models(config, request.allowed_models)
        target.allowed_models = request.allowed_models

    try:
        STORE.save(config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _to_public_local_key(target)


@app.delete("/api/local-keys/{key_id}")
def delete_local_key(key_id: str) -> dict[str, bool]:
    config = STORE.load()
    before = len(config.local_keys)
    config.local_keys = [record for record in config.local_keys if record.id != key_id]

    if len(config.local_keys) == before:
        raise HTTPException(status_code=404, detail=f"Local key '{key_id}' not found.")

    try:
        STORE.save(config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"deleted": True}


@app.post("/api/providers/{provider_id}/test")
async def test_provider(provider_id: str) -> dict[str, Any]:
    config = STORE.load()
    provider = next((p for p in config.providers if p.id == provider_id), None)
    if provider is None:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found.")
    return await test_provider_connection(provider)


@app.get("/api/providers/{provider_id}/upstream-models")
async def get_upstream_models(provider_id: str) -> dict[str, Any]:
    config = STORE.load()
    provider = next((p for p in config.providers if p.id == provider_id), None)
    if provider is None:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found.")
    models = await fetch_upstream_models(provider)
    return {"models": models}


@app.post("/v1/chat/completions", response_model=None)
async def openai_chat_proxy(payload: dict[str, Any], request: Request) -> StreamingResponse | JSONResponse:
    result = await _relay_openai_compatible(payload, request)
    if isinstance(result, StreamingResponse):
        return result
    return JSONResponse(content=result)


@app.post("/v1/responses", response_model=None)
async def openai_responses_proxy(payload: dict[str, Any], request: Request) -> JSONResponse | StreamingResponse:
    result = await _relay_openai_compatible(payload, request)
    if isinstance(result, StreamingResponse):
        return result
    return JSONResponse(content=openai_chat_response_to_responses_api(result))


@app.post("/v1/completions", response_model=None)
async def openai_legacy_completions_proxy(
    payload: dict[str, Any], request: Request
) -> JSONResponse | StreamingResponse:
    result = await _relay_openai_compatible(payload, request)
    if isinstance(result, StreamingResponse):
        return result
    return JSONResponse(content=openai_chat_response_to_completions(result))


@app.post("/v1/messages", response_model=None)
async def anthropic_messages_proxy(
    payload: dict[str, Any], request: Request
) -> StreamingResponse | JSONResponse:
    result = await _relay_anthropic_messages_compatible(payload, request)
    if isinstance(result, StreamingResponse):
        return result
    return JSONResponse(content=result)


@app.post("/v1/complete", response_model=None)
async def anthropic_legacy_complete_proxy(
    payload: dict[str, Any], request: Request
) -> JSONResponse | StreamingResponse:
    converted = legacy_anthropic_complete_to_messages_request(payload)
    result = await _relay_anthropic_messages_compatible(converted, request)
    if isinstance(result, StreamingResponse):
        return result
    return JSONResponse(content=anthropic_message_response_to_legacy_complete(result))
