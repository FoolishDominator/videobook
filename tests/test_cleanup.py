"""Cleanup must preserve usable books and recovery records, and fail closed."""

import errno
import json
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
        # A newly added test must never accidentally touch the real host trash.
        trash = patch.object(cleanup, "send2trash", side_effect=AssertionError("Mock the trash backend explicitly"))
        self.trash = trash.start()
        self.addCleanup(trash.stop)

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
            for platform in ("win32", "linux"):
                with patch.object(cleanup.sys, "platform", platform):
                    for path in (self.directory, self.root / "outside", self.directory / ".." / "outside", nested):
                        with self.subTest(platform=platform, path=path), self.assertRaises(ValueError):
                            cleanup.recycle_paths([path], self.directory)
            backend.assert_not_called()
            self.trash.assert_not_called()

    def test_windows_recycler_failure_keeps_file_and_has_no_delete_fallback(self):
        path = self.write("video_source.mp4")
        with patch.object(cleanup.sys, "platform", "win32"), patch.object(
            cleanup.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "unavailable")
        ) as backend:
            with self.assertRaisesRegex(OSError, "unavailable"):
                cleanup.recycle_paths([path], self.directory)
            backend.assert_called_once()
        self.trash.assert_not_called()
        self.assertEqual(path.read_text(), "temporary")

    def test_windows_recycler_preserves_powershell_backend_and_literal_json_paths(self):
        path = self.write("_tmp/影片 ' quoted.mp4")
        with patch.object(cleanup.sys, "platform", "win32"), patch.object(
            cleanup.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")
        ) as backend:
            cleanup.recycle_paths([path], self.directory)
        backend.assert_called_once()
        args, kwargs = backend.call_args
        self.assertEqual(args[0][:6], ["powershell.exe", "-NoProfile", "-NonInteractive", "-STA", "-Command",
                                     Path(cleanup.__file__).with_name("recycle.ps1").read_text(encoding="utf-8")])
        self.assertEqual(json.loads(kwargs["input"]), {"root": str(self.directory), "paths": [str(path)]})
        self.assertTrue(kwargs["text"])
        self.assertTrue(kwargs["capture_output"])
        self.trash.assert_not_called()

    def test_linux_recycler_passes_checked_paths_to_recoverable_trash(self):
        paths = [self.write("video_source.mp4"), self.write("_tmp/preview.png").parent]
        quarantine = self.root / "quarantine"
        quarantine.mkdir()

        def move_to_test_quarantine(items):
            for index, item in enumerate(items):
                shutil.move(item, quarantine / str(index))

        self.trash.side_effect = move_to_test_quarantine
        with patch.object(cleanup.sys, "platform", "linux"), patch.object(cleanup.subprocess, "run") as windows:
            cleanup.recycle_paths(paths, self.directory)
            windows.assert_not_called()
        self.trash.assert_called_once_with([str(path.resolve()) for path in paths])
        self.assertTrue(all(not path.exists() for path in paths))
        self.assertEqual((quarantine / "0").read_text(), "temporary")
        self.assertEqual((quarantine / "1" / "preview.png").read_text(), "temporary")
        self.assertTrue(self.fixture.status()["complete"])

    def test_linux_recycler_failure_keeps_file_and_has_no_delete_fallback(self):
        path = self.write("video_source.mp4")
        self.trash.side_effect = PermissionError("trash unavailable on this filesystem")
        with patch.object(cleanup.sys, "platform", "linux"), patch.object(cleanup.subprocess, "run") as windows:
            with self.assertRaisesRegex(OSError, "no permanent-delete fallback"):
                cleanup.recycle_paths([path], self.directory)
            windows.assert_not_called()
        self.trash.assert_called_once_with([str(path)])
        self.assertEqual(path.read_text(), "temporary")

    def test_linux_partial_failure_preserves_remaining_files_without_retry(self):
        paths = [self.write("video_source.mp4"), self.write("audio.m4a")]
        quarantine = self.root / "quarantine"
        quarantine.mkdir()

        def partly_move_to_test_quarantine(items):
            shutil.move(items[0], quarantine / "video_source.mp4")
            raise PermissionError("second item could not be recycled")

        self.trash.side_effect = partly_move_to_test_quarantine
        with patch.object(cleanup.sys, "platform", "linux"), patch.object(cleanup.subprocess, "run") as windows:
            with self.assertRaisesRegex(OSError, "retain remaining files"):
                cleanup.recycle_paths(paths, self.directory)
            windows.assert_not_called()
        self.trash.assert_called_once_with([str(path) for path in paths])
        self.assertEqual((quarantine / "video_source.mp4").read_text(), "temporary")
        self.assertEqual(paths[1].read_text(), "temporary")
        self.assertTrue(self.fixture.status()["complete"])

    def test_linux_recycler_does_not_claim_success_when_backend_leaves_file(self):
        path = self.write("video_source.mp4")
        self.trash.side_effect = None
        with patch.object(cleanup.sys, "platform", "linux"), patch.object(cleanup.subprocess, "run") as windows:
            with self.assertRaisesRegex(OSError, "left files in place"):
                cleanup.recycle_paths([path], self.directory)
            windows.assert_not_called()
        self.assertEqual(path.read_text(), "temporary")

    def test_recycler_validates_entire_batch_before_backend_call(self):
        valid = self.write("video_source.mp4")
        invalid = self.root / "outside"
        for platform in ("win32", "linux"):
            with self.subTest(platform=platform), patch.object(cleanup.sys, "platform", platform), patch.object(cleanup.subprocess, "run") as windows:
                with self.assertRaisesRegex(ValueError, "outside cleanup root"):
                    cleanup.recycle_paths([valid, invalid], self.directory)
                windows.assert_not_called()
                self.trash.assert_not_called()
        self.assertEqual(valid.read_text(), "temporary")

    def test_recycler_refuses_file_directory_broken_and_nested_symlinks(self):
        target = self.write("_tmp/target.txt")
        outside = self.root / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        links = [(self.directory / "file-link", target),
                 (self.directory / "outside-link", outside),
                 (self.directory / "directory-link", target.parent),
                 (self.directory / "broken-link", self.root / "missing")]
        try:
            for link, destination in links:
                link.symlink_to(destination, target_is_directory=destination.is_dir())
            nested = self.directory / "nested"
            nested.mkdir()
            (nested / "link").symlink_to(outside)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Cannot create synthetic symlink fixtures: {exc}")
        candidates = [link for link, _ in links] + [self.directory / "directory-link" / "target.txt", nested]
        for platform in ("win32", "linux"):
            with patch.object(cleanup.sys, "platform", platform), patch.object(cleanup.subprocess, "run") as windows:
                for path in candidates:
                    with self.subTest(platform=platform, path=path), self.assertRaisesRegex(ValueError, "Linked cleanup path"):
                        cleanup.recycle_paths([path], self.directory)
                windows.assert_not_called()
                self.trash.assert_not_called()
        self.assertEqual(target.read_text(), "temporary")
        self.assertEqual(outside.read_text(), "outside")

    def test_unsupported_platform_keeps_file_and_empty_plan_is_noop(self):
        path = self.write("video_source.mp4")
        with patch.object(cleanup.sys, "platform", "darwin"), patch.object(cleanup.subprocess, "run") as windows:
            with self.assertRaisesRegex(OSError, "Unsupported cleanup platform: darwin"):
                cleanup.recycle_paths([path], self.directory)
            cleanup.recycle_paths([], self.directory)
            windows.assert_not_called()
        self.trash.assert_not_called()
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

    def test_local_archive_restores_synthetic_files_and_directories_end_to_end(self):
        paths = [self.write("video_source.mp4"), self.write("_tmp/preview.png").parent]
        before = {path.relative_to(self.directory): path.read_bytes()
                  for path in self.directory.rglob("*") if path.is_file()}
        batch_id = cleanup.archive_paths(paths, self.root)
        batch = self.root / cleanup.ARCHIVE_DIRECTORY / batch_id
        manifest = json.loads((batch / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], 1)
        self.assertTrue(manifest["created_at"].endswith("+00:00"))
        self.assertEqual([entry["original_path"] for entry in manifest["entries"]],
                         [path.relative_to(self.root).as_posix() for path in paths])
        self.assertTrue(all(entry["archived_at"] for entry in manifest["entries"]))
        self.assertTrue(all(not path.exists() for path in paths))
        self.assertTrue(self.fixture.status()["complete"])
        _, _, plan = cleanup.plan_archive_restore(batch_id, self.root)
        self.assertEqual([target for _, target, _ in plan], paths)
        self.assertTrue(all(not path.exists() for path in paths))  # Preview never restores.
        self.assertEqual(cleanup.restore_archive(batch_id, self.root), paths)
        self.assertEqual(before, {path.relative_to(self.directory): path.read_bytes()
                                 for path in self.directory.rglob("*") if path.is_file()})
        self.assertTrue(self.fixture.status()["complete"])
        self.assertEqual(cleanup.restore_archive(batch_id, self.root), [])
        manifest = json.loads((batch / "manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(all(entry["restored_at"] for entry in manifest["entries"]))
        self.assertTrue((batch / "files").is_dir())  # No automatic batch purge.
        self.trash.assert_not_called()

    def test_local_archive_rejects_roots_outside_paths_and_overlap_before_moving(self):
        path = self.write("_tmp/preview.png")
        for paths in ([self.root], [self.root / "output"], [self.root / "outside"],
                      [path, path], [path, path.parent]):
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                cleanup.archive_paths(paths, self.root)
        self.assertEqual(path.read_text(), "temporary")
        self.assertFalse((self.root / cleanup.ARCHIVE_DIRECTORY).exists())

    def test_local_archive_cross_device_error_leaves_original_and_manifest(self):
        path = self.write("video_source.mp4")
        with patch.object(cleanup, "_rename_without_replace", side_effect=OSError(errno.EXDEV, "Cross-device link")) as move:
            with self.assertRaisesRegex(OSError, "Recover moved files with --restore-archive"):
                cleanup.archive_paths([path], self.root)
            move.assert_called_once()
        self.assertEqual(path.read_text(), "temporary")
        batch = next((self.root / cleanup.ARCHIVE_DIRECTORY).iterdir())
        self.assertTrue((batch / "manifest.json").is_file())
        self.assertEqual(cleanup.restore_archive(batch.name, self.root), [])
        self.trash.assert_not_called()

    def test_local_archive_rejects_colon_in_original_path(self):
        if sys.platform == "win32":
            self.skipTest("Synthetic colon-named files are not portable to Windows")
        path = self.write("_tmp/source:stream")
        with self.assertRaisesRegex(ValueError, "Unsupported original archive path"):
            cleanup.archive_paths([path], self.root)
        self.assertEqual(path.read_text(), "temporary")
        self.assertFalse((self.root / cleanup.ARCHIVE_DIRECTORY).exists())

    def test_local_archive_partial_failure_can_restore_only_moved_entries(self):
        paths = [self.write("video_source.mp4"), self.write("audio.m4a")]
        rename = cleanup._rename_without_replace

        def fail_second(source, target):
            if source == paths[1]:
                raise OSError(errno.EXDEV, "Cross-device link")
            return rename(source, target)

        with patch.object(cleanup, "_rename_without_replace", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "Archive batch .* stopped"):
                cleanup.archive_paths(paths, self.root)
        self.assertFalse(paths[0].exists())
        self.assertEqual(paths[1].read_text(), "temporary")
        batch = next((self.root / cleanup.ARCHIVE_DIRECTORY).iterdir())
        self.assertEqual(cleanup.restore_archive(batch.name, self.root), [paths[0]])
        self.assertTrue(all(path.read_text() == "temporary" for path in paths))

    def test_restore_refuses_conflict_for_whole_batch_without_overwrite(self):
        paths = [self.write("video_source.mp4"), self.write("audio.m4a")]
        batch_id = cleanup.archive_paths(paths, self.root)
        paths[1].write_text("new content", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Restore destination already exists"):
            cleanup.restore_archive(batch_id, self.root)
        self.assertFalse(paths[0].exists())
        self.assertEqual(paths[1].read_text(), "new content")
        files = self.root / cleanup.ARCHIVE_DIRECTORY / batch_id / "files"
        self.assertEqual(len(list(files.iterdir())), 2)

    def test_restore_rejects_unsafe_manifest_paths_and_batch_ids(self):
        path = self.write("video_source.mp4")
        batch_id = cleanup.archive_paths([path], self.root)
        manifest_path = self.root / cleanup.ARCHIVE_DIRECTORY / batch_id / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        original = manifest["entries"][0]["original_path"]
        for name in ("../outside", "/tmp/outside", "output/../../outside", "output", "output//alias", "output/\\outside",
                     "output/video/book.md:stream", "output/C:/outside"):
            manifest["entries"][0]["original_path"] = name
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.subTest(name=name), self.assertRaises(ValueError):
                cleanup.restore_archive(batch_id, self.root)
        manifest["entries"][0]["original_path"] = original
        manifest["entries"][0]["archive_path"] = "../../outside"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Invalid archived data path"):
            cleanup.restore_archive(batch_id, self.root)
        for invalid_id in ("../outside", "/tmp/outside", "", ".", ".."):
            with self.subTest(batch_id=invalid_id), self.assertRaisesRegex(ValueError, "Invalid archive batch ID"):
                cleanup.restore_archive(invalid_id, self.root)
        self.assertFalse(path.exists())

    def test_archive_and_restore_reject_linked_directories(self):
        path = self.write("_tmp/preview.png")
        outside = self.root / "outside"
        outside.mkdir()
        archive = self.root / cleanup.ARCHIVE_DIRECTORY
        try:
            archive.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Cannot create synthetic symlink fixtures: {exc}")
        with self.assertRaisesRegex(ValueError, "Linked cleanup path"):
            cleanup.archive_paths([path], self.root)
        archive.unlink()  # Synthetic test link only.
        batch_id = cleanup.archive_paths([path], self.root)
        path.parent.rename(self.directory / "saved-tmp")
        path.parent.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "Linked cleanup path"):
            cleanup.restore_archive(batch_id, self.root)
        self.assertEqual(list(outside.iterdir()), [])

    def test_archive_rejects_symlink_inside_source_tree(self):
        target = self.write("video_source.mp4")
        directory = self.directory / "_tmp"
        directory.mkdir()
        try:
            (directory / "linked").symlink_to(target)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Cannot create synthetic symlink fixtures: {exc}")
        with self.assertRaisesRegex(ValueError, "Linked cleanup path"):
            cleanup.archive_paths([directory], self.root)
        self.assertEqual(target.read_text(), "temporary")
        self.assertFalse((self.root / cleanup.ARCHIVE_DIRECTORY).exists())

    def test_safe_rename_never_overwrites_late_destination_conflict(self):
        source = self.write("source.tmp", "original")
        target = self.write("target.tmp", "keep existing")
        with self.assertRaises(FileExistsError):
            cleanup._rename_without_replace(source, target)
        self.assertEqual(source.read_text(), "original")
        self.assertEqual(target.read_text(), "keep existing")

    def test_cli_local_archive_and_restore_both_require_apply(self):
        scratch = self.root / "output" / "_tmp" / "deploy-check"
        scratch.mkdir(parents=True)
        (scratch / "preview.png").write_text("temporary", encoding="utf-8")
        with patch.object(cleanup, "ROOT", self.root), patch.object(cleanup, "recycle_paths") as system_trash, patch("builtins.print"):
            self.assertEqual(cleanup.main(["--scratch", "deploy-check", "--archive"]), 0)
            self.assertTrue(scratch.exists())
            self.assertFalse((self.root / cleanup.ARCHIVE_DIRECTORY).exists())
            self.assertEqual(cleanup.main(["--scratch", "deploy-check", "--archive", "--apply"]), 0)
            self.assertFalse(scratch.exists())
            batch = next((self.root / cleanup.ARCHIVE_DIRECTORY).iterdir())
            self.assertEqual(cleanup.main(["--restore-archive", batch.name]), 0)
            self.assertFalse(scratch.exists())
            self.assertEqual(cleanup.main(["--restore-archive", batch.name, "--apply"]), 0)
            self.assertEqual((scratch / "preview.png").read_text(), "temporary")
            system_trash.assert_not_called()
        self.trash.assert_not_called()


if __name__ == "__main__":
    unittest.main()
