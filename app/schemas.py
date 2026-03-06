from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProviderModel(BaseModel):
    alias: str = Field(..., min_length=1)
    upstream_name: str = Field(..., min_length=1)
    enabled: bool = True


class ProviderConfig(BaseModel):
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    base_url: str = Field(..., min_length=1)
    protocol: Literal["openai", "anthropic"]
    api_key: str = Field("", description="Upstream provider API key")
    models: list[ProviderModel] = Field(default_factory=list)

    @field_validator("base_url")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")


class LocalKeyRecord(BaseModel):
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    key_hash: str = Field(..., min_length=64, max_length=64)
    key_prefix: str = Field(..., min_length=4)
    enabled: bool = True
    allowed_models: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class LocalKeyPublic(BaseModel):
    id: str
    name: str
    key_prefix: str
    enabled: bool
    allowed_models: list[str]
    created_at: datetime


class CreateLocalKeyResponse(LocalKeyPublic):
    plain_key: str


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    providers: list[ProviderConfig] = Field(default_factory=list)
    local_keys: list[LocalKeyRecord] = Field(default_factory=list)


class CreateLocalKeyRequest(BaseModel):
    name: str = Field("default-key", min_length=1, max_length=80)
    allowed_models: list[str] = Field(default_factory=list)


class UpdateLocalKeyRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    enabled: bool | None = None
    allowed_models: list[str] | None = None
