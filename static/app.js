/* global React, ReactDOM, antd, icons, marked */
"use strict";

// @ant-design/icons UMD exposes global 'icons'
const AntdIcons = window.icons || {};

const { useState, useEffect, useCallback } = React;
const {
  Layout, Typography, Card, Button, Input, Select, Switch, Table, Tag, Modal,
  Checkbox, Space, Form, Divider, message, Spin, Empty, Tooltip, Badge,
  Alert, Row, Col,
} = antd;
const { Header, Content } = Layout;
const { Title, Text, Paragraph } = Typography;

// ─── Utils ───────────────────────────────────────────────────────────────────

function formatDateTime(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("zh-CN", {
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
  } catch (_) { return iso; }
}

async function apiFetch(url, options = {}) {
  const merged = {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  };
  const response = await fetch(url, merged);
  const raw = await response.text();
  let parsed = null;
  if (raw) { try { parsed = JSON.parse(raw); } catch (_) { parsed = null; } }
  if (!response.ok) {
    const detail = parsed?.detail ?? raw ?? "request failed";
    throw new Error(`${response.status} ${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
  }
  return parsed ?? raw ?? null;
}

function ensureConfigShape(config) {
  return {
    providers: Array.isArray(config?.providers) ? config.providers : [],
    local_keys: Array.isArray(config?.local_keys) ? config.local_keys : [],
  };
}

function makeDefaultProvider(count) {
  const idx = count + 1;
  return {
    id: `provider-${idx}`,
    name: `Provider ${idx}`,
    base_url: "https://api.openai.com",
    protocol: "openai",
    api_key: "",
    models: [{ alias: `model-${idx}-1`, upstream_name: "", enabled: true }],
  };
}

function makeDefaultModel() {
  return { alias: "", upstream_name: "", enabled: true };
}

// ─── API Key Row ──────────────────────────────────────────────────────────────

function ApiKeyRow({ providerId, apiKey, onChange }) {
  const [testStatus, setTestStatus] = useState(null); // null | 'loading' | 'ok' | 'fail'
  const [testMsg, setTestMsg] = useState("");

  async function handleTest() {
    setTestStatus("loading");
    setTestMsg("");
    try {
      const res = await apiFetch(`/api/providers/${encodeURIComponent(providerId)}/test`, { method: "POST" });
      if (res.ok) {
        setTestStatus("ok");
        setTestMsg("连接成功");
      } else {
        setTestStatus("fail");
        setTestMsg(res.detail || "连接失败");
      }
    } catch (err) {
      setTestStatus("fail");
      setTestMsg(err.message);
    }
  }

  return React.createElement(React.Fragment, null,
    React.createElement(Form.Item, { label: "API_KEY", style: { marginBottom: 0 } },
      React.createElement(Space.Compact, { style: { width: "100%" } },
        React.createElement(Input, {
          value: apiKey,
          onChange: (e) => onChange(e.target.value),
          placeholder: "sk-...",
          allowClear: true,
          style: { flex: 1 },
        }),
        React.createElement(Button, {
          onClick: handleTest,
          loading: testStatus === "loading",
          icon: testStatus === "loading" ? null : React.createElement(AntdIcons.ApiOutlined),
        }, "测试连接"),
      ),
    ),
    testStatus && testStatus !== "loading" && React.createElement(
      Alert,
      {
        type: testStatus === "ok" ? "success" : "error",
        message: testStatus === "ok" ? "✓ 连接成功" : `✗ ${testMsg}`,
        showIcon: true,
        style: { marginTop: 6, marginBottom: 6 },
        closable: true,
        onClose: () => setTestStatus(null),
      }
    ),
  );
}

// ─── Import Models Modal ──────────────────────────────────────────────────────

function ImportModelsModal({ providerId, existingAliases, onImport, onClose }) {
  const [loading, setLoading] = useState(true);
  const [upstreamModels, setUpstreamModels] = useState([]);
  const [selected, setSelected] = useState([]);

  useEffect(() => {
    apiFetch(`/api/providers/${encodeURIComponent(providerId)}/upstream-models`, { method: "GET" })
      .then((data) => setUpstreamModels(data.models || []))
      .catch((err) => { message.error(`获取失败: ${err.message}`); onClose(); })
      .finally(() => setLoading(false));
  }, [providerId]);

  function handleOk() {
    const toAdd = selected.filter((id) => !existingAliases.has(id));
    onImport(toAdd);
    onClose();
  }

  const checkboxItems = upstreamModels.map((id) => ({
    label: existingAliases.has(id)
      ? React.createElement(Space, null, id, React.createElement(Tag, { color: "green", style: { fontSize: 11 } }, "已添加"))
      : id,
    value: id,
    disabled: existingAliases.has(id),
  }));

  return React.createElement(Modal, {
    title: "从上游导入模型",
    open: true,
    onOk: handleOk,
    onCancel: onClose,
    okText: "添加到列表",
    cancelText: "取消",
    width: 520,
    okButtonProps: { disabled: selected.length === 0 },
  },
    loading
      ? React.createElement(Spin, { style: { display: "block", textAlign: "center", padding: 32 } })
      : upstreamModels.length === 0
        ? React.createElement(Empty, { description: "该供应商不支持获取上游模型列表，或返回为空" })
        : React.createElement(React.Fragment, null,
            React.createElement(Text, { type: "secondary", style: { display: "block", marginBottom: 12 } },
              "勾选后点击「添加到列表」写入，不自动保存配置。"
            ),
            React.createElement(Checkbox.Group, {
              options: checkboxItems,
              value: selected,
              onChange: setSelected,
              style: { display: "flex", flexDirection: "column", gap: 8 },
            }),
          ),
  );
}

// ─── Models Table ─────────────────────────────────────────────────────────────

function ModelsTable({ models, onChange }) {
  const [importOpen, setImportOpen] = useState(false);
  const providerId = null; // injected via closure below

  function updateModel(index, field, value) {
    const next = models.map((m, i) => i === index ? { ...m, [field]: value } : m);
    onChange(next);
  }

  function removeModel(index) {
    onChange(models.filter((_, i) => i !== index));
  }

  function addModel() {
    onChange([...models, makeDefaultModel()]);
  }

  const columns = [
    {
      title: "本地别名 alias",
      dataIndex: "alias",
      render: (val, _, idx) => React.createElement(Input, {
        value: val,
        onChange: (e) => updateModel(idx, "alias", e.target.value),
        size: "small",
      }),
    },
    {
      title: "上游模型 upstream_name",
      dataIndex: "upstream_name",
      render: (val, _, idx) => React.createElement(Input, {
        value: val,
        onChange: (e) => updateModel(idx, "upstream_name", e.target.value),
        size: "small",
      }),
    },
    {
      title: "启用",
      dataIndex: "enabled",
      width: 60,
      render: (val, _, idx) => React.createElement(Switch, {
        checked: val,
        size: "small",
        onChange: (checked) => updateModel(idx, "enabled", checked),
      }),
    },
    {
      title: "操作",
      width: 80,
      render: (_, __, idx) => React.createElement(Button, {
        danger: true,
        size: "small",
        icon: React.createElement(AntdIcons.DeleteOutlined),
        onClick: () => removeModel(idx),
      }),
    },
  ];

  return React.createElement(React.Fragment, null,
    React.createElement(Table, {
      dataSource: models.map((m, i) => ({ ...m, key: i })),
      columns,
      size: "small",
      pagination: false,
      locale: { emptyText: React.createElement(Empty, { description: '还没有模型，点击"新增模型"', imageStyle: { height: 40 } }) },
    }),
  );
}

// ─── Provider Card ────────────────────────────────────────────────────────────

function ProviderCard({ provider, index, onChange, onRemove }) {
  const [importOpen, setImportOpen] = useState(false);

  function update(field, value) {
    onChange({ ...provider, [field]: value });
  }

  const existingAliases = new Set((provider.models || []).map((m) => m.alias));

  function handleImport(newIds) {
    const newModels = newIds.map((id) => ({ alias: id, upstream_name: id, enabled: true }));
    onChange({ ...provider, models: [...(provider.models || []), ...newModels] });
    if (newIds.length > 0) message.success(`已添加 ${newIds.length} 个模型，请保存配置使其生效`);
  }

  return React.createElement(Card, {
    size: "small",
    style: { marginBottom: 12 },
    title: React.createElement(Space, null,
      React.createElement(AntdIcons.ApiOutlined),
      `供应商 ${index + 1}`,
      React.createElement(Badge, { count: provider.models?.length || 0, showZero: true, color: "blue" }),
    ),
    extra: React.createElement(Button, {
      danger: true,
      size: "small",
      icon: React.createElement(AntdIcons.DeleteOutlined),
      onClick: onRemove,
    }, "删除"),
  },
    React.createElement(Row, { gutter: [12, 0] },
      React.createElement(Col, { xs: 24, sm: 12, md: 6 },
        React.createElement(Form.Item, { label: "ID", style: { marginBottom: 8 } },
          React.createElement(Input, { value: provider.id || "", onChange: (e) => update("id", e.target.value), size: "small" }),
        ),
      ),
      React.createElement(Col, { xs: 24, sm: 12, md: 6 },
        React.createElement(Form.Item, { label: "名称", style: { marginBottom: 8 } },
          React.createElement(Input, { value: provider.name || "", onChange: (e) => update("name", e.target.value), size: "small" }),
        ),
      ),
      React.createElement(Col, { xs: 24, sm: 12, md: 8 },
        React.createElement(Form.Item, { label: "BASE_URL", style: { marginBottom: 8 } },
          React.createElement(Input, { value: provider.base_url || "", onChange: (e) => update("base_url", e.target.value), size: "small" }),
        ),
      ),
      React.createElement(Col, { xs: 24, sm: 12, md: 4 },
        React.createElement(Form.Item, { label: "协议", style: { marginBottom: 8 } },
          React.createElement(Select, {
            value: provider.protocol || "openai",
            onChange: (v) => update("protocol", v),
            size: "small",
            style: { width: "100%" },
            options: [{ value: "openai", label: "openai" }, { value: "anthropic", label: "anthropic" }],
          }),
        ),
      ),
    ),

    React.createElement(ApiKeyRow, {
      providerId: provider.id,
      apiKey: provider.api_key || "",
      onChange: (v) => update("api_key", v),
    }),

    React.createElement(Divider, { style: { margin: "12px 0 8px" } },
      React.createElement(Space, null,
        React.createElement(AntdIcons.UnorderedListOutlined),
        "模型列表",
        React.createElement(Button, {
          size: "small",
          icon: React.createElement(AntdIcons.CloudDownloadOutlined),
          onClick: () => setImportOpen(true),
          style: { marginLeft: 8 },
        }, "从上游导入"),
        React.createElement(Button, {
          type: "primary",
          size: "small",
          icon: React.createElement(AntdIcons.PlusOutlined),
          onClick: () => onChange({ ...provider, models: [...(provider.models || []), makeDefaultModel()] }),
        }, "新增模型"),
      ),
    ),

    React.createElement(ModelsTable, {
      models: provider.models || [],
      onChange: (newModels) => onChange({ ...provider, models: newModels }),
    }),

    importOpen && React.createElement(ImportModelsModal, {
      providerId: provider.id,
      existingAliases,
      onImport: handleImport,
      onClose: () => setImportOpen(false),
    }),
  );
}

// ─── Providers Section ────────────────────────────────────────────────────────

function ProvidersSection({ config, onChange, onSave, onReload, saving }) {
  function updateProvider(index, updated) {
    const next = config.providers.map((p, i) => i === index ? updated : p);
    onChange({ ...config, providers: next });
  }

  function removeProvider(index) {
    onChange({ ...config, providers: config.providers.filter((_, i) => i !== index) });
  }

  function addProvider() {
    onChange({ ...config, providers: [...config.providers, makeDefaultProvider(config.providers.length)] });
  }

  return React.createElement(Card, {
    title: React.createElement(Space, null, React.createElement(AntdIcons.CloudServerOutlined), "供应商配置"),
    extra: React.createElement(Space, null,
      React.createElement(Button, { icon: React.createElement(AntdIcons.ReloadOutlined), onClick: onReload }, "重新加载"),
      React.createElement(Button, { icon: React.createElement(AntdIcons.PlusOutlined), onClick: addProvider }, "新增供应商"),
      React.createElement(Button, { type: "primary", icon: React.createElement(AntdIcons.SaveOutlined), onClick: onSave, loading: saving }, "保存配置"),
    ),
    style: { marginBottom: 16 },
  },
    React.createElement(Text, { type: "secondary", style: { display: "block", marginBottom: 12 } },
      "每个供应商可配置：base_url、协议（OpenAI/Anthropic）、api_key、可用模型列表。"
    ),
    config.providers.length === 0
      ? React.createElement(Empty, { description: '暂无供应商，点击上方"新增供应商"' })
      : config.providers.map((provider, index) =>
          React.createElement(ProviderCard, {
            key: provider.id || index,
            provider,
            index,
            onChange: (updated) => updateProvider(index, updated),
            onRemove: () => removeProvider(index),
          })
        ),
  );
}

// ─── Create Key Section ───────────────────────────────────────────────────────

function CreateKeySection({ allModels, onCreated }) {
  const [name, setName] = useState("default-key");
  const [selectedModels, setSelectedModels] = useState([]);
  const [generatedKey, setGeneratedKey] = useState(null);
  const [loading, setLoading] = useState(false);

  async function handleCreate() {
    setLoading(true);
    try {
      const result = await apiFetch("/api/local-keys", {
        method: "POST",
        body: JSON.stringify({ name: name.trim() || "default-key", allowed_models: selectedModels }),
      });
      setGeneratedKey(result.plain_key);
      message.success("本地 Key 已生成");
      onCreated();
    } catch (err) {
      message.error(err.message);
    } finally {
      setLoading(false);
    }
  }

  const modelOptions = allModels.map((m) => ({ label: m, value: m }));

  return React.createElement(Card, {
    title: React.createElement(Space, null, React.createElement(AntdIcons.KeyOutlined), "创建本地 API Key"),
    style: { marginBottom: 16 },
  },
    React.createElement(Row, { gutter: [16, 0] },
      React.createElement(Col, { xs: 24, md: 8 },
        React.createElement(Form.Item, { label: "Key 名称" },
          React.createElement(Input, { value: name, onChange: (e) => setName(e.target.value), placeholder: "default-key" }),
        ),
      ),
      React.createElement(Col, { xs: 24, md: 16 },
        React.createElement(Form.Item, { label: "允许的模型" },
          allModels.length === 0
            ? React.createElement(Text, { type: "secondary" }, "当前没有模型，请先在供应商里添加模型。不勾选 = 访问所有已启用模型。")
            : React.createElement(Select, {
                mode: "multiple",
                value: selectedModels,
                onChange: setSelectedModels,
                options: modelOptions,
                style: { width: "100%" },
                placeholder: "不选 = 访问所有已启用模型",
                allowClear: true,
              }),
        ),
      ),
    ),
    React.createElement(Button, {
      type: "primary",
      icon: React.createElement(AntdIcons.ThunderboltOutlined),
      onClick: handleCreate,
      loading,
    }, "生成本地 Key"),
    generatedKey && React.createElement(Alert, {
      style: { marginTop: 16 },
      type: "success",
      showIcon: true,
      message: "新 Key（只显示一次，请立即复制）",
      description: React.createElement("code", { style: { fontSize: 14, fontFamily: "monospace", wordBreak: "break-all" } }, generatedKey),
    }),
  );
}

// ─── Keys Table ───────────────────────────────────────────────────────────────

function KeyNameCell({ value, onSave }) {
  const [v, setV] = useState(value);
  return React.createElement(Input, {
    value: v,
    size: "small",
    onChange: (e) => setV(e.target.value),
    onBlur: () => onSave(v),
  });
}

function KeyModelsCell({ value, allModels, onSave }) {
  const [v, setV] = useState(value || []);
  return React.createElement(Select, {
    mode: "multiple",
    value: v,
    size: "small",
    options: allModels.map((m) => ({ label: m, value: m })),
    style: { minWidth: 160 },
    placeholder: "全部",
    onChange: setV,
    onBlur: () => onSave(v),
  });
}

function KeysSection({ keys, allModels, onRefresh }) {
  async function handleSave(record, newName, newEnabled, newModels) {
    try {
      await apiFetch(`/api/local-keys/${encodeURIComponent(record.id)}`, {
        method: "PATCH",
        body: JSON.stringify({ name: newName, enabled: newEnabled, allowed_models: newModels }),
      });
      message.success(`Key ${record.id} 已更新`);
      onRefresh();
    } catch (err) { message.error(err.message); }
  }

  async function handleDelete(id) {
    Modal.confirm({
      title: `确认删除 ${id}？`,
      icon: React.createElement(AntdIcons.ExclamationCircleOutlined),
      okText: "删除",
      okType: "danger",
      cancelText: "取消",
      onOk: async () => {
        try {
          await apiFetch(`/api/local-keys/${encodeURIComponent(id)}`, { method: "DELETE" });
          message.success(`Key ${id} 已删除`);
          onRefresh();
        } catch (err) { message.error(err.message); }
      },
    });
  }

  const columns = [
    { title: "ID", dataIndex: "id", render: (v) => React.createElement("code", { style: { fontSize: 12 } }, v) },
    {
      title: "名称",
      dataIndex: "name",
      render: (val, record) => React.createElement(KeyNameCell, {
        value: val,
        onSave: (newName) => handleSave(record, newName, record.enabled, record.allowed_models),
      }),
    },
    { title: "前缀", dataIndex: "key_prefix", render: (v) => React.createElement("code", null, v) },
    {
      title: "启用",
      dataIndex: "enabled",
      width: 60,
      render: (val, record) => React.createElement(Switch, {
        checked: val,
        size: "small",
        onChange: (checked) => handleSave(record, record.name, checked, record.allowed_models),
      }),
    },
    {
      title: "允许模型",
      dataIndex: "allowed_models",
      render: (models, record) => React.createElement(KeyModelsCell, {
        value: models,
        allModels,
        onSave: (newModels) => handleSave(record, record.name, record.enabled, newModels),
      }),
    },
    { title: "创建时间", dataIndex: "created_at", render: (v) => React.createElement("span", { style: { fontSize: 12, whiteSpace: "nowrap" } }, formatDateTime(v)) },
    {
      title: "操作",
      render: (_, record) => React.createElement(Button, {
        danger: true,
        size: "small",
        icon: React.createElement(AntdIcons.DeleteOutlined),
        onClick: () => handleDelete(record.id),
      }, "删除"),
    },
  ];

  return React.createElement(Card, {
    title: React.createElement(Space, null, React.createElement(AntdIcons.SafetyOutlined), "本地 API Keys"),
    style: { marginBottom: 16 },
  },
    React.createElement(Table, {
      dataSource: keys.map((k) => ({ ...k, key: k.id })),
      columns,
      size: "small",
      pagination: false,
      scroll: { x: true },
      locale: { emptyText: React.createElement(Empty, { description: "暂无本地 Key" }) },
    }),
  );
}

// ─── Endpoints Section ────────────────────────────────────────────────────────

const ENDPOINTS_MD = `
## 如何调用

本服务运行在 **\`http://localhost:8000\`**，对外暴露与 OpenAI / Anthropic 完全兼容的 HTTP 接口。

你只需把任何 AI 客户端、SDK 或工具的 **base_url** 指向本服务，并使用本地生成的 \`sk-\` 开头的 Key 即可。

---

## OpenAI 兼容接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | \`/v1/chat/completions\` | Chat 对话（主要接口）|
| POST | \`/v1/responses\` | Responses API |
| POST | \`/v1/completions\` | Legacy Completions |

**示例（curl）**

\`\`\`bash
curl http://localhost:8000/v1/chat/completions \\
  -H "Authorization: Bearer sk-你的本地Key" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "gpt-4.1-mini",
    "messages": [{"role": "user", "content": "你好"}]
  }'
\`\`\`

**示例（Python openai SDK）**

\`\`\`python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="sk-你的本地Key",
)

resp = client.chat.completions.create(
    model="gpt-4.1-mini",
    messages=[{"role": "user", "content": "你好"}],
)
print(resp.choices[0].message.content)
\`\`\`

**流式输出**

\`\`\`python
for chunk in client.chat.completions.create(
    model="gpt-4.1-mini",
    messages=[{"role": "user", "content": "你好"}],
    stream=True,
):
    print(chunk.choices[0].delta.content or "", end="", flush=True)
\`\`\`

---

## Anthropic 兼容接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | \`/v1/messages\` | Messages API |
| POST | \`/v1/complete\` | Legacy Complete |

**示例（curl）**

\`\`\`bash
curl http://localhost:8000/v1/messages \\
  -H "Authorization: Bearer sk-你的本地Key" \\
  -H "Content-Type: application/json" \\
  -H "anthropic-version: 2023-06-01" \\
  -d '{
    "model": "claude-sonnet",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "你好"}]
  }'
\`\`\`

---

## 鉴权方式

所有接口统一使用 HTTP Bearer Token：

\`\`\`
Authorization: Bearer <本地生成的 sk- 开头的 Key>
\`\`\`

> **注意：** model 字段填写的是你在上方"供应商配置"里设置的**本地别名**（alias），不是上游模型名。

---

## 配合 Claude Code / Cursor 使用

在 Claude Code 或 Cursor 的配置中：

- **API Base URL**: \`http://localhost:8000\`
- **API Key**: 你在本页生成的 \`sk-\` Key
- **Model**: 你配置的别名（如 \`gpt-4.1-mini\` / \`claude-sonnet\`）
`;

function EndpointsSection() {
  return React.createElement(Card, {
    title: React.createElement(Space, null, React.createElement(AntdIcons.ApiOutlined), "兼容接口"),
  },
    React.createElement("div", {
      className: "md-content",
      dangerouslySetInnerHTML: { __html: marked.parse(ENDPOINTS_MD) },
    }),
  );
}

// ─── App ──────────────────────────────────────────────────────────────────────

function App() {
  const [config, setConfig] = useState(ensureConfigShape({}));
  const [keys, setKeys] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [messageApi, contextHolder] = message.useMessage();

  const allModels = [];
  config.providers.forEach((p) => {
    (p.models || []).forEach((m) => { if (m.alias && !allModels.includes(m.alias)) allModels.push(m.alias); });
  });

  async function loadConfig() {
    try {
      const data = await apiFetch("/api/config", { method: "GET" });
      setConfig(ensureConfigShape(data));
    } catch (err) { messageApi.error(err.message); }
  }

  async function loadKeys() {
    try {
      const data = await apiFetch("/api/local-keys", { method: "GET" });
      setKeys(Array.isArray(data) ? data : []);
    } catch (err) { messageApi.error(err.message); }
  }

  async function init() {
    setLoading(true);
    await Promise.all([loadConfig(), loadKeys()]);
    setLoading(false);
    messageApi.success("已加载");
  }

  useEffect(() => { init(); }, []);

  async function handleSaveConfig() {
    setSaving(true);
    try {
      const updated = await apiFetch("/api/config", { method: "PUT", body: JSON.stringify(config) });
      setConfig(ensureConfigShape(updated));
      await loadKeys();
      messageApi.success("配置已保存");
    } catch (err) { messageApi.error(err.message); }
    finally { setSaving(false); }
  }

  async function handleReload() {
    await init();
  }

  if (loading) {
    return React.createElement("div", { style: { display: "flex", justifyContent: "center", alignItems: "center", height: "100vh" } },
      React.createElement(Spin, { size: "large", tip: "加载中…" }),
    );
  }

  return React.createElement(React.Fragment, null,
    contextHolder,
    React.createElement(Layout, { style: { minHeight: "100vh", background: "#f4f7fb" } },
      React.createElement(Header, { className: "app-header" },
        React.createElement("div", { className: "header-inner" },
          React.createElement(Space, null,
            React.createElement(AntdIcons.ThunderboltOutlined, { style: { fontSize: 24 } }),
            React.createElement(Title, { level: 4, style: { margin: 0, color: "#fff" } }, "Local AI API Gateway"),
          ),
          React.createElement(Text, { style: { color: "rgba(255,255,255,0.85)", fontSize: 13 } }, "直接管理供应商、模型、协议和本地中转 Key"),
        ),
      ),
      React.createElement(Content, { style: { maxWidth: 1200, margin: "0 auto", padding: "24px 16px", width: "100%" } },
        React.createElement(ProvidersSection, {
          config,
          onChange: setConfig,
          onSave: handleSaveConfig,
          onReload: handleReload,
          saving,
        }),
        React.createElement(CreateKeySection, {
          allModels,
          onCreated: loadKeys,
        }),
        React.createElement(KeysSection, {
          keys,
          allModels,
          onRefresh: loadKeys,
        }),
        React.createElement(EndpointsSection),
      ),
    ),
  );
}

// ─── Mount ────────────────────────────────────────────────────────────────────

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(React.createElement(antd.ConfigProvider, { locale: antd.locale?.zhCN }, React.createElement(App)));
