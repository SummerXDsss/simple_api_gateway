let stateConfig = { providers: [], local_keys: [] };
let cachedModels = [];

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function showStatus(message, type = "") {
  const status = document.getElementById("status");
  status.textContent = message;
  status.classList.remove("error", "success");
  if (type) {
    status.classList.add(type);
  }
}

async function apiFetch(url, options = {}) {
  const merged = {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  };

  const response = await fetch(url, merged);
  const raw = await response.text();
  let parsed = null;

  if (raw) {
    try {
      parsed = JSON.parse(raw);
    } catch (_err) {
      parsed = null;
    }
  }

  if (!response.ok) {
    const detail = parsed?.detail ?? raw ?? "request failed";
    throw new Error(`${response.status} ${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
  }

  if (!raw) {
    return null;
  }

  return parsed ?? raw;
}

function ensureConfigShape(config) {
  return {
    providers: Array.isArray(config?.providers) ? config.providers : [],
    local_keys: Array.isArray(config?.local_keys) ? config.local_keys : [],
  };
}

function collectModelAliases() {
  const unique = new Set();
  stateConfig.providers.forEach((provider) => {
    if (!Array.isArray(provider.models)) {
      return;
    }
    provider.models.forEach((model) => {
      if (model && typeof model.alias === "string" && model.alias.trim()) {
        unique.add(model.alias.trim());
      }
    });
  });
  cachedModels = Array.from(unique).sort();
}

function makeDefaultProvider() {
  const idx = stateConfig.providers.length + 1;
  return {
    id: `provider-${idx}`,
    name: `Provider ${idx}`,
    base_url: "https://api.openai.com",
    protocol: "openai",
    api_key: "",
    models: [
      {
        alias: `model-${idx}-1`,
        upstream_name: "",
        enabled: true,
      },
    ],
  };
}

function makeDefaultModel() {
  return {
    alias: "",
    upstream_name: "",
    enabled: true,
  };
}

function renderModelPills(container, allModels, selectedModels, checkboxClass) {
  container.innerHTML = "";

  if (!allModels.length) {
    container.innerHTML = '<span class="hint">当前没有模型，请先在供应商里添加模型。</span>';
    return;
  }

  allModels.forEach((model) => {
    const checked = selectedModels.includes(model);
    const pill = document.createElement("label");
    pill.className = "model-pill";
    pill.innerHTML = `
      <input type="checkbox" class="${checkboxClass}" value="${escapeHtml(model)}" ${checked ? "checked" : ""} />
      <span>${escapeHtml(model)}</span>
    `;
    container.appendChild(pill);
  });
}

function renderProviderModels(tableBody, providerIndex) {
  tableBody.innerHTML = "";
  const provider = stateConfig.providers[providerIndex];

  if (!Array.isArray(provider.models)) {
    provider.models = [];
  }

  provider.models.forEach((model, modelIndex) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><input type="text" value="${escapeHtml(model.alias || "")}" class="model-alias" /></td>
      <td><input type="text" value="${escapeHtml(model.upstream_name || "")}" class="model-upstream" /></td>
      <td><input type="checkbox" class="model-enabled" ${model.enabled ? "checked" : ""} /></td>
      <td><button type="button" class="danger btn-remove-model">删除模型</button></td>
    `;

    tr.querySelector(".model-alias").addEventListener("input", (e) => {
      provider.models[modelIndex].alias = e.target.value;
      collectModelAliases();
      renderNewKeyModelSelector();
    });

    tr.querySelector(".model-upstream").addEventListener("input", (e) => {
      provider.models[modelIndex].upstream_name = e.target.value;
    });

    tr.querySelector(".model-enabled").addEventListener("change", (e) => {
      provider.models[modelIndex].enabled = e.target.checked;
    });

    tr.querySelector(".btn-remove-model").addEventListener("click", () => {
      provider.models.splice(modelIndex, 1);
      renderProviders();
      collectModelAliases();
      renderNewKeyModelSelector();
    });

    tableBody.appendChild(tr);
  });

  if (!provider.models.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = '<td colspan="4" class="hint">还没有模型，点击“新增模型”。</td>';
    tableBody.appendChild(tr);
  }
}

function renderProviders() {
  const container = document.getElementById("provider-list");
  container.innerHTML = "";

  if (!stateConfig.providers.length) {
    container.innerHTML = '<p class="hint">暂无供应商，点击上方“新增供应商”。</p>';
    return;
  }

  stateConfig.providers.forEach((provider, providerIndex) => {
    if (!Array.isArray(provider.models)) {
      provider.models = [];
    }

    const card = document.createElement("article");
    card.className = "provider-card";

    card.innerHTML = `
      <div class="provider-head">
        <h3>供应商 ${providerIndex + 1}</h3>
        <button type="button" class="danger btn-remove-provider">删除供应商</button>
      </div>

      <div class="provider-grid">
        <label>
          ID
          <input type="text" class="provider-id" value="${escapeHtml(provider.id || "")}" />
        </label>
        <label>
          名称
          <input type="text" class="provider-name" value="${escapeHtml(provider.name || "")}" />
        </label>
        <label>
          BASE_URL
          <input type="text" class="provider-base-url" value="${escapeHtml(provider.base_url || "")}" />
        </label>
        <label>
          协议
          <select class="provider-protocol">
            <option value="openai" ${provider.protocol === "openai" ? "selected" : ""}>openai</option>
            <option value="anthropic" ${provider.protocol === "anthropic" ? "selected" : ""}>anthropic</option>
          </select>
        </label>
      </div>

      <label>
        API_KEY
        <input type="text" class="provider-api-key" value="${escapeHtml(provider.api_key || "")}" />
      </label>

      <div class="models-head">
        <h4>模型列表</h4>
        <button type="button" class="btn-add-model">新增模型</button>
      </div>

      <table class="model-edit-table">
        <thead>
          <tr>
            <th>本地别名 alias</th>
            <th>上游模型 upstream_name</th>
            <th>启用</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody class="model-edit-body"></tbody>
      </table>
    `;

    card.querySelector(".provider-id").addEventListener("input", (e) => {
      provider.id = e.target.value;
    });

    card.querySelector(".provider-name").addEventListener("input", (e) => {
      provider.name = e.target.value;
    });

    card.querySelector(".provider-base-url").addEventListener("input", (e) => {
      provider.base_url = e.target.value;
    });

    card.querySelector(".provider-protocol").addEventListener("change", (e) => {
      provider.protocol = e.target.value;
    });

    card.querySelector(".provider-api-key").addEventListener("input", (e) => {
      provider.api_key = e.target.value;
    });

    card.querySelector(".btn-remove-provider").addEventListener("click", () => {
      stateConfig.providers.splice(providerIndex, 1);
      renderProviders();
      collectModelAliases();
      renderNewKeyModelSelector();
    });

    card.querySelector(".btn-add-model").addEventListener("click", () => {
      provider.models.push(makeDefaultModel());
      renderProviders();
      collectModelAliases();
      renderNewKeyModelSelector();
    });

    const modelBody = card.querySelector(".model-edit-body");
    renderProviderModels(modelBody, providerIndex);

    container.appendChild(card);
  });
}

function renderLocalKeys(keys) {
  const body = document.getElementById("key-table-body");
  body.innerHTML = "";

  if (!Array.isArray(keys) || keys.length === 0) {
    body.innerHTML = '<tr><td colspan="7" class="hint">暂无本地 Key。</td></tr>';
    return;
  }

  keys.forEach((key) => {
    const tr = document.createElement("tr");
    tr.dataset.keyId = key.id;

    const modelCellId = `models-${key.id}`;

    tr.innerHTML = `
      <td><code>${escapeHtml(key.id)}</code></td>
      <td><input type="text" class="key-name" value="${escapeHtml(key.name)}" /></td>
      <td><code>${escapeHtml(key.key_prefix)}</code></td>
      <td><input type="checkbox" class="key-enabled" ${key.enabled ? "checked" : ""} /></td>
      <td class="key-models"><div id="${escapeHtml(modelCellId)}" class="model-pills"></div></td>
      <td>${escapeHtml(key.created_at)}</td>
      <td>
        <div class="actions">
          <button type="button" class="save-key primary">保存</button>
          <button type="button" class="delete-key danger">删除</button>
        </div>
      </td>
    `;

    body.appendChild(tr);

    const modelContainer = document.getElementById(modelCellId);
    const selectedModels = Array.isArray(key.allowed_models) ? key.allowed_models : [];
    renderModelPills(modelContainer, cachedModels, selectedModels, "key-model-checkbox");

    tr.querySelector(".save-key").addEventListener("click", () => saveLocalKey(tr));
    tr.querySelector(".delete-key").addEventListener("click", () => deleteLocalKey(key.id));
  });
}

function selectedModelsFromContainer(container, checkboxClass) {
  const checked = container.querySelectorAll(`input.${checkboxClass}:checked`);
  return Array.from(checked).map((el) => el.value);
}

function renderNewKeyModelSelector() {
  const newKeyModels = document.getElementById("new-key-models");
  renderModelPills(newKeyModels, cachedModels, [], "new-key-model");
}

async function loadConfig() {
  const config = await apiFetch("/api/config", { method: "GET" });
  stateConfig = ensureConfigShape(config);
  collectModelAliases();
  renderProviders();
  renderNewKeyModelSelector();
}

async function saveConfig() {
  const updated = await apiFetch("/api/config", {
    method: "PUT",
    body: JSON.stringify(stateConfig),
  });

  stateConfig = ensureConfigShape(updated);
  collectModelAliases();
  renderProviders();
  renderNewKeyModelSelector();

  await loadLocalKeys();
  showStatus("配置已保存。", "success");
}

async function loadLocalKeys() {
  const keys = await apiFetch("/api/local-keys", { method: "GET" });
  renderLocalKeys(keys);
}

async function generateLocalKey() {
  const nameInput = document.getElementById("new-key-name");
  const container = document.getElementById("new-key-models");
  const selected = selectedModelsFromContainer(container, "new-key-model");

  const payload = {
    name: nameInput.value.trim() || "default-key",
    allowed_models: selected,
  };

  const result = await apiFetch("/api/local-keys", {
    method: "POST",
    body: JSON.stringify(payload),
  });

  document.getElementById("generated-key").textContent = result.plain_key;
  await loadLocalKeys();
  showStatus("本地 Key 已生成。", "success");
}

async function saveLocalKey(row) {
  const keyId = row.dataset.keyId;
  const name = row.querySelector(".key-name").value.trim() || "default-key";
  const enabled = row.querySelector(".key-enabled").checked;
  const modelContainer = row.querySelector(".key-models .model-pills");
  const allowedModels = selectedModelsFromContainer(modelContainer, "key-model-checkbox");

  await apiFetch(`/api/local-keys/${encodeURIComponent(keyId)}`, {
    method: "PATCH",
    body: JSON.stringify({
      name,
      enabled,
      allowed_models: allowedModels,
    }),
  });

  await loadLocalKeys();
  showStatus(`本地 Key ${keyId} 已更新。`, "success");
}

async function deleteLocalKey(keyId) {
  if (!window.confirm(`确认删除本地 Key ${keyId} 吗？`)) {
    return;
  }

  await apiFetch(`/api/local-keys/${encodeURIComponent(keyId)}`, {
    method: "DELETE",
  });

  await loadLocalKeys();
  showStatus(`本地 Key ${keyId} 已删除。`, "success");
}

function bindEvents() {
  document.getElementById("btn-reload").addEventListener("click", async () => {
    try {
      await loadConfig();
      await loadLocalKeys();
      showStatus("配置已重新加载。", "success");
    } catch (err) {
      showStatus(String(err), "error");
    }
  });

  document.getElementById("btn-add-provider").addEventListener("click", () => {
    stateConfig.providers.push(makeDefaultProvider());
    collectModelAliases();
    renderProviders();
    renderNewKeyModelSelector();
  });

  document.getElementById("btn-save-config").addEventListener("click", async () => {
    try {
      await saveConfig();
    } catch (err) {
      showStatus(String(err), "error");
    }
  });

  document
    .getElementById("btn-generate-key")
    .addEventListener("click", async () => {
      try {
        await generateLocalKey();
      } catch (err) {
        showStatus(String(err), "error");
      }
    });
}

async function init() {
  bindEvents();

  try {
    await loadConfig();
    await loadLocalKeys();
    showStatus("已加载。", "success");
  } catch (err) {
    showStatus(String(err), "error");
  }
}

document.addEventListener("DOMContentLoaded", init);
