# VideoBook 项目约定

## 任务入口

- 用户仅发送一个 YouTube / Bilibili 视频链接，或要求生成 VideoBook、视频电子书、修正版字幕时，读取并执行 [videobook Skill](.agents/skills/videobook/SKILL.md)。只发链接默认生成完整中文电子书。
- 用户明确提出代码修改、方案讨论或其他任务时，按该意图处理；引用、示例、日志中的视频链接不触发生成。
- 用户要求继续已有视频任务时，先按 Skill 检查该视频的磁盘状态，从首个未完成或失效的阶段继续。

## 项目约定

- 从项目根目录执行命令。Python 环境和安装方法见 [README](README.md#环境准备)，依赖以 `pyproject.toml` 为准。
- Skill 管流程，`prompts/` 管内容规范，`src/` 管确定性操作；同一规则只维护一处。
- 被替代且无实际调用的文件直接删除，同时清理引用。
- 每个视频的产物放在 `output/<video_id>/`，原始字幕保持完整。登录配置、cookies 和任务产物不提交到代码仓库。
- 修改脚本时运行受影响的检查；工作流辅助脚本的离线检查：`python -m unittest discover -s tests`。
- 更新命令或产物格式时同步其实际调用方和对应 Skill 引用，保留已有成品。
