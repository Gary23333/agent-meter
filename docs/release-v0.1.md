# v0.1 · Agent 用量

2026-10-09 发布；App 内部版本为 0.1.0。适用于 macOS 14+、Apple Silicon（arm64）。

## 发布内容

- Swift 原生菜单栏应用：账户额度、重置时间、积分、Token 用量、通知及多账号连接。
- 内嵌独立 Python 后端，安装后无需 Python、Xcode 或源码目录。
- 应用数据保存在 `~/Library/Application Support/AgentMeter/.runtime/`，网页登录/API 凭据使用钥匙串。
- 源码按后端、前端、构建脚本、测试、文档、示例和发布产物组织。缓存、真实账户快照及截图不上传。
- DMG 和 SHA256SUMS 作为 GitHub Release 资产提供；二进制不进入 Git 历史。

## 验证

- Python 后端回归：137 项全部通过。
- Swift release 编译通过；当前工具链仍有既有 WebKit actor 隔离及闭包捕获警告。
- DMG 校验通过；挂载后复制到独立目录，App 深度签名检查通过。
- 使用合成 CC Switch 数据、最小 PATH 测试内嵌后端：collect、verify、本机 HTTP health/snapshot、拒绝未认证请求和 token 文件权限均通过。
- 从独立路径运行 App 离线预览，账户、本机消耗、应用覆盖和连接界面正常生成。

这些检查验证打包与已有回归，不代表所有供应方都已完成真实账户端到端验收。

## 已知限制

当前为 ad-hoc 签名，未做 Apple 公证。首次打开可能需要在系统设置中允许；升级后钥匙串可能再次询问。

各来源需对应客户端/CLI 或网页登录态；数据不足时显示未接入/未知。账户额度与本机消耗分别保留，不同供应方积分不能直接相加。仅发布 arm64 架构。

## 重建

```sh
python3 -m pip install -r requirements-build.txt
sh scripts/build-dmg.sh
python3 scripts/smoke-release.py 'release/Agent 用量.app/Contents/Resources/backend/agent-meter-backend' .runtime/synthetic-snapshot.json
```
