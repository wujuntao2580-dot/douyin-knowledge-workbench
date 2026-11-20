import asyncio
import json
import sys

from f2.apps.douyin.crawler import DouyinCrawler
from f2.apps.douyin.model import UserCollects, UserCollectsVideo, UserCollection
from f2.apps.douyin.utils import ClientConfManager

from providers import normalize_works


async def fetch_page(request):
    cursor = request["cursor"]
    folder = request.get("folder")
    settings = {"cookie": request["cookie"], "timeout": request.get("timeout", 12),
                "max_retries": request.get("max_retries", 1),
                "headers": {"User-Agent": ClientConfManager.user_agent(), "Referer": ClientConfManager.referer()}}
    async with DouyinCrawler(settings) as crawler:
        if request["kind"] == "folders":
            result = await crawler.fetch_user_collects(UserCollects(cursor=cursor, count=20))
            field = "collects_list"
        elif folder == "all":
            result = await crawler.fetch_user_collection(UserCollection(cursor=cursor, count=20))
            field = "aweme_list"
        else:
            result = await crawler.fetch_user_collects_video(
                UserCollectsVideo(cursor=cursor, count=20, collects_id=folder))
            field = "aweme_list"
    if (not isinstance(result, dict) or result.get("status_code") != 0 or field not in result
            or result[field] is not None and not isinstance(result[field], list)):
        raise ValueError("抖音未返回收藏数据，请在右侧「抖音账号」检查登录。")
    more = bool(result.get("has_more"))
    next_cursor = result.get("cursor")
    if more and (type(next_cursor) is not int or next_cursor <= cursor):
        raise ValueError("收藏列表分页失败，请重新加载。")
    rows = result[field] or []
    if field == "collects_list":
        items = []
        for row in rows:
            folder_id = str(row.get("collects_id") or "")
            if not folder_id.isdecimal() or len(folder_id) > 25:
                continue
            total = row.get("total_number")
            items.append({"id": folder_id, "name": str(row.get("collects_name") or "未命名收藏夹")[:120],
                          "count": total if type(total) is int and total >= 0 else None})
    else:
        items = normalize_works({"data": rows}, "", allow_empty=True)["works"]
    return {"items": items, "more": more, "cursor": next_cursor if more else None}


if __name__ == "__main__":
    request = json.load(sys.stdin)
    try:
        result = asyncio.run(fetch_page(request))
    except Exception as error:
        message = str(error) if type(error) is ValueError else "无法读取收藏，请检查网络和右侧的抖音登录状态。"
        print("F2_FAVORITES " + json.dumps({"error": message}, ensure_ascii=False))
        raise SystemExit(1)
    print("F2_FAVORITES " + json.dumps(result, ensure_ascii=False, separators=(",", ":")))
