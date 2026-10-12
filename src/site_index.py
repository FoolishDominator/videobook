"""Render the public Lessons directory; styling belongs to the personal site."""

from html import escape
import re
from urllib.parse import quote

SITE_URL = "https://foolishdominator.github.io"


def session_number(meta):
    stored = re.search(r"(?:^|/)ses-(\d+)$", meta.get("folder", ""))
    if stored:
        return int(stored.group(1))
    match = re.search(r"\[(\d+)[-－]|\bses(?:sion)?\.?\s*(\d+)\b", meta.get("title", ""), re.I)
    return int(next(group for group in match.groups() if group)) if match else None


def course_slug(title):
    slug = re.sub(r"[\W_]+", "-", title.lower()).strip("-")
    if not slug:
        raise ValueError(f"课程名称需要包含文字或数字: {title}")
    return slug


def _courses(manifest):
    courses = {}
    slugs = {}
    for video_id, meta in manifest.items():
        title = meta.get("course")
        if not title:
            continue
        slug = meta.get("course_slug") or course_slug(title)
        if slug in slugs and slugs[slug] != title:
            raise ValueError(f"课程目录名称冲突: {slugs[slug]} / {title}")
        slugs[slug] = title
        courses.setdefault(slug, (title, {}))[1][video_id] = meta
    return courses


def note_url(folder, filename="book.html"):
    return "/lessons/" + quote(folder, safe="/") + "/" + filename


def _notes_list(manifest):
    rows = sorted(manifest.items(), key=lambda item: (
        session_number(item[1]) if session_number(item[1]) is not None else 10**9,
        item[1].get("updated", "")))
    items = []
    for video_id, meta in rows:
        folder = meta["folder"]
        title = escape(meta.get("title") or video_id)
        date = escape(meta.get("updated", "")[:10], quote=True)
        details = [f'<time datetime="{date}">{date}</time>'] if date else []
        if meta.get("markdown"):
            details.append(f'<a href="{note_url(folder, "book.md")}" download>Markdown</a>')
        if meta.get("corrected"):
            details.append(f'<a href="{note_url(folder, "transcript.corrected.txt")}">字幕对照</a>')
        metadata = f'<span class="note-meta">{" · ".join(details)}</span>' if details else ""
        items.append(f'        <li><a href="{note_url(folder)}">{title}</a>{metadata}</li>')
    return ('      <ol class="notes-list">\n' + "\n".join(items) + '\n      </ol>') if items else '      <p class="muted">暂无公开课程笔记。</p>'


def build_index_html(manifest):
    courses = _courses(manifest)
    sections = []
    if courses:
        items = []
        for slug, (title, notes) in sorted(courses.items()):
            href = f"/lessons/courses/{quote(slug, safe='')}/"
            items.append(f'        <li><a href="{href}">{escape(title)}</a><span class="note-meta">{len(notes)} 节课</span></li>')
        sections.append('''    <section aria-labelledby="courses-title">
      <h2 id="courses-title">课程目录</h2>
      <ul class="notes-list">
''' + "\n".join(items) + '''
      </ul>
    </section>''')
    ungrouped = {video_id: meta for video_id, meta in manifest.items() if not meta.get("course")}
    if ungrouped or not courses:
        heading = "其他笔记" if courses else "笔记目录"
        sections.append(f'''    <section aria-labelledby="notes-title">
      <h2 id="notes-title">{heading}</h2>
{_notes_list(ungrouped)}
    </section>''')
    return _page("Lessons", "课程笔记", "\n".join(sections), "/lessons/")


def build_course_pages(manifest):
    pages = {}
    for slug, (title, notes) in _courses(manifest).items():
        content = f'''    <section aria-labelledby="notes-title">
      <h2 id="notes-title">课程内容</h2>
{_notes_list(notes)}
    </section>'''
        breadcrumb = '    <p class="breadcrumb"><a href="/lessons/">← Lessons</a></p>\n'
        pages[slug] = _page(title, f"{len(notes)} 节课程笔记", content,
                            f"/lessons/courses/{quote(slug, safe='')}/", breadcrumb)
    return pages


def _page(title, intro, content, path, breadcrumb=""):
    title = escape(title)
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="RAY 的课程笔记。">
  <title>{title} · RAY's Space</title>
  <link rel="canonical" href="{SITE_URL}{path}">
  <link rel="icon" type="image/svg+xml" href="/assets/favicon.svg">
  <link rel="stylesheet" href="/assets/site.css">
</head>
<body>
  <a class="skip-link" href="#main">跳到正文</a>
  <header class="site-header">
    <div class="header-inner">
      <a class="site-name" href="/">RAY's Space</a>
      <nav class="site-nav" aria-label="主导航">
        <a href="/">首页</a>
        <a href="/lessons/" aria-current="page">Lessons</a>
      </nav>
    </div>
  </header>
  <main id="main" tabindex="-1">
{breadcrumb}    <h1>{title}</h1>
    <p class="intro">{intro}</p>
{content}
  </main>
  <footer class="site-footer">
    <span>RAY · 学习与记录</span>
    <a href="https://github.com/FoolishDominator">GitHub</a>
  </footer>
</body>
</html>
'''
