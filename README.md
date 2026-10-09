# VideoBook

在本项目中新开 Codex 会话，发送一个 YouTube 或 Bilibili 视频链接，即按项目工作流生成中文图文电子书。也可明确要求“只订正字幕”。字幕订正与书籍编排由当前 AI 会话完成，Python 脚本负责字幕获取、截帧、渲染和产物校验。

## 使用

1. 完成下面的一次性环境准备，在 Codex 中打开本项目并新建会话。
2. 直接发送视频链接，例如 `https://www.bilibili.com/video/BV.../`；需要限定语言、下载或交付范围时一并说明。
3. 助手执行流程，返回修正版字幕、Markdown、HTML 和实际的本地预览地址。

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

浏览器截帧需要已安装 Chrome。专用配置的一次性登录：

```powershell
uv run python src/capture_frames.py --setup-profile
```

在打开的 Chrome 中登录所需平台后关闭窗口。配置保存在 `.capture-profile/`。网络代理、ASR 与浏览器故障的处理方法按需见 Skill 的引用文档。

## 文件职责

| 位置 | 维护内容 |
| --- | --- |
| `AGENTS.md` | 默认任务路由和项目约定 |
| `.agents/skills/videobook/SKILL.md` | 阶段、完成条件、恢复和交付 |
| Skill 的 `references/` | 字幕获取、截帧与发布的条件分支 |
| `prompts/correct_transcript.md` | 保留原话的字幕订正规范与修改记录格式 |
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

完整流程生成 `transcript.corrected.txt`、`corrections.json`、`book.tagged.md`、`book.md`、`images/` 和 `book.html`。`run.json` 记录检查点；原始字幕和下载兜底文件供追溯与恢复。

本地生成完成后，需要发布时明确告诉助手。发布要求目录具有 Git 元数据和预期远端，操作见 [发布说明](.agents/skills/videobook/references/publishing.md)。

## 开发检查

```powershell
python -m unittest discover -s tests
```

检查覆盖字幕修改追溯、缺图与占位符、检查点失效和本地预览。实际字幕获取、登录画质和 AI 编辑质量需要在生成任务中验证。
