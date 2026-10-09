"""准备课程笔记发布；--site-repo 写入个人主页的 lessons/。

发布 book.html / book.md / images/*.png 及订正字幕；不发布原始字幕、srt、
tagged 稿等中间物。全程使用 git plumbing + 临时 index/工作树，不切换分支、
不触碰 main 工作区与 output/ 目录。脚本只写本地 ref，推送由执行者显式完成。

用法:
    python publish.py <video_id> [<video_id> ...] --site-repo <homepage_checkout>
    python publish.py --all --site-repo <homepage_checkout>
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
from site_index import build_index_html

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


def safe_folder(title, bvid):
    """标题 → 文件系统安全目录名：/ → ／，其余非法字符删除，空白折叠。"""
    name = (title or "").strip()
    name = name.replace("/", "／")
    name = re.sub(r'[\\:*?"<>|]', "", name)
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    return name or bvid


def content_path(root, folder):
    """Resolve a publication directory without allowing it to escape its root."""
    root = os.path.realpath(root)
    path = os.path.realpath(os.path.join(root, folder))
    if path == root or os.path.commonpath([root, path]) != root:
        raise ValueError(f"发布目录超出笔记目录: {folder}")
    return path


def _src_blob_map(src):
    """源目录三件套 -> blob sha（与 add 相同过滤标准）。"""
    rels = ["book.html", "book.md"]
    if os.path.isfile(os.path.join(src, CORRECTED)):
        rels.append(CORRECTED)
    img = os.path.join(src, "images")
    rels += ["images/" + f for f in sorted(os.listdir(img)) if f.lower().endswith(".png")]
    out = {}
    for rel in rels:
        r = run(["hash-object", "--", os.path.join(src, *rel.split("/"))])
        out[rel] = r.stdout.strip()
    return out


def _published_blob_map(folder, ref, cwd):
    """已发布目录的 relpath -> blob sha；不存在返回 {}。"""
    if not folder:
        return {}
    r = run(["-c", "core.quotePath=false", "ls-tree", "-r", ref, "--", folder], cwd=cwd, check=False)
    if r.returncode != 0:
        return {}
    m = {}
    for line in r.stdout.splitlines():
        meta, _, path = line.partition("\t")
        m[path[len(folder) + 1:]] = meta.split()[2]
    return m


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
    ap.add_argument("--site-repo", required=True, help="个人主页仓库路径；将笔记写入 main 的 lessons/，生成 codex/publish-lessons 分支")
    args = ap.parse_args()

    if args.all:
        out = os.path.join(BASE, "output")
        ids = [d for d in sorted(os.listdir(out))
               if os.path.isfile(os.path.join(out, d, "book.html"))]
    else:
        ids = args.video_id
    if not ids:
        sys.exit("没有可发布的视频：请提供 video_id 或使用 --all")

    for vid in ids:
        if not os.path.isfile(os.path.join(BASE, "output", vid, "book.html")):
            sys.exit(f"output/{vid}/book.html 不存在，先完成渲染步骤")

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

        now = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")

        # 3) 规划目录名、处理改名与冲突
        for vid in ids:
            title = read_title(vid)
            folder = safe_folder(title, vid)
            others = {k: v.get("folder") for k, v in manifest.items() if k != vid}
            if folder in others.values():
                folder = f"{folder} ({vid})"
            old = manifest.get(vid, {}).get("folder")
            src = os.path.join(BASE, "output", vid)
            dst = content_path(content_root, folder)
            if os.path.exists(dst) and old != folder:
                raise RuntimeError(f"目录已存在且不属于该笔记，停止覆盖: {folder}")

            # 4) 内容未变且目录未改名：保持原发布（含原 updated），保证幂等
            if old == folder and _published_blob_map(f"lessons/{old}", tip, repo) == _src_blob_map(src):
                manifest[vid] = {"folder": folder, "title": title,
                                 "updated": manifest[vid].get("updated", now),
                                 "corrected": os.path.isfile(os.path.join(src, CORRECTED))}
                print(f">> {vid}: 内容无变化，保持原发布")
                continue

            if old and old != folder:
                shutil.rmtree(content_path(content_root, old), ignore_errors=True)
                print(f">> {vid}: 目录改名 {old} -> {folder}")
            manifest[vid] = {"folder": folder, "title": title, "updated": now,
                             "corrected": os.path.isfile(os.path.join(src, CORRECTED))}

            # 5) 复制三件套到临时工作树
            shutil.rmtree(dst, ignore_errors=True)
            os.makedirs(os.path.join(dst, "images"))
            shutil.copyfile(os.path.join(src, "book.html"), os.path.join(dst, "book.html"))
            shutil.copyfile(os.path.join(src, "book.md"), os.path.join(dst, "book.md"))
            if os.path.isfile(os.path.join(src, CORRECTED)):
                shutil.copyfile(os.path.join(src, CORRECTED), os.path.join(dst, CORRECTED))
            n = 0
            for fn in sorted(os.listdir(os.path.join(src, "images"))):
                if fn.lower().endswith(".png"):
                    shutil.copyfile(os.path.join(src, "images", fn),
                                    os.path.join(dst, "images", fn))
                    n += 1
            print(f">> {vid}: {n} 张截图 -> {folder}/")

        # 5) 写 manifest 与落地页
        with open(os.path.join(content_root, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        with open(os.path.join(content_root, "index.html"), "w", encoding="utf-8") as f:
            f.write(build_index_html(manifest))

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
