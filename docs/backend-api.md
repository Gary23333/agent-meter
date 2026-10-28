# 后端快照与测试约定

后端通过 JSON CLI 和本机 HTTP 返回相同的 schema 版本 4。来源之间独立采集，一个来源失败时仍返回其他来源的数据。

## 快照

| 字段 | 含义 |
| --- | --- |
| `schema_version` | 当前为 4 |
| `collected_at` | 本轮采集开始时间 |
| `display_timezone` | 北京时间 `Asia/Shanghai` |
| `sources` | 来源列表，包含指标、范围、观测时间和固定错误代码 |
| `coverage` | 应用与指标覆盖矩阵，关联到数据源 |
| `coverage_summary` | 应用数、已采集字段、部分字段、缺失字段数 |
| `served_from_cache` | 是否复用当前进程的短期快照 |

时间返回 `epoch_seconds`、UTC ISO 字符串和北京时间 ISO 字符串。适配器按来源协议显式处理毫秒；不猜测时间单位。`account_key` 是账户 ID 的 SHA256 摘要前 24 位，接口不暴露原账户 ID 或重置卡 ID。无法确认身份时留空，并保持来源独立。

## 指标

每个来源包含 `quota`、`reset_time`、`reset_cards`、`credits`、`tokens`、`cost`、`renewal_time`、`renewal_countdown`、`renewal_amount`、`credit_refresh_time`、`credit_refresh_countdown` 十一类通用指标，外加只属于预测来源的 `reset_forecast` 与 `known_reset_countdown`。每类指标都有 `status`、`value` 和 `reason`。

| 状态 | 用户含义 |
| --- | --- |
| `available` | 已读取数据；零值也是有效测量 |
| `partial` | 部分信息可用，需要查看具体覆盖或价格缺口 |
| `not_provided` | 此来源这次没有返回该信息 |
| `not_connected` | 未连接、未配置或被显式禁用 |
| `not_supported` | 当前没有对应适配器 |
| `error` | 此来源读取或解析失败 |
| `stale` | 最近读取失败，保留较早成功值及其原观测时间 |

`available` 表示读取与解析状态，真实正确性验证另由测试和对账报告给出。单个复杂指标还可能有子项缺失，例如已取得重置卡数量但没有逐张详情。

重置卡 `available_count` 使用服务端总数；`cards=null` 表示没有返回详情，`cards=[]` 表示已查详情为空。截断详情标记 `details_state=truncated`，最早已知过期时间称 `next_known_expiry`，不把部分明细当成完整库存。卡的到期状态是采样时状态；读取旧快照时应结合当前时刻判断。

余额保留钱包、单位、币种和无限额度状态，允许来源报告负余额。它不与其他公司的积分相加。token 的本机记录与账户活动汇总分别展示，生命周期总量不与每日桶重复相加。

## Codex 账户读取与缓存

`codex` 来源通过官方 `codex app-server` 只读调用 `account/rateLimits/read` 与 `account/usage/read`。`account/rateLimits/read` 在正常网络下也可能耗时 15–25 秒，因此使用独立配置 `codex_timeout_seconds`（默认 45，且不低于全局 `timeout_seconds`），不再用 20 秒通用超时误判。

成功读取后把**归一化后的** quota / reset / credits / tokens 指标写入 `<runtime>/codex-account-cache.json`（0600），不保存 `accountId`、重置卡 ID 或原始响应。出现瞬时错误（`rpc_timeout` / `rpc_disconnected` / `rpc_request_failed`）且 24 小时内有成功值时，来源以 `stale` 返回缓存指标：`observed_at` 保留上次成功时间，`diagnostics.cached_at` 标注缓存时间，界面显示“旧数据”而不是“读取失败”。`account/usage/read` 的上游超时单独缓存：成功值 6 小时、错误 1 小时，避免每轮快照重复等待 10 秒；它只影响账户累计 Token 行，不影响本机 token 历史。

## CC Switch 统计

适配数据库 schema 20，查询规则参考固定版 4.0.5，读取使用只读连接和一致事务。只查询用量列；历史统计不读取聊天正文。

按 `today`、`7d`、`30d`、`all` 返回新增输入、输出、缓存读取、缓存写入、请求数、模型分组与估算费用。总 token 是归一后的四个分项之和。缓存读取占缓存相关输入的比例作为命中率，分母为零时留空。

代理与会话日志去重沿用上游 600 秒匹配规则，它是启发式规则；与上游一致不代表账单中的每个请求都已经精确归属。旧日汇总只纳入完整覆盖的源时区日期。范围覆盖到旧汇总的一部分日期时，返回 `excluded_partial_rollup_days`、`period_status=partial` 和 `total_is_lower_bound=true`。

CC Switch 日汇总的源时区默认按本机研究设置为北京时间，可用 `ccswitch_timezone` 改成真实写入时区。如果历史记录跨时区，需额外对账。费用用 Decimal 汇总已有估价，保持 API 等价估算标签；价格缺失和旧日汇总无法确认的定价完整性单独保留。

## 其他本机 token 记录

除 CC Switch 与 Kimi Code 会话日志外，后端还从三处本机数据读取 token 历史，均使用只读连接、固定错误码，不读取消息正文：

| 来源 id | scope | 数据位置 | 去重规则 | 与 CC Switch 的关系 |
| --- | --- | --- | --- | --- |
| `zcode` | `local_session_history` | `~/.zcode/cli/db/db.sqlite` 的 `model_usage` 表 | 每行一次模型请求尝试（含重试行） | 无重叠（CC Switch 不导入 ZCode） |
| `opencode` | `local_session_history` | `~/.local/share/opencode/opencode.db` 的 `message` 表 | 每条 assistant 消息一次响应 | CC Switch 已导入的本地日期被剔除并以 CC Switch 为主，`ccswitch_overlap` 记录剔除日期与检查状态，绝不叠加 |
| `workbuddy`（tokens 指标） | 附着在 workbuddy 来源上 | `~/.workbuddy/projects/**/*.jsonl` 的 `providerData.rawUsage` | 每条 rawUsage 记录一次响应 | 无重叠 |

口径：ZCode/OpenCode 的 `input` 均为不含缓存的新鲜输入，缓存读写单列，ZCode 另有 `reasoning` 字段；WorkBuddy 为 OpenAI 风格 `prompt_tokens`，doubao 方言下新鲜输入取 `prompt_cache_miss_tokens`（本机已验证 hit+miss==prompt 恒等），anthropic 方言按 prompt−read−write 推导并在诊断中计数。WorkBuddy 的 `credit_charged` 是其自身积分扣减（all 期间，单位 `workbuddy_credits`），不是货币费用。tokens 指标结构与 CC Switch/Kimi 一致：`periods`（today/7d/30d/all）+ `daily_buckets` + `coverage` + `dedup_rule`。

注意各来源 tokens 指标是**单账本口径**：与 CC Switch 重叠的日期已按日剔除（`ccswitch_overlap.excluded_days`），因此装了 CC Switch 的机器上 Codex/Claude/MiniMax Code 直读来源的 periods 会是全 0——这是防双算的设计，不是故障。展示层（菜单栏"本机消耗"页与账户卡片的 token 行）必须在客户端把 CC Switch 与各直读来源合并后按 app 归因，不能直接展示单来源指标；合并链路只有 Swift 侧 `LocalUsage.merged` 一份实现，账户卡片经 `LocalUsage.appTotals` 按 app 投影同一函数的结果。按 app 的日序列在当前快照中不存在（CC Switch 的 daily_buckets 不分 app），需要时以后端增加按 app 日汇总为前提，不做客户端拼凑。

覆盖矩阵中，同一 provider 存在专用 `local_session_history` 来源且其 tokens 可用时，token 字段由该来源署名，cost 仍归 CC Switch；专用来源不可用时回落到 CC Switch 历史署名。用户在应用内关闭 workbuddy 时其本地 token 记录一并停止；zcode/opencode/gemini 与 ccswitch 一样属于本机历史，不提供应用内开关，可通过配置 `disabled_sources` 或 CLI `--disable` 关闭。stale 恢复不会用旧的本地 token 记录覆盖新采集值。

## Qoder CN 本地积分账本（仅账户卡片）

Qoder CN CLI 的会话日志（`~/.qoder-cn/projects/**/*.jsonl`，Claude Code 兼容格式）每条 assistant 请求的最终记录带 `message.usage`，其中 token 字段在本机恒为 0（2026-10-15 实测 8,896 条无一条非零，IDE 亦报 `tokenCountsAvailable=false`），但 `credits`/`original_credits`/`billable`/`request_id`/`context_usage_ratio`/`model` 为真实值。采集器 `agent_meter/qoder_tokens.py` 只报积分，不臆造 token。

| 项 | 契约 |
| --- | --- |
| 数据位置 | `qoder_projects_dir`（默认 `~/.qoder-cn/projects`）下 `**/*.jsonl`，只读，仅取 usage 字段，不读消息正文 |
| 去重 | `request_id` 逐请求唯一（本机 8,896/8,896 验证），跨文件全局去重 |
| 增量 | 每文件 `(mtime,size)` 缓存；文件被清理时天然为下界 |
| 错误码 | 目录或 jsonl 不存在 → `qoder_sessions_not_found`（not_connected）；usage 对象普遍失去 `credits` → `unsupported_qoder_usage_schema`（私有格式漂移，不静默） |
| 附着位置 | **qoder 账户源的 `credits` 指标**：`{"rows": [网页/SDK 钱包…], "usage": [账本]}`，**不写 tokens 指标** |

账本结构：`{unit: qoder_credits, token_fields: not_provided, coverage: qoder_cn_cli_local_sessions, dedup_rule: request_id_unique_per_record, usage_records_seen, excluded_usage_records, sidechain: {requests, credits}, periods: {today/7d/30d/all: {start, end, timezone, totals: {requests, credits, billable_requests, billable_credits}, groups: [按 model]}}, daily_buckets: [{date, requests, credits}]}`。积分为 Decimal 定点字符串（与 WorkBuddy `credit_charged` 同约定）；`billable` 双口径分开，`isSidechain` 子代理单列，均不合并。

**边界**：该账本只在账户额度卡片展示（"积分消耗 今日/近30天/全部"行），不计入本机消耗——`LocalUsage` 只汇总各来源 tokens 指标，qoder 的 tokens 保持 not_provided；也不参与 API 价格表估算（cost 仅由 tokens 驱动）。网页/SDK 钱包查询失败时账本照常附着（账户源 status 仍为失败原因，卡片显示本地积分）；账本读取失败不覆盖已有钱包行，错误码记入 `diagnostics.credits_ledger_error`。用户在应用内关闭 qoder 时本地积分一并停止。与 CC Switch 无重叠（其 `data_source` 无 qoder 类记录）。verify 对 today/all 两个周期的 requests/credits/billable 做独立重算对账（本机实测逐位一致）。

## CLI 会话日志直读（无 CC Switch 也可用）

Codex CLI、Claude Code、Gemini CLI 与 MiniMax Code 的会话历史增加直读采集器，口径已与本机 CC Switch 4.0.5 的导入结果逐日对齐验证（共享日完全一致，差异仅为同步滞后）：

| 来源 | 数据位置 | 去重规则 | 附着位置 |
| --- | --- | --- | --- |
| Codex | `~/.codex/sessions` 与 `~/.codex/archived_sessions` 的 rollout 文件 `token_count` 事件 | 对累计 `total_token_usage` 序列做差分：重复事件计零，序列回落视为重置重新起算；output 不含 reasoning；model 取自文件头 session_meta（混合会话归入主模型，仅影响模型分组不影响总量） | 附着在 `codex` 来源 tokens 指标 |
| Claude Code | `~/.claude/projects/**/*.jsonl` | 同一 `requestId` 的多条流式记录取时间戳最新的一条（跨文件全局去重）；sidechain 子代理记录计入 | 附着在 `claude` 来源 |
| Gemini CLI | `~/.gemini/tmp/*/chats/session-*.jsonl` | 同一消息 id 取最新记录；fresh = input − cached；output = output + thoughts | 独立来源 `gemini`（scope `local_session_history`） |
| MiniMax Code | `~/.minimax/v2/sqlite/runtime-state.sqlite` 的 `local_runtime_token_usage` 表 | 每行一次请求，input 已是新鲜值 | 附着在 `minimax_code` 来源 |
| Antigravity CLI (agy) | `~/.gemini/antigravity-cli/conversations/*.db` 的 `steps.metadata` protobuf | 每个 LLM 步（step_type=15）一次调用的 usage 子消息；模型名取自按序对齐的 `gen_metadata` 行 | 独立来源 `antigravity`（scope `local_session_history`） |

Antigravity 的 usage 字段是从本机数据（agy 1.3.2）解码验证的：f2=单次输入、f3=含思考的输出总量、f9=思考部分（f3−f9=f10 恒成立）；两个恒定字段（f1=1319、f6=24）未能识别，按不臆测原则不计入指标并以 `cache_semantics=unverified_constants_excluded` 声明，cache_hit_rate 为 null 而非零。数据库以 `mode=ro&immutable=1` 打开（agy 的 schema 在未检查点的 WAL 中）；活跃会话尚未落盘主库的最新几步不可见，采集为下界。本机数据显示其历史自 2026-06-17 开始，恰为 Gemini CLI 最后一次记录之日，`gemini` 与 `antigravity` 两来源互补不重叠。

## DeepSeek Harness（dsh）本机会话账本

DeepSeek Harness（dsh）把每个会话的账本写成 zstd 压缩的 JSONL：`~/.dsh/sessions/<编码后的项目路径>/<会话id>/session.v3.jsonl.zstd`（v3）或旧格式 `session.jsonl.zstd`。采集器 `agent_meter/dsh_tokens.py` 递归读取 `session*.jsonl.zstd`，只读 usage 字段、绝不读对话文本；解压优先用标准库 `compression.zstd`（Python ≥ 3.14，诊断记 `stdlib_compression_zstd`），否则调用 `zstd -dc`（`zstd_binary` 配置，记 `zstd_cli`），两者都不可用报 `zstd_unavailable`。

两代 schema 的 usage 位置（本机 20,578 条记录验证，2026-10-18）：

| 代 | usage 位置 | 模型位置 |
| --- | --- | --- |
| v3 | `type=="assistant/message"` 的 `data.usage`（`inputTokens/outputTokens/cacheReadTokens/reasoningTokens/totalTokens`） | `data.message.source.model` |
| 旧 | `type=="assistant/chunk"` 的 `data.chunk.usage` 为渐进值（早期可为 0），同 (turn, step) 随后的 `assistant/message` 的 `data.usage` 是最终值（无 totalTokens） | 同文件最近一条 `type=="request/header"` 的 `data.header.config.model`，没有则 unknown |

v3 的 `data.stream` 数组可能内嵌一份相同的 usage 块——只读 `data.usage`，绝不重复计数。字段拆分：`fresh_input=inputTokens`（未命中缓存的新鲜输入）、`output=outputTokens−reasoningTokens`、`reasoning=reasoningTokens`、`cache_read=cacheReadTokens`、`cache_write=0`（无该字段）。去重：同文件内按 `(turn, step)` 保留时间戳最大的一条（`last_usage_per_turn_step`，last-wins 同时覆盖 chunk+message 成对重复与渐进 0 值）；跨文件不去重（每文件独立会话）。`time` 为毫秒 epoch，换算成秒后再分桶。

独立来源 `deepseek_harness`（scope `local_session_history`），分组 app 名 `dsh`。与 CC Switch 无重叠（其 app_type 不含 dsh），仍按统一模式调用 `app_imported_days` 保持诊断一致。错误码：目录不存在或没有任何 `session*.jsonl.zstd` → `dsh_sessions_not_found`（not_connected）；单文件解压/解析失败只跳过并计入 `diagnostics.skipped_session_files`，不炸整个来源。diagnostics 另有 v3/旧格式文件数与 `decompression_route`。配置项 `dsh_sessions_dir`（默认 `~/.dsh/sessions`）与 `zstd_binary`（默认 `shutil.which("zstd")`）。verify 对四个周期做独立重算对账（与 CC Switch 的交叉对账因无重叠日自动跳过）。

## Kimi 桌面端本地会话账本

Kimi.app 的 Agent 模式自带一套独立的 Kimi Code 运行时，账本写在 `~/Library/Application Support/kimi-desktop/daimon-share/daimon/runtime/kimi-code/home/sessions`（配置键 `kimi_desktop_sessions_dir`），与 CLI 的 `~/.kimi-code/sessions` 目录结构相同：`**/agents/<agent>/wire.jsonl`，schema 一致。采集器 `agent_meter/kimi_desktop_tokens.py` 只替换根目录与分组 app 名，解析与汇总复用 `agent_meter/kimi_tokens.py`；只读 token 字段与模型名，绝不读对话正文，每文件按 `(mtime,size)` 增量缓存。自动起名（`ctitle-*`）与子代理会话照常计入。

wire.jsonl 口径（与 CLI Kimi Code 相同）：

- 每个模型轮次只写一条 `{"type": "usage.record", "usageScope": "turn"}`；该轮 `step.end`、逐消息元数据与父会话的 `subagent.completed` 是同一组数字的重复，只计 `usage.record`/`turn` 这一条。
- 字段：`fresh_input=inputOther`、`output=output`、`cache_read=inputCacheRead`、`cache_write=inputCacheCreation`，`total_tokens` 为四者之和；`time` 为毫秒 epoch，换算后按 Asia/Shanghai 分桶。
- `usageScope=session` 的记录含义未确认，排除并计入 `excluded_session_scope_records`（本机 13 条）。

独立来源 `kimi_desktop`（scope `local_session_history`），分组 app 名 `kimi_desktop`，`coverage=kimi_desktop_local_sessions`，`dedup_rule=usage.record_turn_only`；tokens 指标结构与其他会话账本一致（`periods.today/7d/30d/all` 的 totals 与按模型 groups、`daily_buckets`）。**只出现在「本机消耗」页，不挂账户卡片**——Kimi 桌面端没有账户额度接口，普通聊天也不写本地账本，只有 Agent 模式产生记录。错误码：目录不存在或没有任何 `wire.jsonl` → `kimi_desktop_sessions_not_found`（not_connected）。配置键 `kimi_desktop_sessions_dir`（默认路径见上）。

与已接 CLI `kimi` 来源的关系：两者按 session id 与逐条 usage 记录比对**零重叠**（2026-10-26 实测 153 个会话 / 7,896 轮 / 约 6.36 亿 token，覆盖 2026-06-05 至今），因此**不合并也不剔除**：不套用 CC Switch 式重叠剔除，两条账本各自独立汇总；CC Switch 的 `kimi-for-coding` 是它路由的另一客户端，与这两个账本都不重叠。verify 对四个周期的 totals 与按模型分项做独立重算对账。

## 本地价格表与 API 等价估算

`GET/PUT /v1/prices` 管理一份本地价格表（`prices.json`，0600，位于 runtime 目录）：`{currency: USD|CNY, models: {pattern: {input, cache_read, cache_write, output}}, peak_multipliers, aliases}`，单价按每百万 tokens。默认值来自[定价摸排](pricing-survey-2026-10-09.md)（含 2026-10-15 与 2026-10-28 增补）：取有官方刊例的一侧币种，另一侧按 7.25 汇率折算并在 GET 的 `converted_patterns` 中列出（双向：仅 USD 刊例的折成 CNY，仅 CNY 刊例的国产模型折成 USD）；用户编辑过的条目移出该列表。CNY 表中，官方人民币刊例的模型优先于 `models.dev` 目录的美元折算值（目录按美元下发，折算可能覆盖国内价），目录只在没有官方人民币价时参与折算。匹配规则（2026-10-15 起先归一化再匹配）：两侧都取最后一个 `/` 之后的模型 id、转小写并把 `.` 统一成 `-`（`account:bigmodel-coding-plan/GLM-5.3-Flash`、`glm-5-3-flash`、`GLM-5.3.Flash` 都命中 `glm-5.3-flash`），归一化后精确命中优先、否则取最长子串 pattern；快照里的 `model` 字段保留原始拼写。

带按模型分项的本地 token 来源（ZCode/OpenCode/Gemini/Antigravity/Codex/Claude/MiniMax Code 直读、Kimi Code、Kimi 桌面端、WorkBuddy、DeepSeek Harness）会得到 `cost` 指标：`{unit: 币种, kind: estimate, basis: local_price_table, peak_window, peak_multipliers, periods: {period: {amount, peak_amount, offpeak_amount, models, unmatched_models, unsplit_models}}}`；有未匹配模型时 status=partial（未匹配部分不计零价）。仅 CC Switch 自带估价与 CodexBar 保留自己的口径；DeepSeek 的 provider 账单 cost（见下）不会被覆盖。订阅套餐内的调用不按 API 价计费，估算仅作量级比较。

**峰谷计价（2026-10-28）**：DeepSeek 官方峰时为北京时间工作日 09:00–12:00、14:00–18:00（UTC 周一至周五 01:00–04:00、06:00–10:00），峰时价为谷时刊例的 2 倍；周末全天谷时，法定节假日未内置日历（按工作日处理）。价格表的四项单价始终是谷时基准，`peak_multipliers` 单独保存用户覆盖（默认 DeepSeek 系 2.0）；`GET/PUT /v1/prices` 的每个模型带 `peak_multiplier`，顶层带 `peak_window` 与已保存的 `peak_multipliers`。带逐请求时间戳的账本在 tokens 指标的每个 period `totals` 与每个 model `group` 内写 `peak`/`offpeak` 两个分项（字段镜像该来源自身 token 字段，并各带 `total_tokens`），指标顶层标 `peak_split: request_timestamp`；估算时峰时部分按倍率、谷时部分按基准价，无拆分或没有时间戳的整组按谷价并记入该 period 的 `unsplit_models`。CC Switch 只有日汇总，不参与峰谷拆分，其自带 USD 估价仍按原值展示。

菜单栏「本机消耗」页把两路估算合成一个总数：CC Switch 自带 USD 估价 + 价格表估算（价格表为 USD 时相加，为 CNY 时分列展示、不跨币种相加）；按应用行与模型排行显示各自金额（CC Switch 组自带 `estimated_cost_usd`，本地来源按 `models` 金额表），无定价模型按 token 量排序列出前几个。全零估算显示「—」，不把未知价格当零。

## DeepSeek 网页用量（仅展示）

`deepseek_api` 来源可选携带 `user_token`（platform.deepseek.com 登录后的 localStorage 值，经应用内存通道传入，不落盘）。提供时后端以 Bearer 只读调用控制台未公开接口 `GET /api/v0/usage/by_api_key/amount|cost?start&end&tz=28800`（契约取自 MIT 的 deepseek-harness-usage-dashboard 逆向，2026-09 schema），把近 30 天按天分桶写进 `cost` 指标：`{basis: platform_web_usage, currency, daily: [{date, tokens, requests, amount}], windows: {today, 3d, 7d, 30d}, total_amount, total_tokens}`。`windows` 每项为 `{amount, tokens, requests, days}`，按 GMT+8 日历日含今天向前取 1/3/7/30 天，晚于今天的日期忽略；账户卡展示今日、近 3 天、近 7 天，另保留近 30 天合计。它**不计入本机消耗**（tokens 指标不受影响）。接口失败只降级该指标（固定错误码），不影响余额读取。该接口未公开、随时可能变更，尚未在本机登录会话上实测。

与 CC Switch 的重叠处理：CC Switch 记录过该应用（折叠 claude-desktop、任意 data_source）的本地日期被剔除、以 CC Switch 为主，动态计算，绝不叠加；`ccswitch_overlap` 字段记录剔除日期与检查状态（`checked` / `ccswitch_absent` / `ccswitch_read_failed`）。CC Switch 缺失或未运行时为全量覆盖。直读解析带每文件 (mtime,size) 增量缓存；文件被 CLI 清理时本地记录天然为下界，verify 的交叉对账跳过 CC Switch 的代理路由日（其库内存在上游自身的 600 秒去重语义，原始文件无法复现）。

## 阶跃星辰 (StepFun) 开放平台

`stepfun` 来源（scope `account`）有两条只读路线，与 ZCode、火山方舟同构：控制台网页登录（`cookie`）优先，其次开放平台 API Key（`api_key`）；两者都没有时 `stepfun_credential_not_connected`（not_connected）。

| 路线 | 端点 | 读取内容 |
| --- | --- | --- |
| 控制台会话 | `POST https://platform.stepfun.com/api/step.openapi.devcenter.Dashboard/{QueryAccountBalance,GetStepPlanStatus,QueryStepPlanRateLimit}`，body `{}` | 余额 + STEP plan 用量 + 套餐名与到期日 |
| 开放平台 API Key | `GET https://api.stepfun.com/v1/accounts`（Bearer，官方文档 `/docs/zh/api-reference/accounts/get`） | 仅余额；quota 报 `stepfun_step_plan_needs_console_login` |

**Cookie 收窄**：控制台会话里只要多带 `INGRESSCOOKIE`、`Oasis-Webid` 等任意一个字段，服务端就会把整串当成单个 JWT 解析并回 401。因此 `console_session` 只保留 `Oasis-Token`，并从该值的两段 JWT（`access...device`，`.` 分段共 8 段）取 `device_id` 作为 `oasis-webid` 请求头、取 `oasis_id` 作为 `account_key` 的散列输入（不落盘、不进快照）。

**金额单位**：控制台 `QueryAccountBalance` 全部以**分**下发（`"1500"` = 15.00 元），按元换算后写入 `credits`；官方 `/v1/accounts` 已是元，两者产出同一个钱包形状 `{unit: CNY, balance, cash, topped_up, granted}`（`payment`/`total_cash_balance` → 充值，`voucher`/`total_voucher_balance` → 赠送）。`notify_threshold` 是全响应里唯一按元的例外，未使用。

**「0」表示没有配额，不是已用完**：套餐不配置某个窗口时，服务端把比例与重置时间都返回 `0`。因此只有出现**真实重置时间**的窗口才成为一行 `quota`；`five_hour_usage_left_rate`/`weekly_usage_left_rate` 的 `0` 不会被渲染成 0% 的假进度条。两种计费模型：

- **Coding Plan**：5 小时 / 每周滚动窗口（`bucket` 为 `limit5h` / `limit7d`，`window_minutes` 300 / 10080），只有剩余比例，不臆造 token 计数。
- **Token Plan**：`plan_credit_rate_limit` 的月度积分池。订阅积分与加油积分是**各自独立的比例，不相加**；优先用 `credit_buckets` 的 `credit_residual/credit_total` 求和（全部桶可用时），任一桶不可用则回退到 `subscription_credit_left_rate`（无则 `topup_credit_left_rate`），此时只给百分比、不给计数（`unit=percent`），避免把不同量纲的数硬凑成一对。

`GetStepPlanStatus` 的 `subscription.expired_at` 只取**日精度**写入 `renewal_time`（`origin=provider`），`subscription` 另存 `plan`、`ends_on`、`auto_renew`。`plan_definition.price` 是套餐刊例价，**不作为 `renewal_amount`**（不把公开套餐价当成下一笔扣款）。没有套餐时 `subscription.plan` 为「按量付费」，quota 报 `stepfun_no_step_plan`。

错误码：`stepfun_not_authenticated`（会话失效，Connect 错误 `unauthenticated`/`permission_denied` 或 HTTP 401/重定向）、`stepfun_api_error`、`stepfun_step_plan_usage_unrecognized`（有套餐但未识别用量格式）、`unsupported_stepfun_balance_contract`、`invalid_stepfun_{amount,rate,credits,response}`。余额查询成功而套餐查询失败时只降级 quota 指标，余额照常展示。

## 测试分层

1. 人工可核算的固定样例：缓存语义、重复记录、时间边界、零与未知、截断卡片及货币。
2. 接口与生命周期测试：本机 HTTP 认证、Host 和 Origin、超时、子进程关闭、缓存并发和失败保留。
3. 本机 CC Switch 对账：同一只读事务中分别运行后端 SQL 和独立 Python 逐记录算法，比较四个时间范围。ZCode、WorkBuddy、OpenCode 三个本机来源各有独立重算对账；ZCode 另与 `turn_usage` 做容差交叉校验（上游记账存在约 0.0001% 漂移）；OpenCode 与 CC Switch 的剔除日期集合必须一致。
4. Codex 跨接口对账：使用脱敏的原生用量工具参考，先核对账户摘要，再核对窗口、使用率、重置时刻、积分和卡片时间。
5. 覆盖审计：所有识别出的相关应用逐指标列出已采集、部分、缺失或错误；缺口不算作测试通过的接入。

原生参考与后端不是原子读取，使用率差异在 1 个百分点内时标为 `inconclusive_live_drift`，不会算通过；大于该范围则失败。不同账户不进行数值对账。供应方未返回的字段不补零，未知契约直接拒绝解析。

当前 HTTP 服务按请求刷新并缓存，不包含自动轮询调度、开机启动或菜单栏界面。持久化快照用于检查，进程重启会重新采集。运行时数据与第三方安装代码私有缓存都位于 `.runtime/`。

## 续费字段（schema 2）

- `renewal_time.value`：`date`（YYYY-MM-DD）、`precision=day`、`timezone`、`event=renewal`、`origin=provider|user`。日精度不返回编造的 UTC 扣款瞬间。
- `renewal_countdown.value`：目标日期、时区、`days_remaining`、`days_overdue`、`state=upcoming|today|overdue`、计算时间；日精度的 `seconds_remaining=null`。缓存和 stale 结果每次服务读取时更新倒计时，但原数据观测时间保持不变，stale 倒计时仍标 stale。
- `renewal_amount.value`：Decimal 字符串 `amount`、ISO 币种 `currency`、`basis=next_renewal`、来源及 `confirmed_by_provider`。当前即梦与 Design 都没有自动返回此字段，用户配置时 `origin=user`、`confirmed_by_provider=false`。不把积分数、公开套餐价或初次优惠价当下一笔扣款金额。

MiniMax Design `subscription` 另外保存计划、周期、状态是否已知、`auto_renew` 和 `ends_on`。取消自动续费后到期日仍保留，但续费倒计时为空。额度/积分补发日在 `reset_time` 内单独标记，不能混用续费日期。

新来源的会话失效或确认切换账户不恢复旧账户财务缓存。用户手填数据必须匹配稳定账户指纹；只有当前账户已成功读取后才使用。后端只允许 Design 本机的健康、计费上下文、账户上下文和钱包 GET 路径；MCP 客户端只允许 initialize、initialized notification、tools/list，没有 tools/call。

历史验收文件保留原版本。客户端应读取版本并支持新增字段，不能继续假设固定六列。

## 下一次积分更新（schema 3）

`credit_refresh_time` 使用与续费日期相同的日期精度、时区和来源结构，但 `event=credit_refresh`。`credit_refresh_countdown` 独立计算剩余自然日；缓存命中时重算，旧采样日期过后标 overdue，不推算下次事件。日精度的 seconds_remaining 保持 null。

Design 读取 `next_credit_refresh_time`；原 `reset_time` 中的 membership_credit_refill 保留为同一事件的兼容映射，客户端应优先显示新字段，不计为两次补发。即梦 CLI 没返回更新时间，不能从会员等级或积分余额推算。积分桶 expires_at 是失效时间，不是补发时间。

手填配置增加 `billing_overrides.<provider>.credit_refresh_date`，仍需匹配当前 account_key，使用用户来源标识。不会覆盖当前提供方的有效日期。无数据时该字段和倒计时为 not_provided；错误日期只影响积分更新字段，不抹去余额或续费日期。

历史 schema 1/2 证据文件保留原版本；当前快照和 health 为 3。

## 全员重置预测（schema 4）

独立来源 `reset_forecast`，scope `external_forecast`。它记录 OpenAI Codex 负责人在 X 上不定期宣布的**全员额度重置**（社区称 Tibo 重置），与各账户自身的 5 小时 / 每周窗口是两类事件：本来源**永不写 `reset_time`**，也不进入账户卡片、菜单栏滚动和本机消耗，只在面板「重置预测」页展示。

三家追踪站各自的字段由 `agent_meter/reset_forecast.py` 归一化到同一行结构：`raw_24h/raw_48h`（站内模型值）、`headline_24h/headline_48h`（该站对外公布的答复）、`band_24h/band_48h`（该站自评区间）、`self_reported`（信心、注记、Brier/回测样本与状态）、`cadence`（间隔统计与样本口径）、`promise`（承诺横幅）、`typical_window`（常见公告时段）、`last_reset`、`updated_at`、`provenance`。

合成规则：`ensemble.horizons.<24h|48h>` 的区间与加权中位数**只用各站自己公布的数值**（`basis=published_answer`；某站没公布时才回退到站内模型值并标 `cadence_model_fallback`）。权重完全取自各站上报的质量字段——自报信心、校准状态、样本量、数据新鲜度——系数常量在模块顶部，逐行随 `weight_components` 下发，便于核对。超过 48 小时未更新的来源整体剔除（`forecast_source_stale`），不按 0 处理。

`known_reset_countdown.targets[]` 每项带 `kind`（`promised_reset` / `typical_window`）、`precision`（`window` / `label_only`）、`open_at/close_at`、`state`（`upcoming` / `inside_window` / `elapsed_awaiting_landing` / `no_clock` / `label_only`）与 `sources`。只有拿到可机读的时间或时段才给 `seconds_remaining_*`；公告只说"会重置"没给时间时保留 null 并在面板显示"未给时间"，与日精度续费倒计时不给秒数同一原则。时段类目标按"下一个每日出现窗口"滚动。

历史 `history_events[]` 按各站共享的 X 状态 ID 去重合并，`sources` 列出印证家数；`announced_at`（公告）与 `effective_at`（观测落地）、`official_window`（官方窗口）是三个不同事实，不相加也不互相覆盖；推文正文不进快照，只留各站的摘要文本（截断 240 字）。

失败与节流：三家全挂且无缓存时来源为 `error`、code `reset_forecast_sources_unavailable`；有缓存则按 `stale` 返回旧值并保留原观测时间。默认 45 分钟抓一次（`reset_forecast_refresh_minutes`），有来源失败时缩短到 5 分钟重试，缓存写在 `.runtime/reset-forecast.json`（0600）。三家都拒绝默认 User-Agent，请求固定带应用 UA；纯公开只读 GET，不发送任何本机数据、不带 Cookie。

`codexreset.org` 没有 JSON 接口，预测对象内嵌在页面脚本里且 `score24h` 在历史序列中重复 400+ 次，解析锚定 `forecast:$R[` 到 `semanticSignals` 的区间；锚点缺失即 `forecast_object_not_found`，字段缺失即 `unsupported_forecast_contract`，两者都只让该源降级，不影响其余两源。

预测类两个指标不计入应用覆盖矩阵（`COVERAGE_METRICS` 排除），否则每个应用都会凭空多出两项"缺失"。`verify` 对每条区间、中位数、分歧标签、去重与倒计时状态做独立重算，共 33 项。

