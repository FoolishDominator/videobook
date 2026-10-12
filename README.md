# VideoBook

在本项目中新开 Codex 会话，发送一个 YouTube 或 Bilibili 视频链接，即按项目工作流生成中文图文电子书。先获取字幕并按原语言订正，外文字幕随后逐段翻译成中文，再编排电子书、截帧和渲染。也可明确要求“只订正字幕”。字幕订正、翻译与书籍编排由当前 AI 会话完成，Python 脚本负责字幕获取、截帧、渲染和产物校验。

## 使用

1. 完成下面的一次性环境准备，在 Codex 中打开本项目并新建会话。
2. 直接发送视频链接，例如 `https://www.bilibili.com/video/BV.../`；需要限定语言、下载或交付范围时一并说明。
3. 助手执行流程，返回修正版字幕、需要翻译时的译稿、Markdown、HTML 和实际的本地预览地址。

项目根目录的 [AGENTS.md](AGENTS.md) 定义默认触发行为，[videobook Skill](.agents/skills/videobook/SKILL.md) 定义流程。代码讨论或示例中出现的视频链接不会启动生成。其他 AI 客户端需按其约定加载项目入口，或明确要求它读取该 Skill。

生成任务需要平台访问能力；首次登录、登录过期或缺少执行权限时，助手会说明需要用户完成的具体动作。当前会话恢复进度依据磁盘产物和检查点。

## 环境准备

使用 Python 3.12 或更新版本。依赖的唯一维护位置是 `pyproject.toml`，`uv.lock` 固定解析结果。推荐使用 uv：

```powershell
uv sync --locked
uv run python src/pipeline.py --help
```

没有 uv 时可使用标准虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe src/pipeline.py --help
```

后续文档中的 `python` 均指项目环境中的解释器，可替换为 `uv run python` 或 `.venv` 中的完整路径。

平台没有字幕、需要本地 ASR 时安装可选依赖：

```powershell
uv sync --locked --extra asr
# pip 环境对应：python -m pip install -e ".[asr]"
```

浏览器截帧需要已安装 Chrome；Linux 也支持 Chromium。登录、截帧与 cookies 工具共用同一浏览器选择，可用 `VIDEOBOOK_BROWSER_EXECUTABLE` 指定可执行文件路径。专用配置的一次性登录：

```powershell
uv run python src/capture_frames.py --setup-profile
```

在打开的 Chrome 中登录所需平台后关闭窗口。配置保存在 `.capture-profile/`。网络代理、ASR 与浏览器故障的处理方法按需见 Skill 的引用文档。

在线截帧优先使用播放器最高可用画质，并按解码后的原生尺寸保存。需要重截已有图片时使用 `python src/capture_frames.py <video_id> "<VIDEO_URL>" --recapture`；旧图会自动备份，实际画质、时间与失败原因写入该视频目录的 `capture.json`。详见[截帧说明](.agents/skills/videobook/references/capture.md)。

## 文件职责

| 位置 | 维护内容 |
| --- | --- |
| `AGENTS.md` | 默认任务路由和项目约定 |
| `.agents/skills/videobook/SKILL.md` | 阶段、完成条件、恢复和交付 |
| Skill 的 `references/` | 字幕获取、截帧与发布的条件分支 |
| `prompts/correct_transcript.md` | 保留原话的字幕订正规范与修改记录格式 |
| `prompts/translate_transcript.md` | 逐段翻译、语言记录与译稿复核规范 |
| `prompts/stitcher_system.md` | 书面化电子书、章节和插图规范 |
| `src/` | 可重复执行的机械操作与验证 |
| `output/<video_id>/` | 每个视频的素材、检查点与成品 |

## 检查、恢复与预览

```powershell
python src/pipeline.py status <video_id>
python src/pipeline.py status <video_id> --mode transcript
python src/validate.py <video_id> --stage html
python src/pipeline.py serve <video_id>
```

`status` 只读检查 `run.json` 与实际文件，报告首个待处理阶段；无记录为 `pending`，已记录但上游、提示词或产物变化为 `stale`。阶段完成后由助手执行 `checkpoint`，校验成功才记录。已有旧成品不会自动改写；首次接入时逐阶段审查，再补齐修改记录和检查点。

`serve` 只绑定本机，默认自动选择可用端口，避免多视频预览争用固定端口；输出实际 URL，按 `Ctrl+C` 关闭。也可显式指定 `--port 8080`。服务应保持在长驻终端中。

## 产物与发布

完整流程生成 `transcript.corrected.txt`、`corrections.json`、`translation.json`、`book.tagged.md`、`book.md`、`images/` 和 `book.html`。需要翻译时另存 `transcript.translated.txt`，保留原语言订正稿；无需翻译时在 `translation.json` 记录相同的源语言和目标语言并沿用订正稿。`run.json` 记录检查点；原始字幕供追溯与恢复。每次生成或发布验证完成后执行[清理约定](.agents/skills/videobook/references/cleanup.md)，将临时截图、下载媒体等送入系统回收站。`python src/cleanup.py <video_id>` 预览清单，添加 `--apply` 执行。旧任务恢复时需补齐 `translated` 阶段并复核后续产物，已有成品保留。

本地生成完成后，需要发布时明确告诉助手。每次发布前确认目标仓库、分支、公开地址和内容范围；不默认使用历史 Lessons 地址。本仓库用于生成笔记。发布命令必须通过 `--site-repo`、`--public-base-url` 和 `--content-dir` 指定目的地，`--site-branch` 指定已确认的分支；操作见 [发布说明](.agents/skills/videobook/references/publishing.md)。原创摘要可用 `--exclude-transcripts` 排除字幕附件，但仍须人工复核正文。

发布后的笔记按课程和固定课时目录组织，修改标题保留网址。课程归属与已有站点迁移统一由发布脚本维护，具体命令见上述发布说明。

## 开发检查

```powershell
python -m unittest discover -s tests
```

检查覆盖字幕修改追溯、译稿对应关系与版本、缺图与占位符、检查点失效和本地预览。实际字幕获取、登录画质和 AI 编辑质量需要在生成任务中验证。

浏览器截帧回归测试使用本地生成的视频检查就绪等待、页面重试、画质菜单和原生尺寸；安装 Chrome 时自动运行，无 Chrome 时跳过，不访问在线视频。

## 云端运行

云端准备、CPU ASR、Windows/Linux 可恢复清理、逐次确认发布地址与内容权限检查见 [Cloud operations](docs/CLOUD_OPERATIONS.md)。浏览器受宿主权限限制时保留检查点并报告，不绕过安全限制。
