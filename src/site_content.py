"""Prepare public note files and share static-site assets."""

from hashlib import sha256
from html import escape
from pathlib import Path
import re
import shutil
from urllib.parse import quote, unquote

from site_index import SITE_URL, note_url


def content_path(root, folder):
    """Resolve a nonempty relative path strictly inside the publication root."""
    root = Path(root).resolve()
    parts = folder.split("/")
    if any(part in ("", ".", "..") or "\\" in part or ":" in part for part in parts):
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


def prepare_note(source, meta, site_root, *, published=False):
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
                      lambda match: match[1] + f"/assets/vendor/{filename}" + match[2], html)

    # Remove only markup owned by the publisher before regenerating it.
    html = re.sub(r'\n?<!-- publication-navigation -->.*?<!-- /publication-navigation -->\n?',
                  "\n", html, flags=re.S)
    html = re.sub(r'''\s*<link\b(?=[^>]*\brel=["']canonical["'])[^>]*>''', "", html, flags=re.I)
    canonical = escape(SITE_URL + note_url(meta["folder"]), quote=True)
    html = re.sub(r"</head>", f'    <link rel="canonical" href="{canonical}">\n</head>', html, count=1, flags=re.I)
    if meta.get("course"):
        course_href = f'/lessons/courses/{quote(meta["course_slug"], safe="")}/'
        navigation = ('\n<!-- publication-navigation -->\n'
                      '<nav aria-label="课程导航" style="margin:0 0 1.5rem;font-size:14px">'
                      '<a href="/lessons/">Lessons</a> · '
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
