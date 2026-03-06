from __future__ import annotations

import json
from pathlib import Path
from threading import RLock

from .schemas import AppConfig, ProviderConfig, ProviderModel


def build_default_config() -> AppConfig:
    return AppConfig(
        providers=[
            ProviderConfig(
                id="openai-main",
                name="OpenAI Main",
                base_url="https://api.openai.com",
                protocol="openai",
                api_key="",
                models=[
                    ProviderModel(
                        alias="gpt-4.1-mini",
                        upstream_name="gpt-4.1-mini",
                        enabled=True,
                    ),
                    ProviderModel(
                        alias="gpt-4.1",
                        upstream_name="gpt-4.1",
                        enabled=False,
                    ),
                ],
            ),
            ProviderConfig(
                id="anthropic-main",
                name="Anthropic Main",
                base_url="https://api.anthropic.com",
                protocol="anthropic",
                api_key="",
                models=[
                    ProviderModel(
                        alias="claude-sonnet",
                        upstream_name="claude-3-7-sonnet-latest",
                        enabled=True,
                    )
                ],
            ),
        ],
        local_keys=[],
    )


def validate_config(config: AppConfig) -> None:
    provider_ids: set[str] = set()
    model_alias_owner: dict[str, str] = {}

    for provider in config.providers:
        if provider.id in provider_ids:
            raise ValueError(f"Duplicate provider id: {provider.id}")
        provider_ids.add(provider.id)

        provider_aliases: set[str] = set()
        for model in provider.models:
            if model.alias in provider_aliases:
                raise ValueError(
                    f"Duplicate model alias '{model.alias}' inside provider '{provider.id}'"
                )
            provider_aliases.add(model.alias)

            if model.alias in model_alias_owner:
                owner = model_alias_owner[model.alias]
                raise ValueError(
                    f"Model alias '{model.alias}' exists in both '{owner}' and '{provider.id}'"
                )
            model_alias_owner[model.alias] = provider.id

    all_models = set(model_alias_owner.keys())
    for key in config.local_keys:
        invalid = sorted(set(key.allowed_models) - all_models)
        if invalid:
            raise ValueError(
                f"Local key '{key.id}' has unknown allowed models: {', '.join(invalid)}"
            )


class ConfigStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = RLock()

    def ensure_exists(self) -> None:
        with self._lock:
            if self.path.exists():
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._write_unlocked(build_default_config())

    def load(self) -> AppConfig:
        with self._lock:
            self.ensure_exists()
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            config = AppConfig.model_validate(raw)
            validate_config(config)
            return config

    def save(self, config: AppConfig) -> AppConfig:
        with self._lock:
            validate_config(config)
            self._write_unlocked(config)
            return config

    def _write_unlocked(self, config: AppConfig) -> None:
        serialized = json.dumps(config.model_dump(mode="json"), indent=2, ensure_ascii=True)
        self.path.write_text(serialized + "\n", encoding="utf-8")
