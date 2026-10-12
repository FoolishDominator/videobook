"""Render the public Lessons directory; styling belongs to the personal site."""

from dataclasses import dataclass
from html import escape
import re
from urllib.parse import quote, unquote, urlsplit, urlunsplit


@dataclass(frozen=True)
class PublicationSite:
    """A public site root and its repository-relative notes directory.

    Empty public_base_url is only a backwards-compatible relative-link default
    for library callers. The CLI requires an explicit absolute public URL.
    """

    public_base_url: str = ""
    content_dir: str = "lessons"

    def __post_init__(self):
        parts = self.content_dir.split("/")
        if any(part in ("", ".", "..") or part.startswith(".") or
               "\\" in part or ":" in part for part in parts):
            raise ValueError("--content-dir 必须是仓库内的非空相对目录，不能是首页根目录")
        if not self.public_base_url:
            return
        url = urlsplit(self.public_base_url)
        if (url.scheme not in ("https", "http") or not url.hostname or
                url.username is not None or url.password is not None or
                "?" in self.public_base_url or "#" in self.public_base_url or
                any(character.isspace() or ord(character) < 32 for character in self.public_base_url) or
                "\\" in self.public_base_url):
            raise ValueError("--public-base-url 必须是无凭据、查询参数或片段的 http(s) 网站根地址")
        # Reject ambiguous encoded paths rather than guessing how the web server
        # maps them onto the repository (including project Pages prefixes).
        path = unquote(url.path)
        if any(part in (".", "..") for part in path.split("/")) or "\\" in path or "//" in path:
            raise ValueError("--public-base-url 包含不安全的路径")
        if url.port is not None and not 0 < url.port < 65536:
            raise ValueError("--public-base-url 端口无效")
        path = quote(path.rstrip("/"), safe="/")
        object.__setattr__(self, "public_base_url", urlunsplit((url.scheme, url.netloc, path, "", "")))

    def site_href(self, relative=""):
        prefix = urlsplit(self.public_base_url).path.rstrip("/")
        return prefix + "/" + quote(relative, safe="/")

    def content_href(self, relative=""):
        return self.site_href(self.content_dir + "/" + relative)

    def canonical(self, relative=""):
        return self.public_base_url + "/" + quote(self.content_dir + "/" + relative, safe="/")


DEFAULT_SITE = PublicationSite()


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


def note_url(folder, filename="book.html", *, site=DEFAULT_SITE):
    return site.content_href(folder + "/" + filename)


def _notes_list(manifest, site):
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
            details.append(f'<a href="{note_url(folder, "book.md", site=site)}" download>Markdown</a>')
        if meta.get("corrected"):
            details.append(f'<a href="{note_url(folder, "transcript.corrected.txt", site=site)}">字幕对照</a>')
        metadata = f'<span class="note-meta">{" · ".join(details)}</span>' if details else ""
        items.append(f'        <li><a href="{note_url(folder, site=site)}">{title}</a>{metadata}</li>')
    return ('      <ol class="notes-list">\n' + "\n".join(items) + '\n      </ol>') if items else '      <p class="muted">暂无公开课程笔记。</p>'


def build_index_html(manifest, *, site=DEFAULT_SITE):
    courses = _courses(manifest)
    sections = []
    if courses:
        items = []
        for slug, (title, notes) in sorted(courses.items()):
            href = site.content_href(f"courses/{slug}/")
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
{_notes_list(ungrouped, site)}
    </section>''')
    return _page("Lessons", "课程笔记", "\n".join(sections), "", site=site)


def build_course_pages(manifest, *, site=DEFAULT_SITE):
    pages = {}
    for slug, (title, notes) in _courses(manifest).items():
        content = f'''    <section aria-labelledby="notes-title">
      <h2 id="notes-title">课程内容</h2>
{_notes_list(notes, site)}
    </section>'''
        breadcrumb = f'    <p class="breadcrumb"><a href="{site.content_href()}">← Lessons</a></p>\n'
        pages[slug] = _page(title, f"{len(notes)} 节课程笔记", content,
                            f"courses/{slug}/", breadcrumb, site=site)
    return pages


def _page(title, intro, content, path, breadcrumb="", *, site=DEFAULT_SITE):
    title = escape(title)
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="课程笔记。">
  <title>{title} · 课程笔记</title>
  <link rel="canonical" href="{escape(site.canonical(path), quote=True)}">
  <link rel="icon" type="image/svg+xml" href="{site.site_href("assets/favicon.svg")}">
  <link rel="stylesheet" href="{site.site_href("assets/site.css")}">
</head>
<body>
  <a class="skip-link" href="#main">跳到正文</a>
  <header class="site-header">
    <div class="header-inner">
      <a class="site-name" href="{site.site_href()}">首页</a>
      <nav class="site-nav" aria-label="主导航">
        <a href="{site.site_href()}">首页</a>
        <a href="{site.content_href()}" aria-current="page">Lessons</a>
      </nav>
    </div>
  </header>
  <main id="main" tabindex="-1">
{breadcrumb}    <h1>{title}</h1>
    <p class="intro">{intro}</p>
{content}
  </main>
  <footer class="site-footer">
    <span>学习与记录</span>
  </footer>
</body>
</html>
'''
