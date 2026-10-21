# v0.8.3 发布说明

2026-10-21 发布；App 内部版本为 0.8.3。适用于 macOS 14+、Apple Silicon（arm64）。

## 修复：分享卡风格点不动

0.8.2 的报告窗口把 `ReportView` 手动挂到 `window.contentView`，没有设置 `contentViewController`；AppKit 桥接的系统分段控件因此收不到点击（纯 SwiftUI 手势却正常），表现为「极简 / 原生」点了没反应。

- 窗口改用 `NSHostingController` 挂载，桥接控件恢复正常的点击与动作分发。
- 风格切换从系统 `Picker(.segmented)` 换成纯 SwiftUI 的 `PillTabs`，与其他页签交互一致，也不受桥接层影响。

## 修复：刚打开窗口时切换风格要等一会儿

- 报告窗口打开时立即抢焦点：`NSApp.activate` + `NSRunningApplication.current.activate` + `makeKey`，并在下一轮 runloop 与 0.15 秒后各补一次。
- 实测窗口在 +100ms 与 +800ms 时均已是激活态，点击风格到预览更新约 186–189ms；修复前约 2 秒内点击会被吞掉。

## 验证

- `swift build` 通过；`--preview` 正常产出报告窗口截图与 4 张竖版分享卡（1080×1071 ~ 1080×1221）。
- 合成点击回归：打开后立即切换四套风格，预览均正确刷新，无崩溃。
