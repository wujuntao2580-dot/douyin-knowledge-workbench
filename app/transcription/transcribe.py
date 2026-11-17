import argparse
import json
import os
import re
import time
from collections.abc import Callable
from pathlib import Path

import av
from faster_whisper import BatchedInferencePipeline, WhisperModel

from restore_punctuation import load_punctuation, punctuate_segments

PROJECT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).resolve().parent
MODEL = PROJECT / ".runtime/models/faster-whisper-small"
MEDIA = PROJECT / "data/inputs"
TRANSCRIPTS = PROJECT / "data/transcripts"


def srt_time(seconds):
    hours, remainder = divmod(round(seconds * 1000), 3600000)
    minutes, remainder = divmod(remainder, 60000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def write(path, content):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(content, encoding="utf-8")
    temp.replace(path)


def duration(file):
    with av.open(str(file)) as media:
        return media.duration


def main(*, has_entitlement: Callable[[str], bool] | None = None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--stop-file", type=Path)
    parser.add_argument("--media", type=Path, default=MEDIA)
    parser.add_argument("--records", type=Path, default=PROJECT / "data/transcript-records")
    parser.add_argument("--transcripts", type=Path, default=TRANSCRIPTS)
    parser.add_argument("--follow-download", type=Path)
    parser.add_argument("--selection", type=Path, help="仅转写 JSON 中指定的作品 ID 和文件路径")
    args = parser.parse_args()
    selection = None
    if args.selection:
        if args.follow_download:
            parser.error("--selection 与 --follow-download 不可同时使用")
        selection = {key: Path(value) for key, value in json.loads(args.selection.read_text(encoding="utf-8")).items()}
        if not selection or any(not re.fullmatch(r"[0-9]{19}", key) or not file.is_file() for key, file in selection.items()):
            parser.error("选定作品的 ID 或本地文件无效")
    if selection is None and not args.follow_download and not any(args.media.glob("*.mp4")):
        parser.error(f"未找到视频文件：{args.media}")
    args.records.mkdir(parents=True, exist_ok=True)
    args.transcripts.mkdir(parents=True, exist_ok=True)

    def pending():
        attempted = set()
        while True:
            ready = []
            candidates = selection.items() if selection is not None else (
                (match[1], file) for file in args.media.glob("*.mp4")
                if (match := re.match(r"^(\d{19})(?!\d)", file.name))
            )
            for video_id, file in candidates:
                if video_id in attempted or (args.records / f"{video_id}.json").is_file():
                    continue
                if args.follow_download and time.time() - file.stat().st_mtime < 15:
                    continue
                try:
                    length = duration(file)
                except (OSError, av.FFmpegError):
                    continue
                ready.append((length or 0, video_id, file))
            for _, video_id, file in sorted(ready):
                attempted.add(video_id)
                yield video_id, file
                if args.sample or args.limit is not None and len(attempted) >= args.limit:
                    return
            if not args.follow_download:
                return
            stage = json.loads(args.follow_download.read_text(encoding="utf-8"))["stage"]
            if stage not in {"sample", "downloading"}:
                if any(time.time() - file.stat().st_mtime < 15 for file in args.media.glob("*.mp4")):
                    time.sleep(15)
                    continue
                return
            if args.stop_file and args.stop_file.exists():
                return
            time.sleep(15)

    punctuation = load_punctuation(has_entitlement=has_entitlement)
    dll_dirs = []
    if args.device == "cuda":
        gpu_paths = list((PROJECT / ".runtime/gpu/nvidia").glob("*/bin"))
        os.environ["PATH"] = os.pathsep.join([*(str(path) for path in gpu_paths), os.environ.get("PATH", "")])
        for directory in gpu_paths:
            dll_dirs.append(os.add_dll_directory(str(directory)))
    model = WhisperModel(str(MODEL), device=args.device, compute_type="int8" if args.device == "cpu" else "float16",
                         cpu_threads=args.threads, local_files_only=True)
    recognizer = BatchedInferencePipeline(model=model) if args.batch_size else model
    options = {"batch_size": args.batch_size} if args.batch_size else {}
    failures = []
    for video_id, file in pending():
        if args.stop_file and args.stop_file.exists():
            break
        start = time.monotonic()
        if selection is not None:
            print(f"START {video_id}", flush=True)
        try:
            with av.open(str(file)) as media:
                if not media.streams.audio:
                    print(f"NO_AUDIO {video_id}", flush=True)
                    continue
            raw_segments, info = recognizer.transcribe(
                str(file), language="zh", vad_filter=True, beam_size=3, **options
            )
            segments = [{"start": s.start, "end": s.end, "text": s.text.strip()}
                        for s in raw_segments if s.text.strip()]
            if not segments:
                raise ValueError("No speech detected")
            segments = punctuate_segments(punctuation, segments)
            srt = "\n\n".join(f'{i}\n{srt_time(s["start"])} --> {srt_time(s["end"])}\n{s["text"]}'
                              for i, s in enumerate(segments, 1)) + "\n"
            write(args.transcripts / f"{video_id}.srt", srt)
            if args.transcripts != TRANSCRIPTS:
                paragraphs = "\n\n".join(f'**{srt_time(s["start"]).split(",")[0]}** {s["text"]}' for s in segments)
                write(args.transcripts / f"{video_id}.md", f"# {file.stem}\n\n{paragraphs}\n")
            write(args.records / f"{video_id}.json", json.dumps({
                "id": video_id, "duration": info.duration, "segments": segments,
                "punctuation_restored": punctuation is not None,
            }, ensure_ascii=False))
            print(f"OK {video_id} {info.duration:.0f}s audio {time.monotonic() - start:.1f}s elapsed", flush=True)
        except Exception as error:
            failures.append(video_id)
            print(f"FAILED {video_id} {error}", flush=True)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
