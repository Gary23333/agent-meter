# v0.8.2 发布说明

2026-10-21 发布；App 内部版本为 0.8.2。适用于 macOS 14+、Apple Silicon（arm64）。

## 修复：点击分享导致崩溃

0.8.0 / 0.8.1 的报告窗口在 `body` 里用 `NSHostingView` 量分享卡高度，等于在一次 SwiftUI 布局中再嵌套一次宿主视图布局，触发 `AttributeGraph precondition_failure` 并 SIGABRT，点开分享即崩溃。

- 预览高度改为纯 SwiftUI 测量（`GeometryReader` 背景 + `PreferenceKey`），全程不创建宿主视图。
- PNG 导出改为 `ImageRenderer` 固定宽度、高度留空，由卡片自身理想高度决定，不再预先量高。

## 调整：分享卡只保留竖版

- 分享卡统一为竖版，宽度固定 540（2x 输出 1080），高度随内容自适应（实测约 1071–1221 px）。
- 移除横版布局与相关尺寸分支；报告窗口的尺寸标签、预览占位与 `--preview` 产物同步更新。

## 性能

- **报告窗口**：一次 `body` 只聚合一次 `ReportData`（此前预览、明细、底部栏各算一遍，单次刷新约 4 次聚合），缩放测量触发二次刷新时也不会重复聚合。
- **MiniMax Code 读取**：改为 SQLite JSON1 在库内取出 `context_usage_telemetry.model`，不再把整条消息（含工具输出）搬进 Python；并按数据库 mtime+size 缓存解析结果，直读账本与 CC Switch 回填共用同一份，实测该路径由约 `77ms × 2` 降至约 `48ms × 1`。

## 验证

- 单元回归全部通过（含 MiniMax Code 模型还原、CC Switch 回填与定价、分享报告渲染）。
- `--preview` 正常产出 4 张竖版分享卡（1080×1071 ~ 1080×1221）与报告窗口截图，无崩溃。
