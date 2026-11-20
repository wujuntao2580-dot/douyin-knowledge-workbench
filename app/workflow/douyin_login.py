"""Own Edge session; JSON pipe protocol consumed by the local account manager."""
import json
import queue
import sys
import threading
import time

from playwright.sync_api import sync_playwright


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def main():
    executable, profile = sys.argv[1:3]
    url = sys.argv[3] if len(sys.argv) > 3 else 'https://www.douyin.com/user/self'
    commands = queue.Queue()

    def read_commands():
        try:
            for line in sys.stdin:
                commands.put(json.loads(line))
        finally:
            commands.put({'action': 'close'})

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(profile, executable_path=executable,
                   headless=False, no_viewport=True, args=['--no-first-run', '--no-default-browser-check'])
        closed = threading.Event()
        context.on('close', lambda _: closed.set())
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto(url, wait_until='domcontentloaded', timeout=25000)
        except Exception:
            pass  # Keep the window available for the user to retry the page.
        emit({'event': 'ready'})
        threading.Thread(target=read_commands, daemon=True).start()
        try:
            while not closed.is_set():
                try:
                    request = commands.get_nowait()
                except queue.Empty:
                    page.wait_for_timeout(100)
                    continue
                if request.get('action') == 'close':
                    break
                if request.get('action') == 'snapshot':
                    cookies = context.cookies('https://www.douyin.com/')
                    now = time.time()
                    emit({'event': 'cookies', 'cookie': {item['name']: item['value'] for item in cookies
                                                       if item['expires'] <= 0 or item['expires'] > now}})
        finally:
            if not closed.is_set():
                context.close()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        emit({'event': 'error', 'message': '无法打开抖音登录窗口，请关闭旧窗口后重试。'})
        raise SystemExit(1)
