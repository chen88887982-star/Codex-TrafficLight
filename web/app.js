"use strict";

const STATUS_LABELS = {idle: "空闲", running: "运行中", waiting: "等待确认", success: "已完成", error: "异常", ignored: "已忽略"};

function elapsedLabel(value) {
  const seconds = Math.max(0, Math.floor(Number(value) || 0));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = String(seconds % 60).padStart(2, "0");
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${rest}` : `${String(minutes).padStart(2, "0")}:${rest}`;
}

function dateLabel(value) {
  if (value === null || value === undefined || value === "" || value === 0) return "--";
  const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  if (!Number.isFinite(date.getTime())) return "--";
  return date.toLocaleString("zh-CN", {hour12: false});
}

function percentValue(usage, prefix) {
  if (!usage || usage.available === false) return null;
  const raw = usage[`${prefix}_remaining_value`] ?? usage[`${prefix}_remaining_percent`];
  if (raw === null || raw === undefined || raw === "") return null;
  const value = Number(String(raw).replace(/%$/, ""));
  return Number.isFinite(value) ? Math.min(100, Math.max(0, value)) : null;
}

function compactNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(0, Math.round(number)).toLocaleString("zh-CN") : "--";
}

function statusTone(status) {
  if (status === "error" || status === "offline") return "error";
  if (status === "waiting" || status === "degraded" || status === "stale" || status === "pending") return "warn";
  if (status === "running" || status === "success" || status === "ok" || status === "refreshing") return "";
  return "muted";
}

function initializeDashboard() {
  const $ = id => document.getElementById(id);
  const state = {local: null, peers: [], online: false, lastSuccess: 0, source: "local", historyOffset: 0, historyLimit: 20, historyTotal: 0, historyGeneration: 0, polling: false, timer: null, selectedTab: "overview", refreshRequested: false, connectionError: false};
  let token = "";
  try { token = sessionStorage.getItem("codex-status-token") || ""; } catch (_) { /* Storage may be unavailable in a private browser. */ }
  $("access-token").value = token;

  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = String(text);
    if (className) node.className = className;
    return node;
  }
  function setText(id, text) { $(id).textContent = text === null || text === undefined || text === "" ? "--" : String(text); }
  function badge(node, label, tone) { node.textContent = label; node.className = `badge ${tone || ""}`; }
  function notice(message, success = false) { $("notice").textContent = message; $("notice").className = `notice${success ? " success" : ""}`; $("notice").hidden = !message; }
  function localControlEnabled() { return state.source === "local" && state.online; }

  async function api(path, payload) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 12000);
    const headers = {Accept: "application/json"};
    if (token) headers.Authorization = `Bearer ${token}`;
    if (payload !== undefined) headers["Content-Type"] = "application/json";
    try {
      const response = await fetch(path, {method: payload === undefined ? "GET" : "POST", headers, body: payload === undefined ? undefined : JSON.stringify(payload), signal: controller.signal, cache: "no-store", credentials: "same-origin"});
      if (response.status === 401 || response.status === 403) {
        $("access-panel").hidden = false;
        throw new Error("访问被拒绝，请填写或检查这台服务的访问令牌");
      }
      let data;
      try { data = await response.json(); } catch (_) { throw new Error("服务返回了无法读取的响应"); }
      if (!response.ok || data.ok === false) throw new Error(data.error || `请求失败 (${response.status})`);
      return data;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("服务响应超时，正在保留最后成功的快照");
      if (error instanceof TypeError) throw new Error("无法连接状态服务，正在保留最后成功的快照");
      throw error;
    } finally { clearTimeout(timer); }
  }

  function selectedSource() {
    if (state.source === "local") return {name: "这台电脑", snapshot: state.local, connected: state.online, last_success_at: state.lastSuccess, local: true};
    const peer = state.peers.find(item => item.id === state.source);
    return peer ? {...peer, local: false} : {name: "设备", snapshot: null, connected: false, local: false};
  }

  function renderSources() {
    const select = $("source-select");
    const options = [element("option", "本机服务")];
    options[0].value = "local";
    state.peers.forEach(peer => { const option = element("option", `${peer.name}${peer.connected ? "" : " · 离线"}`); option.value = peer.id; options.push(option); });
    select.replaceChildren(...options);
    if (state.source !== "local" && !state.peers.some(item => item.id === state.source)) state.source = "local";
    select.value = state.source;
  }

  function renderQuota(snapshot) {
    const usage = snapshot?.usage || {};
    const health = snapshot?.health || {};
    for (const prefix of ["primary", "secondary"]) {
      const value = percentValue(usage, prefix);
      setText(`${prefix}-quota`, value === null ? "--" : `${value.toLocaleString("zh-CN", {maximumFractionDigits: 1})}%`);
      $(`${prefix}-bar`).style.width = `${value ?? 0}%`;
      $(`${prefix}-bar`).style.background = value !== null && value < 15 ? "var(--red)" : value !== null && value < 35 ? "var(--yellow)" : "var(--accent)";
      const reset = usage[`${prefix}_resets_at_epoch`] || usage[`${prefix}_resets_at`];
      setText(`${prefix}-reset`, reset ? `重置 ${dateLabel(reset)}` : "等待额度快照");
      const minutes = Number(usage[`${prefix}_window_minutes`] || usage[`${prefix}_window_duration_mins`] || 0);
      setText(`${prefix}-window`, minutes ? minutes >= 1440 ? `${Math.round(minutes / 1440)} 天` : minutes >= 60 ? `${Math.round(minutes / 60)} 小时` : `${minutes} 分钟` : "");
    }
    const worker = snapshot?.usage_refresh || health.usage_worker || {};
    const refreshing = worker.running || worker.pending || usage.refreshing || state.refreshRequested;
    const error = health.usage_query?.last_error || worker.last_error;
    const sync = usage.sync_label || `更新于 ${dateLabel(usage.updated_at)}`;
    setText("usage-sync", `${refreshing ? "正在查询账户额度 · " : ""}${sync}${error ? ` · ${error}` : ""}`);
    $("refresh-usage").disabled = !localControlEnabled() || !!refreshing;
    $("refresh-usage").textContent = refreshing ? "查询中…" : state.source === "local" ? "刷新账户额度" : "由对端服务刷新";
  }

  function renderHealth(snapshot, connected) {
    const health = snapshot?.health || {};
    const usage = snapshot?.usage || {};
    const task = snapshot?.task || {};
    const monitor = health.monitor || {};
    const worker = health.usage_worker || {};
    const query = health.usage_query || {};
    const telemetry = health.telemetry || {};
    const components = health.components || {};
    const monitorDisabled = components.monitor?.status === "disabled" || health.monitor_enabled === false || monitor.enabled === false;
    const monitorTone = monitorDisabled ? "muted" : !monitor.initialized || monitor.heartbeat_age_seconds > 15 || monitor.last_error ? "warn" : "";
    const rows = [
      ["服务连接", connected ? "已连接" : "离线", connected ? "" : "error", connected ? "自动读取最新状态" : "当前为最后成功快照；等待服务恢复"],
      ["状态服务", connected ? health.label || "正在读取" : "待核验", connected ? statusTone(health.status) : "muted", (health.reasons || []).join("；") || `版本 ${health.service_version || "--"}`],
      ["会话监控", connected ? monitorDisabled ? "已关闭" : !monitor.initialized ? "初始化中" : monitorTone ? "待核验" : "正常" : "待核验", connected ? monitorTone : "muted", monitor.last_error || `监控 ${monitor.tracked_files || 0} 个日志 · 心跳 ${monitor.heartbeat_age_seconds ?? "--"} 秒前`],
      ["账户额度", connected ? worker.running || worker.pending ? "查询中" : query.last_error || worker.last_error ? "查询失败" : usage.available ? "有快照" : "等待查询" : "缓存快照", connected ? query.last_error || worker.last_error || !usage.available ? "warn" : "" : "muted", query.last_error || worker.last_error || usage.sync_label || "尚未读取账户额度"],
      ["Git 统计", connected ? telemetry.git_refreshing || telemetry.git_fetching ? "更新中" : telemetry.git_last_error || telemetry.git_fetch_last_error ? "待核验" : task.git_available ? "正常" : "无仓库" : "待核验", connected ? telemetry.git_last_error || telemetry.git_fetch_last_error ? "warn" : task.git_available ? "" : "muted" : "muted", telemetry.git_last_error || telemetry.git_fetch_last_error || task.git_remote_error_label || task.git_state_label || "等待任务关联的仓库"],
    ];
    const componentLabels = {ok: "正常", pending: "等待中", refreshing: "更新中", degraded: "待核验", error: "异常", disabled: "已关闭"};
    for (const [index, key] of [[2, "monitor"], [3, "usage"], [4, "git"]]) {
      if (components[key]) {
        rows[index][1] = connected ? componentLabels[components[key].status] || "待核验" : "待核验";
        rows[index][2] = connected ? statusTone(components[key].status) : "muted";
        rows[index][3] = components[key].label || rows[index][3];
      }
    }
    for (const [key, title] of [["version", "服务版本"], ["runtime_data", "运行数据"]]) {
      if (components[key]) rows.push([title, connected ? componentLabels[components[key].status] || "待核验" : "待核验", connected ? statusTone(components[key].status) : "muted", components[key].label || "--"]);
    }
    $("health-list").replaceChildren(...rows.map(([title, label, tone, detail]) => {
      const row = element("div", null, "health-row");
      const copy = element("div");
      const heading = element("p", null, "health-row-title");
      heading.append(element("i", null, `tiny-dot ${tone}`), element("span", title));
      copy.append(heading, element("p", detail, "health-row-detail"));
      row.append(copy, element("span", label, `badge ${tone}`));
      return row;
    }));
    setText("service-version", health.service_version ? `v${health.service_version}` : "");
  }

  function renderGit(task) {
    setText("git-branch", task.git_available ? `分支 ${task.git_branch || "--"}` : "当前任务未关联 Git 仓库");
    badge($("git-dirty"), task.git_available ? task.git_dirty ? "有未提交修改" : "工作区干净" : "无仓库", task.git_dirty ? "warn" : "muted");
    setText("git-task", task.git_task_label || task.git_change_label || "--");
    setText("git-local", task.git_worktree_label || task.git_uncommitted_label || task.git_state_label || "--");
    setText("git-push", task.git_push_label || task.git_sync_label || (task.git_available ? `${task.git_ahead || 0} 个提交` : "--"));
    setText("git-pull", task.git_pull_label || (task.git_available ? `${task.git_behind || 0} 个提交` : "--"));
    const remoteLabels = {confirmed: "已确认", unchanged: "已确认", verified: "已确认", different: "远端有更新", unconfirmed: "未确认", disabled: "未启用核验", fetching: "正在核验", checking: "正在核验"};
    setText("git-remote", task.git_remote_error_label || remoteLabels[task.git_remote_status] || task.git_remote_status || "--");
  }

  async function taskControl(action, task = {}) {
    if (!localControlEnabled()) return;
    try {
      await api("/api/tasks/control", {action, session_id: task.session_id || "", turn_id: task.turn_id || ""});
      notice(action === "ignore" ? "已忽略本轮的监控显示；Codex 任务继续运行。" : action === "recheck" ? "已重新核验任务日志。" : action === "clear_selection" ? "已恢复自动选择任务。" : "已更新关注任务。", true);
      await poll();
    } catch (error) { notice(error.message); }
  }

  function renderTasks(task) {
    const tasks = Array.isArray(task.active_tasks) ? task.active_tasks : [];
    $("automatic-selection").disabled = !localControlEnabled();
    setText("task-control-note", state.source === "local" ? "选择关注或固定显示。忽略本轮仅影响看板，任务仍继续运行。" : "此设备为只读来源。需管理任务或刷新额度时，在设备页打开对端看板并填写令牌。");
    if (!tasks.length) { $("task-list").replaceChildren(element("p", "暂无活动任务", "empty")); return; }
    $("task-list").replaceChildren(...tasks.map(item => {
      const current = item.session_id === task.session_id && (!item.turn_id || item.turn_id === task.turn_id);
      const pinned = item.pinned || item.session_id === task.pinned_session_id;
      const row = element("article", null, `task-row${current ? " current" : ""}`);
      const copy = element("div", null, "task-copy");
      copy.append(element("strong", item.task_title || item.project || "Codex 任务"), element("p", `${item.project || "--"} · ${item.stage || STATUS_LABELS[item.status] || "--"} · ${elapsedLabel(item.elapsed_seconds)}`));
      const labels = element("div", null, "task-labels");
      labels.append(element("span", STATUS_LABELS[item.status] || item.status || "--", `badge ${statusTone(item.status)}`));
      if (current) labels.append(element("span", "当前显示", "badge muted"));
      if (pinned) labels.append(element("span", "已固定", "badge"));
      copy.append(labels);
      const actions = element("div", null, "task-actions");
      [["select", "关注"], [pinned ? "unpin" : "pin", pinned ? "取消固定" : "固定"], ["recheck", "重新核验"], ["ignore", "忽略本轮"]].forEach(([action, label]) => {
        const button = element("button", label, "quiet");
        button.disabled = !localControlEnabled();
        button.addEventListener("click", () => taskControl(action, item));
        actions.append(button);
      });
      row.append(copy, actions);
      return row;
    }));
  }

  function renderOverview() {
    const source = selectedSource();
    const snapshot = source.snapshot;
    const task = snapshot?.task || {};
    const status = snapshot?.status || {};
    const current = task.status || status.status || "idle";
    const connected = !!source.connected;
    setText("page-title", source.local ? "这台电脑的工作状态" : `${source.name}的工作状态`);
    badge($("connection"), connected ? "已连接" : snapshot ? "离线 · 历史快照" : "等待连接", connected ? "" : "warn");
    setText("last-connected", source.last_success_at ? `${connected ? "最近读取" : "最后成功读取"} ${dateLabel(source.last_success_at)}` : "等待第一次读取");
    setText("task-project", task.project || "等待任务");
    setText("task-title", task.task_title || (snapshot ? "暂无活动任务" : "正在连接状态服务"));
    setText("task-stage", connected ? task.stage || status.message || "--" : snapshot ? "服务离线，以下内容来自最后成功快照" : source.error || "等待第一次读取");
    $("state-dot").className = `state-dot ${connected && Object.hasOwn(STATUS_LABELS, current) ? current : "idle"}`;
    badge($("task-state"), connected ? STATUS_LABELS[current] || current : "离线", connected ? statusTone(current) : "muted");
    setText("task-elapsed", elapsedLabel(task.elapsed_seconds));
    setText("task-model", [task.model, task.reasoning_effort].filter(Boolean).join(" · "));
    setText("active-count", `${task.active_count || 0} 个活动任务`);
    setText("task-tokens", task.token_label || `本轮 ${compactNumber(task.last_tokens)} tokens`);
    setText("task-context", task.context_label || "上下文 --");
    setText("account-change", status.task_usage_label || "期间账户变化 --");
    renderQuota(snapshot);
    renderHealth(snapshot, connected);
    renderGit(task);
    renderTasks(task);
    setText("footer-state", `${source.local ? "本机" : source.name}状态服务 · ${connected ? "自动刷新" : "连接中断"}`);
  }

  function renderDevices() {
    const sources = [{id: "local", name: "本机服务", url: location.origin, connected: state.online, last_success_at: state.lastSuccess, snapshot: state.local, local: true}, ...state.peers];
    setText("device-count", `${sources.length} 台设备`);
    $("device-list").replaceChildren(...sources.map(source => {
      const snapshot = source.snapshot || {};
      const task = snapshot.task || {};
      const usage = snapshot.usage || {};
      const card = element("article", null, "device-card");
      const heading = element("div", null, "device-heading");
      heading.append(element("h3", source.name), element("span", source.connected ? "已连接" : "离线", `badge ${source.connected ? "" : "warn"}`));
      card.append(heading, element("p", source.url, "device-address"), element("p", task.task_title || "等待任务快照", "device-task"), element("p", source.error || `${STATUS_LABELS[task.status] || "空闲"} · ${task.active_count || 0} 个活动任务`, "device-subtle"));
      const metrics = element("div", null, "device-metrics");
      const primary = percentValue(usage, "primary");
      const secondary = percentValue(usage, "secondary");
      metrics.append(element("span", `主要剩余 ${primary === null ? "--" : `${primary}%`}`), element("span", `次要剩余 ${secondary === null ? "--" : `${secondary}%`}`));
      card.append(metrics);
      const controls = element("div", null, "device-controls");
      controls.append(element("span", source.last_success_at ? dateLabel(source.last_success_at) : "等待首次连接", "subtle"));
      const buttons = element("div");
      const view = element("button", "查看", "quiet");
      view.addEventListener("click", () => { state.source = source.id; renderSources(); renderOverview(); showTab("overview"); });
      buttons.append(view);
      if (!source.local) {
        const open = element("a", "打开看板", "link-button");
        open.href = `${source.url}/dashboard`;
        open.target = "_blank";
        open.rel = "noopener noreferrer";
        buttons.append(open);
        const remove = element("button", "移除", "quiet danger");
        remove.disabled = !state.online;
        remove.addEventListener("click", async () => {
          remove.disabled = true;
          try { await api("/api/peers", {action: "remove", peer_id: source.id}); notice("已移除设备。", true); await poll(); } catch (error) { notice(error.message); remove.disabled = false; }
        });
        buttons.append(remove);
      }
      controls.append(buttons);
      card.append(controls);
      return card;
    }));
  }

  async function loadHistory() {
    const generation = ++state.historyGeneration;
    const params = new URLSearchParams({limit: String(state.historyLimit), offset: String(state.historyOffset)});
    const project = $("history-project").value.trim();
    const status = $("history-status").value;
    if (project) params.set("project", project);
    if (status) params.set("status", status);
    if ($("history-since").value) params.set("since", `${$("history-since").value}T00:00:00`);
    if ($("history-until").value) params.set("until", `${$("history-until").value}T23:59:59`);
    $("refresh-history").disabled = true;
    try {
      const data = await api(`/api/history?${params}`);
      if (generation !== state.historyGeneration) return;
      const items = Array.isArray(data.items) ? data.items : [];
      state.historyTotal = Math.max(0, Number(data.total) || 0);
      $("history-list").replaceChildren(...items.map(item => {
        const row = element("tr");
        const title = element("td");
        title.append(element("strong", item.task_title || "Codex 任务"), element("span", item.project || "--", "subtle"));
        const status = element("td");
        status.append(element("span", STATUS_LABELS[item.status] || item.status || "--", `badge ${statusTone(item.status)}`));
        row.append(title, status, element("td", dateLabel(item.started_at || item.updated_at)), element("td", elapsedLabel(item.duration_seconds)), element("td", compactNumber(item.tokens ?? item.total_tokens)), element("td", `${item.git_files || 0} 项 · +${item.git_added || 0} / -${item.git_deleted || 0}`));
        return row;
      }));
      $("history-empty").hidden = !!items.length;
      setText("history-empty", data.available === false ? "历史存储不可用，请检查服务的运行目录权限" : "没有符合条件的任务记录");
      setText("history-count", state.historyTotal ? `共 ${state.historyTotal} 条 · ${state.historyOffset + 1}–${state.historyOffset + items.length}` : "共 0 条");
      $("history-previous").disabled = !state.historyOffset;
      $("history-next").disabled = state.historyOffset + items.length >= state.historyTotal;
    } catch (error) {
      if (generation === state.historyGeneration) {
        $("history-list").replaceChildren(); $("history-empty").hidden = false; setText("history-empty", error.message);
        $("history-previous").disabled = true; $("history-next").disabled = true;
      }
    } finally { if (generation === state.historyGeneration) $("refresh-history").disabled = false; }
  }

  function showTab(name) {
    state.selectedTab = name;
    document.querySelectorAll(".tab").forEach(tab => { const selected = tab.dataset.tab === name; tab.classList.toggle("selected", selected); tab.setAttribute("aria-selected", String(selected)); });
    for (const tab of ["overview", "history", "devices"]) $(`${tab}-view`).hidden = tab !== name;
    if (name === "history") loadHistory();
  }

  async function poll() {
    if (state.polling) return;
    state.polling = true;
    clearTimeout(state.timer);
    try {
      const results = await Promise.allSettled([api("/api/snapshot"), api("/api/peers")]);
      if (results[0].status === "fulfilled") {
        const snapshot = results[0].value;
        if (!snapshot || typeof snapshot.status !== "object" || typeof snapshot.task !== "object" || typeof snapshot.usage !== "object" || typeof snapshot.health !== "object") throw new Error("状态服务返回格式不兼容");
        state.local = snapshot; state.online = true; state.lastSuccess = Date.now() / 1000;
        state.refreshRequested = false;
        if (state.connectionError) { notice(""); state.connectionError = false; }
      } else { state.online = false; state.refreshRequested = false; state.connectionError = true; notice(results[0].reason.message); }
      if (results[1].status === "fulfilled") {
        const data = results[1].value;
        state.peers = Array.isArray(data.items) ? data.items : [];
        if (data.configuration_error) notice(data.configuration_error);
      } else {
        state.peers = state.peers.map(peer => ({...peer, connected: false, stale: true, error: "本机聚合服务无法读取，保留最后成功快照"}));
      }
      renderSources(); renderOverview(); renderDevices();
    } catch (error) { state.online = false; state.refreshRequested = false; notice(error.message); renderOverview(); renderDevices(); }
    finally { state.polling = false; state.timer = setTimeout(poll, document.hidden ? 15000 : 3000); }
  }

  $("access-button").addEventListener("click", () => { $("access-panel").hidden = !$("access-panel").hidden; if (!$("access-panel").hidden) $("access-token").focus(); });
  $("access-form").addEventListener("submit", async event => {
    event.preventDefault(); token = $("access-token").value.trim();
    try { sessionStorage.setItem("codex-status-token", token); } catch (_) { /* Use the in-memory token when storage is unavailable. */ }
    $("access-panel").hidden = true; notice(""); await poll(); if (state.selectedTab === "history") await loadHistory();
  });
  $("clear-access").addEventListener("click", async () => { token = ""; $("access-token").value = ""; try { sessionStorage.removeItem("codex-status-token"); } catch (_) {} notice("已清除当前标签页的访问令牌。", true); await poll(); });
  $("source-select").addEventListener("change", () => { state.source = $("source-select").value; renderOverview(); });
  document.querySelectorAll(".tab").forEach(tab => tab.addEventListener("click", () => showTab(tab.dataset.tab)));
  $("automatic-selection").addEventListener("click", () => taskControl("clear_selection"));
  $("refresh-usage").addEventListener("click", async () => {
    if (!localControlEnabled()) return;
    state.refreshRequested = true; renderQuota(state.local);
    try { await api("/api/usage/refresh", {}); notice("已安排账户额度查询，进度会自动更新。", true); await poll(); }
    catch (error) { state.refreshRequested = false; notice(error.message); renderQuota(state.local); }
  });
  $("history-filter").addEventListener("submit", event => { event.preventDefault(); state.historyOffset = 0; loadHistory(); });
  $("refresh-history").addEventListener("click", loadHistory);
  $("history-previous").addEventListener("click", () => { state.historyOffset = Math.max(0, state.historyOffset - state.historyLimit); loadHistory(); });
  $("history-next").addEventListener("click", () => { state.historyOffset += state.historyLimit; loadHistory(); });
  $("peer-form").addEventListener("submit", async event => {
    event.preventDefault(); const button = $("peer-form").querySelector("button"); button.disabled = true;
    try { await api("/api/peers", {action: "add", name: $("peer-name").value.trim(), url: $("peer-url").value.trim(), token: $("peer-token").value.trim()}); $("peer-form").reset(); notice("已添加设备，后台正在连接。", true); await poll(); }
    catch (error) { notice(error.message); }
    finally { button.disabled = false; }
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });
  poll();
}

if (typeof document !== "undefined") initializeDashboard();
