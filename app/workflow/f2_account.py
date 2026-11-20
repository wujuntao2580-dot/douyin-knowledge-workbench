import asyncio
import json
import sys

from f2.apps.douyin.crawler import DouyinCrawler
from f2.apps.douyin.model import BaseRequestModel
from f2.apps.douyin.utils import ClientConfManager


async def verify(cookie):
    settings = {"cookie": cookie, "timeout": 12, "max_retries": 1,
                "headers": {"User-Agent": ClientConfManager.user_agent(), "Referer": ClientConfManager.referer()}}
    async with DouyinCrawler(settings) as crawler:
        endpoint = crawler.bogus_manager.model_2_endpoint(
            crawler.headers["User-Agent"], "https://www.douyin.com/aweme/v1/web/user/profile/self/",
            BaseRequestModel().model_dump())
        result = await crawler._fetch_get_json(endpoint)
    user = result.get("user") or {}
    if result.get("status_code") != 0 or not user.get("uid") or not user.get("nickname"):
        return {"state": "expired", "message": "未能确认已登录账号，请在抖音窗口重新登录"}
    account = next((str(value) for value in (user.get("unique_id"), user.get("short_id"))
                    if value and str(value) != "0"), "")
    return {"state": "connected", "name": str(user["nickname"])[:100], "account": account}


if __name__ == "__main__":
    request = json.load(sys.stdin)
    try:
        response = asyncio.run(verify(request["cookie"]))
    except Exception:
        response = {"state": "check_failed", "message": "登录检查失败，请检查网络后重试"}
    print("F2_ACCOUNT " + json.dumps(response, ensure_ascii=False))
