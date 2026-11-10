# E 组功能契约（2026-11-08）

预算提醒（E1）、项目归因（E2）、周报环比（E3）、状态面板与省资源（E4）。后端均已合入；端点接线与 Swift UI 随本轮发布完成。验收数字见[批次验收](harness-batch-acceptance-2026-11-08.md)。

## daily_models（E3 基础，所有本机账本）

tokens 指标新增 `daily_models`：`[{date, model, app?, requests, fresh_input, output, reasoning, cache_read, cache_write, total_tokens, unclassified?}]`，与 `daily_buckets` 同一次遍历产生，verify 强制两者逐日相等。覆盖路径：cli_sessions（codex/claude/gemini/mcode/dsh/agy）、opencode 家族（opencode/mimo_code/deveco）、kimi/kimi_desktop/kimi_legacy、zcode_local、workbuddy、design、imported_history（detail 行按时刻、daily 行按日期，逐行带 app）。无请求时刻的导入日汇总行不可拆峰谷。

## GET /v1/periods/week 与 /v1/periods/month（E3）

`agent_meter/report_periods.py`。自然周（周一始）/自然月，北京时间；当期截至现在（部分周期），上期为完整周期。输出 current/previous（tokens、requests、分项、days_with_data、cache_hit_rate、cost_cny、by_app、by_model、unmatched_models）、delta（百分比，上期为 0 时 null）、top_movers、sources_without_daily_detail。费用按价格表基准（谷时）价估算，`basis=daily_rollup_base_price_no_peak_split` 明示，不是账单。本机首验：95 个项目账本全有逐日分项，周/月环比可算。

## GET /v1/projects（E2）

`agent_meter/projects.py`。只归因有明确项目路径的账本：ZCode/OpenCode/MiMo Code/DevECo（session.directory）、dsh v3/v4（header cwd）；其余全部进 unattributed，绝不从正文或编码目录名猜。输出 projects[]（project_path、tokens、requests、apps、models）、attributed/total/unattributed（含 by_app）、sources_scanned、source_gaps。不变量：attributed + unattributed = 本机消耗全部周期总量（application_usage 同口径）。本机首验：95 个项目、归因 10.82B / 总 39.42B token，无扫描缺口。**项目路径敏感：分享必须用用户别名（前端 UserDefaults），接口只在本机回环提供。**

## GET /v1/status 与省资源模式（E4）

`agent_meter/status.py` 投影快照：各来源 status/reason/observed_at/last_error、stale 列表、未计价模型并集、禁用列表、缓存 TTL、是否缓存命中。preferences 新增：

- `low_resource_mode`（bool）：快照缓存 TTL ×3；活动端点节奏不变（本就轻量）。
- `skip_ledgers_low_resource`（来源 id 列表）：仅低资源模式下生效，跳过的来源标 `skipped_low_resource`（not_connected），与用户关闭（disabled_by_user）区分；开关优先级：用户关闭 > 低资源跳过。

## GET/PUT /v1/budget（E1）

见 budget.py 实现与测试：日/周预算（CNY）、异常倍率；事件 id 稳定供通知去重；未知≠0。