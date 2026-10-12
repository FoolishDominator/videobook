"""Prepare public note files and share static-site assets."""

from hashlib import sha256
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path
import re
import shutil
from urllib.parse import unquote, urlsplit

from markdown import markdown

from site_index import DEFAULT_SITE


def content_path(root, folder):
    """Resolve a nonempty relative path strictly inside the publication root."""
    root = Path(root).resolve()
    parts = folder.split("/")
    if any(part in ("", ".", "..") or part.casefold() == ".git" or
           "\\" in part or ":" in part for part in parts):
        raise ValueError(f"无效的发布目录: {folder}")
    path = (root / folder).resolve()
    if path == root or root not in path.parents:
        raise ValueError(f"发布目录超出笔记目录: {folder}")
    return path


def validate_note_paths(root, manifest):
    """Note folders must be separate, owned leaves."""
    owners = {}
    for video_id, meta in manifest.items():
        folder = meta["folder"]
        content_path(root, folder)
        key = folder.casefold()
        for existing, owner in owners.items():
            if key == existing or key.startswith(existing + "/") or existing.startswith(key + "/"):
                raise ValueError(f"笔记目录冲突: {folder} ({video_id}) / {existing} ({owner})")
        owners[key] = video_id


def _read_file(path):
    data = path.read_bytes()
    # Git converts checkout line endings on Windows. Compare and hash the public
    # text consistently so identical content remains idempotent across machines.
    if path.suffix.lower() in (".html", ".md", ".txt", ".js", ".css", ".json", ".svg"):
        data = data.replace(b"\r\n", b"\n")
    return data


def read_files(directory):
    directory = Path(directory)
    return {p.relative_to(directory).as_posix(): _read_file(p)
            for p in directory.rglob("*") if p.is_file()}


def _transcript_attachment(name):
    """Conservatively exclude text/subtitle downloads and named transcripts.

    This cannot classify prose inside book.html/book.md, or an arbitrarily
    renamed attachment. Those still require human publication review.
    """
    path = Path(name.lower())
    return (path.suffix in (".txt", ".srt", ".vtt", ".sbv", ".ttml", ".ass", ".ssa") or
            re.search(r"transcript|subtitle|caption|translation|corrections", path.name) is not None)


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.values = []

    def handle_starttag(self, tag, attrs):
        self.values.extend(value for key, value in attrs
                           if key.lower() in ("href", "src", "data", "poster", "action") and value)
        for key, value in attrs:
            if key.lower() == "srcset" and value:
                self.values.extend(candidate.strip().split()[0] for candidate in value.split(",")
                                   if candidate.strip())


def _check_transcript_links(files):
    """Fail closed instead of publishing links to excluded transcript files."""
    for name, data in files.items():
        if Path(name).suffix.lower() not in (".html", ".md"):
            continue
        text = data.decode("utf-8")
        if name.lower().endswith(".md"):
            text = markdown(text)
        parser = _Links()
        parser.feed(text)
        for reference in parser.values:
            reference = unquote(unescape(reference))
            path = urlsplit(reference).path
            if _transcript_attachment(path):
                raise ValueError(f"--exclude-transcripts: {name} 仍引用字幕/文本附件 {reference}；请先移除链接并复核摘要")


def prepare_note(source, meta, site_root, *, published=False, site=DEFAULT_SITE,
                 exclude_transcripts=False):
    """Keep public payloads, trim unused images, and share identical Mermaid bundles."""
    source = Path(source)
    if published:
        files = read_files(source)
    else:
        files = {name: _read_file(source / name)
                 for name in ("book.html", "book.md", "transcript.corrected.txt")
                 if (source / name).is_file()}
        for folder in ("images", "assets"):
            files.update({f"{folder}/{name}": data for name, data in read_files(source / folder).items()})
    if "book.html" not in files:
        raise ValueError(f"已发布笔记缺少 book.html: {source}")
    if exclude_transcripts:
        files = {name: data for name, data in files.items()
                 if name in ("book.html", "book.md") or not _transcript_attachment(name)}
        _check_transcript_links(files)
    html = files["book.html"].decode("utf-8")
    references = unquote(html + "\n" + files.get("book.md", b"").decode("utf-8"))
    for name in list(files):
        if name.startswith("images/") and name not in references:
            del files[name]

    asset = "assets/mermaid.min.js"
    if re.search(r'''src=["']assets/mermaid\.min\.js["']''', html):
        if asset not in files:
            raise ValueError(f"笔记引用的 Mermaid 文件不存在: {source / asset}")
        data = files.pop(asset)
        filename = f"mermaid-{sha256(data).hexdigest()[:16]}.min.js"
        shared = Path(site_root) / "assets" / "vendor" / filename
        shared.parent.mkdir(parents=True, exist_ok=True)
        shared.write_bytes(data)
        html = re.sub(r'''(src=["'])assets/mermaid\.min\.js(["'])''',
                      lambda match: match[1] + site.site_href(f"assets/vendor/{filename}") + match[2], html)

    # A migrated note may already use a publisher-owned shared bundle. Rebase
    # those URLs for the explicitly configured project Pages prefix only when
    # the matching asset exists in this repository.
    def rebase_shared(match):
        filename = match[2]
        if not (Path(site_root) / "assets" / "vendor" / filename).is_file():
            raise ValueError(f"共享 Mermaid 文件不存在: {filename}")
        return match[1] + site.site_href(f"assets/vendor/{filename}") + match[3]

    html = re.sub(r'''(src=["'])/[^"']*assets/vendor/(mermaid-[0-9a-f]{16}\.min\.js)(["'])''',
                  rebase_shared, html)

    # Remove only markup owned by the publisher before regenerating it.
    html = re.sub(r'\n?<!-- publication-navigation -->.*?<!-- /publication-navigation -->\n?',
                  "\n", html, flags=re.S)
    html = re.sub(r'''\s*<link\b(?=[^>]*\brel=["']canonical["'])[^>]*>''', "", html, flags=re.I)
    canonical = escape(site.canonical(meta["folder"] + "/book.html"), quote=True)
    html = re.sub(r"\s*</head>", f'\n    <link rel="canonical" href="{canonical}">\n</head>', html, count=1, flags=re.I)
    if meta.get("course"):
        course_href = site.content_href(f'courses/{meta["course_slug"]}/')
        navigation = ('\n<!-- publication-navigation -->\n'
                      '<nav aria-label="课程导航" style="margin:0 0 1.5rem;font-size:14px">'
                      f'<a href="{site.content_href()}">Lessons</a> · '
                      f'<a href="{course_href}">{escape(meta["course"])}</a></nav>\n'
                      '<!-- /publication-navigation -->\n')
        article = r'''(<article\b[^>]*\bclass=["'][^"']*\bbook-content\b[^"']*["'][^>]*>)\s*'''
        anchor = article if re.search(article, html, flags=re.I) else r"(<body\b[^>]*>)\s*"
        html = re.sub(anchor, lambda match: match[1] + navigation,
                      html, count=1, flags=re.I)
    files["book.html"] = html.encode("utf-8")
    return files


def replace_files(root, folder, files):
    # Resolve and check both the directory and every file before deleting anything.
    directory = content_path(root, folder)
    paths = {name: content_path(directory, name) for name in files}
    if directory.exists():
        shutil.rmtree(directory)
    for name, path in paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(files[name])


def prune_shared_assets(site_root):
    """Only remove unreferenced assets generated by this publisher."""
    site_root = Path(site_root)
    references = "\n".join(p.read_text(encoding="utf-8") for p in site_root.rglob("*")
                           if p.is_file() and p.suffix in (".html", ".md"))
    for path in (site_root / "assets" / "vendor").glob("mermaid-*.min.js"):
        if re.fullmatch(r"mermaid-[0-9a-f]{16}\.min\.js", path.name) and path.name not in references:
            path.unlink()
