# Local AI API Gateway

一个本地 AI API 网关，将请求转发给不同的 AI 供应商，并通过本地 API Key 实现模型级别的访问控制。

## 功能特性

- **可视化 Web 管理界面**（React 18 + Ant Design 5.x）
- **多供应商管理**：支持 OpenAI 协议 / Anthropic 协议
- **跨协议转发**：OpenAI 请求 ↔ Anthropic 上游，自动适配
- **本地 API Key 管理**：生成本地密钥，可指定可用模型白名单
- **AES 加密持久化**：api_key 字段加密存储，防止明文泄露
- **连接测试**：一键验证供应商 API Key 是否有效
- **模型快速导入**：从上游 `/v1/models` 批量导入模型
- **流式响应**：支持 `stream=true` SSE 流式输出
- **接入文档**：内置完整的接入示例（curl / Python SDK）

## 支持的代理端点

| 端点 | 协议 | 说明 |
|------|------|------|
| `GET /v1/models` | OpenAI | 列出所有已启用模型（标准 models 接口） |
| `POST /v1/chat/completions` | OpenAI | 标准 Chat Completions |
| `POST /v1/completions` | OpenAI | Legacy Completions（兼容） |
| `POST /v1/responses` | OpenAI Responses API | Responses API（兼容） |
| `POST /v1/messages` | Anthropic | Messages API |
| `POST /v1/complete` | Anthropic Legacy | Legacy Complete（兼容） |

## 快速开始

### 1. 安装依赖

```bash
python -m venv .venv
# Windows
.\.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. 启动服务

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### 3. 打开管理界面

浏览器访问 http://127.0.0.1:8000/

在"供应商配置"页面：
1. 新增供应商，填写 `base_url`、`api_key`（不含 `/v1` 后缀）
2. 在供应商下添加模型（`alias` 为本地别名，`upstream_name` 为上游真实名称）
3. 在"本地 API Key"页面生成密钥（**只显示一次，请妥善保存**）

## 接入示例

> 将 `<LOCAL_KEY>` 替换为生成的本地密钥，`<MODEL_ALIAS>` 替换为配置的模型本地别名

### curl

**OpenAI 协议：**

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer <LOCAL_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "<MODEL_ALIAS>",
    "messages": [{"role": "user", "content": "你好！"}]
  }'
```

**OpenAI 协议（流式）：**

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer <LOCAL_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "<MODEL_ALIAS>",
    "messages": [{"role": "user", "content": "你好！"}],
    "stream": true
  }'
```

**Anthropic 协议：**

```bash
curl http://127.0.0.1:8000/v1/messages \
  -H "Authorization: Bearer <LOCAL_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "<MODEL_ALIAS>",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "你好！"}]
  }'
```

### Python（OpenAI SDK）

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8000/v1",
    api_key="<LOCAL_KEY>",
)

resp = client.chat.completions.create(
    model="<MODEL_ALIAS>",
    messages=[{"role": "user", "content": "你好！"}],
)
print(resp.choices[0].message.content)
```

**流式调用：**

```python
with client.chat.completions.stream(
    model="<MODEL_ALIAS>",
    messages=[{"role": "user", "content": "你好！"}],
) as stream:
    for chunk in stream:
        delta = chunk.choices[0].delta.content or ""
        print(delta, end="", flush=True)
```

### Python（Anthropic SDK）

```python
import anthropic

client = anthropic.Anthropic(
    base_url="http://127.0.0.1:8000",
    api_key="<LOCAL_KEY>",
)

message = client.messages.create(
    model="<MODEL_ALIAS>",
    max_tokens=1024,
    messages=[{"role": "user", "content": "你好！"}],
)
print(message.content[0].text)
```

## Cherry Studio / 第三方客户端接入

| 字段 | 填写内容 |
|------|---------|
| API Host / Base URL | `http://127.0.0.1:8000` |
| API Key | 生成的本地密钥（`lk_` 开头） |
| 模型名 | 在管理界面中配置的**本地别名**（alias） |

> **注意**：不要在 Base URL 末尾加 `/v1`；Cherry Studio 的"连接测试"按钮可能误报失败，直接发送消息验证即可。

## 配置文件格式

`data/config.json`（api_key 字段自动加密，存储为 `enc:...` 前缀）：

```json
{
  "providers": [
    {
      "id": "my-provider",
      "name": "My Provider",
      "base_url": "https://api.openai.com",
      "protocol": "openai",
      "api_key": "sk-...",
      "models": [
        {
          "alias": "gpt-4o-mini",
          "upstream_name": "gpt-4o-mini",
          "enabled": true
        }
      ]
    }
  ],
  "local_keys": []
}
```

## 注意事项

- `allowed_models` 为空时，本地密钥可访问所有已启用模型
- 本地密钥以 SHA-256 哈希存储，明文只在创建时显示一次
- api_key 使用机器唯一 ID 派生密钥加密，迁移到其他机器后需重新填写
- 流式响应完整支持（`stream: true`）
