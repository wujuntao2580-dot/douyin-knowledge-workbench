"use strict";

const get = id => document.getElementById(id);
const key = location.hash.slice(1) || sessionStorage.getItem("workbench-key") || "";
if (location.hash) {
  sessionStorage.setItem("workbench-key", key);
  history.replaceState(null, "", location.pathname);
}
const notice = get("notice");
const library = get("library");
let catalog = [];
let chosen = new Set();
let page = 0;
let local = false;
let favorites = null;
let nextFolderCursor = null;
let status = null;
let current = "";
let approved = new Set();
let approvedFrom = "";
let lastBatch = "";
let lastBatchList = "";
let working = false;
const pageSize = 8;
const metricLabels = {plays: "播放量", likes: "点赞", saves: "收藏"};
const countFormat = new Intl.NumberFormat("zh-CN");
let source = "creator";
const sourceStates = new Map();
let favoriteFoldersLoaded = false;

function activateView(view) {
  for (const name of ["pick", "tasks"]) {
    get(name + "-view").hidden = name !== view;
    get(name + "-tab").setAttribute("aria-selected", String(name === view));
  }
}
get("pick-tab").onclick = () => activateView("pick");
get("tasks-tab").onclick = () => activateView("tasks");
get("workflow-home").onclick = event => {event.preventDefault();activateView("pick");};
for (const button of document.querySelectorAll("[data-close]")) button.onclick = () => get(button.dataset.close).close();
get("account-open").onclick = () => get("account-dialog").showModal();
get("settings-open").onclick = () => {fillSettings();get("settings-dialog").showModal();};
get("change-creator").onclick = () => {get("keyword").focus();get("keyword").select();};
for (const button of document.querySelectorAll("[data-sort]")) button.onclick = () => {
  get("sort").value = button.dataset.sort;
  page = 0;
  drawCatalog();
};
get("compress-downloads").onchange = () => {
  get("compression-help").textContent = get("compress-downloads").checked
    ? "压缩在后台排队，下载可以继续。" : "保留原视频，下载完成就能转写。";
};
function selectSource(next) {
  if (next === source) return;
  sourceStates.set(source, {catalog, chosen, page, local, favorites,
    name:get("name").value, account:get("account").value, destination:get("destination").value,
    title:get("creator-name").textContent, caption:get("catalog-source").textContent});
  source = next;
  for (const button of document.querySelectorAll("[data-source]")) {
    const active = button.dataset.source === source;
    button.setAttribute("aria-selected", String(active));
    get("source-" + button.dataset.source).hidden = !active;
  }
  const saved = sourceStates.get(source);
  catalog = saved?.catalog || [];chosen = saved?.chosen || new Set();page = saved?.page || 0;
  local = saved?.local || false;favorites = saved?.favorites || null;
  for (const name of ["name", "account", "destination"]) get(name).value = saved?.[name] || "";
  get("creator-name").textContent = saved?.title || "";
  get("catalog-source").textContent = saved?.caption || "";
  get("creator-avatar").textContent = (saved?.title || (source === "favorites" ? "藏" : "播")).slice(0,1);
  get("picker").hidden = !saved;
  get("picker-empty").hidden = Boolean(saved);
  get("creator-fields").hidden = !saved || Boolean(favorites) || Boolean(saved.name && saved.account && !local);
  get("name").required = get("account").required = !get("creator-fields").hidden;
  get("change-creator").hidden = source !== "creator";
  get("destination").readOnly = local;
  get("folder").hidden = local;
  get("more-favorite-videos").hidden = !favorites?.more;
  drawCatalog();
  if (source === "favorites" && !favoriteFoldersLoaded) task(() => loadFavoriteFolders());
}
for (const button of document.querySelectorAll("[data-source]")) button.onclick = () => {
  if (working) {show("当前请求正在处理，请稍候再切换来源。");return;}
  selectSource(button.dataset.source);
};

function drawRecent() {
  const creators = [...new Map((status?.batches || []).filter(row => row.sourceType !== "favorites" && !row.local)
    .map(row => [row.account, row])).values()].slice(0,3);
  const parent = get("recent-creators");
  parent.hidden = !creators.length;
  parent.replaceChildren(element("span", "最近处理"), ...creators.map(row => button(row.name, () => {
    get("keyword").value = row.account;
    get("search-form").requestSubmit();
  })));
}

function show(message, error = false) {
  notice.textContent = message;
  notice.classList.toggle("error", error);
  notice.hidden = !message;
  for (const dialog of document.querySelectorAll("dialog")) {
    let feedback = dialog.querySelector(".dialog-notice");
    if (!feedback) {
      feedback = element("p", "", "dialog-notice");
      feedback.setAttribute("role", "status");
      dialog.querySelector(".dialog-head").after(feedback);
    }
    feedback.textContent = message;
    feedback.hidden = !message || !dialog.open;
    feedback.classList.toggle("error-text", error);
  }
}

async function api(route, payload = {}) {
  const response = await fetch("/workflow/api/" + route, {
    method: "POST", headers: {"Content-Type": "application/json", "X-Playback-Key": key},
    body: JSON.stringify(payload)
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "工作台请求失败");
  return data;
}

async function task(fn) {
  if (working) return;
  working = true;
  document.body.classList.add("busy");
  const submits = [...document.querySelectorAll("form button[type=submit], #search-form button, #login-open, #login-save, #login-check")];
  const disabled = submits.map(button => button.disabled);
  submits.forEach(button => button.disabled = true);
  show("");
  try { await fn(); }
  catch (error) { show(error.message, true); }
  finally {
    working = false;
    document.body.classList.remove("busy");
    submits.forEach((button, index) => button.disabled = disabled[index]);
    updateSelection();
    if (status) drawAccount();
  }
}

function submit(id, fn) {
  get(id).addEventListener("submit", event => {
    event.preventDefault();
    task(fn);
  });
}

function element(tag, value, className) {
  const node = document.createElement(tag);
  if (value) node.textContent = value;
  if (className) node.className = className;
  return node;
}

function button(label, fn) {
  const node = element("button", label);
  node.type = "button";
  node.addEventListener("click", fn);
  return node;
}

function openCatalog(data, folder = "") {
  catalog = data.works;
  local = data.source === "本地视频";
  favorites = data.sourceType === "favorites" ? data.favorites : null;
  get("creator-fields").hidden = Boolean(favorites) || Boolean(data.creator.name && data.creator.account && !local);
  get("name").required = get("account").required = !get("creator-fields").hidden;
  get("more-favorite-videos").hidden = !favorites?.more;
  page = 0;
  chosen.clear();
  get("name").value = data.creator.name || "";
  get("account").value = data.creator.account || "";
  get("destination").value = folder || (data.creator.account && status?.defaultFolder
    ? status.defaultFolder + "\\" + data.creator.account : "");
  get("destination").readOnly = local;
  get("folder").hidden = local;
  get("creator-name").textContent = data.creator.name || (local ? "本地视频" : "链接清单");
  get("creator-avatar").textContent = (data.creator.name || (local ? "本地" : "链接")).slice(0,1);
  get("change-creator").hidden = source !== "creator";
  get("catalog-source").textContent = data.source + " · " + catalog.length + " 条视频";
  get("picker").hidden = false;
  get("picker-empty").hidden = true;
  drawCatalog();
}

function currentCatalog() {
  const subset = get("only-new").checked ? catalog.filter(row => !row.existing) : catalog.slice();
  const order = get("sort").value;
  return subset.sort((a, b) => {
    if (Object.hasOwn(metricLabels, order)) {
      const difference = (b.metrics?.[order] ?? -1) - (a.metrics?.[order] ?? -1);
      if (difference) return difference;
    }
    return (order === "asc" ? 1 : -1) *
      (String(a.date).localeCompare(String(b.date)) || a.id.localeCompare(b.id));
  });
}

function check(checked, title, fn) {
  const control = element("input");
  control.type = "checkbox";
  control.checked = checked;
  control.setAttribute("aria-label", title);
  control.addEventListener("change", () => fn(control.checked));
  return control;
}

function drawCatalog() {
  const list = currentCatalog();
  const order = get("sort").value;
  const metricLabel = metricLabels[order];
  const note = get("sort-note");
  const known = metricLabel ? list.filter(row => row.metrics?.[order] !== undefined).length : 0;
  note.hidden = !metricLabel || !list.length || known === list.length;
  note.textContent = known
    ? known + " / " + list.length + " 条有" + metricLabel + "数据，缺失的作品排在最后。"
    : "这份清单暂无" + metricLabel + "数据，暂按最新发布排列。";
  get("list-total").textContent = list.length + " 条作品";
  for (const button of document.querySelectorAll("[data-sort]")) {
    button.setAttribute("aria-pressed", String(button.dataset.sort === order));
    const name = button.dataset.sort;
    const missing = metricLabels[name] && !catalog.some(row => row.metrics?.[name] !== undefined);
    button.classList.toggle("unavailable", Boolean(missing));
    button.title = missing ? "这份清单暂未提供" + metricLabels[name] + "数据" : "";
  }
  page = Math.min(page, Math.max(0, Math.ceil(list.length / pageSize) - 1));
  get("works").replaceChildren(...list.slice(page * pageSize, (page + 1) * pageSize).map(item => {
    const label = element("label", "", "work" + (chosen.has(item.id) ? " selected" : ""));
    const control = check(chosen.has(item.id), item.title, checked => {
      if (checked) chosen.add(item.id); else chosen.delete(item.id);
      label.classList.toggle("selected", checked);
      updateSelection();
    });
    const copy = element("div", "", "video-copy");
    const title = element("p", item.title, "video-title");
    title.title = item.title;
    copy.append(title, element("small", [favorites ? item.author?.name || "原作者待补充" : "",
      item.date || "日期未提供", item.existing].filter(Boolean).join(" · "), "video-meta"));
    label.append(control, copy);
    for (const metric of ["plays", "likes", "saves"]) {
      if (metric === "plays" && order !== "plays") continue;
      const value = item.metrics?.[metric];
      const text = value === undefined ? "—" : value >= 10000 ? (value / 10000).toFixed(1) + "万" : countFormat.format(value);
      const number = element("div", text, "video-metric" + (metric === "plays" ? " plays-metric" : ""));
      number.append(element("small", metricLabels[metric]));
      label.append(number);
    }
    label.classList.toggle("with-plays", order === "plays");
    return label;
  }));
  if (!list.length) get("works").append(element("p", "当前没有符合条件的视频。", "empty"));
  get("page").textContent = list.length ? (page + 1) + " / " + Math.ceil(list.length / pageSize) : "没有符合条件的视频";
  get("previous").disabled = page === 0;
  get("next").disabled = (page + 1) * pageSize >= list.length;
  updateSelection();
}

function updateSelection() {
  const fresh = currentCatalog();
  const n = fresh.filter(row => chosen.has(row.id)).length;
  get("all-works").checked = Boolean(n && n === fresh.length);
  get("all-works").indeterminate = n > 0 && n < fresh.length;
  get("selection").textContent = "已选 " + chosen.size + " 条";
  get("selected-count").textContent = chosen.size;
  get("start").textContent = (local ? "导入所选 " : "下载所选 ") + chosen.size + " 条";
  get("start").disabled = !chosen.size || working || !status;
  get("summary-title").textContent = local ? "本次导入" : "本次下载";
  get("asr-mode").textContent = status?.settings.autoTranscribe ? "自动" : "手动";
  get("import-mode").textContent = status?.settings.autoImport ? "自动" : "手动";
  get("start-hint").textContent = !chosen.size ? "先从左侧勾选感兴趣的视频。" : status?.settings.autoTranscribe
    ? "提交后自动转写，可在「任务进度」里查看。" : "提交后，在「任务进度」里开始转写。";
}

async function loadProfile(value) {
  const match = value.match(/https:\/\/(?:www\.|v\.)douyin\.com\/[^\s，。]+/);
  if (!match) throw new Error("请填入抖音主播主页链接");
  show("正在获取作品列表…");
  openCatalog(await api("works", {profile: match[0]}));
  clearCreatorResults();
  show("");
}

function clearCreatorResults() {
  get("creators").hidden = true;
  get("creators").replaceChildren();
}

submit("search-form", async () => {
  const keyword = get("keyword").value.trim();
  if (/https:\/\/(?:www\.|v\.)douyin\.com\//.test(keyword)) return loadProfile(keyword);
  show("正在搜索主播…");
  clearCreatorResults();
  const data = await api("search", {keyword});
  get("creators").replaceChildren(...data.creators.map(row => {
    const label = row.account ? row.name + " · 抖音号 " + row.account : row.name;
    const control = button(label, () => task(() => loadProfile(row.profile)));
    control.className = "creator";
    if (/^https:\/\//.test(row.avatar)) {
      const image = element("img");
      image.alt = "";
      image.referrerPolicy = "no-referrer";
      image.src = row.avatar;
      control.prepend(image);
    }
    return control;
  }));
  get("creators").hidden = !data.creators.length;
  show(data.creators.length ? "" : data.accountSearch
    ? "没有找到完全匹配的抖音号。可以试试主播名称，或粘贴主播主页链接。"
    : "没有搜到符合条件的主播。");
});

async function loadFavoriteFolders(cursor = 0) {
  show("正在读取收藏夹…");
  const data = await api("favorite-folders", {cursor});
  favoriteFoldersLoaded = true;
  const select = get("favorite-folder");
  const current = select.value;
  if (cursor === 0) select.replaceChildren(new Option("全部收藏", "all"));
  const existing = new Set([...select.options].map(option => option.value));
  for (const row of data.items) {
    if (!existing.has(row.id)) {
      const option = new Option(row.name + (row.count === null ? "" : " · " + row.count + " 条"), row.id);
      option.dataset.name = row.name;
      select.add(option);
      existing.add(row.id);
    }
  }
  if (existing.has(current)) select.value = current;
  nextFolderCursor = data.more ? data.cursor : null;
  get("more-favorite-folders").hidden = !data.more;
  const note = get("favorite-folders-status");
  note.hidden = false;
  note.textContent = select.options.length > 1
    ? "已读取 " + (select.options.length - 1) + " 个收藏夹。"
    : "当前账号未返回命名收藏夹，可尝试「全部收藏」，或在右上角检查登录。";
  show("");
}

get("favorite-folders").addEventListener("click", () => task(() => loadFavoriteFolders()));
get("more-favorite-folders").addEventListener("click", () => task(() => loadFavoriteFolders(nextFolderCursor)));

submit("favorites-form", async () => {
  const select = get("favorite-folder");
  const folder = select.value;
  const title = select.selectedOptions[0].dataset.name || "全部收藏";
  show("正在加载收藏视频…");
  const data = await api("favorite-videos", {folder});
  openCatalog({
    sourceType: "favorites", source: "抖音收藏 · " + title,
    creator: {name: ("收藏 · " + title).slice(0, 100), account: "favorites-" + folder},
    works: data.items, favorites: {folder, title, more: data.more, cursor: data.cursor}
  });
  clearCreatorResults();
  show(data.items.length ? "" : data.more
    ? "本页没有可下载的视频，可继续加载下一页。"
    : "当前账号未返回可下载的收藏视频，可在右上角检查登录。");
});

get("more-favorite-videos").addEventListener("click", () => task(async () => {
  if (!favorites?.more) return;
  show("正在加载更多收藏视频…");
  const data = await api("favorite-videos", {folder: favorites.folder, cursor: favorites.cursor});
  catalog = [...new Map([...catalog, ...data.items].map(row => [row.id, row])).values()];
  favorites.more = data.more;
  favorites.cursor = data.cursor;
  get("more-favorite-videos").hidden = !data.more;
  get("catalog-source").textContent = "抖音收藏 · " + favorites.title + " · 已加载 " + catalog.length + " 条视频";
  drawCatalog();
  show("");
}));

submit("cache-form", async () => openCatalog(await api("works", {profile: get("cached").value, cached: true})));
submit("text-form", async () => openCatalog(await api("text", {text: get("links").value})));
get("txt").addEventListener("change", () => task(async () => {
  const file = get("txt").files[0];
  if (!file) return;
  if (file.size > 300000) throw new Error("链接清单过大");
  const contents = await file.text();
  get("links").value = contents;
  openCatalog(await api("text", {text: contents}));
}));
get("local").addEventListener("click", () => task(async () => {
  const {path} = await api("choose");
  if (path) {
    get("local-path").value = path;
    openCatalog(await api("local", {path}), path);
  }
}));
submit("local-form", async () => {
  const path = get("local-path").value.trim();
  openCatalog(await api("local", {path}), path);
});
get("folder").addEventListener("click", () => task(async () => {
  const {path} = await api("choose");
  if (path) get("destination").value = path;
}));
get("default-folder-choose").addEventListener("click", () => task(async () => {
  const {path} = await api("choose");
  if (path) get("default-folder").value = path;
}));

function drawAccount() {
  const account = status.account;
  if (!account) return;
  get("account-panel").hidden = false;
  const labels = {missing: "请先登录抖音", saved: "已保存登录信息，可以检查当前账号",
    connected: "已连接", check_failed: "登录检查未通过"};
  get("account-status").textContent = (labels[account.state] || "请检查登录") +
    (account.name ? " · " + account.name : "") +
    (account.account ? " · 抖音号 " + account.account : "");
  get("login-guide").hidden = !account.browserOpen;
  get("login-save").hidden = !account.browserOpen;
  get("login-close").hidden = !account.browserOpen;
  get("login-open").disabled = account.browserOpen;
  get("login-check").disabled = !account.configured;
  get("account-dot").classList.toggle("not-connected", account.state !== "connected");
  get("account-open").title = account.name || "抖音账号";
}

for (const action of ["login-open", "login-save", "login-close", "login-check"]) {
  get(action).addEventListener("click", () => task(async () => {
    show({"login-open": "正在打开抖音登录窗口…", "login-save": "正在验证并保存账号…",
      "login-close": "正在关闭登录窗口…", "login-check": "正在检查抖音登录…"}[action]);
    try {
      await api(action);
      show({"login-open": "请在弹出的抖音窗口完成登录，再回到这里保存。",
        "login-save": "抖音账号已保存，搜索、收藏和下载会使用这个账号。",
        "login-close": "登录窗口已关闭。", "login-check": "抖音登录检查通过。"}[action]);
    } finally {
      await refresh();
    }
  }));
}
submit("login-cookie-form", async () => {
  show("正在检查登录信息…");
  await api("login-cookie", {cookie: get("login-cookie").value});
  get("login-cookie").value = "";
  await refresh();
  show("抖音账号已保存。");
});
for (const name of ["sort", "only-new"]) {
  get(name).addEventListener("change", () => { page = 0; drawCatalog(); });
}
get("all-works").addEventListener("change", event => {
  for (const row of currentCatalog()) {
    if (event.target.checked) chosen.add(row.id); else chosen.delete(row.id);
  }
  drawCatalog();
});
get("previous").addEventListener("click", () => { page--; drawCatalog(); });
get("next").addEventListener("click", () => { page++; drawCatalog(); });
submit("start-form", async () => {
  const result = await api("start", {
    name: get("name").value, account: get("account").value,
    destination: get("destination").value, local, compress: get("compress-downloads").checked,
    classificationMode: get('classification-mode').value,
    sourceType: favorites ? "favorites" : "creator",
    works: catalog.filter(row => chosen.has(row.id))
  });
  current = result.batch;
  get('classification-mode').value = '';
  await refresh();
  activateView("tasks");
  get("tasks-tab").focus();
  show(local ? "本地视频已添加到处理批次。" : "下载已提交。");
});
submit("settings-form", async () => {
  await api("settings", {
    downloader: get("downloader").value,
    catalogTool: get("catalog-tool").value,
    autoTranscribe: get("auto-transcribe").value === "true",
    transcribeDevice: get("transcribe-device").value,
    autoImport: get("auto-import").value === "true",
    ...(status.account ? {defaultFolder: get("default-folder").value,
      downloadTimeout: Number(get("download-timeout").value),
      downloadRetries: Number(get("download-retries").value)} : {})
  });
  await refresh(true);
  get("settings-dialog").close();
  show("默认方式已保存。下次开始任务时生效。");
});
get("batch-list").addEventListener("change", event => { current = event.target.value; drawBatch(); });
get("close-preview").addEventListener("click", () => get("preview").close());
library.href = "#";
library.addEventListener("click", event => {
  event.preventDefault();
  task(() => api("library"));
});
for (const link of document.querySelectorAll("[data-library]")) link.onclick = event => {event.preventDefault();library.click();};

function eligible(row, stage) {
  return ["pending", "failed"].includes(row[stage]) &&
    (stage === "download" || stage === "transcribe" && row.download === "done" ||
      stage === "import" && row.transcribe === "done");
}

function progress(batch, stage, title) {
  const success = batch.works.filter(row => ["done", "existing"].includes(row[stage])).length;
  const failed = batch.works.filter(row => row[stage] === "failed").length;
  const skippedRows = batch.works.filter(row => row[stage] === "skipped");
  const skipped = skippedRows.length;
  const running = batch.works.filter(row => row[stage] === "running");
  const pending = batch.works.length - success - failed - skipped - running.length;
  const card = element("div");
  const meter = element("progress");
  meter.max = batch.works.length;
  meter.value = success + failed + skipped;
  meter.setAttribute("aria-label", title + "进度");
  card.append(element("strong", title), meter,
    element("small", "完成 " + success + " · 失败 " + failed + " · 待处理 " + pending +
      (skipped ? " · 跳过 " + skipped : "")));
  if (stage === "compressionState" && skipped) {
    const reasons = new Map();
    for (const row of skippedRows) {
      const reason = row.compression === "原件更小" ? "压缩后未变小，保留原版"
        : batch.compress === false || row.compression === "保留原版"
          ? "按批次设置保留原版"
          : "历史记录未注明跳过原因";
      reasons.set(reason, (reasons.get(reason) || 0) + 1);
    }
    for (const [reason, count] of reasons) {
      card.append(element("p", count + " 条" + reason, "compression-note"));
    }
  }
  if (stage === "transcribe" && batch.transcribeDevice) {
    card.append(element("p", batch.transcribeDevice === "cuda" ? "NVIDIA 显卡加速" : "CPU", "compression-note"));
  }
  if (running.length === 1) {
    const row = running[0];
    card.append(element("p", (stage === "download" ? row.downloadTask : title) + "中 · " + row.title));
  } else if (running.length > 1) {
    card.append(element("p", "正在处理 " + running.length + " 条"));
  }
  else if (batch.stage === stage && pending > 0) card.append(element("p", "正在准备" + title + "…"));
  return card;
}

function runStage(batch, stage, ids) {
  return task(async () => { await api(stage, {batch: batch.id, ids}); await refresh(); });
}

function drawBatch() {
  const parent = get("batch");
  const batch = status.batches.find(item => item.id === current);
  parent.hidden = !batch;
  get("empty").hidden = Boolean(batch);
  if (!batch) return;
  const signature = JSON.stringify([batch, status.settings, status.batches.some(item => item.stage)]);
  if (signature === lastBatch) return;
  lastBatch = signature;
  if (approvedFrom !== batch.id) {
    approvedFrom = batch.id;
    approved.clear();
  }
  const oldScroll = get("batch-works")?.scrollTop || 0;
  const expanded = get("batch-details")?.open || false;
  const operationsOpen = get("batch-operations")?.open || false;
  const states = {pending:"待处理", running:"处理中", done:"已完成", failed:"待重试", existing:"已入库",
    waiting:"等候下载", queued:"排队中", skipped:"已跳过"};
  const active = status.batches.some(item => item.stage);
  const meters = element("div", "", "progress");
  meters.append(progress(batch,"download","下载"), progress(batch,"compressionState","压缩"),
    progress(batch,"transcribe","转写"), progress(batch,"import","入库与摘要"));
  const actions = element("div", "", "row");
  const toDownload = batch.works.filter(row => eligible(row, "download"));
  const toTranscribe = batch.works.filter(row => eligible(row, "transcribe"));
  const toImport = batch.works.filter(row => eligible(row, "import"));
  const dl = button("重试下载", () => runStage(batch, "download", toDownload.map(row => row.id)));
  const asr = button(toTranscribe.some(row => row.transcribe === "failed") ? "开始或重试转写" : "开始转写",
    () => runStage(batch, "transcribe", toTranscribe.map(row => row.id)));
  const all = button("全部入库", () => runStage(batch, "import", toImport.map(row => row.id)));
  const selected = button("所选入库", () => runStage(batch, "import", toImport.filter(row => approved.has(row.id)).map(row => row.id)));
  dl.disabled = active || !toDownload.length;
  asr.disabled = active || !toTranscribe.length;
  all.disabled = active || !toImport.length;
  dl.hidden = !toDownload.length;
  asr.hidden = !toTranscribe.length;
  all.hidden = !toImport.length;
  dl.classList.toggle("primary", !toTranscribe.length && !toImport.length);
  asr.classList.toggle("primary", Boolean(toTranscribe.length));
  const label = element("label", "全选待入库", "check");
  const control = check(false, "全选待入库", checked => {
    for (const row of toImport) { if (checked) approved.add(row.id); else approved.delete(row.id); }
    lastBatch = "";
    drawBatch();
  });
  label.prepend(control);
  control.disabled = !toImport.length;
  label.hidden = !toImport.length;
  const update = () => {
    const count = toImport.filter(row => approved.has(row.id)).length;
    control.checked = Boolean(count && count === toImport.length);
    control.indeterminate = Boolean(count && count < toImport.length);
    selected.textContent = "所选入库" + (count ? " " + count + " 条" : "");
    selected.disabled = active || !count;
    selected.hidden = !count;
    selected.classList.toggle("primary", Boolean(count));
    all.classList.toggle("primary", !count && !toTranscribe.length);
  };
  update();
  actions.append(dl, asr, label, selected, all);
  actions.classList.add("task-actions");
  const operations = element("details", "", "task-operations");
  operations.id = "batch-operations";
  operations.open = operationsOpen;
  operations.append(element("summary", "其他操作"));
  const extras = element("div", "", "row");
  operations.append(extras);
  if (batch.compress && batch.works.some(row => ["waiting", "queued", "failed"].includes(row.compressionState))) {
    extras.append(button("跳过剩余压缩", () => runStage(batch, "skip-compression")));
  }
  if (batch.compress && batch.works.some(row => row.compressionState === "failed")) {
    extras.append(button("重试压缩", () => runStage(batch, "retry-compression")));
  }
  const rows = element("div");
  rows.id = "batch-works";
  for (const row of batch.works) {
    const line = element("div", "", "batch-row");
    const tick = check(approved.has(row.id), "选中入库 " + row.title, checked => {
      if (checked) approved.add(row.id); else approved.delete(row.id);
      update();
    });
    tick.disabled = !eligible(row, "import");
    const title = element("div");
    if (batch.sourceType === "favorites" && row.author) {
      title.append(element("small", row.author.name));
    }
    title.append(element("strong", row.title),
      element("small", ["下载 " + states[row.download], "压缩 " + states[row.compressionState],
        "转写 " + states[row.transcribe], "入库 " + states[row.import],
        row.reused ? "复用已有文件" : "", row.compression].filter(Boolean).join(" · ")));
    const error = row.downloadError || row.compressionError || row.transcribeError || row.importError;
    if (error) title.append(element("small", error, "error-text"));
    const preview = button("预览", () => task(async () => {
      const record = await api("preview", {batch: batch.id, id: row.id});
      get("preview-text").replaceChildren(...record.segments.map(segment => {
        const paragraph = element("p");
        const n = Math.floor(segment.start);
        const time = element("time", String(Math.floor(n / 60)).padStart(2,"0") + ":" + String(n % 60).padStart(2,"0"));
        paragraph.append(time, "  " + segment.text);
        return paragraph;
      }));
      get("preview").showModal();
    }));
    preview.hidden = row.transcribe !== "done";
    line.append(tick, title, preview);
    rows.append(line);
  }
  const top = element("div", "", "task-top");
  const copy = element("div");
  copy.append(element("h2", batch.name), element("p", batch.works.length + " 条视频 · " + batch.created.replace("T", " ")));
  if (batch.classificationMode) copy.append(element('p', batch.classificationMode === 'manual'
    ? '主题归属：入库后到知识库确认推荐或调整'
    : '主题归属：自动整理，不明确的小主题会提示确认'));
  const errors = batch.works.filter(row => [row.download,row.transcribe,row.import].includes("failed")).length;
  const completed = batch.works.every(row => ["done","existing"].includes(row.import));
  const stageName = {download:"正在下载",transcribe:"正在转写",import:"正在入库"}[batch.stage];
  const stateName = stageName || (errors ? errors + " 条待重试" : completed ? "已入库" : toDownload.length ? "待下载" : toTranscribe.length ? "待转写" : toImport.length ? "待入库" : "处理中");
  top.append(copy, element("span", stateName, "status-pill" + (completed ? " done" : "")));
  if (completed) {
    const view = button("查看知识库", () => task(() => api("library")));
    view.className = "primary";
    actions.append(view);
  }
  const bottom = element("div", "", "task-bottom");
  bottom.append(element("small", batch.destination), actions);
  const details = element("details", "", "task-detail");
  details.id = "batch-details";
  details.open = expanded;
  details.append(element("summary", "查看视频明细与口播稿（" + batch.works.length + " 条）"), rows);
  parent.replaceChildren(top, meters, bottom);
  if (active && !batch.stage && (toDownload.length || toTranscribe.length || toImport.length)) {
    parent.append(element("p", "另一批视频正在处理，完成后可继续本批。", "small-note"));
  }
  if (extras.children.length) parent.append(operations);
  parent.append(details);
  if (batch.error) parent.append(element("p", batch.error, "error-text"));
  rows.scrollTop = oldScroll;
}

async function refresh(first = false) {
  status = await api("status");
  drawAccount();
  updateSelection();
  get("task-badge").textContent = status.batches.length;
  drawRecent();
  if (first) fillSettings();
  for (const [field, capability] of [["downloader", "download"], ["catalog-tool", "catalog"]]) {
    const option = get(field).querySelector('[value="f2"]');
    option.disabled = !status.f2[capability];
    option.textContent = status.f2[capability] ? "F2" : status.f2.installed ? "F2（尚未通过验证）" : "F2（未安装）";
  }
  if (!status.batches.some(batch => batch.id === current)) current = status.batches[0]?.id || "";
  const list = get("batch-list");
  const signature = status.batches.map(batch => batch.id).join(",");
  if (signature !== lastBatchList) {
    lastBatchList = signature;
    list.replaceChildren(...status.batches.map(batch => {
      const option = element("option", batch.name + " · " + batch.created.replace("T"," ") + " · " + batch.works.length + " 条");
      option.value = batch.id;
      return option;
    }));
  }
  list.hidden = !current;
  list.value = current;
  drawBatch();
}

function fillSettings() {
  if (!status) return;
  if (status.account) {
    get("download-config").hidden = false;
    get("default-folder").value = status.defaultFolder || "";
    get("download-timeout").value = status.account.downloadTimeout;
    get("download-retries").value = status.account.downloadRetries;
  }
  get("downloader").value = status.settings.downloader;
  get("catalog-tool").value = status.settings.catalogTool;
  get("auto-transcribe").value = String(status.settings.autoTranscribe);
  get("auto-import").value = String(status.settings.autoImport);
  if (status.settings.transcribeDevice) {
    get("transcribe-device").value = status.settings.transcribeDevice;
    get("transcribe-device-setting").hidden = false;
  }
}

refresh(true).then(() => {
  let refreshing = false;
  setInterval(async () => {
    if (refreshing || document.hidden) return;
    refreshing = true;
    try { await refresh(); } catch (error) { show(error.message, true); }
    finally { refreshing = false; }
  }, 1500);
}).catch(error => show(error.message || "请从个人知识工作台重新打开。", true));
