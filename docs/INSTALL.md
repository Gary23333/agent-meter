# Agent 用量 v0.3.1 安装说明

适用系统：macOS 14 或以上，Apple Silicon（arm64）。

1. 打开 DMG，将「Agent 用量.app」拖到 Applications。
2. 从 Applications 启动，顶部菜单栏会出现小组件。
3. 在设置菜单中连接网页账户或填写 API 密钥；本机已有客户端的用量会自动发现。

应用包含 Python 后端，无需安装 Python、Xcode 或下载项目源码。各供应方的本机 CLI、桌面客户端或登录态仍需用户自行安装/连接；缺少来源时显示未接入。未知值不按零计算，不同账户余额不合计。

当前发布使用 ad-hoc 签名，尚未做 Apple 公证。如果系统阻止首次打开，在「系统设置 → 隐私与安全性」中查看对应提示并允许打开。升级后钥匙串可能再次询问访问权限。

应用数据和日志位于 ~/Library/Application Support/AgentMeter/.runtime/；网页登录凭据保存在 macOS 钥匙串。删除应用不会自动删除上述数据。

源码开发方式、功能范围和接入限制见仓库 README.md、menubar/README.md。
