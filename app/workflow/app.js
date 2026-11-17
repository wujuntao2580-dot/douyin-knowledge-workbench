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
let status = null;
let current = "";
let approved = new Set();
let approvedFrom = "";
let lastBatch = "";
let lastBatchList = "";
let working = false;
const pageSize = 35;
const metricLabels = {plays: "播放量", likes: "点赞", saves: "收藏"};
const countFormat = new Intl.NumberFormat("zh-CN");

function show(message, error = false) {
  notice.textContent = message;
  notice.classList.toggle("error", error);
  notice.hidden = !message;
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
  show("");
  try { await fn(); }
  catch (error) { show(error.message, true); }
  finally { working = false; }
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
  page = 0;
  chosen.clear();
  get("name").value = data.creator.name || "";
  get("account").value = data.creator.account || "";
  get("destination").value = folder || (data.creator.account && status?.defaultFolder
    ? status.defaultFolder + "\\" + data.creator.account : "");
  get("destination").readOnly = local;
  get("folder").hidden = local;
  get("start").textContent = local ? "添加所选" : "下载所选";
  get("catalog-source").textContent = data.source + " · " + catalog.length + " 条视频";
  get("picker").hidden = false;
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
  page = Math.min(page, Math.max(0, Math.ceil(list.length / pageSize) - 1));
  get("works").replaceChildren(...list.slice(page * pageSize, (page + 1) * pageSize).map(item => {
    const label = element("label", "", "work");
    const control = check(chosen.has(item.id), item.title, checked => {
      if (checked) chosen.add(item.id); else chosen.delete(item.id);
      updateSelection();
    });
    const metrics = Object.entries(metricLabels)
      .filter(([key]) => item.metrics?.[key] !== undefined)
      .map(([key, title]) => title + " " + countFormat.format(item.metrics[key]));
    const details = element("small", "", "work-meta");
    details.append(element("span", [item.date, item.existing].filter(Boolean).join(" · ")));
    if (metrics.length) details.append(element("span", metrics.join(" · ")));
    label.append(control, element("span", item.title), details);
    return label;
  }));
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
  get("start").disabled = !chosen.size;
}

async function loadProfile(value) {
  const match = value.match(/https:\/\/(?:www\.|v\.)douyin\.com\/[^\s，。]+/);
  if (!match) throw new Error("请填入抖音主播主页链接");
  show("正在获取作品列表…");
  openCatalog(await api("works", {profile: match[0]}));
  show("");
}

submit("search-form", async () => {
  show("正在搜索主播…");
  get("creators").hidden = true;
  get("creators").replaceChildren();
  const data = await api("search", {keyword: get("keyword").value});
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

submit("profile-form", () => loadProfile(get("profile").value));
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
    works: catalog.filter(row => chosen.has(row.id))
  });
  current = result.batch;
  await refresh();
  get("batch-list").scrollIntoView({block:"nearest"});
  show(local ? "本地视频已添加到处理批次。" : "下载已提交。");
});
submit("settings-form", async () => {
  await api("settings", {
    downloader: get("downloader").value,
    catalogTool: get("catalog-tool").value,
    autoTranscribe: get("auto-transcribe").value === "true",
    transcribeDevice: get("transcribe-device").value,
    autoImport: get("auto-import").value === "true"
  });
  show("默认方式已保存。下次开始任务时生效。");
});
get("batch-list").addEventListener("change", event => { current = event.target.value; drawBatch(); });
get("close-preview").addEventListener("click", () => get("preview").close());
library.href = "#";
library.addEventListener("click", event => {
  event.preventDefault();
  if (history.length > 1) history.back();
  else task(() => api("library"));
});

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
  const signature = JSON.stringify([batch, status.batches.some(item => item.stage)]);
  if (signature === lastBatch) return;
  lastBatch = signature;
  if (approvedFrom !== batch.id) {
    approvedFrom = batch.id;
    approved.clear();
  }
  const oldScroll = get("batch-works")?.scrollTop || 0;
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
  const label = element("label", "全选待入库", "check");
  const control = check(false, "全选待入库", checked => {
    for (const row of toImport) { if (checked) approved.add(row.id); else approved.delete(row.id); }
    lastBatch = "";
    drawBatch();
  });
  label.prepend(control);
  control.disabled = !toImport.length;
  const update = () => {
    const count = toImport.filter(row => approved.has(row.id)).length;
    control.checked = Boolean(count && count === toImport.length);
    control.indeterminate = Boolean(count && count < toImport.length);
    selected.textContent = "所选入库" + (count ? " " + count + " 条" : "");
    selected.disabled = active || !count;
  };
  update();
  actions.append(dl, asr, label, selected, all);
  if (batch.compress && batch.works.some(row => ["waiting", "queued", "failed"].includes(row.compressionState))) {
    actions.append(button("跳过剩余压缩", () => runStage(batch, "skip-compression")));
  }
  if (batch.compress && batch.works.some(row => row.compressionState === "failed")) {
    actions.append(button("重试压缩", () => runStage(batch, "retry-compression")));
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
  parent.replaceChildren(element("p", batch.destination, "muted"), meters, actions, rows);
  if (batch.error) parent.append(element("p", batch.error, "error-text"));
  rows.scrollTop = oldScroll;
}

async function refresh(first = false) {
  status = await api("status");
  if (first) {
    get("downloader").value = status.settings.downloader;
    get("catalog-tool").value = status.settings.catalogTool;
    get("auto-transcribe").value = String(status.settings.autoTranscribe);
    if (status.settings.transcribeDevice) {
      get("transcribe-device").value = status.settings.transcribeDevice;
      get("transcribe-device-setting").hidden = false;
    }
    get("auto-import").value = String(status.settings.autoImport);
  }
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

refresh(true).then(() => {
  let refreshing = false;
  setInterval(async () => {
    if (refreshing || document.hidden) return;
    refreshing = true;
    try { await refresh(); } catch (error) { show(error.message, true); }
    finally { refreshing = false; }
  }, 1500);
}).catch(error => show(error.message || "请从个人知识工作台重新打开。", true));
