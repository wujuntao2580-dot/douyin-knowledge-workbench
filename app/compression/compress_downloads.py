import errno
import json
import msvcrt
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from tempfile import NamedTemporaryFile

import av
from imageio_ffmpeg import get_ffmpeg_exe


PROJECT = Path(__file__).resolve().parents[2]
MEDIA = PROJECT / "data/compressed"
BUILDER = PROJECT / "app/catalog/build_full.py"
FFMPEG = shutil.which("ffmpeg") or (PROJECT / ".runtime/ffmpeg/ffmpeg.exe" if (PROJECT / ".runtime/ffmpeg/ffmpeg.exe").is_file() else get_ffmpeg_exe())
SCALE = r"scale=if(gte(iw\,ih)\,-2\,trunc(min(iw\,720)/2)*2):if(gte(iw\,ih)\,trunc(min(ih\,720)/2)*2\,-2)"
ENCODERS = {
    "cpu": ("libx265", "-preset", "medium", "-crf", "26"),
    "gpu": ("hevc_nvenc", "-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", "33", "-b:v", "0"),
}


def media_info(path):
    with av.open(str(path)) as media:
        video = media.streams.video[0]
        return (
            media.duration / av.time_base,
            video.codec_context.name,
            video.width,
            video.height,
            media.streams.audio[0].codec_context.name if media.streams.audio else None,
        )


def playable_copy(source_info, copy):
    duration, _, width, height, audio = source_info
    new_duration, codec, new_width, new_height, new_audio = media_info(copy)
    return (codec == "hevc" and new_audio == audio and abs(duration - new_duration) <= 0.25
            and min(new_width, new_height) <= min(width, height, 720) + 1
            and abs(new_width - new_height * (width / height)) <= 4)


def compress_video(video_id, source, *, has_entitlement: Callable[[str], bool] | None = None,
                   background=False, device="cpu"):
    if has_entitlement is not None and not has_entitlement("video_compression"):
        raise PermissionError("当前权限未开通视频压缩")
    MEDIA.mkdir(parents=True, exist_ok=True)
    with (MEDIA.parent / "encoder.lock").open("a+b") as lock:
        while True:
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            except OSError as error:
                if error.errno != errno.EACCES:
                    raise
            else:
                break
        return _encode_video(video_id, source, background, device)


def _encode_video(video_id, source, background, device):
    output = MEDIA / f"{video_id}.mp4"
    original_bytes = source.stat().st_size
    source_info = media_info(source)
    if output.is_file() and output.stat().st_size < original_bytes and playable_copy(source_info, output):
        return "already_compact"
    with NamedTemporaryFile(dir=MEDIA, prefix=f"{video_id}-", suffix=".partial.mp4", delete=False) as file:
        temporary = Path(file.name)
    try:
        subprocess.run([
            FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-xerror", "-y",
            "-i", source, "-map", "0:v:0", "-map", "0:a:0?", "-vf", SCALE,
            "-c:v", *ENCODERS[device], "-c:a", "copy",
            "-tag:v", "hvc1", "-movflags", "+faststart", temporary,
        ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW | (subprocess.BELOW_NORMAL_PRIORITY_CLASS if background else 0),
            check=True)
        if not playable_copy(source_info, temporary):
            raise ValueError("压缩版的时长、音轨或画面尺寸未通过检查")
        if temporary.stat().st_size >= original_bytes:
            return "original_smaller"
        temporary.replace(output)
        return "compressed"
    finally:
        temporary.unlink(missing_ok=True)


def remember_downloads(queue, ids):
    pending = set(json.loads(queue.read_text(encoding="utf-8"))) if queue.is_file() else set()
    save_queue(queue, pending.union(ids))


def save_queue(queue, ids):
    temporary = queue.with_suffix(".tmp")
    temporary.write_text(json.dumps(sorted(ids)), encoding="utf-8")
    temporary.replace(queue)


def compress_pending(queue, files, *, has_entitlement: Callable[[str], bool] | None = None):
    if not queue.is_file():
        return
    pending = set(json.loads(queue.read_text(encoding="utf-8")))
    ready = pending & files.keys()
    if not ready:
        return
    completed = set()
    refresh = False
    for video_id in sorted(ready):
        try:
            status = compress_video(video_id, files[video_id], has_entitlement=has_entitlement)
            completed.add(video_id)
            refresh |= status != "original_smaller"
        except (av.FFmpegError, OSError, ValueError, IndexError, TypeError, subprocess.CalledProcessError) as error:
            status = f"retry: {type(error).__name__}"
        print(f"压缩 {video_id} {status}", flush=True)
    if refresh:
        result = subprocess.run([sys.executable, "-B", "-X", "utf8", BUILDER])
        if result.returncode:
            print("压缩文件已保存，工作台刷新待下次重试。", flush=True)
            return
    save_queue(queue, pending - completed)
