"""Offline artifact checks; editorial and screenshot quality remain agent reviews."""

import argparse
import json
import math
import re
import struct
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

STAGES = ("transcript", "corrected", "book", "images", "html")
PLACEHOLDER = re.compile(r"!\[([^\]]*)\]\(SCREENSHOT:(\d{2}:\d{2}:\d{2})\)")
IMAGE = re.compile(r"!\[[^\]]*\]\(([^\s)]+)\)")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_text(path):
    text = path.read_text(encoding="utf-8-sig")
    require(bool(text.strip()), f"Empty file: {path.name}")
    return text


def seconds(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        result = float(value)
    else:
        parts = str(value).split(":")
        require(len(parts) in (2, 3), f"Invalid timestamp: {value}")
        nums = [float(part) for part in parts]
        require(all(math.isfinite(n) and n >= 0 for n in nums), f"Invalid timestamp: {value}")
        require(nums[-1] < 60 and (len(nums) == 2 or nums[-2] < 60), f"Invalid timestamp: {value}")
        result = sum(n * 60 ** i for i, n in enumerate(reversed(nums)))
    require(math.isfinite(result) and result >= 0, f"Invalid timestamp: {value}")
    return result


def image_paths(directory, markdown):
    paths = []
    for target in IMAGE.findall(markdown):
        parsed = urlparse(target)
        if parsed.scheme in ("http", "https", "data"):
            continue
        require(not parsed.scheme and not parsed.netloc, f"Invalid image reference: {target}")
        path = (directory / unquote(parsed.path)).resolve()
        require(path.is_relative_to(directory.resolve()), f"Image outside video directory: {target}")
        paths.append(path)
    return paths


def validate_transcript(directory):
    data = read_json(directory / "transcript.json")
    require(isinstance(data, dict), "transcript.json must be an object")
    require(data.get("video_id") == directory.name and directory.name != "Unknown_ID", "Video ID does not match its directory")
    require(data.get("title") and data["title"] != "Unknown Title", "Missing video title")
    require(urlparse(data.get("video_url", "")).scheme in ("https", "http"), "Missing video URL")
    duration = float(data.get("duration", 0))
    require(math.isfinite(duration) and duration > 0, "Missing or invalid video duration")
    require(isinstance(data.get("chapters"), list), "chapters must be a list")
    segments = data.get("segments")
    require(isinstance(segments, list) and segments, "No transcript segments")
    last_start, last_end = -1, 0
    for index, segment in enumerate(segments, 1):
        start, end = seconds(segment["start"]), seconds(segment["end"])
        require(start >= last_start and end >= start and end <= duration + 2, f"Invalid time range at segment {index}")
        require(isinstance(segment["text"], str) and segment["text"].strip(), f"Empty text at segment {index}")
        last_start, last_end = start, max(last_end, end)
    coverage = last_end / duration
    require(coverage >= 0.5, f"Transcript ends too early: {coverage:.1%} of duration")
    warnings = []
    if coverage < 0.9 or seconds(segments[0]["start"]) > 30:
        warnings.append("Check the beginning/end of the video: transcript coverage may be incomplete.")
    return data, warnings


def validate_corrected(directory, data):
    ledger = read_json(directory / "corrections.json")
    segments = data["segments"]
    require(ledger["source_segments"] == len(segments), "Correction ledger uses a different source")
    review = ledger.get("review", {})
    require(review.get("full_read") is True and review.get("stutter_checked") is True, "Full reading and stutter review must be completed")
    require(isinstance(ledger.get("glossary"), dict) and isinstance(ledger.get("uncertain"), list), "Missing glossary or uncertainty list")
    changes = {}
    for change in ledger["changes"]:
        index = change["segment"]
        require(type(index) is int and 1 <= index <= len(segments) and index not in changes, "Invalid or duplicate segment decision")
        require(change["old"] == segments[index - 1]["text"].strip(), f"Source changed at segment {index}")
        require(isinstance(change["new"], str) and change["new"] == change["new"].strip(), f"Invalid corrected text at segment {index}")
        require(isinstance(change.get("reason"), str) and change["reason"].strip(), f"Missing reason at segment {index}")
        changes[index] = change["new"]
    expected = []
    for index, segment in enumerate(segments, 1):
        text = changes.get(index, segment["text"].strip())
        require("\n" not in text and "\r" not in text and "\ufffd" not in text, f"Invalid text at segment {index}")
        if text:
            start = int(seconds(segment["start"]))
            expected.append(f"[{start // 60:02d}:{start % 60:02d}] {text}")
    actual = read_text(directory / "transcript.corrected.txt").splitlines()
    require(actual == expected, "Corrected transcript differs from the reviewed decisions (missing, reordered, or unrecorded edits)")


def validate_book(directory, data):
    tagged = read_text(directory / "book.tagged.md")
    require(re.search(r"^# .+", tagged, re.MULTILINE), "Book needs a title")
    require(re.search(r"^## .+", tagged, re.MULTILINE), "Book needs chapters")
    matches = list(PLACEHOLDER.finditer(tagged))
    require(tagged.count("SCREENSHOT:") == len(matches), "Malformed screenshot placeholder")
    for match in matches:
        require(seconds(match[2]) <= float(data["duration"]), f"Screenshot exceeds video duration: {match[2]}")
    return tagged


def validate_images(directory, tagged):
    book = read_text(directory / "book.md")
    require("SCREENSHOT:" not in book, "Unmaterialized screenshots remain in book.md")
    expected = PLACEHOLDER.sub(lambda m: f"![{m[1]}](images/shot_{m[2].replace(':', '_')}.png)", tagged)
    require(book.rstrip() == expected.rstrip(), "book.md differs from materialized book.tagged.md")
    for path in image_paths(directory, book):
        require(path.is_file() and path.stat().st_size > 0, f"Missing image: {path.name}")
        if path.suffix.lower() == ".png":
            with path.open("rb") as handle:
                header = handle.read(24)
            require(len(header) == 24 and header[:8] == b"\x89PNG\r\n\x1a\n" and header[12:16] == b"IHDR", f"Invalid PNG header: {path.name}")
            require(all(struct.unpack(">II", header[16:24])), f"Empty PNG dimensions: {path.name}")
    return book


class HtmlImages(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = set()

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            self.sources.add(dict(attrs).get("src", ""))


def validate_stage(directory, stage):
    """Check one stage; the pipeline separately verifies preceding checkpoints."""
    try:
        data, warnings = validate_transcript(directory)
        if stage == "corrected":
            validate_corrected(directory, data)
        if stage in ("book", "images", "html"):
            tagged = validate_book(directory, data)
        if stage in ("images", "html"):
            book = validate_images(directory, tagged)
        if stage == "html":
            html = read_text(directory / "book.html")
            require("<html" in html.lower() and "</html>" in html.lower(), "Incomplete HTML document")
            require("SCREENSHOT:" not in html, "Unmaterialized screenshots remain in HTML")
            require((directory / "book.html").stat().st_mtime_ns >= (directory / "book.md").stat().st_mtime_ns, "HTML is older than book.md; render again")
            parser = HtmlImages()
            parser.feed(html)
            require(set(IMAGE.findall(book)).issubset(parser.sources), "HTML is missing book images")
        return {"stage": stage, "ok": True, "errors": [], "warnings": warnings}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError) as exc:
        return {"stage": stage, "ok": False, "errors": [str(exc)], "warnings": []}


def video_directory(video_id, root=None):
    require(re.fullmatch(r"[A-Za-z0-9_-]+", video_id) and video_id != "Unknown_ID", "Invalid video ID")
    base = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    directory = (base / "output" / video_id).resolve()
    require(directory.is_relative_to((base / "output").resolve()), "Video directory is outside output")
    return directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video_id")
    parser.add_argument("--stage", choices=STAGES, default="html", help="validate through this stage")
    args = parser.parse_args()
    directory = video_directory(args.video_id)
    results = [validate_stage(directory, stage) for stage in STAGES[:STAGES.index(args.stage) + 1]]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(result["ok"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
