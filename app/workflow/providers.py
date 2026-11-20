import json
import marshal
import re
import shutil
import socket
import sqlite3
import subprocess
import time
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler

from douyin_account import cookie_header, read_download_config


PROJECT = Path(__file__).resolve().parents[2]
INSTALLED = PROJECT / ".runtime/douk"
F2 = PROJECT / ".runtime/f2/Scripts/f2.exe"
F2_PYTHON = F2.with_name("python.exe")
CACHE = PROJECT / "data/workflow"
ID = re.compile(r"[0-9]{19}")
HOME = re.compile(r"/user/([\w-]+)", re.ASCII)
URL = re.compile(r"https://www\.douyin\.com/video/([0-9]{19})/?(?:\?[^\s]*)?")
NO_WINDOW = subprocess.CREATE_NO_WINDOW
OPENER = build_opener(ProxyHandler({}))


def tool_timeout(config, minimum):
    return max(minimum, config.get("timeout", 10) * (config.get("max_retry", 5) + 1) + 15)


def video_url(video_id):
    return f"https://www.douyin.com/video/{video_id}"


def profile_id(url):
    url = urlsplit(url)
    if url.scheme != "https" or url.netloc != "www.douyin.com":
        return None
    match = HOME.fullmatch(url.path.rstrip("/"))
    return match[1] if match else None


def receive_douk(port, route, data, timeout=40):
    req = Request(f"http://127.0.0.1:{port}{route}", json.dumps(data).encode(),
                  {"Content-Type": "application/json"}, method="POST")
    with OPENER.open(req, timeout=timeout) as response:
        return json.load(response)


class DouK:
    def __init__(self, directory=CACHE / "douk"):
        self.directory = directory

    @contextmanager
    def session(self, destination=None):
        if not (self.directory / "DouK-Downloader.exe").is_file():
            shutil.copytree(INSTALLED, self.directory, ignore=shutil.ignore_patterns("Volume", "__pycache__"),
                            dirs_exist_ok=True)
        volume = self.directory / "Volume"
        volume.mkdir(exist_ok=True)
        database = volume / "DouK-Downloader.db"
        if not database.exists():
            source = INSTALLED / "Volume/DouK-Downloader.db"
            if not source.is_file():
                raise ValueError("请先打开 .runtime/douk/DouK-Downloader.exe 完成首次语言及提示设置，再回工作台重试。")
            with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
                with closing(sqlite3.connect(database)) as target:
                    original.backup(target)
        with closing(sqlite3.connect(database)) as target:
            target.execute("UPDATE config_data SET VALUE = 0 WHERE NAME = 'Record'")
            target.execute("DELETE FROM download_data")
            target.commit()
        config = read_download_config()
        if not config.get("cookie"):
            raise ValueError("请先在页面的「抖音账号」中登录")
        settings = volume / "settings.json"
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        # The packaged 5.8 API defaults to LAN. Change only the disposable copy.
        module = Path("lib/src/custom/static.pyc")
        original = (INSTALLED / module).read_bytes()
        compiled = marshal.loads(original[16:])
        if "0.0.0.0" not in compiled.co_consts or 5555 not in compiled.co_consts:
            raise ValueError("DouK 版本与当前接入不兼容")
        constants = tuple("127.0.0.1" if value == "0.0.0.0" else port if value == 5555 else value
                          for value in compiled.co_consts)
        (self.directory / module).write_bytes(original[:16] + marshal.dumps(compiled.replace(co_consts=constants)))
        stage = destination or self.directory / "unused-media"
        config.update(root=str(stage.parent), folder_name=stage.name, folder_mode=False,
                      download=bool(destination), name_format="id")
        try:
            settings.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            yield self.directory / "DouK-Downloader.exe", port
        finally:
            settings.unlink(missing_ok=True)

    @contextmanager
    def api(self):
        with self.session() as (executable, port):
            with subprocess.Popen([executable], cwd=self.directory, stdin=subprocess.PIPE,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  creationflags=NO_WINDOW) as process:
                process.stdin.write(b"7\n")
                process.stdin.flush()
                try:
                    deadline = time.monotonic() + 18
                    while time.monotonic() < deadline and process.poll() is None:
                        try:
                            with OPENER.open(f"http://127.0.0.1:{port}/openapi.json", timeout=1) as response:
                                if "/douyin/search/user" in json.load(response).get("paths", {}):
                                    break
                        except (URLError, TimeoutError):
                            time.sleep(0.3)
                    else:
                        raise ValueError("搜索服务启动失败，请在右侧「抖音账号」检查登录。")
                    yield port
                finally:
                    if process.poll() is None:
                        process.terminate()

    def search(self, keyword):
        config = read_download_config()
        with self.api() as port:
            result = receive_douk(port, "/douyin/search/user", {"keyword": keyword, "pages": 1, "count": 12},
                                  timeout=tool_timeout(config, 40))
        return [creator for row in result_items(result) if (creator := search_creator(row))]

    def works(self, profile):
        with self.api() as port:
            sec_id = profile_id(profile)
            if not sec_id:
                parsed = urlsplit(profile)
                if parsed.scheme != "https" or parsed.netloc != "v.douyin.com":
                    raise ValueError("请粘贴抖音主播主页链接")
                share = receive_douk(port, "/douyin/share", {"text": profile})
                name = share.get("url")
                if not isinstance(name, str) or not (sec_id := profile_id(name)):
                    raise ValueError("分享链接没有指向抖音主播主页")
            result = receive_douk(port, "/douyin/account", {"sec_user_id": sec_id, "tab": "post", "count": 20},
                                  timeout=tool_timeout(read_download_config(), 120))
        return {**normalize_works(result, sec_id), "profile": f"https://www.douyin.com/user/{sec_id}"}

    @contextmanager
    def downloader(self, stage):
        with self.session(stage) as (executable, _):
            def download(video_id):
                batch = self.directory / "batch.txt"
                batch.write_text(video_url(video_id) + "\n", encoding="utf-8")
                result = subprocess.run([executable], cwd=self.directory,
                                        input=f"5\n2\n2\n{batch}\nQ\nQ\nQ\n".encode("utf-8"),
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        timeout=tool_timeout(read_download_config(), 180),
                                        creationflags=NO_WINDOW)
                output = result.stdout.decode("utf-8", "replace")
                if not any(stage.glob(f"{video_id}*.mp4")):
                    if re.search(r"\b(?:403|429)\b|风控|请先登录|登录失效", output):
                        raise ValueError("抖音拒绝请求或限流，请检查登录状态后重试。")
                    raise ValueError("DouK 未返回可用的 MP4 文件")
            yield download


def result_items(result):
    data = result.get("data")
    if data is None:
        raise ValueError("抖音未返回数据，请在右侧「抖音账号」检查登录后重试。")
    if isinstance(data, list):
        return data
    for key in ("aweme_list", "data", "items", "list", "user_list", "works"):
        if isinstance(data.get(key), list):
            return data[key]
    return [data]


def search_creator(row):
    user = row.get("user_info") or row.get("user") or row
    sec_id = user.get("sec_uid") or user.get("sec_user_id")
    if not isinstance(sec_id, str) or not re.fullmatch(r"[\w-]+", sec_id, re.ASCII):
        return None
    avatar = user.get("avatar") or user.get("avatar_thumb") or user.get("avatar_url")
    if isinstance(avatar, dict):
        avatar = next(iter(avatar.get("url_list") or []), "")
    accounts = list(dict.fromkeys(str(user[key]) for key in ("unique_id", "short_id")
                                 if user.get(key) and str(user[key]) != "0"))
    return {"name": user.get("nickname") or "", "account": accounts[0] if accounts else "",
            "accounts": accounts,
            "avatar": avatar if isinstance(avatar, str) else "",
            "profile": f"https://www.douyin.com/user/{sec_id}"}


def work_metrics(row):
    aliases = {"plays": ("play_count", "playCount", "plays"),
               "likes": ("digg_count", "likes"),
               "saves": ("collect_count", "collectCount", "saves")}
    sources = (row.get("statistics"), row, row.get("metrics"))
    metrics = {}
    for name, fields in aliases.items():
        for source in sources:
            if not isinstance(source, dict):
                continue
            for field in fields:
                value = source.get(field)
                if isinstance(value, str) and re.fullmatch(r"[0-9]{1,16}", value):
                    value = int(value)
                if type(value) is int and (1 if name == "plays" else 0) <= value <= 2**53-1:
                    metrics[name] = value
                    break
            if name in metrics:
                break
    return metrics


def normalize_works(result, sec_id, *, allow_empty=False):
    creator = {"name": "", "account": sec_id}
    works = {}
    for raw in result_items(result):
        row = raw.get("aweme_info") or raw
        video_id = str(row.get("aweme_id") or row.get("id") or "")
        if not ID.fullmatch(video_id):
            continue
        kind = str(row.get("type") or row.get("content_type") or "").casefold()
        if row.get("images") or row.get("image_post_info") or any(word in kind for word in ("图", "image")):
            continue
        author = row.get("author") or {}
        name = author.get("nickname") or row.get("nickname") or row.get("author_nickname")
        account = next((str(value) for value in (author.get("unique_id"), row.get("unique_id"),
                       author.get("short_id"), row.get("short_id"), author.get("sec_uid"), row.get("sec_uid"))
                       if value and str(value) != "0"), "")
        if name:
            creator["name"] = str(name)
        if account:
            creator["account"] = str(account)
        date = row.get("create_time") or row.get("published") or ""
        if isinstance(date, (int, float)) or isinstance(date, str) and date.isdecimal() and len(date) == 10:
            date = datetime.fromtimestamp(int(date)).date().isoformat()
        works[video_id] = {"id": video_id, "title": str(row.get("desc") or row.get("title") or video_id),
                           "date": str(date)[:10], "url": video_url(video_id), "metrics": work_metrics(row),
                           "author": {"name": str(name or ""), "account": account,
                                      "secUid": str(author.get("sec_uid") or row.get("sec_uid") or "")}}
    if not works and not allow_empty:
        raise ValueError("该主页没有返回可用的视频作品")
    return {"creator": creator, "works": list(works.values()), "source": "DouK"}


class F2Downloader:
    def favorites_page(self, kind, folder="all", cursor=0):
        if kind not in {"folders", "videos"} or type(cursor) is not int or not 0 <= cursor < 2**53:
            raise ValueError("收藏列表请求无效")
        if not isinstance(folder, str) or not re.fullmatch(r"(?:all|[0-9]{1,25})", folder):
            raise ValueError("请选择有效的收藏夹")
        config = read_download_config()
        with TemporaryDirectory(prefix="workbench-favorites-") as directory:
            result = subprocess.run([F2_PYTHON, "-B", "-X", "utf8", Path(__file__).with_name("f2_favorites.py")],
                                    cwd=directory,
                                    input=json.dumps({"kind": kind, "folder": folder, "cursor": cursor,
                                                      "cookie": self.cookie(), "timeout": config.get("timeout", 10),
                                                      "max_retries": config.get("max_retry", 5)}),
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                    encoding="utf-8", errors="replace", creationflags=NO_WINDOW,
                                    timeout=tool_timeout(config, 45))
        payload = next((line.removeprefix("F2_FAVORITES ") for line in result.stdout.splitlines()
                        if line.startswith("F2_FAVORITES ")), None)
        if payload is None:
            raise ValueError("无法读取收藏，请检查网络和右侧的抖音登录状态。")
        page = json.loads(payload)
        if page.get("error"):
            raise ValueError(page["error"])
        if result.returncode:
            raise ValueError("收藏列表读取失败，请重试。")
        return page

    @staticmethod
    def cookie():
        if not F2.is_file():
            raise ValueError("F2 尚未安装或验证")
        config = read_download_config()
        cookie = config.get("cookie")
        if not cookie:
            raise ValueError("请先在页面的「抖音账号」中登录")
        return cookie_header(cookie)

    def works(self, profile):
        sec_id = profile_id(profile)
        if not sec_id:
            raise ValueError("F2 请使用浏览器打开后的抖音主页完整链接")
        config = read_download_config()
        result = subprocess.run([F2_PYTHON, "-B", "-X", "utf8", Path(__file__).with_name("f2_works.py")],
                                input=json.dumps({"sec_id": sec_id, "cookie": self.cookie(),
                                                  "timeout": config.get("timeout", 10),
                                                  "max_retries": config.get("max_retry", 5)}),
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                encoding="utf-8", errors="replace", creationflags=NO_WINDOW,
                                timeout=tool_timeout(config, 135))
        payload = next((line.removeprefix("F2_WORKS ") for line in result.stdout.splitlines()
                        if line.startswith("F2_WORKS ")), None)
        if result.returncode or not payload:
            raise ValueError("F2 未能读取主页作品，请换回 DouK 或导入 TXT 清单。")
        normalized = normalize_works({"data": json.loads(payload)}, sec_id)
        return {**normalized, "profile": f"https://www.douyin.com/user/{sec_id}", "source": "F2"}

    @contextmanager
    def downloader(self, stage):
        cookie = self.cookie()
        def download(video_id):
            with TemporaryDirectory(dir=stage.parent, prefix="f2-") as directory:
                root = Path(directory)
                settings = root / "f2-config.json"
                config = read_download_config()
                settings.write_text(json.dumps({"douyin": {"cookie": cookie, "timeout": config.get("timeout", 10),
                                                           "max_retries": config.get("max_retry", 5)}},
                                               ensure_ascii=False), encoding="utf-8")
                subprocess.run([F2, "dy", "-c", settings, "-u", video_url(video_id), "-M", "one",
                                "-p", root, "-n", "{aweme_id}"], cwd=root,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=tool_timeout(config, 180), creationflags=NO_WINDOW)
                source = next((path for path in root.rglob("*.mp4")
                               if path.stem in {video_id, f"{video_id}_video"}), None)
                if source is None:
                    raise ValueError("F2 未返回这个作品的 MP4 文件")
                source.replace(stage / f"{video_id}.mp4")
        yield download
