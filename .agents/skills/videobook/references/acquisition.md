# 字幕获取与 ASR

## 平台字幕

```bash
python src/dump_transcript.py "<VIDEO_URL>"
```

脚本输出真实视频 ID，将素材写入 `output/<video_id>/transcript.json`。字段为 `video_url`、`title`、`video_id`、`duration`、`chapters` 和 `segments`；每段包含 `start`、`end`、`text`。

- B 站在 `.capture-profile/` 有登录态时自动导出临时 cookies。首次登录或登录过期时使用 `python src/capture_frames.py --setup-profile`，由用户在打开的 Chrome 中登录并关闭窗口。
- 指定其他配置可使用 `--cookies-from-profile <dir>`；已有 Netscape 文件可用 `--cookies-file <path>`。Windows 主 Chrome 的 cookies 解密方式受版本影响，默认使用专用配置。
- YouTube 的终端请求与浏览器播放分别需要可用网络；存在代理要求时沿用用户已经配置或指定的代理。
- 获取脚本返回 3 表示字幕末端覆盖率低于 50%，先排查素材不完整。该比例只是末段结束时间 / 视频时长，不证明中间没有缺段；同时检查首尾与中间明显空缺。
- 标题/视频 ID 未识别、时长缺失时先恢复元数据；不要把 `Unknown_ID` 作为正常视频目录继续生成。

登录、网络、地区限制与无字幕是不同分支。无字幕的证据包括平台字幕列表为空，或 yt-dlp 仅列出弹幕；不要仅因非零退出码就下载音频。

## ASR 分支：已确认平台没有字幕

此分支需要下载音频；若用户禁止媒体下载，说明缺少字幕的阻碍并请求其提供字幕。其他情况下按以下步骤继续：

1. 安装项目的 `asr` 可选依赖，见根目录 README。
2. 根据视频主题把术语提示写入 `output/<video_id>/_asr_prompt.txt`。保持简短；避免在 PowerShell 参数中传递长中文提示。
3. 在视频时长内选择一个短区间试跑，例如 `--sample-start 0 --sample-dur 180`。试跑会写 `_asr_progress.jsonl`，不写完整字幕。

```bash
python src/asr_transcript.py "<VIDEO_URL>" --sample-start 0 --sample-dur 180
python src/asr_transcript.py "<VIDEO_URL>" --restart
```

试跑后首次全量转写使用 `--restart`；全量任务中断后重跑不加该参数，以续接进度。不要在完整转写中途再次试跑：试跑会清空原进度。

- 非中文视频显式传入匹配的 `--language`；当前脚本默认中文。修正版字幕保留原语言，电子书阶段再按用户要求翻译。
- GPU/CPU 与计算类型由脚本选择，必要时通过 `--device`、`--compute-type` 指定。只有出现 CUDA DLL 缺失时才安装对应 NVIDIA 运行库。
- 全量完成后核对覆盖率、起始段和结尾段，再记录 `transcript` 检查点。ASR 字幕同样执行订正流程。
- 音频及进度缓存保存在视频目录；cookies 为系统临时文件，用完即删，不作为交付物或发布物。

## 失败与恢复

保留命令的实际错误及已完成产物。修复可定位的配置问题后重试；同样条件下重复失败时停止该阶段并说明缺失条件。原始素材尚未有效时，不推进订正阶段。
