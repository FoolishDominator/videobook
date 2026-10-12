"""Offline integration checks for artifacts, resumption, and localhost previews."""

import base64
import hashlib
import json
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import asr_transcript
import pipeline
import post_process
from validate import STAGES, validate_stage, video_directory

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aQ1cAAAAASUVORK5CYII=")


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.directory = self.root / "output" / "BV1kybV6DE47"
        (self.directory / "images").mkdir(parents=True)
        for name in ("prompts/correct_transcript.md", "prompts/translate_transcript.md", "prompts/stitcher_system.md", "src/post_process.py"):
            path = self.root / name
            path.parent.mkdir(exist_ok=True)
            path.write_text("Fixture rules\n", encoding="utf-8")
        self.source = {
            "video_id": self.directory.name,
            "video_url": "https://www.bilibili.com/video/BV1kybV6DE47/",
            "title": "示例视频",
            "duration": 60,
            "chapters": [],
            "segments": [
                {"start": "00:00:00", "end": "00:00:30", "text": "我我来演示"},
                {"start": "00:00:30", "end": "00:01:00", "text": "这是结果"},
            ],
        }
        self.ledger = {
            "source_segments": 2,
            "review": {"full_read": True, "stutter_checked": True},
            "glossary": {},
            "changes": [{"segment": 1, "old": "我我来演示", "new": "我来演示", "reason": "删除口吃"}],
            "uncertain": [],
        }
        self.write_json("transcript.json", self.source)
        self.write_json("corrections.json", self.ledger)
        self.write("transcript.corrected.txt", "[00:00] 我来演示\n[00:30] 这是结果\n")
        self.record_translation("zh", "zh")
        self.write("book.tagged.md", "# 示例书籍\n\n## 演示\n\n![操作](SCREENSHOT:00:00:10)\n")
        self.write("book.md", "# 示例书籍\n\n## 演示\n\n![操作](images/shot_00_00_10.png)\n")
        (self.directory / "images" / "shot_00_00_10.png").write_bytes(PNG)
        with patch("builtins.print"):
            post_process.process_markdown(self.source["video_url"], str(self.directory / "book.md"))

    def write(self, name, text):
        (self.directory / name).write_text(text, encoding="utf-8")

    def write_json(self, name, value):
        self.write(name, json.dumps(value, ensure_ascii=False))

    def record_translation(self, source_language, target_language):
        self.write_json("translation.json", {
            "source_language": source_language,
            "target_language": target_language,
            "source_sha256": hashlib.sha256((self.directory / "transcript.corrected.txt").read_bytes()).hexdigest(),
            "review": {"full_read": True},
            "glossary": {},
            "uncertain": [],
        })

    def use_english_transcript(self):
        self.source["segments"][0]["text"] = "I I will demonstrate."
        self.source["segments"][1]["text"] = "This is the result."
        self.ledger["changes"] = [{
            "segment": 1, "old": "I I will demonstrate.", "new": "I will demonstrate.", "reason": "Remove stutter",
        }]
        self.write_json("transcript.json", self.source)
        self.write_json("corrections.json", self.ledger)
        self.write("transcript.corrected.txt", "[00:00] I will demonstrate.\n[00:30] This is the result.\n")
        self.record_translation("en", "zh")
        self.write("transcript.translated.txt", "[00:00] 我来演示。\n[00:30] 这是结果。\n")

    def mark(self, through="html"):
        for stage in STAGES[:STAGES.index(through) + 1]:
            pipeline.checkpoint(self.directory, stage, self.root)

    def status(self, mode="book"):
        return pipeline.status(self.directory, mode, self.root)

    def test_complete_render_and_resume(self):
        self.mark()
        state = self.status()
        self.assertTrue(state["complete"], state)
        self.assertIsNone(state["next_stage"])
        self.assertEqual(set(json.loads((self.directory / "run.json").read_text())["stages"]), set(STAGES))

    def test_existing_files_need_reviewed_checkpoints(self):
        state = self.status()
        self.assertEqual(state["next_stage"], "transcript")
        self.assertFalse((self.directory / "run.json").exists())
        with self.assertRaises(ValueError):
            pipeline.checkpoint(self.directory, "html", self.root)

    def test_transcript_only_mode_finishes_after_correction(self):
        self.use_english_transcript()
        (self.directory / "translation.json").unlink()
        (self.directory / "transcript.translated.txt").unlink()
        self.mark("corrected")
        self.assertTrue(self.status("transcript")["complete"])
        self.assertEqual(self.status()["next_stage"], "translated")

    def test_english_book_requires_reviewed_translation_before_compilation(self):
        self.use_english_transcript()
        translated = (self.directory / "transcript.translated.txt").read_text(encoding="utf-8")
        (self.directory / "transcript.translated.txt").unlink()
        self.mark("corrected")
        self.assertFalse(validate_stage(self.directory, "book")["ok"])
        with self.assertRaisesRegex(ValueError, "preceding stages"):
            pipeline.checkpoint(self.directory, "book", self.root)
        with self.assertRaises(ValueError):
            pipeline.checkpoint(self.directory, "translated", self.root)
        self.write("transcript.translated.txt", translated)
        self.mark()
        self.assertTrue(self.status()["complete"])

    def test_missing_reordered_and_untranslated_segments_are_rejected(self):
        self.use_english_transcript()
        for content in (
            "[00:00] 我来演示。\n",
            "[00:30] 这是结果。\n[00:00] 我来演示。\n",
            "[00:01] 我来演示。\n[00:30] 这是结果。\n",
            "[00:00] 我来演示。\n[00:30]   \n",
            (self.directory / "transcript.corrected.txt").read_text(encoding="utf-8"),
        ):
            with self.subTest(content=content):
                self.write("transcript.translated.txt", content)
                self.assertFalse(validate_stage(self.directory, "translated")["ok"])

    def test_updated_correction_requires_translation_to_be_reviewed_again(self):
        self.use_english_transcript()
        self.mark()
        self.ledger["changes"][0]["new"] = "I will demonstrate!"
        self.write_json("corrections.json", self.ledger)
        self.write("transcript.corrected.txt", "[00:00] I will demonstrate!\n[00:30] This is the result.\n")
        self.assertEqual(self.status()["next_stage"], "corrected")
        pipeline.checkpoint(self.directory, "corrected", self.root)
        with self.assertRaisesRegex(ValueError, "Translation source changed"):
            pipeline.checkpoint(self.directory, "translated", self.root)

    def test_translation_edits_invalidate_downstream_checkpoints(self):
        self.use_english_transcript()
        self.mark()
        self.write("transcript.translated.txt", "[00:00] 我将进行演示。\n[00:30] 这是结果。\n")
        state = self.status()
        self.assertEqual(state["next_stage"], "translated")
        self.assertTrue(all(item["status"] == "stale" for item in state["stages"][2:]))
        pipeline.checkpoint(self.directory, "translated", self.root)
        self.assertEqual(self.status()["next_stage"], "book")

    def test_translation_rules_invalidate_translation_and_downstream_stages(self):
        self.use_english_transcript()
        self.mark()
        (self.root / "prompts" / "translate_transcript.md").write_text("Changed rules", encoding="utf-8")
        state = self.status()
        self.assertEqual(state["next_stage"], "translated")
        self.assertTrue(all(item["status"] == "stale" for item in state["stages"][2:]))

    def test_matching_languages_reuse_correction_and_ignore_old_translation(self):
        for language in ("zh", "en"):
            with self.subTest(language=language):
                if language == "en":
                    self.use_english_transcript()
                self.record_translation(language, language)
                self.write("transcript.translated.txt", "Old unused translation")
                self.mark()
                self.write("transcript.translated.txt", "Changed unused translation")
                self.assertTrue(self.status()["complete"])

    def test_old_checkpoints_resume_translation_without_overwriting_books(self):
        self.mark()
        book = (self.directory / "book.html").read_bytes()
        state = json.loads((self.directory / "run.json").read_text(encoding="utf-8"))
        del state["stages"]["translated"]
        self.write_json("run.json", state)
        (self.directory / "translation.json").unlink()
        self.assertEqual(self.status()["next_stage"], "translated")
        self.assertEqual((self.directory / "book.html").read_bytes(), book)
        self.record_translation("zh", "zh")
        pipeline.checkpoint(self.directory, "translated", self.root)
        self.assertTrue(self.status()["complete"])

    def test_invalid_or_unreviewed_translation_record_is_reported(self):
        self.use_english_transcript()
        self.mark("corrected")
        record = json.loads((self.directory / "translation.json").read_text(encoding="utf-8"))
        for invalid in ([], {**record, "source_language": None}, {**record, "review": {"full_read": False}}):
            with self.subTest(record=invalid):
                self.write_json("translation.json", invalid)
                state = self.status()
                self.assertEqual(state["next_stage"], "translated")
                self.assertFalse(state["stages"][2]["ok"])

    def test_changed_prompt_invalidates_dependent_stages(self):
        self.mark()
        (self.root / "prompts" / "correct_transcript.md").write_text("Changed rules", encoding="utf-8")
        state = self.status()
        self.assertEqual(state["next_stage"], "corrected")
        self.assertTrue(all(item["status"] == "stale" for item in state["stages"][1:]))

    def test_changed_source_cannot_reuse_correction_ledger(self):
        self.mark()
        self.source["segments"][0]["text"] = "新版原始字幕"
        self.write_json("transcript.json", self.source)
        self.assertEqual(self.status()["next_stage"], "transcript")
        pipeline.checkpoint(self.directory, "transcript", self.root)
        with self.assertRaisesRegex(ValueError, "Source changed"):
            pipeline.checkpoint(self.directory, "corrected", self.root)

    def test_missing_or_unrecorded_correction_is_rejected(self):
        for content in ("[00:00] 我来演示\n", "[00:00] 完全改写\n[00:30] 这是结果\n"):
            with self.subTest(content=content):
                self.write("transcript.corrected.txt", content)
                self.assertFalse(validate_stage(self.directory, "corrected")["ok"])

    def test_duplicate_decisions_and_unfinished_review_are_rejected(self):
        self.ledger["changes"].append(self.ledger["changes"][0].copy())
        self.write_json("corrections.json", self.ledger)
        self.assertFalse(validate_stage(self.directory, "corrected")["ok"])
        self.ledger["changes"].pop()
        self.ledger["review"]["stutter_checked"] = False
        self.write_json("corrections.json", self.ledger)
        self.assertFalse(validate_stage(self.directory, "corrected")["ok"])

    def test_invalid_transcript_and_screenshot_timestamps_are_rejected(self):
        self.source["segments"][1]["end"] = "00:99:00"
        self.write_json("transcript.json", self.source)
        self.assertFalse(validate_stage(self.directory, "transcript")["ok"])
        self.source["segments"][1]["end"] = "00:01:00"
        self.write_json("transcript.json", self.source)
        self.write("book.tagged.md", "# Book\n\n## Chapter\n\n![Frame](SCREENSHOT:00:01:30)\n")
        self.assertFalse(validate_stage(self.directory, "book")["ok"])

    def test_missing_image_invalidates_images_and_html(self):
        self.mark()
        (self.directory / "images" / "shot_00_00_10.png").unlink()
        state = self.status()
        self.assertEqual(state["next_stage"], "images")
        self.assertFalse(state["stages"][-1]["ok"])

    def test_tagged_and_materialized_books_must_agree(self):
        self.write("book.md", "# Book\n\n## Changed chapter\n")
        self.assertFalse(validate_stage(self.directory, "images")["ok"])

    def test_html_must_include_images(self):
        self.write("book.html", "<html><body>No images</body></html>")
        self.assertFalse(validate_stage(self.directory, "html")["ok"])

    def test_unknown_or_traversing_video_ids_are_rejected(self):
        for video_id in ("../escape", "Unknown_ID", "C:\\escape"):
            with self.subTest(video_id=video_id), self.assertRaises(ValueError):
                video_directory(video_id, self.root)

    def test_two_previews_get_distinct_ports_and_serve_rendered_html(self):
        servers = [pipeline.preview_server(self.directory) for _ in range(2)]
        try:
            self.assertNotEqual(servers[0].server_port, servers[1].server_port)
            for server in servers:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for server in servers:
                with opener.open(f"http://127.0.0.1:{server.server_port}/book.html", timeout=3) as response:
                    self.assertIn("示例书籍", response.read().decode("utf-8"))
        finally:
            for server in servers:
                server.shutdown()
                server.server_close()

    def test_asr_failure_removes_temporary_cookies_and_partial_metadata(self):
        for operation in (asr_transcript.ensure_audio, asr_transcript.fetch_meta):
            with self.subTest(operation=operation.__name__):
                cookie = self.root / "temporary-cookies.txt"
                cookie.write_text("test fixture", encoding="utf-8")
                with patch.object(asr_transcript, "ensure_cookies", return_value=str(cookie)), patch.object(
                    asr_transcript.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "fixture")
                ), self.assertRaises(subprocess.CalledProcessError):
                    operation(str(self.directory), self.source["video_url"])
                self.assertFalse(cookie.exists())
                self.assertFalse((self.directory / "_info.json").exists())
                self.assertFalse((self.directory / "_info.json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
