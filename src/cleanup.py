"""Plan or recycle temporary files after a VideoBook has been verified."""

import argparse
import json
import os
import re
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

import markdown

from pipeline import ROOT, status
from validate import PLACEHOLDER, require, video_directory


RETAIN = {
    "transcript.json", "transcript.corrected.txt", "transcript.translated.txt",
    "corrections.json", "translation.json", "book.tagged.md", "book.md", "book.html",
    "run.json", "capture.json", "acquisition.json", "publication.json", "_publication.json",
}
RAW_SUBTITLES = {".vtt", ".srt", ".json3", ".ttml", ".srv1", ".srv2", ".srv3", ".lrc"}
TEXT_ASSETS = {".html", ".md", ".css", ".svg", ".js", ".mjs"}


def checked_path(path, root):
    """Reject outside paths and links before any recursive operation."""
    root = Path(root).absolute()
    path = Path(path).absolute()
    require(path != root and path.is_relative_to(root), f"Path outside cleanup root: {path}")
    for part in (path, *path.parents):
        require(not part.is_symlink() and not part.is_junction(), f"Linked cleanup path: {part}")
    resolved = path.resolve()
    require(resolved.is_relative_to(root.resolve()), f"Path outside cleanup root: {path}")
    return resolved


def checked_tree(directory):
    def fail(error):
        raise error

    paths = []
    for base, directories, files in os.walk(directory, followlinks=False, onerror=fail):
        require(".git" not in directories + files, f"Nested repository: {base}")
        for name in directories + files:
            paths.append(checked_path(Path(base) / name, directory))
    return paths


class References(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if value and name in {"src", "href", "poster", "data", "xlink:href"}:
                self.urls.append(value)
            if value and name == "srcset" and not value.startswith("data:"):
                self.urls.extend(item.strip().split()[0] for item in value.split(",") if item.strip())


def references(path):
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix in {".js", ".mjs"}:
        # Do not interpret JavaScript string templates as HTML or CSS URLs.
        return re.findall(r"(?:from\s*|import\s*\(?|require\s*\()\s*['\"](\.[^'\"]+)['\"]", text)
    parser = References()
    parser.feed(markdown.markdown(text, extensions=["extra"]) if path.suffix == ".md" else text)
    urls = parser.urls
    urls.extend(match[1] for match in re.findall(r"url\(\s*(['\"]?)(.*?)\1\s*\)", text))
    urls.extend(re.findall(r"@import\s+['\"]([^'\"]+)['\"]", text))
    if path.name == "book.tagged.md":
        urls.extend(f"images/shot_{stamp.replace(':', '_')}.png" for _, stamp in PLACEHOLDER.findall(text))
    return urls


def retained_files(directory):
    """Retain recovery records, original subtitles and the local document dependency graph."""
    directory = Path(directory).resolve()
    keep = set()
    for path in directory.iterdir():
        if not path.is_file():
            continue
        raw = (path.suffix.lower() in RAW_SUBTITLES or path.name.endswith(".info.json")
               or (path.name.startswith("transcript.") and path.suffix == ".json"))
        legacy = (not (directory / "corrections.json").exists()
                  and path.name in {"_correction_review.json", "_stutter_review.json"})
        if path.name in RETAIN or raw or legacy:
            keep.add(path)
    pending = [path for path in keep if path.suffix in TEXT_ASSETS]
    while pending:
        source = pending.pop()
        for url in references(source):
            parsed = urlsplit(url)
            if parsed.scheme or parsed.netloc or not parsed.path or parsed.path.startswith("/"):
                continue
            target = checked_path(source.parent / unquote(parsed.path), directory)
            require(target.is_file(), f"Missing local dependency in {source.name}: {url}")
            if target not in keep:
                keep.add(target)
                if target.suffix in TEXT_ASSETS:
                    pending.append(target)
    return keep


def redundant_paths(directory, keep):
    """Return whole redundant subtrees where possible, never a retained parent."""
    paths = []
    for path in sorted(directory.iterdir()):
        if path in keep:
            continue
        if path.is_dir() and any(item.is_relative_to(path) for item in keep):
            paths.extend(redundant_paths(path, keep))
        else:
            paths.append(path)
    return paths


def plan_cleanup(directory, mode="book", root=ROOT):
    directory = checked_path(directory, Path(root) / "output")
    state = status(directory, mode=mode, root=Path(root))
    require(state["complete"], f"{directory.name}: finish/review {state['next_stage']} before cleanup")
    if mode == "transcript" and any(directory.glob("book.*")):
        require(status(directory, root=Path(root))["complete"], "An existing book is unfinished; retain its working files")
    checked_tree(directory)
    keep = retained_files(directory)
    return redundant_paths(directory, keep)


def recycle_paths(paths, root):
    paths = [checked_path(path, root) for path in paths]
    for path in paths:
        if path.is_dir():
            checked_tree(path)
    if not paths:
        return
    require(os.name == "nt", "This recycler requires Windows; retain files and use the host's recycle-bin tool")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-STA", "-Command",
         Path(__file__).with_name("recycle.ps1").read_text(encoding="utf-8")],
        input=json.dumps({"root": str(Path(root).resolve()), "paths": [str(path) for path in paths]}, ensure_ascii=True),
        text=True, capture_output=True,
    )
    if result.returncode:
        raise OSError(result.stderr.strip() or "Recycle bin operation failed; no permanent-delete fallback")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video_id", nargs="*")
    parser.add_argument("--mode", choices=("book", "transcript"), default="book")
    parser.add_argument("--scratch", help="this task's disposable directory under output/_tmp/")
    parser.add_argument("--apply", action="store_true", help="send the listed files to the Windows Recycle Bin")
    args = parser.parse_args(argv)
    if not args.video_id and not args.scratch:
        parser.error("provide video_id or --scratch task_name")
    try:
        directories = []
        for vid in dict.fromkeys(args.video_id):
            video_directory(vid)  # Validate the ID before resolving, then reject linked aliases.
            directories.append(checked_path(ROOT / "output" / vid, ROOT / "output"))
        plans = [(directory, plan_cleanup(directory, args.mode)) for directory in directories]
        if args.scratch:
            require(re.fullmatch(r"[A-Za-z0-9_-]+", args.scratch), "Invalid scratch task name")
            scratch = checked_path(ROOT / "output" / "_tmp" / args.scratch, ROOT / "output" / "_tmp")
            if scratch.exists():
                checked_tree(scratch)
                plans.append((scratch, [scratch]))
        for directory, paths in plans:
            print(json.dumps({"video_id": directory.name, "action": "recycle" if args.apply else "preview",
                              "paths": [str(p.relative_to(ROOT)) for p in paths]}, ensure_ascii=False))
        if args.apply:
            recycle_paths([path for _, paths in plans for path in paths], ROOT / "output")
            for directory in directories:
                require(status(directory, args.mode)["complete"], f"Check artifacts after cleanup: {directory.name}")
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
