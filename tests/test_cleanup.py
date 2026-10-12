"""Cleanup must preserve usable books and recovery records, and fail closed."""

import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import cleanup
import test_workflow


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_workflow.WorkflowTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.directory = self.fixture.directory
        self.root = self.fixture.root
        self.fixture.mark()

    def write(self, name, content="temporary"):
        path = self.directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def plan(self, mode="book"):
        return cleanup.plan_cleanup(self.directory, mode, self.root)

    def test_recycles_media_chunks_backups_and_unreferenced_images(self):
        garbage = [self.write(name) for name in (
            "video_source.mp4", "video_source.partial.ts", "audio.m4a",
            "images/unused.png", "_translation_chunks/part.txt", "_tmp/preview.png",
            "_asr_models/model.bin", "_capture_backups/old.png",
        )]
        originals = [self.write(name) for name in (
            "original.vtt", "original.json3", "video.info.json", "transcript.platform.json",
            "transcript.gap.asr.json", "capture.json", "acquisition.json", "publication.json",
        )]
        before = {p: p.read_bytes() for p in cleanup.retained_files(self.directory)}
        plan = self.plan()
        for path in garbage:
            self.assertTrue(any(path == item or path.is_relative_to(item) for item in plan), path)
        for path in originals:
            self.assertNotIn(path, plan)
        # A test quarantine simulates successful recycling without polluting the real bin.
        quarantine = self.root / "quarantine"
        quarantine.mkdir()
        for index, path in enumerate(plan):
            shutil.move(str(path), quarantine / str(index))
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        self.assertTrue(self.fixture.status()["complete"])
        self.assertEqual(self.plan(), [])

    def test_follows_html_markdown_css_and_static_module_dependencies(self):
        names = ("assets/style.css", "assets/theme.css", "assets/font.woff2",
                 "assets/app.js", "assets/chunk.js", "images/extra image.png", "appendix.txt")
        for name in names:
            self.write(name)
        self.write("assets/style.css", '@import "theme.css"; body{background:url(../images/extra%20image.png)}')
        self.write("assets/theme.css", '@font-face{src:url(font.woff2)}')
        self.write("assets/app.js", 'import "./chunk.js"; const template = "url(${dynamic})";')
        self.write("assets/chunk.js", "export const value = 1;")
        html = self.directory / "book.html"
        html.write_text(html.read_text(encoding="utf-8") + '<link href="assets/style.css"><script src="assets/app.js"></script><a href="appendix.txt">Appendix</a>', encoding="utf-8")
        self.fixture.mark()
        keep = cleanup.retained_files(self.directory)
        self.assertTrue(all(self.directory / name in keep for name in names))
        self.assertEqual(self.plan(), [])

    def test_refuses_stale_or_missing_dependencies_before_recycling(self):
        self.write("video_source.mp4")
        self.write("book.md", "Changed book")
        with self.assertRaisesRegex(ValueError, "finish/review"):
            self.plan()
        self.assertTrue((self.directory / "video_source.mp4").exists())

    def test_missing_asset_blocks_even_when_pipeline_does_not_check_it(self):
        html = self.directory / "book.html"
        html.write_text(html.read_text(encoding="utf-8") + '<script src="assets/missing.js"></script>', encoding="utf-8")
        self.fixture.mark()
        with self.assertRaisesRegex(ValueError, "Missing local dependency"):
            self.plan()

    def test_local_dependency_cannot_escape_the_video_directory(self):
        html = self.directory / "book.html"
        html.write_text(html.read_text(encoding="utf-8") + '<img src="../outside.png">', encoding="utf-8")
        self.fixture.mark()
        with self.assertRaisesRegex(ValueError, "outside cleanup root"):
            self.plan()

    def test_legacy_records_retained_until_a_correction_ledger_exists(self):
        legacy = self.write("_correction_review.json")
        self.assertNotIn(legacy, cleanup.retained_files(self.directory))
        (self.directory / "corrections.json").unlink()
        self.assertIn(legacy, cleanup.retained_files(self.directory))

    def test_transcript_cleanup_protects_an_unfinished_book(self):
        self.write("book.md", "Unfinished edit")
        self.assertTrue(self.fixture.status("transcript")["complete"])
        with self.assertRaisesRegex(ValueError, "existing book is unfinished"):
            self.plan("transcript")

    def test_recycler_refuses_root_outside_paths_and_nested_repositories(self):
        nested = self.directory / "scratch"
        (nested / ".git").mkdir(parents=True)
        with patch.object(cleanup.subprocess, "run") as backend:
            for path in (self.directory, self.root / "outside", nested):
                with self.assertRaises(ValueError):
                    cleanup.recycle_paths([path], self.directory)
            backend.assert_not_called()

    def test_recycler_failure_keeps_file_and_has_no_delete_fallback(self):
        path = self.write("video_source.mp4")
        with patch.object(cleanup.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "unavailable")):
            with self.assertRaises((OSError, ValueError)):
                cleanup.recycle_paths([path], self.directory)
        self.assertEqual(path.read_text(), "temporary")

    def test_cli_defaults_to_preview_and_scopes_scratch(self):
        scratch = self.root / "output" / "_tmp" / "deploy-check"
        scratch.mkdir(parents=True)
        (scratch / "preview.png").write_text("temporary")
        with patch.object(cleanup, "ROOT", self.root), patch.object(cleanup, "recycle_paths") as backend, patch("builtins.print"):
            self.assertEqual(cleanup.main(["--scratch", "deploy-check"]), 0)
            backend.assert_not_called()
            self.assertEqual(cleanup.main(["--scratch", "../other", "--apply"]), 1)
            backend.assert_not_called()
            self.assertEqual(cleanup.main(["--scratch", "deploy-check", "--apply"]), 0)
            backend.assert_called_once_with([scratch], self.root / "output")


if __name__ == "__main__":
    unittest.main()
