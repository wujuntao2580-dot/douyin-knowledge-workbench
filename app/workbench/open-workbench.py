import ctypes
import hashlib
import hmac
import json
import msvcrt
import os
import re
import secrets
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import gettempdir
from urllib.parse import parse_qs, urlsplit
from urllib.request import ProxyHandler, Request, build_opener


WORK = Path(__file__).resolve().parent
PROJECT = WORK.parents[1]
PAGE = PROJECT / "data/打开知识库.html"
MEDIA = PROJECT / "data/compressed"
VLC = PROJECT / ".runtime/vlc/vlc.exe"
EDGE = Path(os.environ["ProgramFiles(x86)"]) / "Microsoft/Edge/Application/msedge.exe"
INSTANCE = hashlib.sha256((str(PROJECT).casefold() + "/workflow").encode()).hexdigest()[:16]
STATE = Path(gettempdir()) / f"douyin-workbench-{INSTANCE}.json"
OPENER = build_opener(ProxyHandler({}))
WORKFLOW_DIR = PROJECT / "app/workflow"
sys.path.insert(0, str(WORKFLOW_DIR))
from workflow import Workflow, message


def playback_file(video_id, seconds):
    if not re.fullmatch(r"[0-9]{19}", video_id):
        raise ValueError("无效的作品 ID")
    page = PAGE.read_text(encoding="utf-8")
    payload = page.split('<script id="catalog" type="application/json">', 1)[1].split("</script>", 1)[0]
    video = next((item for item in json.loads(payload)["videos"] if item["id"] == video_id), None)
    if video is None:
        raise ValueError("工作台没有这条视频")
    times = {int(minutes) * 60 + int(remainder)
             for time, *_ in video.get("points") or []
             for minutes, remainder in [time.split(":")]}
    if seconds not in {0, *times}:
        raise ValueError("该时间点未收录")
    file = (MEDIA / f"{video_id}.mp4").resolve()
    if file.parent != MEDIA.resolve() or not file.is_file():
        raise ValueError("找不到本地压缩版")
    return file


class PlaybackHandler(BaseHTTPRequestHandler):
    def local_host(self):
        return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

    def workflow_response(self, status, raw, content_type):
        self.send_response(status)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' https:; frame-ancestors 'none'; form-action 'none'; base-uri 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def workflow_json(self, status, value):
        self.workflow_response(status, json.dumps(value, ensure_ascii=False).encode("utf-8"),
                               "application/json; charset=utf-8")

    def do_GET(self):
        assets = {"/workflow/": ("index.html", "text/html"),
                  "/workflow/app.js": ("app.js", "text/javascript"),
                  "/workflow/style.css": ("style.css", "text/css")}
        asset = assets.get(urlsplit(self.path).path)
        if not self.local_host() or asset is None:
            return self.workflow_json(404, {"error": "页面不存在"})
        filename, content_type = asset
        self.workflow_response(200, (WORKFLOW_DIR / filename).read_bytes(), content_type + "; charset=utf-8")

    def workflow_post(self, route, key):
        origin = f"http://127.0.0.1:{self.server.server_port}"
        if (not self.local_host() or self.headers.get("Origin") != origin
                or not hmac.compare_digest(key, self.server.key.encode())):
            return self.workflow_json(403, {"error": "请从个人知识工作台重新打开下载页面。"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4_000_000:
                raise ValueError("请求大小无效")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("请求格式无效")
            if route == "status":
                value = self.server.workflow.status()
                value["defaultFolder"] = str(PROJECT / "data/inputs")
            elif route == "library":
                open_page(self.server.server_port, self.server.key)
                value = {}
            else:
                value = self.server.workflow.act(route, data)
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            return self.workflow_json(400, {"error": message(error)})
        return self.workflow_json(200, value)

    def reply(self, status, message=""):
        raw = message.encode("utf-8")
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "null")
        self.send_header("Access-Control-Allow-Methods", "POST")
        self.send_header("Access-Control-Allow-Headers", "X-Playback-Key")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_):
        pass

    def local_file_request(self):
        return (self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"
                and self.headers.get("Origin") == "null")

    def do_OPTIONS(self):
        self.reply(204 if self.local_file_request() else 403)

    def do_POST(self):
        key = self.headers.get("X-Playback-Key", "").encode("utf-8")
        url = urlsplit(self.path)
        if url.path.startswith("/workflow/api/"):
            return self.workflow_post(url.path.removeprefix("/workflow/api/"), key)
        if not self.local_file_request() or not hmac.compare_digest(key, self.server.key.encode()):
            return self.reply(403, "播放入口未授权")
        if url.path == "/ready":
            return self.reply(200, INSTANCE)
        if url.path != "/play":
            return self.reply(404)
        fields = parse_qs(url.query)
        try:
            seconds = int(fields.get("seconds", [""])[0])
            file = playback_file(fields.get("id", [""])[0], seconds)
            subprocess.Popen(
                [str(VLC), "--no-qt-privacy-ask", "--no-metadata-network-access",
                 "--no-one-instance", f"--start-time={seconds}", str(file)],
                cwd=VLC.parent,
            )
        except ValueError as error:
            return self.reply(400, str(error))
        except OSError:
            return self.reply(500, "无法启动 VLC 播放器")
        return self.reply(200)


def running_connection():
    try:
        state = json.loads(STATE.read_text(encoding="utf-8"))
        port, key = state["port"], state["key"]
        if type(port) is not int or not 1 <= port <= 65535 or not re.fullmatch(r"[\w-]{32}", key, re.ASCII):
            return None
        request = Request(f"http://127.0.0.1:{port}/ready", data=b"", headers={
            "Origin": "null", "X-Playback-Key": key,
        })
        with OPENER.open(request, timeout=1) as response:
            if response.read(64) == INSTANCE.encode():
                return port, key
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def open_page(port, key):
    subprocess.Popen([str(EDGE), "--new-window", PAGE.as_uri() + f"#vlc={port}.{key}"])


def main():
    for path in (EDGE, PAGE):
        if not path.is_file():
            raise SystemExit(f"找不到 {path}")
    with STATE.with_suffix(".lock").open("a+b") as startup_lock:
        startup_lock.seek(0)
        msvcrt.locking(startup_lock.fileno(), msvcrt.LK_LOCK, 1)
        try:
            if connection := running_connection():
                open_page(*connection)
                return
            server = ThreadingHTTPServer(("127.0.0.1", 0), PlaybackHandler)
            server.key = secrets.token_urlsafe(24)
            server.workflow = Workflow()
            temporary = STATE.with_suffix(".tmp")
            temporary.write_text(json.dumps({"port": server.server_port, "key": server.key}), encoding="utf-8")
            temporary.replace(STATE)
        finally:
            startup_lock.seek(0)
            msvcrt.locking(startup_lock.fileno(), msvcrt.LK_UNLCK, 1)
    with server:
        try:
            open_page(server.server_port, server.key)
            server.serve_forever()
        finally:
            STATE.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, SystemExit) as error:
        ctypes.windll.user32.MessageBoxW(None, str(error), "无法打开个人知识工作台", 0x10)
        raise SystemExit(1)
