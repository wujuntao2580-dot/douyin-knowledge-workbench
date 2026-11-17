import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import quote

from creator_imports import load_works, read_registry


WORK = Path(__file__).resolve().parent
PROJECT = WORK.parents[1]
LIBRARY = PROJECT / "data"

def script_json(data):
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


videos = []
topics = {}

for creator_id, creator in read_registry().items():
    local_videos = {}
    for path in sorted((PROJECT / creator["media"]).glob("*.mp4")):
        match = re.match(r"^(\d{19})(?!\d)", path.name)
        if match:
            with path.open("rb") as file:
                if file.read(12)[4:8] == b"ftyp":
                    local_videos[match[1]] = quote(os.path.relpath(path, LIBRARY).replace(os.sep, "/"))

    summary_dir = PROJECT / creator["summaries"]
    for video_id, work in load_works(creator_id, creator).items():
        media_file = work.get("workbenchMedia")
        if media_file:
            media_path = Path(media_file)
            if media_path.is_absolute() and media_path.is_file():
                local_videos[video_id] = media_path.as_uri()
        record = PROJECT / creator["records"] / f"{video_id}.json"
        visual = record.parent.parent / "visual-text" / record.name
        from_visual = visual.is_file()
        if from_visual:
            record = visual
        lines = []
        subtitle_times = []
        if record.is_file():
            raw_record = record.read_bytes()
            data = json.loads(raw_record)
            assert str(data["id"]) == video_id
            for segment in data["segments"]:
                subtitle_times.append([round(segment["start"] * 1000), round(segment["end"] * 1000)])
                minutes, seconds = divmod(int(segment["start"]), 60)
                lines.append(f"[{minutes:02d}:{seconds:02d}] {segment['text']}")
        summary_file = visual.with_suffix(".summary.json") if from_visual else summary_dir / f"{video_id}.json"
        summary = json.loads(summary_file.read_text(encoding="utf-8")) if lines and summary_file.is_file() else {}
        if summary and summary["source_sha256"] != hashlib.sha256(raw_record).hexdigest():
            summary = {}
        points = []
        point_display = {}
        for point in summary.get("points", []):
            segment = data["segments"][point["i"]]
            minutes, seconds = divmod(int(segment["start"]), 60)
            stamp = f"{minutes:02d}:{seconds:02d}"
            heading, detail = point["heading"], point["detail"]
            points.append([stamp, heading + " · " + detail, ""])
            point_display[stamp] = [heading, detail]
        tags = summary.get("tags", [])
        topics.update({tag: tag for tag in tags})
        title = (work.get("title") or work.get("desc") or "").split("#", 1)[0].strip() or "未命名作品"
        url = work["videoUrl"]
        assert url == f"https://www.douyin.com/video/{video_id}" or work.get("workbenchLocalOnly") and not url
        videos.append({
            "id": video_id, "creatorId": creator_id, "creator": creator["name"],
            "date": work.get("date") or "", "title": title[:80] + ("…" if len(title) > 80 else ""),
            "core": summary.get("core", ""), "detail": (work.get("desc") or work.get("title") or "").strip(),
            "tags": tags, "points": points or None, "pointDisplay": point_display,
            "transcript": "\n".join(lines), "url": url, "local": local_videos.get(video_id, ""),
            "subtitleTimes": subtitle_times, "fromVisual": from_visual,
            "subtitle": quote(os.path.relpath(PROJECT / creator["subtitles"] / f"{video_id}.srt", LIBRARY).replace(os.sep, "/")) if lines and not from_visual else "",
        })
assert len(videos) == len({video["id"] for video in videos})

compressed = PROJECT / "data/compressed"
for video in videos:
    video["hasCompressedVideo"] = (compressed / f"{video['id']}.mp4").is_file()

template = (WORK / "template.html").read_text(encoding="utf-8")
start = template.index('<script id="sources"')
end = template.index('const get = id', start)
template = (template[:start] + '<script id="catalog" type="application/json">'
            + script_json({"topics": topics, "videos": videos})
            + '</script>\n<script>\nconst {topics, videos} = JSON.parse(document.getElementById("catalog").textContent);\n'
            + template[end:])
template = template.replace("已收录 0 条视频",
                            f"{len({v['creatorId'] for v in videos})} 位主播 · {len(videos)} 条视频")
template = template.replace('</section>\n    </main>', '''</section>
      <nav class="pagination" aria-label="视频列表分页" hidden>
        <button id="previous" type="button">上一页</button><span id="page-count"></span><button id="next" type="button">下一页</button>
      </nav>
    </main>''', 1)
template = template.replace("</style>", """
  #topics { max-height:65vh; overflow:auto; }
  .points li { padding:0; background:#edf4ed; border:1px solid #dce9df; border-radius:7px; overflow:hidden; }
  .points strong {
    display:flex; align-items:center; min-height:100%; margin:0; padding:7px 9px;
    background:#bad8c4; color:#173924; border-left:5px solid #287649; font-size:14px; font-weight:700;
  }
  .points li:has(.point-description) strong { min-height:2.85em; }
  .point-description { display:block; padding:6px 9px 8px; color:#38463d; }
  .pagination { display:flex; justify-content:center; align-items:center; gap:12px; margin-top:16px; }
  .pagination[hidden] { display:none; }
  .pagination button { background:var(--paper); border:1px solid var(--line); border-radius:6px; padding:5px 11px; }
  .pagination button:disabled { opacity:.45; cursor:default; }
</style>""", 1)
template = template.replace('let activeTopic = "";', '''let activeTopic = "";
let currentPage = 1;
const pageSize = 12;
const creators = new Map(videos.map(video => [video.creatorId, video.creator]));
for (const [id, name] of creators) get("creator").add(new Option(name, id));''', 1)
template = template.replace('v.creator === creator', 'v.creatorId === creator')
template = template.replace('  activeTopic = topic;', '  activeTopic = topic;\n  currentPage = 1;')
template = template.replace('  for (const video of shown) {', '''  const pageCount = Math.max(1, Math.ceil(shown.length / pageSize));
  currentPage = Math.min(currentPage, pageCount);
  get("previous").disabled = currentPage === 1;
  get("next").disabled = currentPage === pageCount;
  get("page-count").textContent = currentPage + " / " + pageCount;
  get("page-count").parentElement.hidden = pageCount === 1;
  const first = (currentPage - 1) * pageSize;
  for (const video of shown.slice(first, first + pageSize)) {''')
template = template.replace('get("query").addEventListener("input", render);\nfor (const id of ["creator", "order"]) get(id).addEventListener("change", render);',
                            '''function resetPage() { currentPage = 1; render(); }
get("query").addEventListener("input", resetPage);
get("order").addEventListener("change", resetPage);
get("creator").addEventListener("change", resetPage);
for (const [id, step] of [["previous", -1], ["next", 1]]) {
  get(id).onclick = () => {
    currentPage += step;
    render();
    get("active-topic").scrollIntoView({block:"start"});
  };
}''')
template = template.replace('  if (!shown.length) add(cards, "p", "videos.length ? "当前筛选没有视频。" : "知识库为空。点击右上角「下载与入库」导入你的第一个视频。", "muted");',
                            '''  if (!shown.length) {
    const message = creator && activeTopic
      ? "当前主播在这个小主题下没有符合筛选条件的视频。点击左侧「全部视频」可查看当前主播的其他作品。"
      : "videos.length ? "当前筛选没有视频。" : "知识库为空。点击右上角「下载与入库」导入你的第一个视频。";
    add(cards, "p", message, "muted");
  }''')
template = template.replace('add(note, "strong", label + "　");\n    note.append(text);',
                            'note.textContent = label;')
template = template.replace('get("detail-text").textContent = video.detail;',
                            'get("detail-text").textContent = video.core || video.detail;')
template = template.replace('for (const [, label, text] of video.points) {\n        const item = add(list, "li", "");\n        add(item, "strong", label);\n        item.append(text);',
                            '''for (const [time, label] of video.points) {
        const item = add(list, "li", "");
        const [heading, description] = video.pointDisplay[time];
        add(item, "strong", heading);
        if (description) add(item, "span", description, "point-description");''')


template = template.replace('placeholder="搜索核心内容或小主题"', 'placeholder="搜索标题、口播或小主题"')
template = template.replace('...v.tags.map(tag => topics[tag])', '...v.tags.map(tag => topics[tag]), v.transcript, v.id')
template = template.replace('\nrender();\n</script>', '''\nconst requestedVideo = new URLSearchParams(location.search).get("video");
if (requestedVideo) get("query").value = requestedVideo;
render();
if (requestedVideo) {
  const video = videos.find(item => item.id === requestedVideo);
  if (video) openDetail(video);
}
</script>''')
template = template.replace('function openDetail(video) {', '''const vlcConnection = /^#vlc=(\\d{1,5})\\.([A-Za-z0-9_-]+)$/.exec(location.hash);
const workflowLink = get("workflow-link");
if (vlcConnection) {
  workflowLink.href = "http://127.0.0.1:" + vlcConnection[1] + "/workflow/#" + vlcConnection[2];
} else {
  workflowLink.href = "#";
  workflowLink.onclick = event => {
    event.preventDefault();
    alert("请从「Open-Workbench.cmd」打开工作台，再使用下载与入库。");
  };
}

async function playInVlc(video, seconds) {
  const [, port, key] = vlcConnection;
  const status = get("clip-status");
  status.hidden = false;
  status.textContent = "正在打开 VLC…";
  try {
    const response = await fetch("http://127.0.0.1:" + port + "/play?" +
      new URLSearchParams({id: video.id, seconds}), {
        method: "POST", headers: {"X-Playback-Key": key},
        signal: AbortSignal.timeout(5000),
      });
    if (!response.ok) throw Error(await response.text());
    status.textContent = "已请求 VLC 从第 " + seconds + " 秒播放压缩版。";
  } catch {
    status.textContent = "无法打开 VLC。请重新运行「Open-Workbench.cmd」，或点击原视频链接。";
  }
}

function openDetail(video) {''')
template = template.replace('      const [minutes, seconds] = time.split(":").map(Number);',
                            '''      const [minutes, seconds] = time.split(":").map(Number);
      if (vlcConnection && video.hasCompressedVideo) {
        await playInVlc(video, minutes * 60 + seconds);
        return;
      }
      if (!video.local) {
        const status = get("clip-status");
        status.hidden = false;
        status.textContent = video.hasCompressedVideo
          ? "此作品已保留 H.265 压缩版。请用「Open-Workbench.cmd」进入，再点击时间点。"
          : "暂无本地视频，可打开抖音原视频。";
        return;
      }''')
template = template.replace('    for (const [label, url] of [["播放本地视频", video.local], ["打开抖音原视频", video.url]]) {',
                            '  }\n  for (const [label, url] of [["播放本地视频", video.local], ["打开抖音原视频", video.url], ["下载字幕", video.subtitle]]) {\n      if (!url) continue;')
template = template.replace('link.rel = "noopener noreferrer";\n    }\n  }\n  dialog.showModal();',
                            'link.rel = "noopener noreferrer";\n      if (url === video.subtitle) {\n        link.download = video.id + ".srt";\n        link.onclick = event => {\n          event.preventDefault();\n          const stamp = ms => new Date(ms).toISOString().slice(11, 23).replace(".", ",");\n          const lines = video.transcript.split("\\n");\n          const blocks = video.subtitleTimes.map(([start, end], index) =>\n            [index + 1, stamp(start) + " --> " + stamp(end), lines[index].replace(/^\\[\\d+:\\d+\\] /, "")].join("\\n"));\n          const file = URL.createObjectURL(new Blob([blocks.join("\\n\\n") + "\\n"], {type:"application/x-subrip;charset=utf-8"}));\n          const save = document.createElement("a");\n          save.href = file;\n          save.download = link.download;\n          save.click();\n          setTimeout(() => URL.revokeObjectURL(file), 1000);\n        };\n      }\n  }\n  dialog.showModal();')
template = template.replace('add(actions, "button", "查看口播稿")', 'add(actions, "button", video.fromVisual ? "查看画面文字摘录" : "查看口播稿")')
template = template.replace('  dialog.showModal();', '''  if (vlcConnection && video.hasCompressedVideo) {
    const vlc = add(actions, "button", "用 VLC 播放压缩版");
    vlc.type = "button";
    vlc.onclick = () => playInVlc(video, 0);
  } else if (video.hasCompressedVideo && !video.local) {
    add(actions, "span", "本地压缩版通过「Open-Workbench.cmd」播放", "muted");
  }
  dialog.showModal();''')
template = template.replace('add(row, "p", video.core, "core");',
                            'add(row, "p", video.core || (video.transcript ? "摘要待整理 · 有口播稿" : "待转写"), video.core ? "core" : "meta");')

LIBRARY.mkdir(parents=True, exist_ok=True)
target = LIBRARY / "打开知识库.html"
temporary = target.with_suffix(f".{os.getpid()}.html.tmp")
temporary.write_text(template, encoding="utf-8")
temporary.replace(target)
print(f"{len(videos)} videos, {len(topics)} topics, {sum(len(v.get('points') or []) for v in videos)} timed points")
