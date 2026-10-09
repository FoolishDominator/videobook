# 发布到 GitHub Pages

仅在用户要求发布时读取。先确认所选视频的 `html` 检查点有效，然后检查当前目录确实是 Git 仓库、`origin` 是用户预期的远端。

```bash
python src/pipeline.py status <video_id> --mode book
git remote -v
python src/publish.py <video_id>
git push origin pages
```

只发布请求中的视频；用户明确要求全部发布时才用 `--all`。已有发布授权时无需重复询问。

脚本把 `book.html`、`book.md`、`images/` 及存在的 `transcript.corrected.txt` 提交到独立 `pages` 分支，目录以视频标题命名。原始字幕、任务状态、修改记录和媒体缓存不发布。推送和站点部署成功是两个不同结果，应核实实际阅读地址再宣告上线。

首次使用需要仓库在 GitHub Pages 中配置 `pages` 分支和根目录。缺少 Git 元数据、远端或权限时保留本地成品并说明阻碍，不自动创建仓库或改变远端。
