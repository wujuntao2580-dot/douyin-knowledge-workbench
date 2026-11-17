"""Verify the catalog and local workflow without opening a browser."""
import argparse
import json
import secrets
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from runpy import run_path
from tempfile import TemporaryDirectory
from urllib.request import ProxyHandler, Request, build_opener


module = run_path(str(Path(__file__).with_name("open-workbench.py")))
project = module["PROJECT"]
page = module["PAGE"].read_text(encoding="utf-8")
marker = '<script id="catalog" type="application/json">'
catalog = json.loads(page.split(marker, 1)[1].split("</script>", 1)[0])
assert isinstance(catalog["videos"], list) and isinstance(catalog["topics"], dict)
assert 'id="workflow-link"' in page

parser = argparse.ArgumentParser()
parser.add_argument("--require-models", action="store_true")
args = parser.parse_args()
models = project / ".runtime/models"
ready = all((models / path).is_file() for path in (
    "faster-whisper-small/config.json",
    "faster-whisper-small/model.bin",
    "faster-whisper-small/tokenizer.json",
    "faster-whisper-small/vocabulary.txt",
    "summary/Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
    "summary/llama/llama-server.exe",
))
if args.require_models and not ready:
    raise SystemExit("Missing requested model files")

opener = build_opener(ProxyHandler({}))
with TemporaryDirectory() as folder, ThreadingHTTPServer(("127.0.0.1", 0), module["PlaybackHandler"]) as server:
    server.key = secrets.token_urlsafe(24)
    server.workflow = module["Workflow"](state_file=Path(folder) / "queue.json")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        for route in ("/workflow/", "/workflow/app.js", "/workflow/style.css"):
            with opener.open(origin + route, timeout=5) as response:
                assert response.status == 200 and response.read()
        request = Request(origin + "/workflow/api/status", data=b"{}", headers={
            "Origin": origin, "X-Playback-Key": server.key, "Content-Type": "application/json",
        })
        with opener.open(request, timeout=5) as response:
            status = json.load(response)
            assert status["batches"] == [] and "settings" in status
    finally:
        server.shutdown()
        thread.join(timeout=5)

print(f"Catalog: {len(catalog['videos'])} videos. Local workflow: OK. Model files: {'present' if ready else 'optional setup pending'}.")
