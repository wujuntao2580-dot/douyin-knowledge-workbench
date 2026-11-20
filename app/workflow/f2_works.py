import asyncio
import json
import sys

from f2.apps.douyin.crawler import DouyinCrawler
from f2.apps.douyin.model import UserPost
from f2.apps.douyin.utils import ClientConfManager


async def collect(sec_id, cookie, timeout=15, max_retries=2):
    settings = {"cookie": cookie, "timeout": timeout, "max_retries": max_retries,
                "headers": {"User-Agent": ClientConfManager.user_agent(), "Referer": ClientConfManager.referer()}}
    cursor = 0
    visited = set()
    items = []
    async with DouyinCrawler(settings) as crawler:
        while cursor not in visited and len(items) < 3000:
            visited.add(cursor)
            response = await crawler.fetch_user_post(UserPost(sec_user_id=sec_id, max_cursor=cursor, count=20))
            if not isinstance(response, dict) or response.get("status_code") != 0:
                raise ValueError("F2 未拿到这个主页的作品")
            items.extend(response.get("aweme_list") or [])
            if not response.get("has_more"):
                break
            cursor = response.get("max_cursor")
            if not isinstance(cursor, int):
                break
            await asyncio.sleep(1)
    return items


if __name__ == "__main__":
    request = json.load(sys.stdin)
    try:
        rows = asyncio.run(collect(request["sec_id"], request["cookie"],
                                   request.get("timeout", 15), request.get("max_retries", 2)))
    except Exception as error:
        print("F2_ERROR " + type(error).__name__)
        raise SystemExit(1)
    print("F2_WORKS " + json.dumps(rows, ensure_ascii=False, separators=(",", ":")))
