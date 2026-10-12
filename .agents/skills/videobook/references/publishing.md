# 发布课程笔记到已确认的站点

用户要求发布或整理已发布目录时读取。生成电子书默认到本地交付结束；生成、修改代码或准备部署都不代表已经授权公开发布。没有默认发布站点，不沿用旧文档中的个人主页地址。

## 先确认目标和公开内容

每个新发布任务先向用户确认：

- 站点仓库及远端、部署源分支（例如 `main` 或 `gh-pages`）
- 公开网站根地址，与该分支的仓库根目录对应；项目 Pages 必须包含项目路径
- 仓库内的笔记目录，以及最终公开目录地址
- 本次发布的视频/笔记范围、公开可见性及是否包含字幕附件

本轮已经明确确认的相同目标和内容范围无需重复询问；目标或范围改变必须重新确认。不能因为用户有一个已知主页，便把笔记发布过去。只发布请求中的视频，明确要求全部发布时才用 `--all`。

先核对所选产物的有效 `html` 检查点，并人工审查正文、图片和来源署名。完整字幕、逐段译文或实质上替代原视频的完整电子书，只用于用户提供并确认可公开、已取得适当授权、或许可明确允许相应用途的内容。其他内容仅发布简洁的原创摘要，附视频来源链接及作者/课程署名；不能把完整翻译改名为“摘要”。

原创摘要使用 `--exclude-transcripts`，但这个开关只是附件过滤器，不是版权或原创性判断器：

- 排除本次所选笔记的字幕、译稿及保守识别的文本/字幕附件，包括 `.txt`、`.srt`、`.vtt` 和文件名含 transcript、subtitle、caption、translation、corrections 的文件
- 不在新目录页生成所选笔记的字幕下载入口；重新发布时删除这些笔记以前发布的字幕副本
- HTML/Markdown 仍链接到被排除的字幕/文本附件时，停止准备提交。先从源文档移除下载链接并重新渲染，不自动删改正文
- `book.html`、`book.md` 和图片仍需人工审查；内嵌全文、被改成其他名称的附件和截图中的文字不能靠开关保证合规
- 未选中的旧笔记保持不变；若用户授权清理该目录下所有已发布笔记，可用 `--migrate-layout --exclude-transcripts`

## 配置及本地准备

`--site-repo`、`--public-base-url` 和 `--content-dir` 都必须显式给出。`--site-branch` 默认 `main`，也可明确指定已确认的其他分支。以下只是示例，`example.org` 和目录名都要替换成用户确认的目标：

```bash
python src/pipeline.py status <video_id> --mode book
git -C output/publishing-site remote -v
# 先核对远端、部署源分支及现有工作区，再按需要同步该分支。
python src/publish.py <video_id> \
  --site-repo output/publishing-site \
  --site-branch main \
  --public-base-url https://example.org/project/ \
  --content-dir study/notes \
  --exclude-transcripts
git -C output/publishing-site diff main codex/publish-lessons --stat
git -C output/publishing-site diff main codex/publish-lessons
```

该配置把文件写入仓库 `study/notes/`，公开目录是 `https://example.org/project/study/notes/`。网站导航、课程/笔记链接、canonical 和共享 Mermaid 资源都带上 `/project/` 前缀。`--content-dir lessons` 则使用仓库 `lessons/` 和公开 `/project/lessons/`。根目录 `.`、绝对路径和目录穿越会被拒绝，防止把站点首页当成笔记目录。

当前映射要求部署源为所选分支的仓库根。如果 Pages 实际只部署 `/docs` 或由自定义构建器改写路径，先确认/适配该映射，不要用一个看似合理的 URL 掩盖不匹配。

脚本复用现有 `assets/site.css`，不创建或覆盖站点首页、样式表，也不重做站点风格；笔记页本身保留已渲染的样式。缺少现有样式表时停止并要求先核对样式集成。目标笔记目录或新课程目录已经有非 VideoBook 的 `index.html` 时，停止覆盖。目录页保留现有样式使用的 CSS 类，采用通用的课程笔记文案，不硬编码其他站点的所有者身份。

脚本从 `--site-branch` 的已提交内容创建本地 `codex/publish-lessons` 提交。不会切换分支、改写当前工作区、修改本地 `output/` 成品、推送或触发部署。现有未提交工作不进入发布提交。若内容无变化则跳过提交；若报告准备分支尚有未合入源分支的提交，先核实内容和此前授权，完成或恢复该次发布，不能直接覆盖。

默认公开产物为 `book.html`、`book.md`、正文或 Markdown 引用的 `images/`、前端 `assets/` 及存在的 `transcript.corrected.txt`。有字幕附件的发布必须符合上面的内容授权要求；摘要模式必须加排除开关。原始字幕、任务状态、修改记录和媒体缓存不作为根目录公开产物。相同的本地 Mermaid 库收敛到站点 `assets/vendor/` 的内容哈希文件。

## 课程目录及迁移

将所选笔记归入课程时，加 `--course "MIT 15.401 Finance Theory"`。`<content-dir>/manifest.json` 记录路径与归属：`course` 为课程名称，`course_slug` 为首次分配的课程目录标识，`folder` 为相对笔记目录的路径。首次按 `courses/<course_slug>/ses-01/` 这类课时编号分配，没有 Ses 编号则使用视频 ID；新独立笔记使用 `notes/<video_id>/`。修改标题沿用已有路径，省略 `--course` 沿用已有归属。每次发布重新生成笔记目录和课程列表。

用户授权整理已有目录时运行：

```bash
python src/publish.py --migrate-layout \
  --site-repo output/publishing-site \
  --site-branch main \
  --public-base-url https://example.org/project/ \
  --content-dir study/notes
```

迁移只读已发布成品，不要求本地视频检查点有效，保留内容及更新时间。它移除旧笔记目录、失去全部课时的课程首页、未引用图片和被替换的共享库。没有旧地址跳转或兼容副本；路径变化必须包含在用户确认的整理范围内。

## 单独授权推送并验证

确认具体仓库远端、目标分支、公开地址和本次内容范围的发布授权仍有效后，才单独推送。先审查完整差异，核对没有其他任务的笔记、私有信息或未经允许的全文。确认目标分支确实为 `main` 时的命令示例为：

```bash
git -C output/publishing-site push origin codex/publish-lessons:main
```

若确认的是其他分支，必须相应替换目标，不能仍推送到 `main`。不要把此命令无条件接在本地准备命令后自动执行。缺少远端、Git 元数据或权限时保留本地成品及必要恢复材料，说明具体阻碍。

推送成功和部署成功分开核实：先验证远端提交，再检查对应部署结果及实际公开地址。抽查目录、课程、笔记、图片和脚本，以及存在的 Markdown/已授权字幕下载；摘要模式不得留下字幕附件或损坏的字幕链接。站点首页和既有样式须保持原样。验证完成后按 [清理约定](cleanup.md) 处理本次临时文件并交付真实访问地址；尚未部署时明确说明只准备了本地提交。
