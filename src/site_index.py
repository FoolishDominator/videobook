"""Render the public Lessons directory; styling belongs to the personal site."""

from html import escape
import re
from urllib.parse import quote


def _sequence(meta):
    match = re.search(r"\[(\d+)[-－]", meta.get("title", ""))
    return int(match.group(1)) if match else 10**9


def build_index_html(manifest):
    rows = sorted(manifest.items(), key=lambda item: (_sequence(item[1]), item[1].get("updated", "")))
    items = []
    for video_id, meta in rows:
        folder = quote(meta["folder"], safe="")
        title = escape(meta.get("title") or video_id)
        date = escape(meta.get("updated", "")[:10], quote=True)
        details = [f'<time datetime="{date}">{date}</time>'] if date else []
        if meta.get("corrected"):
            details.append(f'<a href="{folder}/transcript.corrected.txt">字幕对照</a>')
        metadata = f'<span class="note-meta">{" · ".join(details)}</span>' if details else ""
        items.append(f'        <li><a href="{folder}/book.html">{title}</a>{metadata}</li>')
    listing = ('      <ol class="notes-list">\n' + "\n".join(items) + '\n      </ol>') if items else '      <p class="muted">暂无公开课程笔记。</p>'
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="RAY 的课程笔记。">
  <title>Lessons · RAY's Space</title>
  <link rel="canonical" href="https://foolishdominator.github.io/lessons/">
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
    <h1>Lessons</h1>
    <p class="intro">课程笔记</p>
    <section aria-labelledby="notes-title">
      <h2 id="notes-title">笔记目录</h2>
{listing}
    </section>
  </main>
  <footer class="site-footer">
    <span>RAY · 学习与记录</span>
    <a href="https://github.com/FoolishDominator">GitHub</a>
  </footer>
</body>
</html>
'''
