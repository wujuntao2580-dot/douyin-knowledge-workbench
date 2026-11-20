import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from tempfile import TemporaryDirectory
from threading import Lock, Thread


PROJECT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).resolve().parent
CONFIG = PROJECT / ".runtime/douk/Volume/settings.json"
QUEUE = PROJECT / "data/workflow/queue.json"
F2_PYTHON = PROJECT / ".runtime/f2/Scripts/python.exe"
BROWSER_PYTHON = PROJECT / ".runtime/venv/Scripts/python.exe"
CHROME = Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft/Edge/Application/msedge.exe"
NO_WINDOW = subprocess.CREATE_NO_WINDOW


def read_download_config(config_path=CONFIG, queue_path=QUEUE):
    config = json.loads(config_path.read_text(encoding="utf-8-sig")) if config_path.is_file() else {"cookie": {}, "timeout": 20, "max_retry": 2}
    if queue_path.is_file():
        settings = json.loads(queue_path.read_text(encoding="utf-8")).get("settings", {})
        config["timeout"] = settings.get("downloadTimeout", config.get("timeout", 10))
        config["max_retry"] = settings.get("downloadRetries", config.get("max_retry", 5))
    return config


def cookie_values(raw):
    if isinstance(raw, str):
        raw = raw.strip()
        if raw.casefold().startswith("cookie:"):
            raw = raw[7:].strip()
        if raw.startswith(("{", "[")):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                raise ValueError("登录信息的 JSON 格式有误") from None
        else:
            values = {}
            for field in raw.split(";"):
                if not field.strip():
                    continue
                key, separator, value = field.strip().partition("=")
                if not separator:
                    raise ValueError("Cookie 应是从浏览器复制的完整登录信息")
                values[key] = value
            raw = values
    if isinstance(raw, list):
        raw = {item["name"]: item["value"] for item in raw if isinstance(item, dict)
               and isinstance(item.get("name"), str) and isinstance(item.get("value"), str)
               and (item.get("domain") == "douyin.com" or str(item.get("domain", "")).endswith(".douyin.com"))}
    if not isinstance(raw, dict) or not raw or len(raw) > 600:
        raise ValueError("没有读取到抖音登录信息")
    for key, value in raw.items():
        if (not isinstance(key, str) or not re.fullmatch(r"[!#$%&'*+.^_\x60|~0-9A-Za-z-]+", key)
                or not isinstance(value, str) or any(char in value for char in "\r\n\0;")):
            raise ValueError("登录信息格式有误，请重新复制")
    if len(json.dumps(raw)) > 256000:
        raise ValueError("登录信息过长")
    if not any(raw.get(key) for key in ("sessionid", "sessionid_ss")):
        raise ValueError("这份登录信息缺少已登录会话，请先登录抖音后再保存")
    return raw


def cookie_header(values):
    if isinstance(values, dict):
        return "; ".join(f"{key}={value}" for key, value in values.items())
    return str(values or "")


def fingerprint(values):
    return hashlib.sha256(cookie_header(values).encode()).hexdigest()


def write_private_json(path, value):
    temporary = path.with_suffix(".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def verify_cookie(values):
    with TemporaryDirectory(prefix="workbench-account-") as directory:
        result = subprocess.run([F2_PYTHON, "-B", "-X", "utf8", WORK / "f2_account.py"], cwd=directory,
                                input=json.dumps({"cookie": cookie_header(values)}),
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                encoding="utf-8", errors="replace", timeout=40, creationflags=NO_WINDOW)
    payload = next((line.removeprefix("F2_ACCOUNT ") for line in result.stdout.splitlines()
                    if line.startswith("F2_ACCOUNT ")), None)
    if payload is None:
        raise ValueError("无法检查登录，请检查网络后重试")
    response = json.loads(payload)
    if response.get("state") != "connected":
        raise ValueError(response.get("message") or "未验证登录，请重新登录抖音")
    return response


class DouyinAccount:
    def __init__(self, config_path=CONFIG, queue_path=QUEUE, directory=PROJECT / "data/workflow/account"):
        self.config_path = config_path
        self.queue_path = queue_path
        self.directory = directory
        self.status_file = directory / "status.json"
        self.login_lock = Lock()
        self.process = None
        self.events = None

    def view(self):
        config = read_download_config(self.config_path, self.queue_path)
        values = config.get("cookie")
        status = {"state": "saved" if values else "missing", "configured": bool(values),
                  "browserOpen": self.process is not None and self.process.poll() is None,
                  "downloadTimeout": config.get("timeout", 10), "downloadRetries": config.get("max_retry", 5)}
        if self.status_file.is_file():
            record = json.loads(self.status_file.read_text(encoding="utf-8"))
            if record.get("fingerprint") == fingerprint(values):
                status.update({key: record[key] for key in ("state", "name", "account", "checkedAt", "message")
                               if key in record})
        return status

    def record(self, values, verified):
        self.directory.mkdir(parents=True, exist_ok=True)
        write_private_json(self.status_file, {**verified, "fingerprint": fingerprint(values),
                                              "checkedAt": datetime.now().isoformat(timespec="seconds")})

    def check(self):
        values = read_download_config(self.config_path, self.queue_path).get("cookie")
        if not values:
            return self.view()
        try:
            verified = verify_cookie(values)
        except (OSError, ValueError, subprocess.SubprocessError):
            self.record(values, {"state": "check_failed"})
            raise
        self.record(values, verified)
        return self.view()

    def save(self, raw):
        values = cookie_values(raw)
        verified = verify_cookie(values)
        # Merge at save time so external configuration additions are preserved.
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        config = json.loads(self.config_path.read_text(encoding="utf-8-sig")) if self.config_path.is_file() else {}
        config["cookie"] = values
        write_private_json(self.config_path, config)
        self.record(values, verified)
        return self.view()

    def read_events(self, process, events):
        try:
            for line in process.stdout:
                try:
                    events.put(json.loads(line))
                except json.JSONDecodeError:
                    continue
        finally:
            events.put({"event": "closed"})

    def next_event(self):
        try:
            event = self.events.get(timeout=35)
        except Empty:
            raise ValueError("登录窗口响应超时，请关闭窗口后重试") from None
        if event.get("event") == "error":
            raise ValueError(event.get("message") or "无法打开登录窗口")
        return event

    def open_login(self):
        with self.login_lock:
            if self.process is not None and self.process.poll() is None:
                return self.view()
            chrome = CHROME if CHROME.is_file() else Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft/Edge/Application/msedge.exe"
            if not chrome.is_file():
                raise ValueError("未找到可用浏览器，请使用「手动更新登录信息」")
            self.directory.mkdir(parents=True, exist_ok=True)
            self.process = subprocess.Popen([BROWSER_PYTHON, "-B", "-X", "utf8", WORK / "douyin_login.py", chrome, self.directory / "browser-profile"],
                                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                            text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
            self.events = Queue()
            Thread(target=self.read_events, args=(self.process, self.events), daemon=True).start()
            try:
                if self.next_event().get("event") != "ready":
                    raise ValueError("登录窗口已关闭，请重新打开")
            except (OSError, ValueError):
                if self.process.poll() is None:
                    self.process.terminate()
                raise
            return self.view()

    def save_browser(self):
        with self.login_lock:
            if self.process is None or self.process.poll() is not None:
                raise ValueError("请先打开抖音登录窗口并完成登录")
            self.process.stdin.write(json.dumps({"action": "snapshot"}) + "\n")
            self.process.stdin.flush()
            response = self.next_event()
            if response.get("event") != "cookies":
                raise ValueError("登录窗口已关闭，请重新打开")
            result = self.save(response["cookie"])
            self.process.stdin.write(json.dumps({"action": "close"}) + "\n")
            self.process.stdin.flush()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.terminate()
            return {**result, "browserOpen": False}

    def close_login(self):
        with self.login_lock:
            if self.process is not None and self.process.poll() is None:
                self.process.stdin.write(json.dumps({"action": "close"}) + "\n")
                self.process.stdin.flush()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.terminate()
            return self.view()
