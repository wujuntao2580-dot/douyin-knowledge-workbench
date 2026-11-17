import json
import sys
from collections.abc import Callable
from pathlib import Path

from chinese_text import simplified


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT.parents[1] / "data/punctuated"
MARKS = "，。？！、；：,.?!;:"
CHINESE = dict(zip(",.?!;:", "，。？！；："))


def significant(char):
    return not char.isspace() and char not in MARKS


def restore(punctuation, segments):
    source = "\n".join(segments)
    positions = [i for i, char in enumerate(source) if significant(char)]
    prediction = punctuation.add_punctuation(source.replace("\n", " "))
    predicted_text = "".join(char for char in prediction if significant(char))
    expected_text = "".join(source[i] for i in positions)
    if predicted_text.casefold() != expected_text.casefold() or len(predicted_text) != len(expected_text):
        return segments, False
    insertions = {}
    seen = 0
    for char in prediction:
        if significant(char):
            seen += 1
        elif char in MARKS and seen:
            start = positions[seen - 1] + 1
            end = positions[seen] if seen < len(positions) else len(source)
            gap = source[start:end]
            if start not in insertions and not any(mark in MARKS for mark in gap):
                previous = source[start - 1]
                following = source[end] if end < len(source) else ""
                if not (not gap and previous.isascii() and following.isascii()
                        and previous.isalnum() and following.isalnum()):
                    insertions[start] = CHINESE.get(char, char)
    output = "".join(insertions.get(i, "") + char for i, char in enumerate(source))
    return (output + insertions.get(len(source), "")).split("\n"), True


def load_punctuation(*, has_entitlement: Callable[[str], bool] | None = None):
    if has_entitlement is not None and not has_entitlement("transcript_punctuation"):
        return None
    model = ROOT.parents[1] / ".runtime/models/punctuation/model.int8.onnx"
    if not model.is_file():
        return None
    import sherpa_onnx
    config = sherpa_onnx.OfflinePunctuationConfig(
        model=sherpa_onnx.OfflinePunctuationModelConfig(ct_transformer=str(model), num_threads=3)
    )
    return sherpa_onnx.OfflinePunctuation(config)


def punctuate_segments(punctuation, segments):
    source = [simplified(segment["text"]) for segment in segments]
    if punctuation is None:
        return [{**segment, "text": text} for segment, text in zip(segments, source, strict=True)]
    result = []
    start = 0
    while start < len(source):
        end = start + 1
        while end < len(source) and sum(map(len, source[start:end])) < 400:
            end += 1
        left = max(0, start - 1)
        right = min(end + 1, len(source))
        chunk, matched = restore(punctuation, source[left:right])
        if not matched:
            chunk = [restore(punctuation, [line])[0][0] for line in source[left:right]]
        result.extend(chunk[start-left:end-left])
        start = end
    return [{**segment, "text": text} for segment, text in zip(segments, result, strict=True)]


def main(*, has_entitlement: Callable[[str], bool] | None = None):
    punctuation = load_punctuation(has_entitlement=has_entitlement)
    if punctuation is None:
        print("当前权限未开通口播补标点。")
        return
    OUTPUT.mkdir(exist_ok=True)
    changed = 0
    for file in sorted(ROOT.glob("[0-9]*.json")):
        record = json.loads(file.read_text(encoding="utf-8"))
        if record.get("punctuation_restored"):
            continue
        result = punctuate_segments(punctuation, record["segments"])
        changed += record["segments"] != result
        record["segments"] = result
        record["punctuation_restored"] = True
        (OUTPUT / file.name).write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    print(f"{changed} transcripts received punctuation")


if __name__ == "__main__":
    main()
