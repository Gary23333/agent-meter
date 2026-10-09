# v0.2 · Agent 用量

2026-10-09 发布；App 内部版本为 0.2.0。适用于 macOS 14+、Apple Silicon（arm64）。

## 新增

- **四套界面风格**：极简、原生、极光（默认）、霓虹，从极其简洁到极其绚丽。面板标题栏的调色板按钮或设置菜单「界面风格」切换，立即生效并记住选择；网页账户窗口跟随同一风格。
  - 极简：黑白排版，无卡片、无阴影，额度紧张时才出现颜色。
  - 原生：macOS 系统实色卡片与系统色。
  - 极光：v0.1 的毛玻璃与彩色光斑。
  - 霓虹：固定深色，彩虹描边、HUD 角标、分段 LED 进度条与刻度环；背景旋转光与扫描光带由 Core Animation 驱动。
- **供应商卡片统一**：所有来源按同一顺序展示：额度窗口 → 余额与积分包 → 积分更新 → 重置卡（明细紧跟其后）→ 续费 / 会员到期 → Token。
  - 单个与多个额度窗口统一为进度条，按窗口长度从短到长排列（顶部仪表和菜单栏行情同序）；「1 周」统一写作「7 天」。
  - 积分更新、续费、会员到期的倒计时按紧急程度着色（3 天内标橙），不再按品牌色。
  - 积分包作为余额的子项缩进显示；英文单位 credits 显示为「积分」。
- 离线预览 `--preview` 输出全部风格；README 截图更新并新增风格对比图。

## 验证

- Python 后端回归：137 项全部通过。
- Swift release 编译通过；仍有既有 WebKit actor 隔离及闭包捕获警告。
- DMG 校验通过，App 深度签名检查通过。
- 内嵌后端用合成数据冒烟测试通过：collect、verify、认证 HTTP API、token 文件权限。
- 用演示快照离线预览四套风格的账户、本机消耗、应用覆盖页（浅色 / 深色），界面正常生成。

霓虹风格的动态背景在离线预览中以静态渐变代替；动画仅在实际弹出的面板中运行。

## 已知限制

与 v0.1 相同：ad-hoc 签名，未做 Apple 公证，首次打开可能需要在系统设置中允许，升级后钥匙串可能再次询问；仅发布 arm64。各来源仍需对应客户端或登录态。

## 重建

```sh
python3 -m pip install -r requirements-build.txt
sh scripts/build-dmg.sh
python3 scripts/smoke-release.py 'release/Agent 用量.app/Contents/Resources/backend/agent-meter-backend' .runtime/synthetic-snapshot.json
```
