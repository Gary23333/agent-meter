# v0.9.4 发布说明

2026-10-29 发布；App 内部版本为 0.9.4。适用于 macOS 14+、Apple Silicon（arm64）。

## DeepSeek 峰谷定价迁入账户卡

- 「峰谷定价」从「本机消耗」页移到「账户额度」页的 DeepSeek API 卡内，只汇总各本机账本中的 DeepSeek 系模型（Claude Code、Codex、WorkBuddy、OpenCode、ZCode、DeepSeek Harness 等），其他模型不再混入卡片。
- 卡片内提供今日 / 7 天 / 30 天 / 全部切换，与「本机消耗」页共用同一时间段设置；展示峰时 / 谷时 Token、DeepSeek 专属金额、谷时占比与已拆分比例，并提示没有请求时刻的账本按谷价估算。
- CC Switch 只有日汇总、其自带估价不分峰谷，仍不并入金额行，只在卡片内点名说明。

## 按模型拆分峰谷金额

- 本地价格表估算的每个 period 新增 `peak_models` / `offpeak_models`（按原始模型名的非零峰/谷金额），供前端只取 DeepSeek 模型的金额。
- `agent_meter verify` 增加按模型峰谷金额的独立重算对账。

## 验证

- Python 3.14 全量 306 项单元测试通过。
- `python3 -m agent_meter verify`：2,242 项检查；新增 80 项按模型峰谷对账全部通过。失败项为 ZCode 当日文件在采集后继续写入造成的 20 项 token 差异，以及既有的 `codex_local.ccswitch_cross` 漂移，均与本次改动无关。
- Swift 构建通过；极光、霓虹、原生、棱镜、钛金等主题的离线预览确认卡片内布局正常，「本机消耗」页不再显示旧峰谷卡。
- Developer ID Application 签名、Apple 公证与 DMG 装订完成；`codesign --verify --deep --strict`、`spctl`、`stapler validate`、`hdiutil verify` 与 SHA256 校验均通过。
- 内嵌 Python 3.14 后端的 relocate 冒烟测试通过（synthetic collect/verify、认证 HTTP API、token 权限）。
