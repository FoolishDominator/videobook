"""Checkpoint and preview helpers for the agent-driven VideoBook workflow."""

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from validate import STAGES, image_paths, read_json, read_text, require, validate_stage, video_directory

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = {
    "transcript": ("transcript.json",),
    "corrected": ("transcript.corrected.txt", "corrections.json"),
    "translated": ("translation.json",),
    "book": ("book.tagged.md",),
    "images": ("book.md",),
    "html": ("book.html",),
}
RULES = {
    "corrected": ("prompts/correct_transcript.md",),
    "translated": ("prompts/translate_transcript.md",),
    "book": ("prompts/stitcher_system.md",),
    "html": ("src/post_process.py",),
}


def fingerprint(directory, stage, upstream, root):
    paths = [directory / name for name in OUTPUTS[stage]]
    paths.extend(root / name for name in RULES.get(stage, ()))
    if stage == "translated" and (directory / "translation.json").is_file():
        record = read_json(directory / "translation.json")
        if record.get("source_language", "").lower() != record.get("target_language", "").lower():
            paths.append(directory / "transcript.translated.txt")
    if stage == "images" and (directory / "book.md").is_file():
        paths.extend(image_paths(directory, read_text(directory / "book.md")))
    digest = hashlib.sha256(upstream.encode("ascii"))
    for path in sorted(set(paths)):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        if path.is_file():
            with path.open("rb") as handle:
                digest.update(hashlib.file_digest(handle, "sha256").digest())
        else:
            digest.update(b"MISSING")
    return digest.hexdigest()


def load_state(directory):
    path = directory / "run.json"
    if not path.exists():
        return {"schema_version": 1, "video_id": directory.name, "stages": {}}
    state = read_json(path)
    require(state.get("schema_version") == 1 and state.get("video_id") == directory.name, "Unrecognized run.json; inspect it before resuming")
    require(isinstance(state.get("stages"), dict), "Invalid stages in run.json")
    return state


def status(directory, mode="book", root=ROOT):
    state = load_state(directory)
    stages = STAGES[:2] if mode == "transcript" else STAGES
    results = []
    upstream, previous_complete = "", True
    for stage in stages:
        check = validate_stage(directory, stage)
        try:
            signature = fingerprint(directory, stage, upstream, root)
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            signature = "invalid"
            check["ok"] = False
            check["errors"].append(str(exc))
        recorded = state["stages"].get(stage)
        complete = bool(previous_complete and check["ok"] and recorded and recorded.get("fingerprint") == signature)
        results.append({**check, "status": "complete" if complete else "stale" if recorded else "pending", "fingerprint": signature})
        upstream, previous_complete = signature, complete
    next_stage = next((item["stage"] for item in results if item["status"] != "complete"), None)
    return {"video_id": directory.name, "mode": mode, "next_stage": next_stage, "complete": next_stage is None, "stages": results}


def checkpoint(directory, stage, root=ROOT):
    result = status(directory, root=root)
    index = STAGES.index(stage)
    require(all(item["status"] == "complete" for item in result["stages"][:index]), "Validate and checkpoint preceding stages first")
    check = result["stages"][index]
    require(check["ok"], "; ".join(check["errors"]))
    state = load_state(directory)
    state["video_url"] = read_json(directory / "transcript.json")["video_url"]
    state["stages"][stage] = {"fingerprint": check["fingerprint"], "completed_at": datetime.now(timezone.utc).isoformat()}
    # Atomic replacement keeps an interrupted write from truncating run.json.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(state, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, directory / "run.json")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"stage": stage, "status": "complete", "warnings": check["warnings"]}


def preview_server(directory, port=0):
    require((directory / "book.html").is_file(), "Render book.html before starting a preview")
    handler = partial(SimpleHTTPRequestHandler, directory=str(directory))
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("status", help="inspect checkpoints without writing or downloading")
    inspect.add_argument("video_id")
    inspect.add_argument("--mode", choices=("book", "transcript"), default="book")
    mark = commands.add_parser("checkpoint", help="validate and record a completed agent stage")
    mark.add_argument("video_id")
    mark.add_argument("stage", choices=STAGES)
    serve = commands.add_parser("serve", help="serve a video directory on localhost")
    serve.add_argument("video_id")
    serve.add_argument("--port", type=int, default=0, help="0 selects an available port")
    args = parser.parse_args(argv)
    try:
        directory = video_directory(args.video_id)
        if args.command == "status":
            result = status(directory, args.mode)
        elif args.command == "checkpoint":
            result = checkpoint(directory, args.stage)
        else:
            with preview_server(directory, args.port) as server:
                print(json.dumps({"url": f"http://127.0.0.1:{server.server_port}/book.html"}), flush=True)
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    pass
            return 0
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
