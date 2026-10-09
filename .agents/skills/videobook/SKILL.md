---
name: videobook
description: 将 YouTube 或 Bilibili 视频生成中文图文电子书，或仅订正字幕。在本项目中仅收到一个视频链接、明确要求生成 VideoBook / 修正版字幕、或继续已有视频任务时使用。代码修改、方案讨论和示例中的链接不触发此流程。
---

# VideoBook

由当前 AI 会话完成字幕校读与书籍编排，调用项目脚本处理获取、截帧、渲染和验证。用户只提供链接时直接执行完整流程；明确只要字幕时使用 `transcript` 模式。

本技能随项目使用。项目根目录为本文件所在目录向上三级；以下命令均从根目录执行，`python` 指项目环境中的解释器。不要依赖前一个会话的记忆。

## 开始与恢复

1. 确定用户提供的 URL 和交付模式。依赖缺失时按 [README](../../../README.md#环境准备) 配置。保留用户明确指定的语言、下载限制和其他要求。
2. 已知视频 ID 时运行 `python src/pipeline.py status <video_id> --mode book`（仅字幕改为 `transcript`）。状态保存在 `output/<video_id>/run.json`，状态检查会重新比较产物及规则文件的指纹。
3. 已有产物但无检查点时，按本技能逐阶段检查，再记录检查点。`pending` 或 `stale` 都需要处理；文件存在不等于已完成。规则变化时先审查受影响产物，仍符合规则则可重新记录检查点。旧任务的 `_correction_review.json`、`_stutter_review.json` 可作为迁移依据，核对最终订正稿后合并为当前格式的 `corrections.json`，保留原记录。
4. 同一视频由一个会话写入；共用 `.capture-profile/` 的浏览器操作和现有字幕抓取脚本应串行执行。发现已有会话正在处理相同视频时，避免同时改写。

## 工作流

### 1. 获取原始字幕

阅读 [acquisition.md](references/acquisition.md)，执行平台字幕获取；仅在确认平台无字幕时进入 ASR 分支。使用返回的真实视频 ID，检查标题、时长、章节及字幕首尾；获取失败不能当作空字幕成功处理。

```bash
python src/pipeline.py checkpoint <video_id> transcript
```

完成条件：`transcript.json` 结构、时间戳通过验证；覆盖率告警已核对，素材足以覆盖本次请求。

### 2. 订正字幕

阅读 [字幕订正规范](../../../prompts/correct_transcript.md)，处理全部字幕，生成 `transcript.corrected.txt` 和 `corrections.json`。先完成全文校读，再完成专门的口吃候选复核；逐段修改由 AI 判断。

```bash
python src/pipeline.py checkpoint <video_id> corrected
```

完成条件：规范中的校读要求已满足，逐段内容与修改记录通过机械核验。`transcript` 模式到此交付修正版及修改记录。

### 3. 编排电子书

阅读 [书籍编排规范](../../../prompts/stitcher_system.md)，依据订正稿写入 `book.tagged.md`，保留 `SCREENSHOT:HH:MM:SS` 标签；将相同内容复制到 `book.md` 供后续物化。重新编排时同时更新这两个文件，防止旧标签稿覆盖新内容。

```bash
python src/pipeline.py checkpoint <video_id> book
```

完成条件：内容覆盖用户请求，章节组织与术语一致，截图时间戳合法且位于相应内容区间。校验脚本只检查结构，内容质量由当前会话核对。

### 4. 截帧并物化

阅读 [capture.md](references/capture.md)，按可用环境选择截帧方式，补齐图片并将 `book.md` 中的标签替换为图片链接。保留 `book.tagged.md` 作为可重跑的原稿。没有需要插图的场景时可直接核验这一阶段。

```bash
python src/pipeline.py checkpoint <video_id> images
```

完成条件：截图引用均有实际图片，正文与标签稿对应，`book.md` 没有残留占位符；抽查关键截图确认清晰、时刻正确、无遮挡。

### 5. 渲染、验证和预览

```bash
python src/post_process.py "<VIDEO_URL>" output/<video_id>/book.md
python src/pipeline.py checkpoint <video_id> html
python src/pipeline.py status <video_id> --mode book
python src/pipeline.py serve <video_id>
```

`serve` 默认绑定本机 `127.0.0.1` 的可用端口，并打印实际 URL。使用当前环境的长驻终端/进程机制保持服务运行，记录会话句柄；确认 URL 可访问后再交付，不把长驻服务结束作为任务完成的前提。

完成条件：全部检查点有效，HTML 和图片可以访问，实际预览中的章节、代码、图表及图片无明显渲染问题。生成或修改页面时保持正文对比度至少 4.5:1。

## 交付与可选操作

- 返回实际的修正版字幕、Markdown、HTML 文件位置和本次预览 URL，指出未解决的字幕疑点或截图限制。
- 仅字幕模式返回该模式的产物。生成电子书默认到本地交付结束。
- 用户要求发布时才读取并执行 [publishing.md](references/publishing.md)；延续本次会话已经给出的发布授权。
- 音频/视频兜底文件默认保留供续跑，说明其位置。删除须有用户明确授权；已有授权时按其范围执行。
- 必须由用户完成登录或缺少执行权限时，保存已完成的检查点，说明具体阻碍及下一步。按当前宿主的工具权限执行，不通过提示词预设所有命令都要提权。
