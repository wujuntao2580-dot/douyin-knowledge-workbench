import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from threading import Lock, Thread
from urllib.error import URLError
from uuid import uuid4

import av

from providers import CACHE, PROJECT, F2, ID, URL, DouK, F2Downloader, video_url, work_metrics
from douyin_account import DouyinAccount

sys.path.insert(0, str(PROJECT / 'app/knowledge'))
from library_state import LibraryState

sys.path.insert(0, str(PROJECT / "app/compression"))
from compress_downloads import BUILDER, MEDIA, compress_video
sys.path.insert(0, str(BUILDER.parent))
from creator_imports import load_works, read_registry, register


NO_WINDOW = subprocess.CREATE_NO_WINDOW
PYTHON = Path(sys.executable).with_name("python.exe")
TRANSCRIBE = PROJECT / "app/transcription/transcribe.py"
SUMMARIZE = PROJECT / "app/summary/summarize_offline.py"
STATE_FILE = CACHE / "queue.json"
F2_CHECK = CACHE / "f2-verification.json"
PROFILE_CACHE = CACHE / "creator-profiles.json"
LOG = logging.getLogger("workbench.workflow")
ACCOUNT = re.compile(r"[\w.-]{1,180}")
LOCAL_ID = re.compile(r"^([0-9]{19})(?![0-9])")
DEFAULTS = {"autoTranscribe": True, "autoImport": True, "downloader": "douk", "catalogTool": "douk",
            "transcribeDevice": "cpu"}


def save_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def safe_account(account):
    if not isinstance(account, str) or not ACCOUNT.fullmatch(account) or account in {".", ".."}:
        raise ValueError("请填写有效的主播账号")
    return account


def folder_path(value, allow_create=False):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("请选择保存文件夹")
    path = Path(value.strip())
    if not path.is_absolute() or not re.fullmatch(r"[A-Za-z]:", path.drive):
        raise ValueError("请选择本机磁盘上的完整文件夹路径")
    path = path.resolve()
    windows = Path(os.environ.get("WINDIR", r"C:\Windows")).resolve()
    if path.is_relative_to(windows):
        raise ValueError("请选择普通文件夹")
    if not path.is_dir() and not (allow_create and not path.exists() and path.parent.is_dir()):
        raise ValueError("找不到该文件夹，请检查路径")
    return path


def inspect_video(path):
    with av.open(str(path)) as container:
        streams = container.streams
        if not streams.video or not any(container.decode(video=0)):
            raise ValueError("文件没有可解码的视频画面")
        return bool(streams.audio)


def archive_path(video_id):
    compressed = MEDIA / f"{video_id}.mp4"
    if compressed.is_file():
        return compressed
    return None


def known_catalogs():
    for creator_id, creator in read_registry().items():
        yield creator_id.removeprefix("douyin:"), creator


def existing_media(video_ids):
    media = {}
    for _, creator in known_catalogs():
        for path in (PROJECT / creator["media"]).glob("*.mp4"):
            match = LOCAL_ID.match(path.name)
            if match and match[1] in video_ids:
                media.setdefault(match[1], path)
    return media


def legacy_or_registered():
    indexed = {}
    removed = LibraryState().deleted_records()
    for account, creator in known_catalogs():
        for video_id, work in load_works(f"douyin:{account}", creator).items():
            if video_id in removed:
                continue
            indexed[video_id] = (account, work)
    return indexed


def saved_profiles():
    profiles = json.loads(PROFILE_CACHE.read_text(encoding="utf-8")) if PROFILE_CACHE.is_file() else {}
    for account, creator in known_catalogs():
        for path in creator["catalogs"]:
            catalog = json.loads((PROJECT / path).read_text(encoding="utf-8-sig"))
            profile = catalog.get("profileUrl")
            if profile:
                profiles[profile] = {**profiles.get(profile, {}), "name": creator["name"],
                                     "account": account, "profile": profile}
    return profiles


def remember_profiles(rows):
    if not rows:
        return
    cache = json.loads(PROFILE_CACHE.read_text(encoding="utf-8")) if PROFILE_CACHE.is_file() else {}
    cache.update({row["profile"]: row for row in rows})
    save_json(PROFILE_CACHE, cache)


def choose_folder():
    script = """
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Windows.Forms
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true
$owner.Opacity = 0
$owner.ShowInTaskbar = $false
$owner.Show()
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = '请选择视频文件夹'
$dialog.ShowNewFolderButton = $true
try {
    if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {
        [Console]::WriteLine($dialog.SelectedPath)
    }
} finally {
    $dialog.Dispose()
    $owner.Dispose()
}
"""
    result = subprocess.run(["powershell.exe", "-NoProfile", "-STA", "-Command", script],
                            capture_output=True, creationflags=NO_WINDOW, timeout=180,
                            text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise ValueError("无法打开文件夹选择窗口，请直接输入完整保存路径。")
    return result.stdout.rstrip("\r\n")


class Workflow:
    def retire_deleted(self, ids):
        """Keep batch history but prevent old workers/retry controls restoring deleted material."""
        for batch in self.state['batches']:
            for row in batch['works']:
                if row['id'] in ids:
                    row.update(deleted=True, download='skipped', transcribe='skipped',
                               compressionState='skipped', compression='已清理所选资料', **{'import': 'skipped'})
        self.save()

    def __init__(self, state_file=STATE_FILE, douk=None, account=None):
        self.file = state_file
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.lock = Lock()
        self.provider_lock = Lock()
        self.douk = douk or DouK()
        self.providers = {"douk": self.douk, "f2": F2Downloader()}
        self.account = account or DouyinAccount(queue_path=state_file)
        self.state = (json.loads(self.file.read_text(encoding="utf-8")) if self.file.exists()
                      else {"settings": DEFAULTS.copy(), "batches": []})
        self.active = None
        self.compressing = False
        for batch in self.state["batches"]:
            batch["stage"] = ""
            batch.setdefault("compress", True)
            for row in batch["works"]:
                for field in ("download", "transcribe", "import"):
                    if row.get(field) == "running":
                        row[field] = "failed"
                        row[field + "Error"] = "上次处理被中断，可以重试。"
                if row.get("compressionState") == "running":
                    row["compressionState"] = "queued" if batch["compress"] else "skipped"
                row.setdefault("compressionState", {
                    "已是压缩版": "done", "已有压缩版": "done", "已压缩": "done", "原件更小": "skipped",
                    "压缩失败，已保留原件": "failed",
                }.get(row.get("compression"), "skipped" if row["download"] == "done" or not batch["compress"] else "waiting"))
        self.save()
        with self.lock:
            self.start_compressor()

    def save(self):
        save_json(self.file, self.state)

    def status(self):
        with self.lock:
            data = json.loads(json.dumps(self.state))
        data["settings"] = {**DEFAULTS, **data["settings"]}
        return {**data, "f2": self.f2_status(), "account": self.account.view()}

    @staticmethod
    def f2_status():
        if F2.is_file() and F2_CHECK.is_file():
            return {"installed": True, **json.loads(F2_CHECK.read_text(encoding="utf-8"))}
        return {"installed": F2.is_file(), "download": False, "catalog": False}

    def update(self, row, stage, state, error="", **extra):
        with self.lock:
            row.update({stage: state, stage + "Error": error, **extra})
            self.save()

    def act(self, route, data):
        if route == "login-open":
            return self.account.open_login()
        if route == "login-save":
            return self.account.save_browser()
        if route == "login-close":
            return self.account.close_login()
        if route == "login-check":
            return self.account.check()
        if route == "login-cookie":
            return self.account.save(data.get("cookie"))
        if route == "settings":
            downloader = data.get("downloader", "douk")
            catalog_tool = data.get("catalogTool", "douk")
            device = data.get("transcribeDevice", "cpu")
            if device not in ("cpu", "cuda"):
                raise ValueError("请选择 CPU 或 NVIDIA 显卡加速")
            config = self.account.view()
            timeout = data.get("downloadTimeout", config["downloadTimeout"])
            retries = data.get("downloadRetries", config["downloadRetries"])
            if type(timeout) is not int or not 3 <= timeout <= 120:
                raise ValueError("请求超时请填写 3 至 120 秒")
            if type(retries) is not int or not 0 <= retries <= 10:
                raise ValueError("重试次数请填写 0 至 10")
            default_folder = str(folder_path(data.get("defaultFolder") or str(PROJECT / "data/inputs")))
            backup = self.f2_status()
            if downloader not in self.providers or downloader == "f2" and not backup["download"]:
                raise ValueError("当前无法使用这个下载工具")
            if catalog_tool not in self.providers or catalog_tool == "f2" and not backup["catalog"]:
                raise ValueError("当前无法使用这个主页作品工具")
            with self.lock:
                self.state["settings"] = {"downloader": downloader, "catalogTool": catalog_tool,
                                          "downloadTimeout": timeout, "downloadRetries": retries,
                                          "defaultFolder": default_folder,
                                          "transcribeDevice": device,
                                          "autoTranscribe": data.get("autoTranscribe") is True,
                                          "autoImport": data.get("autoImport") is True}
                self.save()
            return {}
        if route == "choose":
            return {"path": choose_folder()}
        if route == "search":
            keyword = str(data.get("keyword", "")).strip()
            prefix = re.match(r"^(?:抖音号\s*[:：]|[@＠])\s*", keyword)
            if prefix:
                keyword = keyword[prefix.end():].strip()
            if not keyword or len(keyword) > 80:
                raise ValueError("请输入主播名称或抖音号")
            exact_account = bool(prefix) or bool(re.fullmatch(r"[0-9]+", keyword))
            target = keyword.casefold()

            def account_matches(row):
                return any(target == account.casefold() for account in [row["account"], *row.get("accounts", [])])

            with self.provider_lock:
                profiles = saved_profiles()
                cached = [row for row in profiles.values() if account_matches(row)]
                if cached:
                    return {"creators": cached, "accountSearch": True}
                known = {url: row for url, row in profiles.items() if target == row["name"].casefold()}
                try:
                    candidates = self.douk.search(keyword)
                except (OSError, ValueError):
                    if known and not exact_account:
                        return {"creators": list(known.values())}
                    raise
                matched = [row for row in candidates if account_matches(row)]
                remember_profiles([row for row in candidates if row["account"] and
                                   (account_matches(row) or row["name"].casefold() == target)])
                if matched:
                    return {"creators": [{**profiles.get(row["profile"], {}), **row} for row in matched],
                            "accountSearch": True}
            if exact_account:
                return {"creators": [], "accountSearch": True}
            for row in candidates:
                identity = profiles.get(row["profile"])
                known[row["profile"]] = {**row, **(identity or {})}
            return {"creators": list(known.values())}
        if route == "works":
            profile = str(data.get("profile", "")).strip()
            if data.get("cached") is True:
                return self.cached_works(profile)
            with self.lock:
                provider = self.state["settings"].get("catalogTool", "douk")
            with self.provider_lock:
                result = self.providers[provider].works(profile)
            if known := saved_profiles().get(result.get("profile")):
                result["creator"] = {"name": known["name"], "account": known["account"]}
            return self.decorate(result)
        if route == "favorite-folders":
            with self.provider_lock:
                return self.providers["f2"].favorites_page("folders", cursor=data.get("cursor", 0))
        if route == "favorite-videos":
            folder = data.get("folder", "all")
            with self.provider_lock:
                result = self.providers["f2"].favorites_page("videos", folder, data.get("cursor", 0))
            decorated = self.decorate({"creator": {}, "works": result["items"]})
            return {**result, "items": decorated["works"]}
        if route == "text":
            return self.text_works(str(data.get("text", "")))
        if route == "local":
            return self.local_works(folder_path(data.get("path")))
        if route == "start":
            return self.create(data)
        if route in {"skip-compression", "retry-compression"}:
            with self.lock:
                batch = next((item for item in self.state["batches"] if item["id"] == data.get("batch")), None)
                if batch is None:
                    raise ValueError("这个批次不存在")
                if route == "skip-compression":
                    batch["compress"] = False
                    for row in batch["works"]:
                        if row["compressionState"] in {"waiting", "queued", "failed"}:
                            row.update(compressionState="skipped", compression="保留原版", compressionError="")
                elif batch["compress"]:
                    for row in batch["works"]:
                        if row["compressionState"] == "failed":
                            row.update(compressionState="queued", compression="", compressionError="")
                self.save()
                self.start_compressor()
            return {}
        if route in {"download", "transcribe", "import"}:
            with self.lock:
                batch = next((item for item in self.state["batches"] if item["id"] == data.get("batch")), None)
                if batch is None:
                    raise ValueError("这个批次不存在")
                ids = data.get("ids")
                if ids is not None and (not isinstance(ids, list) or any(not isinstance(v, str) for v in ids)):
                    raise ValueError("作品列表无效")
                rows = [row for row in batch["works"] if (ids is None or row["id"] in ids)
                        and self.eligible(row, route)]
                self.start(batch, route, rows)
            return {"batch": batch["id"]}
        if route == "preview":
            with self.lock:
                batch = next((item for item in self.state["batches"] if item["id"] == data.get("batch")), None)
                if batch is None:
                    raise ValueError("这批作品不存在")
                row = next((row for row in batch["works"] if row["id"] == data.get("id") and row["transcribe"] == "done"), None)
                if not row:
                    raise ValueError("这条作品还没有完成转写")
                record = self.batch_path(batch) / "records" / f"{row['id']}.json"
            return {"segments": json.loads(record.read_text(encoding="utf-8"))["segments"]}
        raise ValueError("未知操作")

    def decorate(self, result):
        prior = legacy_or_registered()
        with self.lock:
            states = {}
            for batch in self.state["batches"]:
                for row in batch["works"]:
                    if row["transcribe"] == "done":
                        states[row["id"]] = "已转写"
                    elif row["download"] == "done" and row.get("file") and Path(row["file"]).is_file():
                        states.setdefault(row["id"], "已下载")
        for row in result["works"]:
            row["existing"] = ("已入库" if row["id"] in prior else states.get(row["id"], ""))
            if not row["existing"] and archive_path(row["id"]):
                row["existing"] = "已下载"
        return result

    def cached_works(self, profile):
        account = safe_account(profile)
        entries = [(key, creator) for key, creator in known_catalogs() if key == account]
        if not entries:
            raise ValueError("没有找到该主播的本地作品清单")
        works = {}
        for key, creator in entries:
            for video_id, work in load_works(f"douyin:{key}", creator).items():
                works[video_id] = {"id": video_id, "title": work.get("title") or work.get("desc") or video_id,
                                   "date": work.get("date") or "", "url": work["videoUrl"],
                                   "metrics": work_metrics(work)}
        return self.decorate({"creator": {"name": entries[0][1]["name"], "account": account},
                              "works": list(works.values()), "source": "本地作品清单"})

    def text_works(self, content):
        if len(content) > 300000:
            raise ValueError("链接清单过大")
        rows = {}
        for line in content.replace("\ufeff", "", 1).splitlines():
            line = line.strip()
            if not line:
                continue
            match = URL.fullmatch(line)
            if not match:
                raise ValueError("TXT 每行应填写一条抖音视频完整链接（含 /video/）")
            video_id = match[1]
            rows[video_id] = {"id": video_id, "title": video_id, "date": "", "url": video_url(video_id)}
        if not rows:
            raise ValueError("清单中没有视频链接")
        prior = legacy_or_registered()
        removed = LibraryState().deleted_records()
        for video_id, row in rows.items():
            if video_id in removed:
                row['forceImport'] = True
            if video_id in prior:
                work = prior[video_id][1]
                row.update(title=work.get("title") or work.get("desc") or video_id,
                           date=work.get("date") or "", metrics=work_metrics(work))
        return self.decorate({"creator": {}, "works": list(rows.values()), "source": "TXT 链接清单"})

    def local_works(self, folder):
        rows = {}
        for path in sorted(folder.glob("*.mp4")):
            if match := LOCAL_ID.match(path.stem):
                video_id = match[1]
                url = video_url(video_id)
            else:
                digest = hashlib.sha256(os.path.normcase(str(path)).encode()).hexdigest()
                video_id = "1" + str(int(digest, 16) % 10**18).zfill(18)
                url = ""
            rows[video_id] = {"id": video_id, "title": path.stem, "date": "", "url": url, "file": str(path)}
        if not rows:
            raise ValueError("该文件夹中没有 MP4 文件")
        return self.decorate({"creator": {}, "works": list(rows.values()), "source": "本地视频"})

    def create(self, data):
        name = str(data.get("name", "")).strip()
        if not name or len(name) > 100:
            raise ValueError("请填写主播名称")
        account = safe_account(data.get("account"))
        is_local = data.get("local") is True
        compress = data.get("compress") is not False
        classification = data.get('classificationMode')
        if classification not in ('auto', 'manual'):
            raise ValueError('请为本批视频选择自动归属或推荐后手动确认')
        from_favorites = data.get("sourceType") == "favorites"
        if from_favorites and is_local:
            raise ValueError("收藏来源不能同时使用本地视频导入")
        destination = folder_path(data.get("destination"), allow_create=not is_local)
        selection = data.get("works")
        if not isinstance(selection, list) or not 1 <= len(selection) <= 3000:
            raise ValueError("请选择 1 至 3000 条视频")
        rows = {}
        for item in selection:
            video_id = str(item.get("id", ""))
            if not ID.fullmatch(video_id):
                raise ValueError("作品 ID 无效")
            url = item.get("url") or ""
            if url != video_url(video_id) and (not is_local or url):
                raise ValueError("视频链接与作品 ID 不匹配")
            record = {"id": video_id, "title": str(item.get("title") or video_id)[:500],
                      "date": str(item.get("date") or "")[:10], "url": url,
                      "metrics": work_metrics(item),
                      "compressionState": "waiting" if compress else "skipped",
                      "download": "pending", "transcribe": "pending", "import": "pending"}
            if from_favorites:
                author = item.get("author")
                if not isinstance(author, dict):
                    raise ValueError("收藏视频缺少原作者信息，请重新加载收藏夹")
                author_name = str(author.get("name") or "").strip()
                author_account = str(author.get("account") or "")
                if author_name and len(author_name) <= 100 and ACCOUNT.fullmatch(author_account) and author_account not in {".", ".."}:
                    record["author"] = {"name": author_name, "account": author_account,
                                        "secUid": str(author.get("secUid") or "")}
            if is_local:
                file = Path(str(item.get("file", ""))).resolve()
                if file.parent != destination or file.suffix.lower() != ".mp4" or not file.is_file():
                    raise ValueError("本地视频必须在选定的文件夹里")
                record["file"] = str(file)
            rows[video_id] = record
        prior = legacy_or_registered()
        removed = LibraryState().deleted_records()
        for video_id, row in rows.items():
            if video_id in removed:
                row['forceImport'] = True
            if video_id in prior:
                row["import"] = "existing"
        batch = {"id": uuid4().hex[:12], "name": name, "account": account, "destination": str(destination),
                 "sourceType": "favorites" if from_favorites else "creator",
                 "local": is_local, "compress": compress, "classificationMode": classification, "works": list(rows.values()), "created": datetime.now().isoformat(timespec="minutes"),
                 "stage": "", "error": ""}
        with self.lock:
            if self.active:
                raise ValueError("已有一批作品正在处理")
            self.state["batches"].insert(0, batch)
            LibraryState().restore_import(list(rows))
            self.start(batch, "download", batch["works"])
        return {"batch": batch["id"]}

    @staticmethod
    def eligible(row, stage):
        if row.get('deleted'):
            return False
        if row[stage] not in {"pending", "failed"}:
            return False
        if stage == "transcribe":
            return row["download"] == "done"
        if stage == "import":
            return row["transcribe"] == "done"
        return True

    def start(self, batch, step, rows):
        if self.active:
            raise ValueError("已有一批作品正在处理，请等当前任务结束。")
        if not rows:
            raise ValueError("没有符合条件的作品")
        self.active = batch["id"]
        batch.update(stage=step, error="")
        self.save()
        Thread(target=self.run, args=(batch, step, rows, self.state["settings"].copy()), daemon=True).start()

    def batch_path(self, batch):
        path = self.file.parent / "batches" / batch["id"]
        path.mkdir(parents=True, exist_ok=True)
        return path

    def run(self, batch, step, rows, settings):
        try:
            if step == "download":
                self.download(batch, rows, settings["downloader"])
                if not settings["autoTranscribe"]:
                    return
                rows = [row for row in rows if self.eligible(row, "transcribe")]
                step = "transcribe"
            if step == "transcribe" and rows:
                self.transcribe(batch, rows, settings.get("transcribeDevice", "cpu"))
                if not settings["autoImport"]:
                    return
                rows = [row for row in rows if self.eligible(row, "import")]
                step = "import"
            if step == "import" and rows:
                self.import_works(batch, rows)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, URLError, av.FFmpegError) as error:
            LOG.warning("任务 %s 失败：%s", batch["id"], type(error).__name__)
            with self.lock:
                batch["error"] = message(error)
        except Exception:
            LOG.exception("批次 %s 发生异常", batch["id"])
            with self.lock:
                batch["error"] = "处理失败，请查看工作台日志。"
        finally:
            with self.lock:
                for row in batch["works"]:
                    for field in ("download", "transcribe", "import"):
                        if row[field] == "running":
                            row[field] = "failed"
                            row[field + "Error"] = batch["error"] or "处理被中断，可以重试。"
                batch["stage"] = ""
                self.active = None
                self.save()

    def stage(self, batch, stage):
        with self.lock:
            batch["stage"] = stage
            self.save()

    def download(self, batch, rows, provider):
        dest = Path(batch["destination"])
        dest.mkdir(exist_ok=True)
        prior_files = {}
        with self.lock:
            for old in self.state["batches"]:
                for item in old["works"]:
                    if item["download"] == "done" and item.get("file") and Path(item["file"]).is_file():
                        prior_files.setdefault(item["id"], Path(item["file"]))
        for key, path in existing_media({row["id"] for row in rows}).items():
            prior_files.setdefault(key, path)
        stage = self.batch_path(batch) / "media"
        stage.mkdir(exist_ok=True)
        ready = []
        pending = []
        for row in rows:
            key = row["id"]
            existing = Path(row["file"]) if batch["local"] else dest / f"{key}.mp4"
            if not existing.is_file():
                existing = prior_files.get(key) or archive_path(key) or existing
            if existing.is_file():
                ready.append((row, existing))
            else:
                pending.append(row)
        for row, file in ready:
            if not batch["local"] and file.parent != dest:
                self.update(row, "download", "running", reused=True)
            self.finish_media(batch, row, file)
        if not pending:
            return
        with self.provider_lock:
            try:
                with self.providers[provider].downloader(stage) as fetch:
                    for row in pending:
                        key = row["id"]
                        self.update(row, "download", "running", downloadTool=provider, downloadTask="下载")
                        try:
                            staged = next(stage.glob(f"{key}*.mp4"), None)
                            if staged is None:
                                fetch(key)
                                staged = next(stage.glob(f"{key}*.mp4"), None)
                            if staged is None:
                                raise ValueError("未找到下载文件")
                            try:
                                inspect_video(staged)
                            except (OSError, ValueError, av.FFmpegError):
                                staged.unlink(missing_ok=True)
                                raise
                            target = dest / f"{key}.mp4"
                            if not target.is_file():
                                temporary = dest / f".{key}-{batch['id']}.partial"
                                try:
                                    shutil.copyfile(staged, temporary)
                                    if not target.exists():
                                        temporary.rename(target)
                                finally:
                                    temporary.unlink(missing_ok=True)
                            staged.unlink(missing_ok=True)
                            self.finish_media(batch, row, target)
                        except (OSError, ValueError, subprocess.SubprocessError, av.FFmpegError) as error:
                            self.update(row, "download", "failed", message(error))
            except (OSError, ValueError) as error:
                for row in pending:
                    if row["download"] != "done":
                        self.update(row, "download", "failed", message(error))

    def finish_media(self, batch, row, file):
        self.update(row, "download", "running", downloadTask="检查")
        try:
            has_audio = inspect_video(file)
        except (OSError, ValueError, av.FFmpegError) as error:
            self.update(row, "download", "failed", message(error))
            return
        with self.lock:
            if file.parent == MEDIA:
                compression_state, description = "done", "已是压缩版"
            elif batch["compress"]:
                compression_state, description = "queued", ""
            else:
                compression_state, description = "skipped", "保留原版"
            row.update(download="done", downloadError="", file=str(file), audio=has_audio,
                       compressionState=compression_state, compression=description, compressionError="")
            self.save()
            self.start_compressor()

    def start_compressor(self):
        if self.compressing or not any(row["compressionState"] == "queued"
                                      for batch in self.state["batches"] for row in batch["works"]):
            return
        self.compressing = True
        Thread(target=self.compress_queue, daemon=True).start()

    def compress_queue(self):
        while True:
            with self.lock:
                row = next((row for batch in reversed(self.state["batches"]) for row in batch["works"]
                            if row["compressionState"] == "queued"), None)
                if row is None:
                    self.compressing = False
                    return
                row.update(compressionState="running", compression="")
                self.save()
            try:
                result = compress_video(row["id"], Path(row["file"]), background=True)
            except (OSError, ValueError, TypeError, IndexError, subprocess.SubprocessError, av.FFmpegError) as error:
                with self.lock:
                    row.update(compressionState="failed", compression="压缩失败", compressionError=message(error))
                    self.save()
                continue
            state, description = {"already_compact": ("done", "已有压缩版"), "compressed": ("done", "已压缩"),
                                  "original_smaller": ("skipped", "原件更小")}[result]
            with self.lock:
                row.update(compressionState=state, compression=description, compressionError="")
                refresh = result == "compressed" and (row.get("registered") or row["import"] in {"done", "existing"})
                self.save()
            if refresh:
                try:
                    subprocess.run([PYTHON, "-B", "-X", "utf8", BUILDER], stdout=subprocess.DEVNULL,
                                   creationflags=NO_WINDOW, check=True, timeout=60)
                except (OSError, subprocess.SubprocessError):
                    LOG.warning("压缩版已保存，工作台刷新失败：%s", row["id"])

    def transcribe(self, batch, rows, device):
        with self.lock:
            batch.update(stage="transcribe", transcribeDevice=device)
            self.save()
        directory = self.batch_path(batch)
        records = directory / "records"
        transcripts = directory / "transcripts"
        selection = {}
        for row in rows:
            path = Path(row["file"])
            if not path.is_file():
                self.update(row, "transcribe", "failed", "本地视频文件已移动或删除。")
            else:
                selection[row["id"]] = str(path)
        if not selection:
            return
        request = directory / "transcribe.json"
        save_json(request, selection)
        by_id = {row["id"]: row for row in rows}
        command = [PYTHON, "-B", "-u", "-X", "utf8", TRANSCRIBE, "--device", device,
                   "--selection", request, "--records", records, "--transcripts", transcripts]
        if device == "cuda":
            command.extend(("--batch-size", "4"))
        with (directory / "transcribe.log").open("a", encoding="utf-8") as log, subprocess.Popen(command,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                              encoding="utf-8", errors="replace", creationflags=NO_WINDOW) as process:
            for line in process.stdout:
                log.write(line)
                log.flush()
                parts = line.split(maxsplit=2)
                if len(parts) < 2 or parts[1] not in by_id:
                    continue
                status, video_id = parts[:2]
                row = by_id[video_id]
                if status == "START":
                    self.update(row, "transcribe", "running")
                elif status == "OK":
                    self.update(row, "transcribe", "done")
                elif status in {"FAILED", "NO_AUDIO"}:
                    cause = ("视频没有音轨" if status == "NO_AUDIO" else
                             "显卡转写失败或未识别到口播，可切到 CPU 重试" if device == "cuda" else
                             "Whisper 未识别到口播或转写失败")
                    self.update(row, "transcribe", "failed", cause)
            process.wait()
        for key in selection:
            row = by_id[key]
            if (records / f"{key}.json").is_file():
                self.update(row, "transcribe", "done")
            elif row["transcribe"] != "failed":
                cause = ("显卡转写未生成逐字稿，请检查显卡环境，或切到 CPU 重试。" if device == "cuda" else
                         "转写没有生成逐字稿，请检查本地模型后重试。")
                self.update(row, "transcribe", "failed", cause)

    def import_works(self, batch, rows):
        self.stage(batch, "import")
        LibraryState().mark_import([row['id'] for row in rows], batch.get('classificationMode', 'manual'))
        groups = {}
        profiles = saved_profiles()
        for row in rows:
            if batch.get("sourceType") == "favorites":
                identity = row.get("author") or {}
                known_profile = profiles.get("https://www.douyin.com/user/" + identity.get("secUid", ""))
                account = known_profile["account"] if known_profile else identity.get("account")
                name = known_profile["name"] if known_profile else identity.get("name")
            else:
                account, name = batch["account"], batch["name"]
            if not account or not name:
                self.update(row, "import", "failed", "缺少原作者资料，请重新加载收藏夹后重试。")
                continue
            groups.setdefault((account, name), []).append(row)
        prepared = []
        for (account, name), group in groups.items():
            try:
                prepared.extend(self.prepare_import(batch, group, account, name))
            except (OSError, ValueError) as error:
                for row in group:
                    self.update(row, "import", "failed", message(error))
        if not prepared:
            return
        directory = self.batch_path(batch)
        selected = directory / "approved-ids.json"
        save_json(selected, [row["id"] for row, _, _ in prepared])
        with (directory / "summary.log").open("ab") as log:
            result = subprocess.run([PYTHON, "-B", "-X", "utf8", SUMMARIZE, "--only", selected, "--no-popup",
                                     "--server-log", directory / "model.log"],
                                    stdout=log, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
        for row, records, summaries in prepared:
            key = row["id"]
            target = summaries / f"{key}.json"
            source = records / f"{key}.json"
            if (target.is_file() and source.is_file()
                    and json.loads(target.read_text(encoding="utf-8")).get("source_sha256") == hashlib.sha256(source.read_bytes()).hexdigest()):
                self.update(row, "import", "done")
            else:
                self.update(row, "import", "failed", "已登记，离线摘要待重试。" if result.returncode else "未生成摘要，可重试。")

    def prepare_import(self, batch, rows, account, name):
        directory = self.batch_path(batch)
        creator_key = f"douyin:{account}"
        known = legacy_or_registered()
        registry = read_registry()
        creator = registry.get(creator_key, {})
        if creator and creator["name"] != name:
            raise ValueError("该抖音号已绑定其他主播名称，请使用原名称。")
        records = PROJECT / creator.get("records", f"data/creators/{account}/transcripts")
        subtitles = PROJECT / creator.get("subtitles", f"data/creators/{account}/subtitles")
        summaries = PROJECT / creator.get("summaries", f"data/creators/{account}/summaries")
        records.mkdir(parents=True, exist_ok=True)
        subtitles.mkdir(parents=True, exist_ok=True)
        items = []
        ids = []
        for row in rows:
            key = row["id"]
            old = known.get(key)
            if row.get('forceImport'):
                old = None
            if old and (old[0] != account or (row["import"] == "pending" and not row.get("registered"))):
                self.update(row, "import", "existing")
                continue
            self.update(row, "import", "running")
            if not old:
                for source, target in [(directory / "records" / f"{key}.json", records / f"{key}.json"),
                                       (directory / "transcripts" / f"{key}.srt", subtitles / f"{key}.srt"),
                                       (directory / "transcripts" / f"{key}.md", subtitles / f"{key}.md")]:
                    temp = target.with_suffix(target.suffix + ".workflow.tmp")
                    shutil.copyfile(source, temp)
                    temp.replace(target)
                items.append({"videoId": key, "authorNickname": name, "contentType": "video",
                              "title": row["title"], "date": row["date"], "videoUrl": row["url"],
                              "workbenchMedia": row["file"], "workbenchLocalOnly": not row["url"],
                              "metrics": row.get("metrics", {})})
            ids.append(key)
        if not ids:
            return []
        if items:
            catalog = directory / f"approved-{uuid4().hex[:8]}.json"
            save_json(catalog, {"accountSlug": account, "douyinId": account, "works": items})
            register(account, name, catalog)
        for row in rows:
            if row["id"] in ids:
                self.update(row, "import", "running", registered=True)
        return [(row, records, summaries) for row in rows if row["id"] in ids]


def message(error):
    if isinstance(error, subprocess.TimeoutExpired):
        return "工具响应超时，可以重试。"
    if isinstance(error, PermissionError):
        return "没有权限访问这个文件夹或文件。"
    if isinstance(error, ValueError) and not isinstance(error, json.JSONDecodeError):
        return str(error)[:220]
    if isinstance(error, URLError):
        return "工具未返回结果，请检查网络和抖音登录后重试。"
    return "文件或本地工具未能处理这项任务。"
