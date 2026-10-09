# v0.3.1 · Agent 用量

2026-10-09 发布；App 内部版本为 0.3.1。适用于 macOS 14+、Apple Silicon（arm64）。

## 改进

- **顶部仪表合并**：同一账户的多个额度窗口合成一个同心圆仪表（外圈 5 小时、内圈 7 天，月度窗口为第三圈），下方按余量颜色列出各窗口剩余；单窗口账户保持单圈。调用次数类额度（如 ZCode MCP 月度次数）不进圈，只在账户卡片显示。四套界面风格均适配。
- **火山方舟 Coding Plan 支持控制台登录**：新版控制台只给方舟 API Key，而它无法查询用量。现在可在「连接网页账户」登录火山引擎控制台并停在 Coding Plan 订阅页，App 记下页面自身的 `GetCodingPlanUsage` 请求（地址与 CSRF 头）和登录 Cookie，后端只回放这一个允许的查询，不需要任何密钥、不消耗额度，最多 5 个账号。仍可填写访问控制里的 AccessKey；误填方舟 API Key 时直接提示。

## 修复

- 火山方舟：重置时间为 `-1` / `0` / 字符串、或单个窗口百分比缺失时不再整张卡「读取失败」，只略过该值或该窗口。
- 即梦多账号：后台读取按登录顺序逐个上报，某个账号未读到数据时保留它自己的卡片并提示重新登录，不再被下一个账号顶替（此前两个账号只显示一个，连接窗口的状态也会对错号）。
- 火山、MiMo 返回格式无法解析时，诊断信息只记录字段名与类型（不含任何值），便于定位。

## 验证

- Python 后端回归：163 项全部通过。
- Swift release 编译通过；DMG 校验与 App 深度签名检查通过；内嵌后端合成数据冒烟测试通过。
- 真实账户：火山方舟（控制台登录，5 小时 / 每周 / 每月三个窗口）、两个即梦账号（各自成卡）已在本机读取成功；ZCode 与 MiMo 沿用 v0.3 的已验证路线。

## 已知限制

ad-hoc 签名，未做 Apple 公证；升级后钥匙串会再次询问，请选择「始终允许」。仅发布 arm64。

## 重建

```sh
python3 -m pip install -r requirements-build.txt
sh scripts/build-dmg.sh
python3 scripts/smoke-release.py 'release/Agent 用量.app/Contents/Resources/backend/agent-meter-backend' .runtime/synthetic-snapshot.json
```
