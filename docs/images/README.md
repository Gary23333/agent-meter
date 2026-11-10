# README 演示截图

本目录的图片全部由 **AgentMeter v0.10.4 自带的离线预览**生成，采用虚构账户、虚构额度、虚构余额与虚构用量历史，**没有读取真实账户、私有日志或登录凭据**；来源名称与模型名仅用于展示界面。卡册与奖章进度同样来自虚构数据。

- `accounts-light.png` / `accounts-dark.png`：账户额度、重置卡、积分钱包、续费提醒。
- `usage-light.png` / `usage-dark.png`：本机 Token 构成、API 等价估算费用、按应用 / 模型排行与本周环比。
- `apps-light.png`：应用覆盖矩阵与最近会话。
- `collection-light.png` / `collection-dark.png`：收集册——卡册、46 枚奖章墙，以及「冲刺中」的实时发卡进度。
- `pet-light.png` / `pet-dark.png`：桌宠标签页（形象库、状态、今日读数）。
- `forecast-light.png` / `forecast-dark.png`：重置预测完整页面（Tibo 重置器、概率区间、承诺、倒计时、各站口径与历史记录），预测数据为虚构。
- `ticker-light.png` / `ticker-dark.png`：菜单栏行情条。
- `ticker.gif`：行情条滚动动画（浅色 / 深色菜单栏），由 `scripts/make-ticker-gif.py` 从 `ticker-light.png` / `ticker-dark.png` 生成，滚动速度为 App 的 3 倍以缩短循环。
- `themes-light.png` / `themes-dark.png`：七套界面风格对比（极简、原生、瓷白、极光、钛影、霓虹、棱镜，账户额度页）。
- `forecast-themes-light.png` / `forecast-themes-dark.png`：Tibo 重置器卡片的七套主题对比。
- `share-porcelain-portrait.png` / `share-titanium-portrait.png` / `share-prism-portrait.png`：三套主题的竖版用量分享卡（完整复盘模式）。

## 生成新的演示截图

在 macOS 上，从仓库根目录执行；需要已构建的 release App，构建入口见[根 README](../../README.md#方式二从源码构建原生应用)。

```sh
python3 scripts/make-demo-snapshot.py
'release/Agent 用量.app/Contents/MacOS/AgentMeterBar' --preview .runtime/readme-demo/snapshot.json .runtime/readme-demo/rendered
```

预览遍历当前标签页和七套主题；极光保留无前缀文件名，其余主题带各自名称前缀。分享卡输出为 `share-<主题>-compact.png`、`share-<主题>-review.png` 和 `share-<主题>-no-cost.png`。

`scripts/make-theme-sheet.py` 依赖 Pillow，会从预览目录拼接并覆盖 `themes-*.png` 与 `forecast-themes-*.png`，裁剪位置需随界面变化复核。`scripts/make-ticker-gif.py` 用于重新生成行情条动画。

> **预览必须离线**：`--preview` 走 `UsageStore.preview(_:)`，它把 `isPreview` 置位，使 `panelOpened()` 与 `bootstrap()` 都不会去连真实后端。渲染全部标签页与主题要好几分钟，早于刷新间隔也会触发面板刷新——若没有这道闸，预览会中途把演示数据换成用户自己的真实账户数据。

真实账户截图仍位于被忽略的 `docs/screenshots/`，不发布。这里只应提交检查过的虚构演示数据和图片。
