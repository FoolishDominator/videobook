# 发布课程笔记到 Lessons

用户要求发布或整理已发布目录时读取。公开笔记统一位于 `https://foolishdominator.github.io/lessons/`，主页与 Lessons 使用同一份样式；生成器仓库用于制作笔记。

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

脚本在主页仓库创建 `codex/publish-lessons` 提交，更新 `lessons/` 下的目录和笔记，保留主页、现有笔记与本地工作区。发布 `book.html`、`book.md`、正文或 Markdown 引用的 `images/`、前端 `assets/` 及存在的 `transcript.corrected.txt`；相同的本地 Mermaid 库收敛到网站 `assets/vendor/` 下的内容哈希文件。原始字幕、任务状态、修改记录和媒体缓存不发布。公开目录只显示课程笔记，不展示生成器名称或宣传文案。

将所选笔记归入课程时，发布命令加 `--course "MIT 15.401 Finance Theory"`。`lessons/manifest.json` 是发布路径与归属的依据：`course` 保存课程名称，`course_slug` 保存首次分配的课程目录标识，`folder` 保存相对 `lessons/` 的笔记路径。课程笔记首次按 `courses/<course_slug>/ses-01/` 这类课时编号路径分配，没有 Ses 编号时使用视频 ID；新发布的独立笔记使用 `notes/<video_id>/`。后续修改标题沿用已有路径，省略 `--course` 沿用已有归属。每次发布重新生成 Lessons 课程目录与各课程的课时列表。

用户要求整理已有发布结构时，在同步主页 `main` 后运行 `python src/publish.py --migrate-layout --site-repo output/homepage-site`，再按上述步骤检查差异、推送并验证。此模式只读取已发布成品，保留其内容和更新时间，不要求本地视频检查点有效。脚本移除迁移前的笔记目录、失去全部课时的课程首页、未引用的图片和已替换的共享库。

网站只维护当前目录结构，不生成旧地址跳转或兼容副本。清理后验证从主页经 Lessons、课程目录能到达所有笔记，Markdown 和订正字幕有下载入口，图片和脚本引用有效。

主页仓库通过 `main` 分支部署 GitHub Pages。推送和部署成功是两个不同结果；核实 Lessons 列表、新笔记及其截图可以访问后，按[清理约定](cleanup.md)回收本次临时截图、下载媒体与工作文件，再交付。缺少 Git 元数据、远端或权限时保留本地成品和必要的恢复材料并说明阻碍。
