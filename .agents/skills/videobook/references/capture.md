# 截帧与图片物化

浏览器路径直接截取平台播放器，不下载媒体文件。只有浏览器方法全部不可用或失败时，才使用下面明确允许的下载兜底；用户要求禁止下载时跳过该分支。

## 选择路径

1. 桌面环境中，若已连接真实 Chrome 的浏览器扩展，优先用其控制已登录播放器。遵循当前环境浏览器工具的操作和文件导出能力；工具不能可靠保存截图时使用下一条路径。
2. 否则运行专用配置截帧脚本。
3. 上述可用浏览器方法都失败或环境没有浏览器时，执行下载兜底。

每次失败记录实际原因；不通过降低清晰度要求把未登录的干净浏览器当作已登录 Chrome。

## 浏览器扩展

读取 `book.tagged.md` 中的时间戳，打开相应播放器，定位目标秒、等待渲染并暂停后，保存纯视频区域为 `images/shot_HH_MM_SS.png`。平台地址示例：

- B 站：`https://player.bilibili.com/player.html?bvid=<id>&t=<seconds>&autoplay=1&high_quality=1&danmaku=0`
- YouTube：`https://www.youtube.com/embed/<id>?start=<seconds>&autoplay=1`

地址参数不保证实际画质或定位成功，以播放器状态和图像检查为准。图片保存完成后运行：

```bash
python src/capture_frames.py <video_id> --materialize-only
```

## 专用配置脚本

```bash
python src/capture_frames.py <video_id> "<VIDEO_URL>"
```

脚本使用 `.capture-profile/`，先无头运行，失败后尝试有头模式；读取标签稿中的时间戳、补齐缺失帧并物化图片链接。首次初始化使用 `--setup-profile`；自定义目录使用 `--profile-dir <path>`。

专用配置与用户日常 Chrome 分开。当前实现对 B 站有画质探测与流选择逻辑；其他平台的实际清晰度仍需检查。不要把登录会员等级直接当作本次截图的分辨率证明。

抽查幻灯片和演示画面，核对时间、清晰度、遮挡。脚本的文件大小检查只能筛出部分异常，不替代目视检查。更换登录账号或需要重截已有图片时，先将相关旧图片移入该视频目录的备份子目录，再重跑；当前脚本会跳过已经存在的图片。

## 下载兜底

```bash
python src/extract_frames.py <video_id> "<VIDEO_URL>"
```

缺少 `video_source.mp4` 时下载源视频，再使用 ffmpeg 抽帧。清晰度受可获取视频流限制，交付时说明实际情况。媒体文件保留供续跑，清理由主工作流的授权约定处理。

## 完成核验

- 标签稿保持可复用，`book.md` 中每个标签替换成对应本地图片。
- 新写或修改标签稿后，将其复制到 `book.md` 再物化，避免两份正文漂移。
- `checkpoint ... images` 检查图片存在、PNG 文件头、时间戳与正文对应；目视质量由当前会话核验。
- 源内容确实没有需要截图的场景时，两份 Markdown 可相同，无需调用会拒绝空标签列表的截帧脚本。
