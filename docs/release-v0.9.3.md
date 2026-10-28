# v0.9.3 发布说明

2026-10-28 发布；App 内部版本为 0.9.3。适用于 macOS 14+、Apple Silicon（arm64）。

## 修复 Codex 间歇性“读取失败”

- 实测 `codex app-server` 的 `account/rateLimits/read` 在健康网络下也要 15–25 秒，而旧版沿用全局 20 秒超时，导致间歇性 `rpc_timeout`，卡片显示“读取失败”。
- Codex 改用独立 `codex_timeout_seconds`（默认 45 秒，且不低于全局超时），不再被通用 20 秒误判。
- 成功读取后缓存最后一次账户指标（仅归一化结果，不保存 `accountId`、重置卡 ID 或原始响应）；24 小时内出现瞬时超时/断连时，来源以 `stale` 返回缓存值，界面显示“旧数据”和上次采样时间，而不是整卡失败。

## 减少无效等待

- `account/usage/read` 当前会被上游以 `token usage profile fetch timed out` 拒绝。该结果单独缓存：成功值 6 小时、错误 1 小时，避免每轮快照都白等约 10 秒。
- 该缓存只影响账户卡的“账户累计 Token”行，不影响本机 token 历史和其他来源。

## 错误文案

- `rpc_timeout`、`rpc_disconnected`、`rpc_request_failed`、`rpc_method_unavailable` 改为中文说明，保留具体错误码供排查。

## 验证

- Python 3.14 全量 306 项单元测试通过。
- 新增测试覆盖：瞬时超时回退到最后成功账户、缓存不包含原始账户 ID、usage 成功/失败缓存窗口。
- 真实 Codex 读取复测：`rateLimits` 正常返回；`usage` 上游超时时不再阻断账户卡。
- Swift 构建通过；Developer ID 签名、Apple 公证与 DMG 装订完成。
