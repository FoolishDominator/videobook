"""Plan or recycle temporary files after a VideoBook has been verified."""

import argparse
import ctypes
import errno
import json
import os
import re
import secrets
import subprocess
import sys
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

import markdown
from send2trash import send2trash

from pipeline import ROOT, status
from validate import PLACEHOLDER, require, video_directory


RETAIN = {
    "transcript.json", "transcript.corrected.txt", "transcript.translated.txt",
    "corrections.json", "translation.json", "book.tagged.md", "book.md", "book.html",
    "run.json", "capture.json", "acquisition.json", "publication.json", "_publication.json",
}
RAW_SUBTITLES = {".vtt", ".srt", ".json3", ".ttml", ".srv1", ".srv2", ".srv3", ".lrc"}
TEXT_ASSETS = {".html", ".md", ".css", ".svg", ".js", ".mjs"}
ARCHIVE_DIRECTORY = ".recycle-archive"


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
    """Use only recoverable host trash, after validating the entire batch."""
    paths = [checked_path(path, root) for path in paths]
    for path in paths:
        if path.is_dir():
            checked_tree(path)
    if not paths:
        return
    if sys.platform == "win32":
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-STA", "-Command",
             Path(__file__).with_name("recycle.ps1").read_text(encoding="utf-8")],
            input=json.dumps({"root": str(Path(root).resolve()), "paths": [str(path) for path in paths]}, ensure_ascii=True),
            text=True, capture_output=True,
        )
        if result.returncode:
            raise OSError(result.stderr.strip() or "Recycle bin operation failed; no permanent-delete fallback")
    elif sys.platform.startswith("linux"):
        # Send2Trash implements recoverable desktop trash and raises if the
        # filesystem cannot provide it. Never substitute unlink/rmtree here.
        try:
            send2trash([str(path) for path in paths])
        except OSError as exc:
            raise OSError(f"Linux trash operation failed; retain remaining files; no permanent-delete fallback: {exc}") from exc
        remaining = [str(path) for path in paths if path.exists()]
        if remaining:
            raise OSError(f"Linux trash operation left files in place; no permanent-delete fallback: {remaining}")
    else:
        raise OSError(f"Unsupported cleanup platform: {sys.platform}; retain files and use the host's recycle-bin tool")


def _checked_batch(paths, root):
    paths = [checked_path(path, root) for path in paths]
    for index, path in enumerate(paths):
        require(path.exists(), f"Missing archive source: {path}")
        require(path.is_file() or path.is_dir(), f"Unsupported archive source: {path}")
        for other in paths[:index]:
            require(not path.is_relative_to(other) and not other.is_relative_to(path),
                    f"Overlapping archive paths: {other}, {path}")
        if path.is_dir():
            checked_tree(path)
    return paths


def _archive_batch_directory(batch_id, root):
    require(isinstance(batch_id, str) and re.fullmatch(r"[A-Za-z0-9_-]+", batch_id), "Invalid archive batch ID")
    archive = checked_path(Path(root) / ARCHIVE_DIRECTORY, root)
    return checked_path(archive / batch_id, archive)


def _write_archive_manifest(batch, manifest):
    target = checked_path(batch / "manifest.json", batch)
    temporary = checked_path(batch / "manifest.json.next", batch)
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, target)


def _require_same_device(path, destination_parent):
    device = destination_parent.stat().st_dev
    paths = [path, *checked_tree(path)] if path.is_dir() else [path]
    for item in paths:
        if item.stat().st_dev != device:
            raise OSError(errno.EXDEV, f"Archive requires same-filesystem rename: {item}")


def _rename_without_replace(source, target):
    """Atomic same-filesystem move that cannot overwrite an existing target."""
    if sys.platform == "win32":
        os.rename(source, target)  # Windows rename refuses existing targets.
        return
    if sys.platform.startswith("linux"):
        library = ctypes.CDLL(None, use_errno=True)
        rename = getattr(library, "renameat2", None)
        if rename is None:
            raise OSError(errno.ENOSYS, "Safe local archiving requires renameat2 support")
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        # AT_FDCWD, RENAME_NOREPLACE. EXDEV/unsupported flags fail closed.
        if rename(-100, os.fsencode(source), -100, os.fsencode(target), 1) != 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), str(target))
        return
    raise OSError(f"Safe local archiving is unsupported on {sys.platform}")


def archive_paths(paths, root=ROOT):
    """Explicit local recovery archive; never an automatic system-trash fallback."""
    root = Path(root).absolute()
    output = checked_path(root / "output", root)
    paths = _checked_batch(paths, output)
    if not paths:
        return None
    for path in paths:
        name = path.relative_to(root).as_posix()
        require("\\" not in name and ":" not in name, f"Unsupported original archive path: {path}")
    archive = checked_path(root / ARCHIVE_DIRECTORY, root)
    archive.mkdir(mode=0o700, exist_ok=True)
    for path in paths:
        _require_same_device(path, archive)
    batch_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(6)
    batch = _archive_batch_directory(batch_id, root)
    batch.mkdir(mode=0o700)
    (batch / "files").mkdir(mode=0o700)
    manifest = {"version": 1, "created_at": datetime.now(UTC).isoformat(), "entries": [
        {"original_path": path.relative_to(root).as_posix(), "archive_path": f"files/{index:06d}",
         "archived_at": None, "restored_at": None}
        for index, path in enumerate(paths)
    ]}
    # Persist all recovery destinations before moving any source. A partial
    # batch remains recoverable even if a later rename or manifest write fails.
    _write_archive_manifest(batch, manifest)
    try:
        for path, entry in zip(paths, manifest["entries"]):
            source = checked_path(path, output)
            target = checked_path(batch / entry["archive_path"], batch)
            require(not target.exists(), f"Archive destination already exists: {target}")
            _checked_batch([source], output)
            _require_same_device(source, target.parent)
            _rename_without_replace(source, target)  # Never copy-and-delete.
            entry["archived_at"] = datetime.now(UTC).isoformat()
            _write_archive_manifest(batch, manifest)
    except (OSError, ValueError) as exc:
        raise OSError(f"Archive batch {batch_id} stopped; retain remaining originals. "
                      f"Recover moved files with --restore-archive {batch_id}: {exc}") from exc
    return batch_id


def plan_archive_restore(batch_id, root=ROOT):
    root = Path(root).absolute()
    batch = _archive_batch_directory(batch_id, root)
    require(batch.is_dir(), f"Archive batch not found: {batch_id}")
    checked_tree(batch)
    manifest_path = checked_path(batch / "manifest.json", batch)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(isinstance(manifest, dict) and manifest.get("version") == 1, "Unsupported archive manifest")
    entries = manifest.get("entries")
    require(isinstance(entries, list) and entries, "Invalid archive entries")
    output = checked_path(root / "output", root)
    originals = []
    plan = []
    for index, entry in enumerate(entries):
        require(isinstance(entry, dict), "Invalid archive entry")
        name = entry.get("original_path")
        require(isinstance(name, str) and name and "\\" not in name and ":" not in name, "Invalid original archive path")
        relative = PurePosixPath(name)
        require(not relative.is_absolute() and ".." not in relative.parts
                and len(relative.parts) > 1 and relative.parts[0] == "output"
                and relative.as_posix() == name, f"Invalid original archive path: {name}")
        target = checked_path(root / name, output)
        require(all(not target.is_relative_to(other) and not other.is_relative_to(target) for other in originals),
                f"Overlapping restore paths: {name}")
        originals.append(target)
        require(entry.get("archive_path") == f"files/{index:06d}", "Invalid archived data path")
        source = checked_path(batch / entry["archive_path"], batch)
        if entry.get("restored_at"):
            require(not source.exists() and target.exists(), f"Restored entry needs review: {name}")
            continue
        if not source.exists() and not entry.get("archived_at"):
            require(target.exists(), f"Missing original and archived file: {name}")
            continue  # An interrupted batch never moved this entry.
        require(source.exists(), f"Missing archived file: {source}")
        require(not target.exists(), f"Restore destination already exists: {target}")
        _checked_batch([source], batch)
        parent = target.parent
        while not parent.exists():
            parent = parent.parent
        _require_same_device(source, parent)
        plan.append((source, target, entry))
    return batch, manifest, plan


def restore_archive(batch_id, root=ROOT):
    batch, manifest, plan = plan_archive_restore(batch_id, root)
    for source, target, entry in plan:
        # Recheck each path immediately before mutation. Run cleanup/restore
        # with no other process writing the same output or archive batch.
        source = checked_path(source, batch)
        target = checked_path(target, Path(root) / "output")
        require(not target.exists(), f"Restore destination already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        checked_path(target, Path(root) / "output")
        _checked_batch([source], batch)
        _require_same_device(source, target.parent)
        _rename_without_replace(source, target)
        entry["restored_at"] = datetime.now(UTC).isoformat()
        _write_archive_manifest(batch, manifest)
    return [target for _, target, _ in plan]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video_id", nargs="*")
    parser.add_argument("--mode", choices=("book", "transcript"), default="book")
    parser.add_argument("--scratch", help="this task's disposable directory under output/_tmp/")
    parser.add_argument("--archive", action="store_true", help="explicitly use the project-local recoverable archive instead of system trash")
    parser.add_argument("--restore-archive", metavar="BATCH_ID", help="preview restoring a local archive batch; --apply performs the restore")
    parser.add_argument("--apply", action="store_true", help="perform the previewed trash, local archive or restore operation")
    args = parser.parse_args(argv)
    if args.restore_archive and (args.video_id or args.scratch or args.archive):
        parser.error("--restore-archive cannot be combined with video_id, --scratch or --archive")
    if not args.video_id and not args.scratch and not args.restore_archive:
        parser.error("provide video_id or --scratch task_name")
    try:
        if args.restore_archive:
            _, _, restore_plan = plan_archive_restore(args.restore_archive, ROOT)
            print(json.dumps({"archive_batch": args.restore_archive, "action": "restore" if args.apply else "preview-restore",
                              "paths": [str(target.relative_to(ROOT)) for _, target, _ in restore_plan]}, ensure_ascii=False))
            if args.apply:
                restored = restore_archive(args.restore_archive, ROOT)
                print(json.dumps({"archive_batch": args.restore_archive, "restored": len(restored)}, ensure_ascii=False))
            return 0
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
            action = ("archive" if args.apply else "preview-archive") if args.archive else ("recycle" if args.apply else "preview")
            print(json.dumps({"video_id": directory.name, "action": action,
                              "paths": [str(p.relative_to(ROOT)) for p in paths]}, ensure_ascii=False))
        if args.apply:
            paths = [path for _, paths in plans for path in paths]
            if args.archive:
                batch_id = archive_paths(paths, ROOT)
                print(json.dumps({"archive_batch": batch_id, "action": "archived"}, ensure_ascii=False))
            else:
                recycle_paths(paths, ROOT / "output")
            for directory in directories:
                require(status(directory, args.mode)["complete"], f"Check artifacts after cleanup: {directory.name}")
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
