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
from site_index import PublicationSite, build_course_pages, build_index_html


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
        self.write(self.video, "book.html", '<h1>Course notes</h1><img src="images/frame.png">\n')
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

    def prepare(self, *extra_args):
        with patch.object(publish, "BASE", str(self.source)), patch.object(sys, "argv", [
            "publish.py", "test-video", "--site-repo", str(self.site),
            "--public-base-url", "https://example.invalid/", "--content-dir", "lessons", *extra_args,
        ]), patch("builtins.print"):
            publish.main()

    def migrate(self, *extra_args):
        with patch.object(publish, "BASE", str(self.source)), patch.object(sys, "argv", [
            "publish.py", "--migrate-layout", "--site-repo", str(self.site),
            "--public-base-url", "https://example.invalid/", "--content-dir", "lessons", *extra_args,
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
        self.assertIn("lessons/notes/test-video/book.html", files)
        self.assertIn("lessons/notes/test-video/transcript.corrected.txt", files)
        self.assertNotIn("lessons/notes/test-video/run.json", files)
        self.assertNotIn("draft.txt", files)
        page = self.git(self.site, "show", f"{ref}:lessons/index.html")
        self.assertIn('href="/lessons/notes/test-video/book.html"', page)
        self.assertIn("Course &amp; notes", page)

    def test_repeat_after_merge_is_idempotent(self):
        self.prepare()
        self.git(self.site, "merge", "--ff-only", "codex/publish-lessons")
        tip = self.git(self.site, "rev-parse", "codex/publish-lessons")
        self.prepare()
        self.assertEqual(self.git(self.site, "rev-parse", "codex/publish-lessons"), tip)
        self.assertEqual(self.git(self.site, "status", "--porcelain"), "")

    def test_cli_requires_explicit_public_url_and_content_directory(self):
        for flags in ([], ["--public-base-url", "https://example.invalid/"],
                      ["--content-dir", "lessons"]):
            with self.subTest(flags=flags), patch.object(sys, "argv", [
                "publish.py", "test-video", "--site-repo", str(self.site), *flags,
            ]), patch("sys.stderr"), self.assertRaises(SystemExit) as error:
                publish.main()
            self.assertEqual(error.exception.code, 2)
        self.assertIsNone(publish.branch_tip("codex/publish-lessons", str(self.site)))

    def test_unsafe_destination_configuration_is_rejected(self):
        for url in ("file:///tmp/site", "//example.invalid/", "https://user:secret@example.invalid/",
                    "https://example.invalid/?a=b", "https://example.invalid/#notes",
                    "https://example.invalid/?", "https://example.invalid/#",
                    "https://example.invalid/a/../b", "https://example.invalid/%2e%2e/b",
                    "https://example.invalid/a\\b", "https://example.invalid/a//b", "https://"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                PublicationSite(url, "lessons")
        for folder in ("", ".", "..", "/lessons", "../lessons", "a/../b", "a//b", "C:/notes", "a\\b", ".git"):
            with self.subTest(folder=folder), self.assertRaises(ValueError):
                PublicationSite("https://example.invalid/", folder)

    def test_project_pages_prefix_and_custom_directory_cover_links_and_shared_assets(self):
        self.write(self.video, "book.html", '<html><head><title>Notes</title></head><body>'
                   '<article class="book-content"><p>Original summary</p>'
                   '<script src="assets/mermaid.min.js"></script></article></body></html>')
        self.write(self.video, "assets/mermaid.min.js", "/* Mermaid fixture */")
        self.prepare("--public-base-url", "https://example.invalid/project/", "--content-dir", "study/notes",
                     "--course", "Finance")
        ref = "codex/publish-lessons"
        files = self.git(self.site, "ls-tree", "-r", "--name-only", ref).splitlines()
        asset = next(name for name in files if name.startswith("assets/vendor/mermaid-"))
        note = self.git(self.site, "show", f"{ref}:study/notes/courses/finance/test-video/book.html")
        self.assertIn('href="https://example.invalid/project/study/notes/courses/finance/test-video/book.html"', note)
        self.assertIn('href="/project/study/notes/"', note)
        self.assertIn('href="/project/study/notes/courses/finance/"', note)
        self.assertIn(f'src="/project/{asset}"', note)
        index = self.git(self.site, "show", f"{ref}:study/notes/index.html")
        self.assertIn('href="/project/assets/site.css"', index)
        self.assertIn('href="/project/"', index)
        course = self.git(self.site, "show", f"{ref}:study/notes/courses/finance/index.html")
        self.assertIn('href="/project/study/notes/courses/finance/test-video/book.md"', course)
        self.assertIn('href="/project/study/notes/courses/finance/test-video/transcript.corrected.txt"', course)
        self.assertNotIn("foolishdominator", index.lower() + note.lower() + course.lower())
        self.assertEqual(self.git(self.site, "show", f"{ref}:index.html"), "Personal homepage")
        self.assertEqual(self.git(self.site, "show", f"{ref}:assets/site.css"), "body { color: #25272b; }")
        self.assertEqual(self.git(self.site, "show", f"{ref}:lessons/older/book.html"), "Existing notes")
        self.git(self.site, "merge", "--ff-only", ref)
        original = self.git(self.site, "rev-parse", ref)
        self.migrate("--public-base-url", "https://example.invalid/project/", "--content-dir", "study/notes")
        self.assertEqual(self.git(self.site, "rev-parse", ref), original)

    def test_existing_unowned_landing_page_is_not_overwritten(self):
        self.write(self.site, "study/index.html", "Existing custom landing page")
        self.commit(self.site)
        with self.assertRaisesRegex(RuntimeError, "停止覆盖"):
            self.prepare("--content-dir", "study")
        self.assertIsNone(publish.branch_tip("codex/publish-lessons", str(self.site)))
        self.assertEqual(self.git(self.site, "show", "HEAD:study/index.html"), "Existing custom landing page")

    def test_missing_existing_stylesheet_aborts_instead_of_restyling_the_site(self):
        (self.site / "assets/site.css").unlink()
        self.commit(self.site)
        with self.assertRaisesRegex(RuntimeError, "现有站点样式"):
            self.prepare()
        self.assertIsNone(publish.branch_tip("codex/publish-lessons", str(self.site)))

    def test_explicit_site_branch_is_used_without_touching_main(self):
        main = self.git(self.site, "rev-parse", "main")
        self.git(self.site, "checkout", "-b", "gh-pages")
        self.write(self.site, "index.html", "Published branch homepage")
        self.commit(self.site)
        deployed = self.git(self.site, "rev-parse", "HEAD")
        self.git(self.site, "checkout", "main")
        self.prepare("--site-branch", "gh-pages")
        ref = "codex/publish-lessons"
        self.assertEqual(self.git(self.site, "rev-parse", ref + "^"), deployed)
        self.assertEqual(self.git(self.site, "rev-parse", "main"), main)
        self.assertEqual(self.git(self.site, "show", f"{ref}:index.html"), "Published branch homepage")

    def test_invalid_or_publisher_source_branch_is_rejected(self):
        for branch in ("../main", "main:notes", "codex/publish-lessons", "HEAD"):
            with self.subTest(branch=branch), patch("sys.stderr"), self.assertRaises(SystemExit):
                self.prepare("--site-branch", branch)
        self.assertIsNone(publish.branch_tip("codex/publish-lessons", str(self.site)))

    def test_exclude_transcripts_removes_attachments_and_generated_download_links(self):
        self.write(self.video, "transcript.translated.txt", "Translation fixture")
        self.write(self.video, "assets/transcript.copy.pdf", "Transcript attachment fixture")
        self.write(self.video, "assets/captions.vtt", "Subtitle fixture")
        self.prepare("--exclude-transcripts", "--course", "Finance")
        ref = "codex/publish-lessons"
        files = self.git(self.site, "ls-tree", "-r", "--name-only", ref).splitlines()
        self.assertFalse(any("transcript" in name or "captions" in name for name in files))
        manifest = json.loads(self.git(self.site, "show", f"{ref}:lessons/manifest.json"))
        self.assertFalse(manifest["test-video"]["corrected"])
        course = self.git(self.site, "show", f"{ref}:lessons/courses/finance/index.html")
        self.assertNotIn("字幕对照", course)
        self.assertNotIn("transcript", course)
        self.assertIn("book.md", course)
        self.assertTrue((self.video / "transcript.corrected.txt").is_file())

    def test_exclude_transcripts_fails_closed_on_remaining_html_and_markdown_links(self):
        for name, content in (
            ("book.html", '<a href="transcript.corrected.txt">Transcript</a>'),
            ("book.html", '<a href=transcript.corrected.txt?download=1>Transcript</a>'),
            ("book.html", '<a href="transcript%2Etranslated%2Etxt">Translation</a>'),
            ("book.html", '<a href="assets/captions.vtt">Captions</a>'),
            ("book.html", '<img srcset="assets/captions.vtt 1x">'),
            ("book.md", '[Transcript](transcript.corrected.txt "Download")'),
            ("book.md", '[Download](<assets/full text.txt>)'),
            ("book.md", '[download]: transcript.corrected.txt\n[Transcript][download]'),
            ("book.md", '<a href="transcript.corrected.txt">Transcript</a>'),
        ):
            with self.subTest(name=name, content=content):
                old = (self.video / name).read_text(encoding="utf-8")
                self.write(self.video, name, content)
                with self.assertRaisesRegex(ValueError, "仍引用"):
                    self.prepare("--exclude-transcripts")
                self.assertIsNone(publish.branch_tip("codex/publish-lessons", str(self.site)))
                self.write(self.video, name, old)

    def test_exclude_transcripts_republication_removes_old_downloads(self):
        self.prepare()
        ref = "codex/publish-lessons"
        self.git(self.site, "merge", "--ff-only", ref)
        self.prepare("--exclude-transcripts")
        files = self.git(self.site, "ls-tree", "-r", "--name-only", ref).splitlines()
        self.assertNotIn("lessons/notes/test-video/transcript.corrected.txt", files)
        self.assertNotIn("字幕对照", self.git(self.site, "show", f"{ref}:lessons/index.html"))
        self.git(self.site, "merge", "--ff-only", ref)
        original = self.git(self.site, "rev-parse", ref)
        self.prepare("--exclude-transcripts")
        self.assertEqual(self.git(self.site, "rev-parse", ref), original)

    def test_exclude_transcripts_also_applies_to_migration(self):
        self.prepare()
        ref = "codex/publish-lessons"
        self.git(self.site, "merge", "--ff-only", ref)
        self.write(self.site, "lessons/notes/test-video/transcript.translated.txt", "Published translation")
        self.commit(self.site)
        self.migrate("--exclude-transcripts")
        files = self.git(self.site, "ls-tree", "-r", "--name-only", ref).splitlines()
        self.assertFalse(any("transcript" in name for name in files))

    def test_pending_publication_is_not_overwritten(self):
        self.prepare()
        tip = self.git(self.site, "rev-parse", "codex/publish-lessons")
        with self.assertRaises(SystemExit):
            self.prepare()
        self.assertEqual(self.git(self.site, "rev-parse", "codex/publish-lessons"), tip)

    def test_title_changes_preserve_published_urls(self):
        self.prepare()
        self.git(self.site, "merge", "--ff-only", "codex/publish-lessons")
        self.write(self.video, "transcript.json", json.dumps({"title": "Renamed notes"}))
        self.prepare()
        files = self.git(self.site, "ls-tree", "-r", "--name-only", "codex/publish-lessons")
        self.assertNotIn("Renamed notes/", files)
        self.assertIn("lessons/notes/test-video/book.html", files)
        self.assertIn("lessons/older/book.html", files)
        manifest = json.loads(self.git(self.site, "show", "codex/publish-lessons:lessons/manifest.json"))
        self.assertEqual(manifest["test-video"]["title"], "Renamed notes")

    def test_course_membership_survives_unchanged_and_updated_publications(self):
        course = "MIT 15.401 Finance Theory"
        self.prepare("--course", course)
        ref = "codex/publish-lessons"
        self.git(self.site, "merge", "--ff-only", ref)
        original = self.git(self.site, "rev-parse", ref)
        self.prepare()
        self.assertEqual(self.git(self.site, "rev-parse", ref), original)

        self.write(self.video, "book.html", "<h1>Updated course notes</h1>\n")
        self.prepare()
        manifest = json.loads(self.git(self.site, "show", f"{ref}:lessons/manifest.json"))
        self.assertEqual(manifest["test-video"]["course"], course)
        page = self.git(self.site, "show", f"{ref}:lessons/index.html")
        self.assertIn('href="/lessons/courses/mit-15-401-finance-theory/"', page)
        self.assertNotIn("Course &amp; notes", page)
        self.assertIn("Older notes", page)
        course_page = self.git(self.site, "show", f"{ref}:lessons/courses/mit-15-401-finance-theory/index.html")
        self.assertIn('href="/lessons/courses/mit-15-401-finance-theory/test-video/book.html"', course_page)
        self.assertIn('href="/lessons/courses/mit-15-401-finance-theory/test-video/book.md" download', course_page)
        self.assertIn('href="/lessons/courses/mit-15-401-finance-theory/test-video/transcript.corrected.txt"', course_page)
        self.assertEqual(self.git(self.site, "show", f"{ref}:lessons/older/book.html"), "Existing notes")

    def test_moving_a_note_removes_the_old_directory_and_empty_course(self):
        self.prepare("--course", "Original course")
        ref = "codex/publish-lessons"
        self.git(self.site, "merge", "--ff-only", ref)
        self.prepare("--course", "New course")
        files = self.git(self.site, "ls-tree", "-r", "--name-only", ref).splitlines()
        self.assertFalse(any(name.startswith("lessons/courses/original-course/") for name in files))
        self.assertIn("lessons/courses/new-course/index.html", files)
        self.assertIn("lessons/courses/new-course/test-video/book.html", files)
        note = "lessons/courses/new-course/test-video"
        self.assertEqual(self.git(self.site, "show", f"{ref}:{note}/transcript.corrected.txt"), "Reviewed transcript")
        self.assertEqual(self.git(self.site, "show", f"{ref}:{note}/images/frame.png"), "image fixture")
        self.git(self.site, "merge", "--ff-only", ref)
        self.write(self.video, "book.html", "<h1>Updated notes without the old illustration</h1>\n")
        self.prepare()
        files = self.git(self.site, "ls-tree", "-r", "--name-only", ref).splitlines()
        self.assertFalse(any(name.startswith("lessons/courses/original-course/") for name in files))
        self.assertNotIn("lessons/courses/new-course/test-video/images/frame.png", files)

    def test_course_pages_sort_sessions_numerically_and_escape_titles(self):
        course = "MIT 15.401 Finance Theory"
        manifest = {str(number): {
            "folder": f"Ses {number}", "title": f"Ses {number}: Notes & examples",
            "course": course, "corrected": True,
        } for number in (10, 2, 1)}
        page = build_course_pages(manifest)["mit-15-401-finance-theory"]
        self.assertLess(page.index("Ses 1:"), page.index("Ses 2:"))
        self.assertLess(page.index("Ses 2:"), page.index("Ses 10:"))
        self.assertIn("Notes &amp; examples", page)
        self.assertIn('href="/lessons/Ses%201/book.html"', page)
        self.assertIn("3 节课", build_index_html(manifest))

    def test_moving_one_note_preserves_the_other_notes_in_its_previous_course(self):
        self.prepare("--course", "Original course")
        ref = "codex/publish-lessons"
        self.git(self.site, "merge", "--ff-only", ref)
        manifest = json.loads((self.site / "lessons/manifest.json").read_text(encoding="utf-8"))
        manifest["other"] = {
            "folder": "courses/original-course/other", "title": "Other course notes",
            "course": "Original course", "course_slug": "original-course",
        }
        self.write(self.site, "lessons/manifest.json", json.dumps(manifest))
        self.write(self.site, "lessons/courses/original-course/other/book.html", "Other notes")
        self.commit(self.site)
        self.prepare("--course", "New course")
        original_course = self.git(self.site, "show", f"{ref}:lessons/courses/original-course/index.html")
        self.assertIn("Other course notes", original_course)
        self.assertNotIn("test-video/", original_course)
        self.assertEqual(self.git(self.site, "show", f"{ref}:lessons/courses/original-course/other/book.html"), "Other notes")

    def test_migration_rejects_a_destination_nested_inside_the_old_note(self):
        self.write(self.site, "lessons/manifest.json", json.dumps({
            "nested": {"folder": "courses/finance", "title": "Ses 1", "course": "Finance"},
        }))
        self.write(self.site, "lessons/courses/finance/book.html", "Published notes")
        self.commit(self.site)
        with self.assertRaises(ValueError):
            self.migrate()
        self.assertIsNone(publish.branch_tip("codex/publish-lessons", str(self.site)))
        self.assertEqual(self.git(self.site, "show", "HEAD:lessons/courses/finance/book.html"), "Published notes")

    def test_conflicting_course_paths_are_rejected(self):
        manifest = {
            "first": {"folder": "first", "course": "Course A"},
            "second": {"folder": "second", "course": "Course-A"},
        }
        with self.assertRaises(ValueError):
            build_course_pages(manifest)

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
        self.assertIn('href="/lessons/course%20%231/book.html"', page)
        self.assertIn("&lt;script&gt;", page)

    def test_migration_reuses_published_content_cleans_unused_files_and_is_idempotent(self):
        manifest = json.loads((self.site / "lessons/manifest.json").read_text(encoding="utf-8"))
        for number in (1, 2):
            folder = f"Ses {number} Old title"
            manifest[f"legacy-{number}"] = {
                "folder": folder, "title": f"Ses {number}: Original title",
                "course": "MIT 15.401 Finance Theory", "updated": "2026-01-01", "corrected": True,
            }
            note = self.site / "lessons" / folder
            self.write(note, "book.html", '<html><head><title>Notes</title>\n</head>\n<body>\n'
                       '<h1>Published notes</h1><img src="images/keep.png">'
                       '<script src="assets/mermaid.min.js"></script></body></html>\n')
            self.write(note, "book.md", "# Published notes\n![Keep](images/keep.png)\n")
            self.write(note, "transcript.corrected.txt", "Published transcript")
            self.write(note, "images/keep.png", "published image")
            self.write(note, "images/unused.png", "obsolete image")
            self.write(note, "assets/mermaid.min.js", "/* same Mermaid library */")
            self.write(self.source / "output" / f"legacy-{number}", "book.html", "Unpublished changes")
        self.write(self.site, "lessons/manifest.json", json.dumps(manifest))
        self.commit(self.site)
        original = self.git(self.site, "rev-parse", "HEAD")
        self.migrate()
        ref = "codex/publish-lessons"
        self.assertEqual(self.git(self.site, "rev-parse", "HEAD"), original)
        self.assertEqual(self.git(self.site, "status", "--porcelain"), "")
        files = self.git(self.site, "ls-tree", "-r", "--name-only", ref).splitlines()
        shared_assets = [name for name in files if name.startswith("assets/vendor/mermaid-")]
        self.assertEqual(len(shared_assets), 1)
        self.assertFalse(any(name.endswith("unused.png") or name.endswith("assets/mermaid.min.js") for name in files))
        migrated = json.loads(self.git(self.site, "show", f"{ref}:lessons/manifest.json"))
        for number in (1, 2):
            meta = migrated[f"legacy-{number}"]
            self.assertEqual(meta["folder"], f"courses/mit-15-401-finance-theory/ses-{number:02d}")
            self.assertEqual(meta["course_slug"], "mit-15-401-finance-theory")
            self.assertEqual(meta["updated"], "2026-01-01")
            self.assertNotIn("aliases", meta)
            self.assertTrue(meta["markdown"])
            html = self.git(self.site, "show", f"{ref}:lessons/{meta['folder']}/book.html")
            self.assertIn("Published notes", html)
            self.assertNotIn("Unpublished changes", html)
            self.assertEqual(html.count('rel="canonical"'), 1)
            self.assertEqual(html.count('aria-label="课程导航"'), 1)
            self.assertIn(f'src="/{shared_assets[0]}"', html)
            self.assertFalse(any(name.startswith(f"lessons/Ses {number} Old title/") for name in files))
        self.git(self.site, "merge", "--ff-only", ref)
        first = self.git(self.site, "rev-parse", ref)
        self.migrate()
        self.assertEqual(self.git(self.site, "rev-parse", ref), first)

    def test_course_publication_preserves_paths_on_title_edits_and_shares_assets(self):
        self.git(self.site, "config", "core.autocrlf", "true")
        self.write(self.video, "transcript.json", json.dumps({"title": "Ses 1: Initial title"}))
        self.write(self.video, "book.html", '<html><head><title>Notes</title>\n</head><body>\n'
                   '<article class="book-content"><script src="assets/mermaid.min.js"></script>'
                   '<p>Notes</p></article></body></html>\n')
        self.write(self.video, "assets/mermaid.min.js", "/* Mermaid */")
        self.prepare("--course", "Finance")
        ref = "codex/publish-lessons"
        html = self.git(self.site, "show", f"{ref}:lessons/courses/finance/ses-01/book.html")
        self.assertLess(html.index('<article class="book-content">'), html.index('aria-label="课程导航"'))
        self.git(self.site, "merge", "--ff-only", ref)
        original = self.git(self.site, "rev-parse", ref)
        self.prepare()
        self.assertEqual(self.git(self.site, "rev-parse", ref), original)
        self.write(self.video, "transcript.json", json.dumps({"title": "Introduction, renamed"}))
        self.prepare()
        manifest = json.loads(self.git(self.site, "show", f"{ref}:lessons/manifest.json"))
        self.assertEqual(manifest["test-video"]["folder"], "courses/finance/ses-01")
        self.assertEqual(manifest["test-video"]["title"], "Introduction, renamed")
        manifest["second"] = {"folder": "courses/finance/ses-02", "title": "Ses 2: Valuation", "course": "Finance"}
        page = build_course_pages(manifest)["finance"]
        self.assertLess(page.index("Introduction, renamed"), page.index("Ses 2: Valuation"))

    def test_conflicting_or_nested_note_paths_abort_before_publication(self):
        self.write(self.site, "lessons/manifest.json", json.dumps({
            "older": {"folder": "older", "title": "Ses 1", "course": "Finance"},
            "other": {"folder": "other", "title": "Ses 1", "course": "Finance"},
        }))
        self.commit(self.site)
        with self.assertRaises(ValueError):
            self.migrate()
        self.assertIsNone(publish.branch_tip("codex/publish-lessons", str(self.site)))
        self.assertEqual(self.git(self.site, "show", "HEAD:lessons/older/book.html"), "Existing notes")
        for folder in ("/absolute", "../outside", "courses/../../outside", "C:/outside", "courses\\outside"):
            with self.subTest(folder=folder), self.assertRaises(ValueError):
                publish.content_path(self.site, folder)


if __name__ == "__main__":
    unittest.main()
