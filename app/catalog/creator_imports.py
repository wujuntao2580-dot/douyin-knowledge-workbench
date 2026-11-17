import json
import re
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
REGISTRY = PROJECT / "data/creators.json"


def read_registry():
    return json.loads(REGISTRY.read_text(encoding="utf-8")) if REGISTRY.is_file() else {}


def load_works(creator_id, creator):
    works = {}
    for catalog in creator["catalogs"]:
        snapshot = json.loads((PROJECT / catalog).read_text(encoding="utf-8-sig"))
        account = creator_id.removeprefix("douyin:")
        if account not in {snapshot.get("accountSlug"), snapshot.get("douyinId")}:
            raise ValueError(f"清单与主播账号不匹配：{catalog}")
        for work in snapshot["works"]:
            if work.get("contentType") != "video":
                continue
            video_id = str(work.get("videoId"))
            if work.get("authorNickname") != creator["name"]:
                continue
            local_only = (work.get("workbenchLocalOnly") is True and not work.get("videoUrl")
                          and Path(work.get("workbenchMedia", "")).is_absolute())
            if not re.fullmatch(r"\d{19}", video_id) or not local_only and work.get("videoUrl") != f"https://www.douyin.com/video/{video_id}":
                raise ValueError(f"作品链接与 ID 不匹配：{video_id}")
            works[video_id] = work
    if not works:
        raise ValueError(f"清单中没有 {creator['name']} 的视频")
    return works


def register(account, name, catalog, media=None, records=None):
    if not re.fullmatch(r"[\w.-]+", account) or account in {".", ".."}:
        raise ValueError("请填写清单中的主播账号")
    creator_id = f"douyin:{account}"
    registry = read_registry()
    creator = registry.get(creator_id, {
        "name": name, "catalogs": [],
        "media": f"data/inputs/{account}",
        "records": f"data/creators/{account}/transcripts",
        "summaries": f"data/creators/{account}/summaries",
        "subtitles": f"data/creators/{account}/subtitles",
    })
    if creator["name"] != name:
        raise ValueError("主播名称与既有登记不一致")
    creator = {**creator, "catalogs": list(creator["catalogs"])}
    for value, field in ((catalog, "catalogs"), (media, "media"), (records, "records")):
        if value is None:
            continue
        candidate = (PROJECT / value).resolve().relative_to(PROJECT.resolve()).as_posix()
        if field == "catalogs":
            if candidate not in creator[field]:
                creator[field].append(candidate)
        else:
            creator[field] = candidate
    added = load_works(creator_id, creator)
    for other_id, other in registry.items():
        if other_id != creator_id and added.keys() & load_works(other_id, other).keys():
            raise ValueError("清单包含已归入其他主播的作品")
    registry[creator_id] = creator
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    temp = REGISTRY.with_suffix(".tmp")
    temp.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(REGISTRY)
