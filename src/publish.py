"""准备课程笔记发布；--site-repo 写入个人主页的 lessons/。

发布笔记、引用的图片、前端资源及订正字幕；不发布原始字幕、srt、
tagged 稿等中间物。全程使用 git plumbing + 临时 index/工作树，不切换分支、
不触碰 main 工作区与 output/ 目录。脚本只写本地 ref，推送由执行者显式完成。

用法:
    python publish.py <video_id> [<video_id> ...] --site-repo <homepage_checkout>
    python publish.py --all --site-repo <homepage_checkout>
    python publish.py --migrate-layout --site-repo <homepage_checkout>
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from site_content import (content_path, prepare_note, prune_shared_assets, read_files,
                          replace_files, validate_note_paths)
from site_index import build_course_pages, build_index_html, course_slug, session_number

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORRECTED = "transcript.corrected.txt"


def run(args, env=None, cwd=None, check=True):
    e = os.environ.copy()
    if env:
        e.update(env)
    r = subprocess.run(["git"] + args, cwd=cwd or BASE, env=e,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r


def plan_note(video_id, title, previous, manifest, course=None):
    """Allocate a stable note path once; display-title changes do not change URLs."""
    meta = {**previous, "title": title}
    if course is not None:
        meta["course"] = course
        if course != previous.get("course"):
            meta.pop("course_slug", None)
    old = previous.get("folder")
    video_slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", video_id).strip("-")
    if not video_slug:
        raise ValueError(f"无法生成笔记目录: {video_id}")
    if meta.get("course"):
        existing_slugs = {other.get("course_slug") or course_slug(other["course"])
                          for other in manifest.values() if other.get("course") == meta["course"]}
        if len(existing_slugs) > 1:
            raise ValueError(f"课程存在多个目录标识: {meta['course']}")
        slug = meta.get("course_slug") or next(iter(existing_slugs), None) or course_slug(meta["course"])
        meta["course_slug"] = slug
        prefix = f"courses/{slug}/"
        if old and old.startswith(prefix) and len(old.split("/")) == 3:
            folder = old
        else:
            number = session_number(meta)
            leaf = f"ses-{number:02d}" if number is not None else video_slug
            if old and old.startswith("courses/") and len(old.split("/")) == 3:
                leaf = old.rsplit("/", 1)[1]
            folder = prefix + leaf
    else:
        folder = old or f"notes/{video_slug}"
    meta["folder"] = folder
    return meta


def branch_tip(ref, cwd):
    r = run(["rev-parse", "--verify", "--quiet", f"refs/heads/{ref}"], cwd=cwd, check=False)
    return r.stdout.strip() if r.returncode == 0 else None


def read_title(video_id):
    p = os.path.join(BASE, "output", video_id, "transcript.json")
    try:
        with open(p, encoding="utf-8") as f:
            t = json.load(f).get("title", "")
        return (t or "").strip()
    except (OSError, json.JSONDecodeError):
        return ""


def main():
    ap = argparse.ArgumentParser(description="准备课程笔记的发布提交")
    ap.add_argument("video_id", nargs="*", help="要发布的视频 ID（output/ 下的目录名）")
    ap.add_argument("--all", action="store_true", help="发布 output/ 下所有含 book.html 的视频")
    ap.add_argument("--migrate-layout", action="store_true", help="只整理已经发布的笔记目录与资源，不读取本地视频产物")
    ap.add_argument("--course", type=str.strip, help="将所选笔记收录到指定课程；省略时保留已有课程归属")
    ap.add_argument("--site-repo", required=True, help="个人主页仓库路径；将笔记写入 main 的 lessons/，生成 codex/publish-lessons 分支")
    args = ap.parse_args()
    if args.course == "":
        ap.error("--course 不能为空")
    if args.migrate_layout and (args.video_id or args.all or args.course is not None):
        ap.error("--migrate-layout 单独使用，不与 video_id、--all 或 --course 混用")

    if args.all:
        out = os.path.join(BASE, "output")
        ids = [d for d in sorted(os.listdir(out))
               if os.path.isfile(os.path.join(out, d, "book.html"))]
    else:
        ids = args.video_id
    if not ids and not args.migrate_layout:
        sys.exit("没有可发布的视频：请提供 video_id 或使用 --all")

    for vid in ids:
        for filename in ("book.html", "book.md"):
            if not os.path.isfile(os.path.join(BASE, "output", vid, filename)):
                sys.exit(f"output/{vid}/{filename} 不存在，先完成渲染步骤")

    repo = os.path.abspath(args.site_repo)
    source_ref = "main"
    destination_ref = "codex/publish-lessons"
    git = lambda commands, **kwargs: run(commands, cwd=repo, **kwargs)
    git_dir = git(["rev-parse", "--absolute-git-dir"]).stdout.strip()
    tip = branch_tip(source_ref, repo)
    if not tip:
        sys.exit("个人主页仓库缺少 main 分支，请先同步主页仓库")
    checked_out = git(["symbolic-ref", "--short", "-q", "HEAD"], check=False).stdout.strip()
    if checked_out == destination_ref:
        sys.exit(f"请先切换离开 {destination_ref} 分支，避免修改当前工作区")
    previous_destination = branch_tip(destination_ref, repo)
    if previous_destination:
        merged = git(["merge-base", "--is-ancestor", previous_destination, tip], check=False)
        if merged.returncode:
            sys.exit("codex/publish-lessons 尚有未合入 main 的提交；请先完成该次发布并同步 main")
    tmp = tempfile.mkdtemp(prefix="videobook_publish_")
    env = {"GIT_INDEX_FILE": tmp + ".index"}  # 索引文件必须在工作树之外，否则会被 add 进提交
    g = lambda *a, **k: git(list(a), env=env, **k)

    try:
        # 1) 在临时工作树中保留主页和所有已发布笔记。
        g("--git-dir", git_dir, "--work-tree", tmp, "read-tree", tip)
        g("--git-dir", git_dir, "--work-tree", tmp, "checkout-index", "-a")
        content_root = content_path(tmp, "lessons")
        os.makedirs(content_root, exist_ok=True)
        manifest_path = "lessons/manifest.json"

        # 2) 读旧 manifest
        manifest = {}
        if tip:
            r = git(["show", f"{tip}:{manifest_path}"], check=False)
            if r.returncode == 0:
                try:
                    manifest = json.loads(r.stdout)
                except json.JSONDecodeError as error:
                    raise RuntimeError("已发布的 manifest.json 无法解析，停止发布以保留现有笔记") from error

        validate_note_paths(content_root, manifest)
        previous_courses = build_course_pages(manifest)
        now = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
        previous_manifest = manifest
        manifest = dict(previous_manifest)
        if args.migrate_layout:
            ids = list(manifest)

        # 3) 先规划所有目录，拒绝笔记之间的覆盖或嵌套。
        for vid in ids:
            previous = previous_manifest.get(vid, {})
            title = previous.get("title", vid) if args.migrate_layout else read_title(vid)
            manifest[vid] = plan_note(vid, title, previous, manifest, args.course)
        validate_note_paths(content_root, manifest)
        for vid in ids:
            previous = previous_manifest.get(vid, {})
            meta = manifest[vid]
            folder = meta["folder"]
            if content_path(content_root, folder).exists() and folder != previous.get("folder"):
                raise RuntimeError(f"目录已存在且不属于该笔记，停止覆盖: {folder}")
            if previous.get("folder") and previous["folder"] != folder:
                validate_note_paths(content_root, {
                    **manifest, ("previous", vid): previous,
                })

        # 4) 迁移使用已发布成品；常规发布只读取所选视频的公开产物。
        for vid in ids:
            previous = previous_manifest.get(vid, {})
            meta = manifest[vid]
            old = previous.get("folder")
            source = content_path(content_root, old) if args.migrate_layout else os.path.join(BASE, "output", vid)
            files = prepare_note(source, meta, tmp, published=args.migrate_layout)
            unchanged = old and read_files(content_path(content_root, old)) == files
            meta["updated"] = previous.get("updated", now) if unchanged or args.migrate_layout else now
            meta["corrected"] = CORRECTED in files
            meta["markdown"] = "book.md" in files
            replace_files(content_root, meta["folder"], files)
            if old and old != meta["folder"]:
                old_directory = content_path(content_root, old)
                if old_directory.exists():
                    shutil.rmtree(old_directory)
            print(f">> {vid}: {meta['folder']}/")

        # 5) 写 manifest 与落地页
        with open(os.path.join(content_root, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
            f.write("\n")
        with open(os.path.join(content_root, "index.html"), "w", encoding="utf-8") as f:
            f.write(build_index_html(manifest))
        course_pages = build_course_pages(manifest)
        for slug, page in course_pages.items():
            course_dir = content_path(content_root, f"courses/{slug}")
            os.makedirs(course_dir, exist_ok=True)
            with open(os.path.join(course_dir, "index.html"), "w", encoding="utf-8") as f:
                f.write(page)
        for slug in previous_courses.keys() - course_pages.keys():
            old_page = content_path(content_root, f"courses/{slug}/index.html")
            old_page.unlink(missing_ok=True)
        prune_shared_assets(tmp)

        # 6) 收拢为新树；树未变则跳过提交
        g("-C", tmp, "--git-dir", git_dir, "--work-tree", tmp, "add", "-A")
        tree = g("--git-dir", git_dir, "--work-tree", tmp, "write-tree").stdout.strip()
        if tip:
            old_tree = git(["rev-parse", f"{tip}^{{tree}}"]).stdout.strip()
            if tree == old_tree:
                print(">> 内容无变化，跳过提交")
                return
        parent = ["-p", tip] if tip else []
        commit = git(["commit-tree", tree] + parent +
                     ["-m", f"publish: {', '.join(ids)}"]).stdout.strip()
        git(["update-ref", f"refs/heads/{destination_ref}", commit, previous_destination or "0" * 40])
        print(f">> {destination_ref} 分支已更新: {commit[:8]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            os.remove(tmp + ".index")
        except OSError:
            pass

    print(f'\n完成。推送请执行: git -C "{repo}" push origin {destination_ref}:main')


if __name__ == "__main__":
    main()
