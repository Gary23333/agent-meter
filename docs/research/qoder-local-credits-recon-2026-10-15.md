# Qoder 系列本机用量勘察（2026-10-15）

勘察日期：2026-10-15（Asia/Shanghai）。全部为本机只读勘察：未安装或运行第三方统计应用，未修改任何 Qoder 数据，未发送任何网络请求，未读取任何凭据明文。

勘察范围：Qoder CN CLI（`~/.qoder-cn`）、Qoder CN IDE（`~/Library/Application Support/com.qodercn.app.stable`、`QoderCN`）、Qoder 全球版（`~/.qoder`、`~/.qoder-cli`、`~/.qodersec`）。本机安装 `Qoder CN.app` 与 `Qoder CN IDE.app`。

## 结论（按证据等级）

1. **Token 用量采不到，且本地明确不提供。** Qoder CN CLI 会话日志（Claude Code 兼容格式）8,896 条 usage 记录中，`input_tokens / output_tokens / cache_creation_input_tokens / cache_read_input_tokens` 全部为 0（无一条例外，另搜遍 `usageMetadata`/`tokens`/`token_count` 等模式无其他 token 来源，唯一命中是用户自己写的知识库 ingest 代码文本）；IDE `chat_session_context_usage.snapshot_json` 中 `totalTokens=0`、`tokenCountsAvailable=false`、`apiUsage=null`；全球版 `~/.qoder/projects` 仅 transcript，无 usage。按"未知值不等于零"原则，这些 0 是未提供，不是零消耗，不能据此宣称"Qoder 零用量"。
2. **积分（credits）账本真实存在，可采集。** `~/.qoder-cn/projects/**/*.jsonl` 每条 assistant 请求的 `message.usage` 带 `credits`、`original_credits`、`billable`、`request_id`、`context_usage_ratio`、`model`。这是本机唯一经过真实数据验证的 Qoder 用量信号，可构成 `local_session_history` 来源。
3. **账户额度两条路维持原状。** 安装版 SDK `getUsageInfo()` 初始化失败（与 2026-10-09 结论一致，未复测）；网页接口 `GET https://qoder.com.cn/api/v2/me/usages/big_model_credits` 契约来自 CodexBar 定版源码，本机网页登录态仍未实测。

## 积分账本明细（真实只读聚合）

来源：`~/.qoder-cn/projects/**/*.jsonl`，136 个文件中 108 个带账本（含 81 个 `subagents/` 子目录）。

| 项 | 值 |
|---|---|
| usage 记录数 | 8,896（每条 assistant 请求的最终记录各一条；流式中间记录不带 usage） |
| 唯一 `request_id` | 8,896 / 8,896 全部唯一（天然去重键，无重复） |
| 带 `credits` | 8,896 / 8,896（token 字段存在但恒为 0，无一条例外） |
| 时间范围 | 2026-08-30T15:51:02Z → 2026-10-14T17:50:43Z（ISO 8601，UTC） |
| 模型分布 | `qfmodel` 7,448 / `dfmodel` 781 / `qmodel_38max` 662 |
| 总积分 | 9,973.02（主会话 9,341.26 + `isSidechain=true` 子代理 632.71） |
| 其中计费积分 | 1,093.38（`billable=true`，1,449 条请求） |
| `entrypoint` | 全部为 `cli`（尚无 IDE 侧记录） |

单条 usage 结构（token 字段已清零，积分字段有效）：

```json
{"input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
 "output_tokens": 0, "server_tool_use": {...}, "service_tier": "standard",
 "cache_creation": {"ephemeral_1h_input_tokens": 0, "ephemeral_5m_input_tokens": 0},
 "credits": 0.3464142439999999, "original_credits": 0.3464142439999999,
 "billable": false, "request_id": "c66b19a6-8865-4c3c-b4c5-5fd5b3024e87",
 "context_usage_ratio": 0.012254}
```

外层行结构：`type / uuid / timestamp / message / parentUuid / isSidechain / cwd / sessionId / userType / entrypoint / version / gitBranch`，与 Claude Code 会话日志同构；文件按 `<项目路径编码>/<session-uuid>.jsonl` 与 `<项目路径编码>/subagents/agent-*.jsonl` 组织。

## 其他本地产物盘点（均非模型用量）

| 位置 | 内容 | 判定 |
|---|---|---|
| `~/.qoder-cli/ai-stats/snapshots/` | 按内容哈希的代码快照（141 项） | 非用量 |
| `~/.qoder-cli/ai-stats/projects/**/*.jsonl` | AI 改动行数统计（带 sessionId） | 非用量 |
| `~/.qoder-cli/ai-stats/commit-report-receipts/` | 提交回执（workspacePath/commitId/reportedAt） | 非用量 |
| `~/.qoder-cn/projects/*/transcript/*.session.execution.jsonl` | 会话 transcript（progress/user/assistant） | 无 usage/credits |
| `~/.qoder-cn/logs/runs/`（787 个运行目录） | qodercli.log 运行日志 | 仅认证类 token 字样，无用量 |
| `com.qodercn.app.stable/main.sqlite`（96 表） | `chat_session_context_usage`（32 行，上下文占用快照，数值清零）/ `chat_session_messages`（495 行，无 token/credits）/ `partner_plan_snapshots`（1 行 china_mobile，字段基本空）/ `chat_sessions`（33 行元数据） | 仅上下文占用与统计，无累计用量 |
| `chat-session-turn-payload-buffer.sqlite` | 活跃回合消息投影（124 行） | 无用量字段 |
| `qoder-data.v1.json` | 账户 scope `qoder:prod:cn:0ba2d728…`、deviceId、agents 等配置 | 配置非用量 |

## 数据边界（实施时须保留）

- **credits ≠ tokens**：积分是 Qoder 计费口径，不能换算成 token，也不能与 token 类来源相加；两个指标分开呈现。
- **billable 双口径**：`billable=false` 的请求（8,891 中 7,442 条）不计费但真实发生，`credits` 与 `original_credits` 当前样本一致；是否单列"免费/计费"两个口径应在实现时定案，不合并。
- **子代理单列**：`isSidechain=true` 占 1,662 条、632.71 积分，与主会话同文件混排，需按主/子代理分列或至少可区分，不静默合并。
- **本地 ≠ 全账户**：CLI 账本只覆盖 `entrypoint=cli` 的请求；IDE 内对话、其他设备、网页版用量不在内。
- **去重**：`request_id` 全量唯一，可作为去重键；同一文件的流式重写按行级 JSON 解析，坏行跳过并计数。
- **私有 schema 风险**：路径与字段属 Qoder 私有格式，升级可能变结构；按 `PRAGMA` 式字段存在性校验，缺失即报固定错误码，不猜字段。
- **与 CC Switch 无重叠**：CC Switch schema 20 的 `data_source` 无 qoder 类记录，不存在双算风险。

## 后续可选路线（研究建议，非自动执行指令）

1. ~~新增 `agent_meter/qoder_tokens.py`~~ **已于同日实现**（用户决策：仅在账户额度页面统计，不混入本机消耗）：账本折叠进 qoder 账户源 `credits` 指标的 `usage` 节（`{"rows": 钱包, "usage": 账本}`），不写 tokens 指标；periods（today/7d/30d/all）+ daily_buckets + coverage + dedup_rule=request_id；单位 `qoder_credits`，Decimal 定点字符串；billable 双口径、isSidechain 子代理、按 model 分项均单列；每文件 (mtime,size) 增量缓存；失败固定错误码、进采集线程池、用户开关生效。回归 207 项、verify 588 项（19 项 qoder 对账本机逐位一致）。契约见[后端 API 文档](../../backend-api.md)"Qoder CN 本地积分账本"。
2. 账户额度：复用既有网页来源模式（钥匙串存 Cookie、`PUT /v1/web-sessions` 内存传递、白名单 host+path），用 Qoder CN 应用内嵌网页登录捕获 `qoder.com.cn` 会话后实测 `big_model_credits` 接口；未实测前不进入可用矩阵。
3. 全球版 Qoder：本机 `~/.qoder/projects` 无账本，保留缺口。

## 本轮证据等级

真实本机只读聚合（积分账本全部数字）；静态检查（IDE 表结构、其他产物）；契约来源沿用 2026-10-09 研究的 CodexBar 定版源码。未做：网络请求、凭据读取、应用UI操作、代码改动。
