# README 演示截图

首页演示截图最初由 AgentMeter v0.9.1 自带离线预览生成，采用虚构账户、积分、额度和 Token 历史。没有读取真实账户、私有日志或登录凭据；来源名称与模型名仅用于展示界面。

- `accounts-light.png` / `accounts-dark.png`：账户额度、重置卡、Token 趋势与积分钱包。
- `usage-light.png` / `usage-dark.png`：本机 Token 构成、估算费用、应用和模型排行。
- `apps-light.png`：应用覆盖矩阵。
- `ticker-light.png`：菜单栏行情条。
- `ticker.gif`：行情条滚动动画（浅色 / 深色菜单栏），由 `scripts/make-ticker-gif.py` 从 `ticker-light.png` / `ticker-dark.png` 生成，滚动速度为 App 的 3 倍以缩短循环。
- `themes-light.png` / `themes-dark.png`：七套界面风格对比（极简、原生、瓷白、极光、钛影、霓虹、棱镜，账户额度页）。
- `forecast-light.png` / `forecast-dark.png`：重置预测完整页面（Tibo 重置器、概率区间、承诺、倒计时、各站口径与历史记录），预测数据为虚构。
- `forecast-themes-light.png` / `forecast-themes-dark.png`：Tibo 重置器卡片的七套主题对比。
- `share-porcelain-portrait.png` / `share-titanium-portrait.png` / `share-prism-portrait.png`：三套新主题的竖版用量分享卡。

## 生成新的演示截图

以上保留 v0.9.1 截图的来源说明，不代表当前版本的全部界面。以下命令按当前代码生成新预览，不保证逐像素复刻历史截图；替换公开图片时请同时更新其版本和来源说明。

在 macOS 上，从仓库根目录执行；需要已构建的 release App，构建入口见[根 README](../../README.md#方式二从源码构建原生应用)。

```sh
python3 scripts/make-demo-snapshot.py
'release/Agent 用量.app/Contents/MacOS/AgentMeterBar' --preview .runtime/readme-demo/snapshot.json .runtime/readme-demo/rendered
```

预览遍历当前标签页和七套主题；极光保留无前缀文件名，其余主题带各自名称前缀。当前分享卡输出为 `share-<主题>-compact.png`、`share-<主题>-review.png` 和 `share-<主题>-no-cost.png`，不同于历史保存的 `share-*-portrait.png`。

检查输出后，再按需要复制到本目录；不要批量覆盖历史图片。`scripts/make-theme-sheet.py` 依赖 Pillow，会从预览目录拼接并覆盖 `themes-*.png` 与 `forecast-themes-*.png`，裁剪位置需随界面变化复核。`scripts/make-ticker-gif.py` 用于重新生成行情条动画。

真实账户截图仍位于被忽略的 `docs/screenshots/`，不发布。这里只应提交检查过的虚构演示数据和图片。
