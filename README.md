# Local AI API Aggregator (Python)

A local API gateway that forwards requests to different AI providers and lets you control model-level access by local API keys.

## Features

- Provider config in JSON (stored locally):
  - `base_url`
  - `protocol` (`openai` or `anthropic`)
  - `api_key`
  - multiple models (`alias`, `upstream_name`, `enabled`)
- Browser UI to edit JSON config with a visual editor
- Generate local relay API keys
- Per-key model whitelist control
- Proxy endpoints:
  - `POST /v1/chat/completions` (OpenAI-style local endpoint)
  - `POST /v1/messages` (Anthropic-style local endpoint)
- Supports cross-protocol forwarding:
  - OpenAI request -> Anthropic upstream
  - Anthropic request -> OpenAI upstream

## Quick Start

1. Create virtual env and install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2. Start server:

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8787 --reload
```

3. Open UI:

- http://127.0.0.1:8787/

## Config Schema

`data/config.json`

```json
{
  "providers": [
    {
      "id": "openai-main",
      "name": "OpenAI Main",
      "base_url": "https://api.openai.com",
      "protocol": "openai",
      "api_key": "",
      "models": [
        {
          "alias": "gpt-4.1-mini",
          "upstream_name": "gpt-4.1-mini",
          "enabled": true
        }
      ]
    }
  ],
  "local_keys": []
}
```

## Example Calls

1) OpenAI style local endpoint:

```bash
curl http://127.0.0.1:8787/v1/chat/completions \
  -H "Authorization: Bearer <LOCAL_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4.1-mini",
    "messages": [{"role": "user", "content": "hello"}]
  }'
```

2) Anthropic style local endpoint:

```bash
curl http://127.0.0.1:8787/v1/messages \
  -H "Authorization: Bearer <LOCAL_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-sonnet",
    "max_tokens": 256,
    "messages": [{"role": "user", "content": "hello"}]
  }'
```

## Notes

- Current MVP does not support streaming (`stream=true`).
- `allowed_models` empty means the key can access all enabled models.
- Local keys are stored as SHA-256 hash only; plaintext key is shown once at creation time.
