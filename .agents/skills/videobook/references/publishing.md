# 发布课程笔记到 Lessons

仅在用户要求发布时读取。公开笔记统一位于 `https://foolishdominator.github.io/lessons/`，主页与 Lessons 使用同一份样式；生成器仓库用于制作笔记，旧 `/videobook/` 页面只保留跳转。

先确认所选视频的 `html` 检查点有效。使用主页仓库 `https://github.com/FoolishDominator/FoolishDominator.GitHub.io.git` 的本地检出，下面以 `output/homepage-site` 为例；目录不存在时克隆，存在时核实远端。同步其 `main` 分支后准备发布：

```bash
python src/pipeline.py status <video_id> --mode book
git -C output/homepage-site remote -v
git -C output/homepage-site fetch origin
git -C output/homepage-site merge --ff-only origin/main
python src/publish.py <video_id> --site-repo output/homepage-site
git -C output/homepage-site diff main codex/publish-lessons --stat
git -C output/homepage-site push origin codex/publish-lessons:main
git -C output/homepage-site fetch origin
git -C output/homepage-site merge --ff-only origin/main
```

检出目录应位于 `main`，已有改动需要保留。只发布请求中的视频；用户明确要求全部发布时才用 `--all`。已有发布授权时无需重复询问。若脚本报告内容无变化，则无需推送；若报告待完成的发布分支，先核实该分支的内容与当前请求，再完成或恢复原发布。

脚本在主页仓库创建 `codex/publish-lessons` 提交，更新 `lessons/` 下的目录和笔记，保留主页、现有笔记与本地工作区。笔记目录以视频标题命名，发布 `book.html`、`book.md`、`images/` 及存在的 `transcript.corrected.txt`。原始字幕、任务状态、修改记录和媒体缓存不发布。公开目录只显示课程笔记，不展示生成器名称或宣传文案。

主页仓库通过 `main` 分支部署 GitHub Pages。推送和部署成功是两个不同结果；核实 Lessons 列表、新笔记及其截图可以访问后再宣告上线。缺少 Git 元数据、远端或权限时保留本地成品并说明阻碍。
