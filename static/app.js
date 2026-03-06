let editor = null;
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
  if (!response.ok) {
    let detail = "request failed";
    try {
      const body = await response.json();
      detail = body.detail ? JSON.stringify(body.detail) : JSON.stringify(body);
    } catch (_err) {
      detail = await response.text();
    }
    throw new Error(`${response.status} ${detail}`);
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

function collectModelAliases(config) {
  const unique = new Set();
  if (!config || !Array.isArray(config.providers)) {
    return [];
  }
  config.providers.forEach((provider) => {
    if (!Array.isArray(provider.models)) {
      return;
    }
    provider.models.forEach((model) => {
      if (model && typeof model.alias === "string" && model.alias.trim()) {
        unique.add(model.alias.trim());
      }
    });
  });
  return Array.from(unique).sort();
}

function renderModelPills(container, allModels, selectedModels, checkboxClass) {
  container.innerHTML = "";

  if (!allModels.length) {
    container.innerHTML = '<span class="hint">No models configured</span>';
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

function renderModelOverview(config) {
  const panel = document.getElementById("model-overview");
  const rows = [];

  if (Array.isArray(config.providers)) {
    config.providers.forEach((provider) => {
      if (!Array.isArray(provider.models)) {
        return;
      }
      provider.models.forEach((model) => {
        rows.push(`
          <tr>
            <td>${escapeHtml(model.alias || "")}</td>
            <td>${escapeHtml(model.upstream_name || "")}</td>
            <td>${escapeHtml(provider.id || "")}</td>
            <td>${escapeHtml(provider.protocol || "")}</td>
            <td>${model.enabled ? "enabled" : "disabled"}</td>
          </tr>
        `);
      });
    });
  }

  if (!rows.length) {
    panel.innerHTML = '<p class="hint">No models found in config.</p>';
    return;
  }

  panel.innerHTML = `
    <table class="model-table">
      <thead>
        <tr>
          <th>Alias</th>
          <th>Upstream Model</th>
          <th>Provider</th>
          <th>Protocol</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>${rows.join("")}</tbody>
    </table>
  `;
}

function renderLocalKeys(keys) {
  const body = document.getElementById("key-table-body");
  body.innerHTML = "";

  if (!Array.isArray(keys) || keys.length === 0) {
    body.innerHTML = '<tr><td colspan="7" class="hint">No local keys yet.</td></tr>';
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
          <button type="button" class="save-key primary">Save</button>
          <button type="button" class="delete-key danger">Delete</button>
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

async function loadConfig() {
  const config = await apiFetch("/api/config", { method: "GET" });
  cachedModels = collectModelAliases(config);

  editor.set(config);
  renderModelOverview(config);

  const newKeyModels = document.getElementById("new-key-models");
  renderModelPills(newKeyModels, cachedModels, [], "new-key-model");
}

async function saveConfig() {
  const current = editor.get();
  const updated = await apiFetch("/api/config", {
    method: "PUT",
    body: JSON.stringify(current),
  });

  cachedModels = collectModelAliases(updated);

  renderModelOverview(updated);
  const newKeyModels = document.getElementById("new-key-models");
  renderModelPills(newKeyModels, cachedModels, [], "new-key-model");

  await loadLocalKeys();
  showStatus("Config saved.", "success");
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
  showStatus("Local API key generated.", "success");
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
  showStatus(`Local key ${keyId} updated.`, "success");
}

async function deleteLocalKey(keyId) {
  if (!window.confirm(`Delete local key ${keyId}?`)) {
    return;
  }

  await apiFetch(`/api/local-keys/${encodeURIComponent(keyId)}`, {
    method: "DELETE",
  });

  await loadLocalKeys();
  showStatus(`Local key ${keyId} deleted.`, "success");
}

function bindEvents() {
  document.getElementById("btn-load").addEventListener("click", async () => {
    try {
      await loadConfig();
      await loadLocalKeys();
      showStatus("Config reloaded.");
    } catch (err) {
      showStatus(String(err), "error");
    }
  });

  document.getElementById("btn-save").addEventListener("click", async () => {
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
  editor = new JSONEditor(document.getElementById("editor"), {
    mode: "tree",
    modes: ["tree", "code", "form", "view"],
    navigationBar: true,
    statusBar: true,
    mainMenuBar: true,
  });

  bindEvents();

  try {
    await loadConfig();
    await loadLocalKeys();
    showStatus("Loaded.", "success");
  } catch (err) {
    showStatus(String(err), "error");
  }
}

document.addEventListener("DOMContentLoaded", init);
