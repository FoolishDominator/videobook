"""Publication integration checks using isolated source and personal-site repositories."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import publish
from site_index import build_index_html


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.site = self.root / "site"
        for repo in (self.source, self.site):
            repo.mkdir()
            self.git(repo, "init", "-b", "main")
            self.git(repo, "config", "user.name", "Publication test")
            self.git(repo, "config", "user.email", "test@example.invalid")
            self.git(repo, "config", "core.autocrlf", "false")
        self.write(self.source, "README.md", "Generator source\n")
        self.commit(self.source)
        self.write(self.site, "index.html", "Personal homepage\n")
        self.write(self.site, "assets/site.css", "body { color: #25272b; }\n")
        self.write(self.site, "lessons/older/book.html", "Existing notes\n")
        self.write(self.site, "lessons/manifest.json", json.dumps({
            "older": {"folder": "older", "title": "Older notes", "updated": "2026-01-01"},
        }))
        self.commit(self.site)
        self.video = self.source / "output" / "test-video"
        self.write(self.video, "transcript.json", json.dumps({"title": "Course & notes"}))
        self.write(self.video, "book.html", "<h1>Course notes</h1>\n")
        self.write(self.video, "book.md", "# Course notes\n")
        self.write(self.video, "transcript.corrected.txt", "Reviewed transcript\n")
        self.write(self.video, "images/frame.png", "image fixture")
        self.write(self.video, "run.json", "private checkpoint")

    def git(self, repo, *args):
        return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                              text=True, encoding="utf-8", check=True).stdout.strip()

    def write(self, root, name, content):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")

    def commit(self, repo):
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-m", "Fixture")

    def prepare(self):
        with patch.object(publish, "BASE", str(self.source)), patch.object(sys, "argv", [
            "publish.py", "test-video", "--site-repo", str(self.site),
        ]), patch("builtins.print"):
            publish.main()

    def test_publication_preserves_site_and_existing_notes_without_touching_checkout(self):
        original = self.git(self.site, "rev-parse", "HEAD")
        self.write(self.site, "draft.txt", "Uncommitted work\n")
        self.prepare()
        ref = "codex/publish-lessons"
        self.assertEqual(self.git(self.site, "rev-parse", "HEAD"), original)
        self.assertEqual(self.git(self.site, "status", "--porcelain"), "?? draft.txt")
        self.assertEqual(self.git(self.site, "show", f"{ref}:index.html"), "Personal homepage")
        self.assertEqual(self.git(self.site, "show", f"{ref}:lessons/older/book.html"), "Existing notes")
        files = self.git(self.site, "ls-tree", "-r", "--name-only", ref).splitlines()
        self.assertIn("lessons/Course & notes/book.html", files)
        self.assertIn("lessons/Course & notes/transcript.corrected.txt", files)
        self.assertNotIn("lessons/Course & notes/run.json", files)
        self.assertNotIn("draft.txt", files)
        page = self.git(self.site, "show", f"{ref}:lessons/index.html")
        self.assertIn('href="Course%20%26%20notes/book.html"', page)
        self.assertIn("Course &amp; notes", page)

    def test_repeat_after_merge_is_idempotent(self):
        self.prepare()
        self.git(self.site, "merge", "--ff-only", "codex/publish-lessons")
        tip = self.git(self.site, "rev-parse", "codex/publish-lessons")
        self.prepare()
        self.assertEqual(self.git(self.site, "rev-parse", "codex/publish-lessons"), tip)
        self.assertEqual(self.git(self.site, "status", "--porcelain"), "")

    def test_pending_publication_is_not_overwritten(self):
        self.prepare()
        tip = self.git(self.site, "rev-parse", "codex/publish-lessons")
        with self.assertRaises(SystemExit):
            self.prepare()
        self.assertEqual(self.git(self.site, "rev-parse", "codex/publish-lessons"), tip)

    def test_title_changes_remove_only_the_previous_note_folder(self):
        self.prepare()
        self.git(self.site, "merge", "--ff-only", "codex/publish-lessons")
        self.write(self.video, "transcript.json", json.dumps({"title": "Renamed notes"}))
        self.prepare()
        files = self.git(self.site, "ls-tree", "-r", "--name-only", "codex/publish-lessons")
        self.assertNotIn("Course & notes/", files)
        self.assertIn("lessons/Renamed notes/book.html", files)
        self.assertIn("lessons/older/book.html", files)

    def test_publication_paths_stay_inside_content_root(self):
        with self.assertRaises(ValueError):
            publish.content_path(str(self.site), "../outside")
        with self.assertRaises(ValueError):
            publish.content_path(str(self.site), ".")

    def test_listing_escapes_titles_and_preserves_readable_links(self):
        page = build_index_html({"id": {
            "folder": "course #1", "title": '<script>alert("x")</script>',
        }})
        self.assertNotIn("<script>", page)
        self.assertIn('href="course%20%231/book.html"', page)
        self.assertIn("&lt;script&gt;", page)


if __name__ == "__main__":
    unittest.main()
