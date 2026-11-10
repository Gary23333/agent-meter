# 后端快照与测试约定

后端通过 JSON CLI 和本机 HTTP 返回相同的 schema 版本 5。来源之间独立采集，一个来源失败时仍返回其他来源的数据。

## 快照

| 字段 | 含义 |
| --- | --- |
| `schema_version` | 当前为 5 |
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

## 历史导入（imported_history）

运行时不再读取任何 CC Switch 数据库；`agent_meter/ccswitch.py`、`agent_meter/ccswitch_sql.py` 与来源 id `ccswitch` 均已删除。项目自有历史由一次性迁移脚本写入 `<runtime>/imported-history.json`（0600，`schema=1`），采集器 `agent_meter/imported_history.py` 每次采集只读该文件。来源 id `imported_history`，scope `local_imported_history`。

| 字段 | 形状 | 说明 |
| --- | --- | --- |
| `detail` | `[app, model, epoch_seconds, fresh_input, output, cache_read, cache_write]` | 逐请求记录，保留请求时刻，可拆峰谷 |
| `daily` | `[app, model, "YYYY-MM-DD", requests, fresh_input, output, cache_read, cache_write]` | 日汇总，没有请求时刻，不参与峰谷拆分，按谷价估算 |
| `apps` | `{app: {imported_detail_days, imported_daily_days, supplemented_days, skipped_days, supplement_gap}}` | 每个应用的一次性迁移统计 |
| `imported_at` | `epoch_seconds` | 迁移写入时间 |

迁移口径（一次性、在删除旧账本读取器之前执行）：本机各直读账本优先。只有当某应用某日在本地账本没有数据时才导入旧账本该日记录——有逐请求行则保留时间戳写入 `detail`，只有日汇总则写入 `daily`。本地该日总量比旧账本低 5% 以上且差额 ≥5 token 时，仅按模型把差额写成 `daily` 补差行；其余日期跳过。旧账本同一日的 `detail` 与 `daily` 只取总量较大的一张，不相加。

tokens 指标按 `today`/`7d`/`30d`/`all` 返回 totals、按 app/model 分组、`daily_buckets` 与 `history` 元数据；`peak_split="request_timestamp_and_daily_rollups"`、`coverage="imported_history_store"`、`dedup_rule="one_time_import_before_local_ledgers"`。`detail` 行按请求时间戳拆峰谷；`daily` 行没有时刻，整组按谷价计价并进入该周期的 `unsplit_models`。同一 app/model 混合两种粒度时，逐请求部分保留 `peak` 和 `offpeak`，日汇总另列 `unsplit`，模型名进入 `mixed_split_models`。滚动窗口起始日只有日汇总且跨越窗口边界时，无法定位到时刻的该日合计暂不计入，日期列入 `boundary_days_omitted`。总 token 为四项之和，缓存命中率分母为零时留空。

错误码：文件不存在 `history_store_not_found`；读取或结构错误 `history_store_read_failed`；`schema` 不是 1 `unsupported_history_schema`。文件缺失视为没有历史，不影响其他来源。

同一次迁移还会把当前 MiniMax 配额凭据写入 `<runtime>/secrets/minimax_code.json`（0600，`{api_key, region, migrated_at}`）。运行时凭据优先级为：应用内 API Key → 环境变量 `MINIMAX_TOKEN_PLAN_KEY` → 该文件；不再读取任何第三方 providers 配置。

## 其他本机 token 记录

除 Kimi Code 会话日志外，后端还从三处本机数据读取 token 历史，均使用只读连接、固定错误码，不读取消息正文。每个账本独立汇总：

| 来源 id | scope | 数据位置 | 去重规则 | 账本关系 |
| --- | --- | --- | --- | --- |
| `zcode` | `local_session_history` | `~/.zcode/cli/db/db.sqlite` 的 `model_usage` 表 | 每行一次模型请求尝试（含重试行） | 独立账本，不与其它来源做日期剔除 |
| `opencode` | `local_session_history` | `~/.local/share/opencode/opencode.db` 的 `message` 表 | 每条 assistant 消息一次响应 | 独立账本，按消息记录去重，不跨来源剔除 |
| `workbuddy`（tokens 指标） | 附着在 workbuddy 来源上 | `~/.workbuddy/projects/**/*.jsonl` 的 `providerData.rawUsage` | 每条 rawUsage 记录一次响应 | 独立账本，不与其它来源做日期剔除 |

口径：ZCode/OpenCode 的 `input` 均为不含缓存的新鲜输入，缓存读写单列，ZCode 另有 `reasoning` 字段；WorkBuddy 为 OpenAI 风格 `prompt_tokens`，doubao 方言下新鲜输入取 `prompt_cache_miss_tokens`（本机已验证 hit+miss==prompt 恒等），anthropic 方言按 prompt−read−write 推导并在诊断中计数。WorkBuddy 的 `credit_charged` 是其自身积分扣减（all 期间，单位 `workbuddy_credits`），不是货币费用。tokens 指标结构与 Kimi 等本机会话账本一致：`periods`（today/7d/30d/all）+ `daily_buckets` + `coverage` + `dedup_rule`。

每个来源的 `tokens.periods` 只汇总自己的账本。后端输出 `application_usage[application_id][period]`，包含 `total_tokens`、`requests`，以及有证据时的 `direct`、`history` 分项。分项给出来源、状态、Token 与请求数。当前账本已读取且周期没有记录时直读可为零；缺少直读账本时不生成该分项。账户额度、Qoder 积分和生图次数各自保留原单位。Codex 官方账户用量保存在独立的 `metrics.account_tokens`，本机账本使用 `metrics.tokens`。

应用覆盖行与活动行通过 `application_id` 关联。桌面包有单独的路径与版本；同一采集器覆盖多个客户端时在同一应用组展示。仅发现账本的 CLI 标为 `discovery_kind=local_ledger`，仅有历史导入标为 `imported_history`，两者均不声明已安装桌面包。来源开关同时约束直读与活动。Claude 的额度开关单独控制钥匙串与账户查询。

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

**边界**：该账本只在账户额度卡片展示（"积分消耗 今日/近30天/全部"行），不计入本机消耗——`LocalUsage` 只汇总各来源 tokens 指标，qoder 的 tokens 保持 not_provided；也不参与 API 价格表估算（cost 仅由 tokens 驱动）。网页/SDK 钱包查询失败时账本照常附着（账户源 status 仍为失败原因，卡片显示本地积分）；账本读取失败不覆盖已有钱包行，错误码记入 `diagnostics.credits_ledger_error`。用户在应用内关闭 qoder 时本地积分一并停止。该账本独立计量，不与其他本机 Token 账本合并。verify 对 today/all 两个周期的 requests/credits/billable 做独立重算对账（本机实测逐位一致）。

## CLI 会话日志直读

Codex CLI、Claude Code、Gemini CLI 与 MiniMax Code 的会话历史由直读采集器读取，不依赖任何第三方路由数据库。Codex 直读支持压缩 rollout `*.jsonl.zst` / `*.jsonl.zstd`（优先标准库 `compression.zstd`（Python ≥ 3.14），否则调用 `zstd` CLI；两者都不可用时跳过压缩文件、未压缩文件照常统计），`~/.codex/sessions` 与 `~/.codex/archived_sessions` 都会读取；同一 base 名同时存在未压缩与压缩文件时优先未压缩。

| 来源 | 数据位置 | 去重规则 | 附着位置 |
| --- | --- | --- | --- |
| Codex | `~/.codex/sessions` 与 `~/.codex/archived_sessions` 的 rollout 文件（`.jsonl` 与压缩 `.jsonl.zst` / `.jsonl.zstd`）的 `token_count` 事件 | 首条优先取本次 `last_token_usage`，后续按累计差分，重复快照跳过；按上游总量判断推理是否已含在输出中，模型随 `turn_context` 更新。只有总量的记录保留 `unclassified`，不参与估价 | 附着在 `codex` 来源 tokens 指标 |
| Claude Code | `~/.claude/projects/**/*.jsonl` + Claude 桌面端 `~/Library/Application Support/Claude/local-agent-mode-sessions/**/.claude/projects/**/*.jsonl` | 同一 `requestId` 的多条流式记录取时间戳最新的一条（跨文件、跨 CLI/桌面端全局去重）；sidechain 子代理记录计入 | 附着在 `claude` 来源；coverage=`claude_code_and_desktop_local_sessions` |
| Gemini CLI | `~/.gemini/tmp/*/chats/session-*.jsonl` | 同一消息 id 取最新记录；fresh = input − cached；output = output + thoughts | 独立来源 `gemini`（scope `local_session_history`） |
| MiniMax Code | `~/.minimax/v2/sqlite/runtime-state.sqlite` 的 `local_runtime_token_usage` 表 | 每行一次请求，input 已是新鲜值 | 附着在 `minimax_code` 来源 |
| Antigravity (agy CLI 与桌面端) | `~/.gemini/antigravity-cli/conversations/*.db` 与 `~/.gemini/antigravity/conversations/*.db` 的 `steps.metadata` protobuf | 每个 LLM 步（step_type=15）一次调用的 usage 子消息；模型名取自按序对齐的 `gen_metadata` 行；跨两个目录按会话 UUID 去重（取 mtime、size 较大者） | 独立来源 `antigravity`（scope `account`）；token 进本机消耗，5 小时/周额度进账户卡 |

Antigravity 的 usage 字段在本机（agy 1.3.2 / 桌面 2.28.2）解码并交叉验证：f2=新鲜输入、f3=含思考的输出总量、f5=缓存读取、f9=思考部分、f10=不含思考的输出（f3−f9=f10 在 155/155 条带 token 字段的 transcript 上成立）；f5 与转录里的 `cache_read_tokens` 在 155/155 条上逐位一致。f1/f6 随会话变化但在会话内恒定，未能识别，按不臆测原则不计入指标。所有已检查步骤没有 cache write（转录字段为 null/0），故 `cache_write=0`，`cache_semantics=f5_cache_read_verified_cache_write_absent`。数据库使用包含已提交 WAL 的只读事务。主库只读打开失败且目录没有 WAL 时回退到 immutable。缓存同时检查主库和 WAL 的变更。CLI 与桌面两个目录合并为一个账本，跨目录按会话 UUID 去重。本机数据显示 CLI 历史自 2026-06-17 开始，恰为 Gemini CLI 最后一次记录之日，`gemini` 与 `antigravity` 两来源互补不重叠。

**直读为主**：agy 历史完全由 `~/.gemini/antigravity-cli/conversations` 与 `~/.gemini/antigravity/conversations` 的直读账本提供，不做跨来源重叠剔除，也不再有"导入日"概念。verify 对四个周期做独立重算；因 WAL checkpoint 可能在快照后才露出新步，较小的正漂移记为 `inconclusive_live_drift`，反向漂移仍失败。

### Antigravity 桌面端 5 小时/周额度（本地 RPC）

额度只在 Antigravity 应用运行时读取，不访问外网、不复用 OAuth 凭据：采集器 `agent_meter/agy_quota.py` 用 `ps` 找到带 `--app_data_dir antigravity`（桌面优先，其次 `antigravity-cli`）的 `language_server` 进程，解析其 `--csrf_token` 与 `--override_ide_version`；再用 `lsof` 找该进程的 localhost 监听端口，只对 `http://127.0.0.1:<port>` POST `exa.language_server_pb.LanguageServerService/<Method>`，请求头 `x-codeium-csrf-token`，body `{}`。

| 项 | 契约 |
| --- | --- |
| 方法 | `RetrieveUserQuotaSummary`（主）；失败时退化为 `GetUserStatus.cascadeModelConfigData` 的逐模型 `quotaInfo`（仅保留带 `resetTime` 的模型，`source=agy_language_server_models`） |
| 输出 | `quota` 指标为 rows 数组：`{bucket, group, window, window_minutes, used_percent, remaining_percent, remaining_fraction, resets_at, description, source}` |
| 窗口 | 上游 `window` 字段直接映射：`5h`→300 分钟，`weekly`→10080 分钟；本机看到 Gemini Models（5h/weekly）、Claude and GPT models（5h/weekly）、Gemini 4 Argon（weekly）共 5 个桶 |
| 数值 | `remaining_percent=remainingFraction*100`，`used_percent=(1−remainingFraction)*100`；`resets_at` 为上游 `resetTime` 的时间戳合同对象 |
| 隐私 | 不读取、不返回、不记录 `GetUserStatus` 中的姓名、邮箱、token；只连 127.0.0.1 |
| 失败 | 没有运行中的服务 → `antigravity_language_server_not_running`（quota 指标 `not_connected`）；RPC/解析失败 → `antigravity_quota_unreadable`（`error`）。token 账本不受影响，来源整体标 `partial` |
| 配置 | `agy_conversations_dir`（CLI，默认 `~/.gemini/antigravity-cli/conversations`）与 `agy_desktop_conversations_dir`（桌面，默认 `~/.gemini/antigravity/conversations`） |
| UI | 来源 `antigravity`（scope `account`）进「账户额度」页：一张卡显示 5 小时/周额度条 + 本机 Token 今日/30 天/全部；应用关闭时额度区显示未连接，卡片因 token 账本仍在而保留 |
| verify | 结构（bucket 集合、`window_minutes`、`resets_at`）逐项核对；`remaining_percent` 允许 1 个百分点漂移（用户可能正在生成） |

## DeepSeek Harness（dsh）本机会话账本

DeepSeek Harness（dsh）把每个会话的账本写成 zstd 压缩的 JSONL：`~/.dsh/sessions/<编码后的项目路径>/<会话id>/session.v3.jsonl.zstd`（v3）、`session.v4.jsonl.zstd`（v4）或旧格式 `session.jsonl.zstd`。采集器 `agent_meter/dsh_tokens.py` 递归读取 `session*.jsonl.zstd`，只读 usage 字段、绝不读对话文本；解压优先用标准库 `compression.zstd`（Python ≥ 3.14，诊断记 `stdlib_compression_zstd`），否则调用 `zstd -dc`（`zstd_binary` 配置，记 `zstd_cli`），两者都不可用报 `zstd_unavailable`。

三代 schema 的 usage 位置（本机 v3/旧格式 20,578 条验证于 2026-10-18，v4 5,044 条验证于 2026-10-31）：

| 代 | usage 位置 | 模型位置 |
| --- | --- | --- |
| v3 | `type=="assistant/message"` 的 `data.usage`（`inputTokens/outputTokens/cacheReadTokens/reasoningTokens/totalTokens`） | `data.message.source.model` |
| v4 | 同 v3 的 `assistant/message.data.usage`；新增 `cacheWriteTokens`，不再有 `reasoningTokens` | `data.message.source.model` |
| 旧 | `type=="assistant/chunk"` 的 `data.chunk.usage` 为渐进值（早期可为 0），同 (turn, step) 随后的 `assistant/message` 的 `data.usage` 是最终值（无 totalTokens） | 同文件最近一条 `type=="request/header"` 的 `data.header.config.model`，没有则 unknown |

v3/v4 的 `data.stream` 数组可能内嵌一份相同的 usage 块——只读 `data.usage`，绝不重复计数。字段拆分：`fresh_input=inputTokens`（未命中缓存的新鲜输入）、`output=outputTokens−reasoningTokens`（v4 无 reasoning 字段，按 0）、`reasoning=reasoningTokens`、`cache_read=cacheReadTokens`、`cache_write=cacheWriteTokens`（v4 本机全部为 0，缺失记 0）。去重：同文件内按 `(turn, step)` 保留时间戳最大的一条（`last_usage_per_turn_step`，last-wins 同时覆盖 chunk+message 成对重复与渐进 0 值）；跨文件不去重（每文件独立会话）。`time` 为毫秒 epoch，换算成秒后再分桶。

独立来源 `deepseek_harness`（scope `local_session_history`），分组 app 名 `dsh`，只汇总自己的会话文件，不做跨账本日期剔除。错误码：目录不存在或没有任何 `session*.jsonl.zstd` → `dsh_sessions_not_found`（not_connected）；单文件解压/解析失败只跳过并计入 `diagnostics.skipped_session_files`，不炸整个来源。diagnostics 另有 v3/v4/旧格式文件数与 `decompression_route`。配置项 `dsh_sessions_dir`（默认 `~/.dsh/sessions`）与 `zstd_binary`（默认 `shutil.which("zstd")`）。verify 对四个周期做独立重算对账。

## Kimi 桌面端本地会话账本

Kimi.app 的 Agent 模式自带一套独立的 Kimi Code 运行时，账本写在 `~/Library/Application Support/kimi-desktop/daimon-share/daimon/runtime/kimi-code/home/sessions`（配置键 `kimi_desktop_sessions_dir`），与 CLI 的 `~/.kimi-code/sessions` 目录结构相同：`**/agents/<agent>/wire.jsonl`，schema 一致。采集器 `agent_meter/kimi_desktop_tokens.py` 只替换根目录与分组 app 名，解析与汇总复用 `agent_meter/kimi_tokens.py`；只读 token 字段与模型名，绝不读对话正文，每文件按 `(mtime,size)` 增量缓存。自动起名（`ctitle-*`）与子代理会话照常计入。

wire.jsonl 口径（与 CLI Kimi Code 相同）：

- 每个模型轮次只写一条 `{"type": "usage.record", "usageScope": "turn"}`；该轮 `step.end`、逐消息元数据与父会话的 `subagent.completed` 是同一组数字的重复，只计 `usage.record`/`turn` 这一条。
- 字段：`fresh_input=inputOther`、`output=output`、`cache_read=inputCacheRead`、`cache_write=inputCacheCreation`，`total_tokens` 为四者之和；`time` 为毫秒 epoch，换算后按 Asia/Shanghai 分桶。
- `usageScope=session` 的记录含义未确认，排除并计入 `excluded_session_scope_records`（本机 13 条）。

独立来源 `kimi_desktop`（scope `local_session_history`），分组 app 名 `kimi_desktop`，`coverage=kimi_desktop_local_sessions`，`dedup_rule=usage.record_turn_only`；tokens 指标结构与其他会话账本一致（`periods.today/7d/30d/all` 的 totals 与按模型 groups、`daily_buckets`）。**只出现在「本机消耗」页，不挂账户卡片**——Kimi 桌面端没有账户额度接口，普通聊天也不写本地账本，只有 Agent 模式产生记录。错误码：目录不存在或没有任何 `wire.jsonl` → `kimi_desktop_sessions_not_found`（not_connected）。配置键 `kimi_desktop_sessions_dir`（默认路径见上）。

与已接 CLI `kimi` 来源的关系：两者按 session id 与逐条 usage 记录核对，实测样本没有重叠，因此**不合并也不剔除**：两条账本各自独立汇总，各自计量。verify 对四个周期的 totals 与按模型分项做独立重算对账。

## 会话活动（GET /v1/activity，schema 1）

`agent_meter/activity.py` 提供一个**独立于全量快照的轻量活动视图**：只扫最近窗口（`activity_window_hours`，默认 24 小时），按会话/线程聚合，绝不触发完整账户采集与全历史解析；文件源先按 mtime 预过滤（窗口外文件不解压不解析），解析结果进独立的 4 MB 小缓存（不挤占 token 账本的 16 MB 共享缓存）。服务端 `SnapshotService.activity()` 额外做 3 秒 TTL 防抖（配置变更即失效重算），菜单栏活动页按 5 秒（页签可见）/15 秒（后台有进行中）/120 秒（空闲）轮询该端点。**只读 usage、status 与路径元数据；绝不读提示词、对话正文、工具输出与会话标题**。费用按 USD 价格表逐模型匹配估算（`estimated_cost_usd`，无匹配模型的行留空——未计价 ≠ 0）。

响应字段：`schema_version=1`、`generated_at`、`window_hours`、`idle_after_minutes`、`window_start`、`activities[]`、`sources_meta`（各来源 `available`/`not_connected`/`error` + 活动行数；单来源失败不拖垮端点）。

状态词汇（分级严格，`unknown` 绝不等于失败）：

| 状态 | 判定依据 |
| --- | --- |
| `running` 进行中 | 最近事件在空闲阈值内（`activity_idle_minutes`，默认 15 分钟）——必须有明确活动证据 |
| `suspected_ended` 疑似结束 | 超过空闲阈值没有新事件；不宣称成功 |
| `completed` / `failed` / `cancelled` | **只接受明确状态事件** |
| `unknown` 未知 | 日志截断、状态值不认识、覆盖不足 |

每行带 `granularity`（行的粒度）与 `status_basis`（`recency`=按最近活动推断 / `explicit_event`=明确事件）、`notes`（粒度局限的稳定键）。**回合完成 ≠ 整个会话完成，子代理完成 ≠ 根任务完成，停止写入不能算成功，应用退出也不能算失败**——因此会话行的自身状态只取 `running`/`suspected_ended`（recency），明确的终态事件降一级放在 `turn_statuses` / `last_turn_status` / `recent_turns`（最多 5 个回合的时间线：起止、终态、模型、步数、token）。`subagent` 标注子代理会话（ZCode `sess_subagent_*`、Claude `isSidechain`、Kimi 非 main agent）。

| 来源（app） | granularity | 会话状态依据 | 明确终态事件的出处 | 项目路径 |
| --- | --- | --- | --- | --- |
| `zcode` | `turn` | recency | `model_usage.status`（completed/error/cancelled，按 turn 聚合）；0 token 行不用于推断状态 | `session.directory` |
| `deepseek_harness` | `turn_steps` | recency | v4/v3 `turn/end` 的 `data.reason.kind`（completed→completed、aborted→cancelled、其余→unknown）；usage 仍按 (turn, step) last-wins 去重 | v4 `session` 头行的 `cwd`（不解码目录名，避免 `-` 歧义） |
| `kimi` / `kimi_desktop` | `steps` | recency | `turn.ended` 的 `reason`（completed→completed 等，未知值→unknown）；`usageScope=session` 记录照旧排除 | 无（别名用 workspace 目录名，不透明但稳定） |
| `codex` | `recent_activity` | recency only | 从 `codex_state_db` 的 threads 索引读活动时刻，优先使用 recency_at | cwd |
| `codex_images` | `image_call` | **explicit** | `thread_items` 的 imageGeneration 调用状态：generating→running、最后调用 failed→failed、completed→completed（该库 3.5 GB，`history_threads` 走 600 秒进程内缓存，进行中状态最多滞后 10 分钟；调用状态只代表调用，不代表整个 Codex 会话） | 无 |
| `claude` / `gemini` / `opencode` | `recent_activity` | recency only | 无终态事件（停止写入 ≠ 成功）；Claude 读 assistant 行的 `message.usage` 与 `cwd`、Gemini 读 `tokens` 行（fresh=input−cached）、OpenCode 读 `message.data.tokens` | Claude `cwd`；OpenCode `session.directory`；Gemini 无（项目哈希不可解 → 未归属） |

隐私与性能红线：配置项 `activity_window_hours`/`activity_idle_minutes` 只影响本端点；窗口过滤按事件时间而不是文件时间；dsh 损坏文件跳过计数不报错；ZCode/OpenCode 侧 schema 不满足时该来源 `not_connected`（`unsupported_zcode_usage_schema`/`unsupported_opencode_schema`）。`GET /v1/activity` 与快照端点同样受 Bearer token、Host 白名单与无 query 参数限制；**调用它绝不会触发 `/v1/refresh` 式全量采集**（有测试断言）。

## 本地价格表与 API 等价估算

`GET/PUT /v1/prices` 管理一份本地价格表（`prices.json`，0600，位于 runtime 目录）：`{currency: USD|CNY, models: {pattern: {input, cache_read, cache_write, output}}, peak_multipliers, aliases}`，单价按每百万 tokens。默认值来自[定价摸排](pricing-survey-2026-10-09.md)（含 2026-10-15 与 2026-10-28 增补）：取有官方刊例的一侧币种，另一侧按 7.25 汇率折算并在 GET 的 `converted_patterns` 中列出（双向：仅 USD 刊例的折成 CNY，仅 CNY 刊例的国产模型折成 USD）；用户编辑过的条目移出该列表。CNY 表中，官方人民币刊例的模型优先于 `models.dev` 目录的美元折算值（目录按美元下发，折算可能覆盖国内价），目录只在没有官方人民币价时参与折算。匹配规则（2026-10-15 起先归一化再匹配）：两侧都取最后一个 `/` 之后的模型 id、转小写并把 `.` 统一成 `-`（`account:bigmodel-coding-plan/GLM-5.3-Flash`、`glm-5-3-flash`、`GLM-5.3.Flash` 都命中 `glm-5.3-flash`），归一化后精确命中优先、否则取最长子串 pattern；快照里的 `model` 字段保留原始拼写。

带按模型分项的本地 token 来源（`imported_history`、ZCode/OpenCode/Gemini/Antigravity/Codex/Claude/MiniMax Code 直读、Kimi Code、Kimi 桌面端、WorkBuddy、DeepSeek Harness）会得到 `cost` 指标：`{unit: 币种, kind: estimate, basis: local_price_table, peak_window, peak_multipliers, periods: {period: {amount, peak_amount, offpeak_amount, peak_models, offpeak_models, models, app_models, unmatched_models, unsplit_models}}}`；有未匹配模型时 status=partial（未匹配部分不计零价）。仅 CodexBar 保留自己的估价口径；DeepSeek 的 provider 账单 cost（见下）不会被覆盖。订阅套餐内的调用不按 API 价计费，估算仅作量级比较。

**峰谷计价（2026-10-28）**：DeepSeek 官方峰时为北京时间工作日 09:00–12:00、14:00–18:00（UTC 周一至周五 01:00–04:00、06:00–10:00），峰时价为谷时刊例的 2 倍；周末全天谷时，法定节假日未内置日历（按工作日处理）。价格表的四项单价始终是谷时基准，`peak_multipliers` 单独保存用户覆盖（默认 DeepSeek 系 2.0）；`GET/PUT /v1/prices` 的每个模型带 `peak_multiplier`，顶层带 `peak_window` 与已保存的 `peak_multipliers`。带逐请求时间戳的账本在 tokens 指标的每个 period `totals` 与每个 model `group` 内写 `peak`/`offpeak` 两个分项（字段镜像该来源自身 token 字段，并各带 `total_tokens`），指标顶层标 `peak_split: request_timestamp`；`imported_history` 同时含逐请求 `detail` 与日汇总 `daily`，标 `peak_split: request_timestamp_and_daily_rollups`，`daily` 行按谷价并计入 `unsplit_models`。估算时峰时部分按倍率、谷时部分按基准价，无拆分或没有时间戳的整组按谷价并记入该 period 的 `unsplit_models`；每个 period 另按原始模型名给出 `peak_models` / `offpeak_models` 峰/谷金额（只列非零），账户额度页的 DeepSeek 卡据此只汇总 DeepSeek 系模型的峰谷数据。

菜单栏「本机消耗」页对全部本机账本（含 `imported_history`）使用同一份本地价格表估算：按应用行与模型排行显示各自金额，无定价模型按 token 量排序列出前几个。账户页金额统一人民币（USD 按固定汇率 1:7.25 折算后汇总，原始账本币种保留用于审计）。全零估算显示「—」，不把未知价格当零。

## DeepSeek 网页用量（仅展示）

`deepseek_api` 来源可选携带 `user_token`（platform.deepseek.com 登录后的 localStorage 值，经应用内存通道传入，不落盘）。提供时后端以 Bearer 只读调用控制台未公开接口 `GET /api/v0/usage/by_api_key/amount|cost?start&end&tz=28800`（契约取自 MIT 的 deepseek-harness-usage-dashboard 逆向，2026-09 schema），把近 30 天按天分桶写进 `cost` 指标：`{basis: platform_web_usage, currency, daily: [{date, tokens, requests, amount}], windows: {today, 3d, 7d, 30d}, total_amount, total_tokens}`。`windows` 每项为 `{amount, tokens, requests, days}`，按 GMT+8 日历日含今天向前取 1/3/7/30 天，晚于今天的日期忽略；账户卡展示今日、近 3 天、近 7 天，另保留近 30 天合计。该指标**不计入本机消耗**（tokens 指标不受影响）；各本机账本独立汇总，不再对任何其他数据源做重叠剔除。接口失败只降级该指标（固定错误码），不影响余额读取。该接口未公开、随时可能变更，尚未在本机登录会话上实测。

直读解析带每文件 (mtime,size) 增量缓存；文件被 CLI 清理时本地记录天然为下界。

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

## 每日积分领取（snapshot.rewards）

`agent_meter/rewards.py`，仅由 `SnapshotService` 调用（CLI 的 `collect` 不涉及）。快照顶层新增 `rewards`：`{schema_version: 1, timezone: "Asia/Shanghai", accounts: [...]}`，每个网页登录账户一项（`trae_cn`、`trae_cn#2`、`workbuddy`…）：

- `status` / `reason`：`available`；`not_connected`（`not_authenticated`、`disabled_by_user`、`local_only_mode`）；`error`（固定错误码）。
- `today`：TRAE 为 `{kind: daily_checkin, enabled, signed_in, daily_credits, extra_credits, claimable}`；WorkBuddy 为 `{kind: growth_tasks, signed_in: null, streak_days, next_tier, next_tier_remaining, makeup_cards, makeup_cards_max, tiers, open_tasks, claimable}`。`claimable` 每项 `{item, title, credits}`，item 为 `daily_checkin` 或 `task:<task_code>`。
- `claims_today`：`{item, title, at, result: ok|already|rejected|error, credits?, code?, reason?, badge?}`；`claimed_credits_today` / `claimed_credits_total`；`streak_days`（仅 TRAE：按北京时间连续已签到的天数，今天未签时截至昨天）；`history`：近 35 天 `{date, signed_in, claimed_credits}`。

节流：每个账户 30 分钟最多读一次状态（跨日立即读）。领取只在 `PUT /v1/preferences` 的 `auto_claim`（`trae_cn`、`workbuddy` 子集，默认空）开启、且北京时间已过 `claim_time`（`HH:MM`，默认 `00:05`；菜单栏默认 08:00）时进行；过了领取时间后的第一次采集不受 30 分钟节流，立即读状态并领取。每个账户的摘要带 `claim_time` 与 `next_claim_at`（自动领取关闭时为 null）。菜单栏在领取时间过 15 秒和再过 70 秒各强制刷新一次，不等常规轮询；每次领取成功发一条系统通知（积分、连续天数、徽章），同一项当天第 3 次失败时发一条失败通知，已通知的结果记在 UserDefaults `notifiedClaims`，首次运行只记录不通知。同一项每天最多试 3 次、失败后 1 小时再试，`ok` / `already` 后不再试。TRAE 的 9004 记作 `already`，但不计为已签到（可能是参数错误），以领取后重读的状态为准。

接口：

- `PUT /v1/preferences` body `{"disabled_sources": [...], "auto_claim": [...], "claim_time": "08:00"}`，`auto_claim`、`claim_time` 可省略。
- `POST /v1/rewards/claim/<slot>`（无 body，`#` 编码为 `%23`）：对该账户立即读状态并领取，不受开关和节流限制，返回最新 `rewards`，同时更新缓存快照。

上游接口与实测记录见[每日积分研究](research/checkin-automation-and-collection-2026-11-09.md)。

## 卡册与奖章（snapshot.collection）

`agent_meter/collection.py`，由 `SnapshotService` 在每次采集后计算，不联网。快照顶层 `collection`：

- `catalog`：卡片定义 `{id, name, series, series_name, rarity: common|rare|epic|legendary|faded, symbol, description}`。系列：5 小时窗口、7 天窗口、重置卡、签到与任务、纪念。
- `cards`：已获得的卡 `{id: {count, first_at, last_at, sources}}`；`recent`：最近 12 次掉落 `{card, at, source, detail}`。
- `open_windows`：未结算的额度窗口 `{source, kind: five_hour|seven_day, peak, resets_at, current_card, next_card, next_threshold}`。
- `medals`：`{id, name, category, category_name, target, unit, symbol, tier: bronze|silver|gold|platinum, value, progress, earned, earned_on, count}`。
- `stats`：`lifetime_tokens, active_days, current_streak, longest_streak, record_breaks, free_credits, best_day, today_tokens, max_apps_in_day, distinct_cards, catalog_size, total_cards, medals_earned, medals_total, by_rarity`。

掉落规则：

- 额度卡：按 `window_minutes`、`window{duration,unit}` 或桶名识别 5 小时 / 7 天窗口；同一窗口（`resets_at` 漂移不超过 10 分钟）记录峰值，下一次读到新的 `resets_at` 时结算一张，取峰值达到的最高档（50% / 80% / 90% / ≥99.5%），低于 50% 不掉卡。`stale`、`error` 来源不参与；来源消失且重置已过 1 天的窗口直接结算。
- 重置卡：库存减少时，按到期时间判断“过期前用掉”（`rc_saved`）或“过期未用”（`rc_wasted`，灰色，不计入收集进度）；只有数量时按上次的最近到期时间判断。
- 签到与任务：由 `rewards.json` 推算（每个签到日一张，连续 7 / 30 / 100 天的整数倍各一张；任务奖励与附带徽章各一张），每次重算。
- 首次生成账本时掉一张「启程」。

奖章每次按本机全部历史重算，旧历史首次即可解锁（共 46 枚，分铜 / 银 / 金 / 铂金）：

- Token：单日（1 / 5 / 10 / 50 亿）、累计（10 / 100 / 1000 / 10000 亿）、连续活跃天数（7 / 30 / 100 / 365）、单日使用的应用数（3 / 5 / 8，不含 `imported_history`）、刷新个人最佳单日次数（1 / 10）。每日 Token 为各账本 `daily_buckets` 按日期相加。
- 估算金额（人民币，USD 按 7.25 折算）：单日（¥100 / 500 / 1000 / 5000）、单个自然月（¥3000 / 1 万 / 3 万 / 10 万）、累计（¥1 万 / 5 万 / 10 万 / 100 万）。来源为各来源 `cost.value.daily`（`basis=local_price_table`），由 `prices.estimate_daily_cost` 按 `tokens.daily_models` 逐日计价；逐日行没有峰谷拆分，一律按谷价（基础价）计，所以逐日合计可能略低于期间总额。网页账单（`platform_web_usage`）不计入。
- 生图：Codex 内置生图 `image_generation.value.daily_buckets` 的张数，单日（10 / 50 / 100 / 300）、累计（100 / 1000 / 5000 / 2 万）、连续出图天数（3 / 7 / 30）。
- 创作积分：即梦、MiniMax Design 钱包余额每次下降的差额累加（充值、月度刷新只移动基线，开始记录之前的消耗无法得知），1000 / 1 万 / 10 万。
- 免费积分：Qoder 非计费积分 + 已领取的每日积分，1000 / 1 万 / 10 万。

`stats` 另含 `lifetime_cost_cny`、`best_cost_day`、`best_cost_month`、`lifetime_images`、`best_image_day`、`creative_credits_spent`。

账本 `.runtime/collection.json`（0600）只保存未结算窗口、重置卡库存、创作钱包基线与已结算的掉落，不含凭据与对话内容；损坏时重新开始。

菜单栏：「收集」标签页的奖章与卡片跟随鼠标做 3D 倾斜和高光（奖章有金属厚度、卡片内部分层视差，悬停处冒火花）；点任一奖章、卡片或最新掉落会打开详情页（与解锁动画同一个舞台：3D 能量环、环绕粒子、开场爆闪、指针拖尾），已获得的可直接复制或保存分享图，未获得的显示进度；收集册顶部有跟随鼠标的漂浮光尘；新获得的奖章或卡片（首次出现的 id，记在 UserDefaults `seenTrophies`，首次运行只记录不播放）会在面板上播放解锁动画，并发一条系统通知；解锁动画、详情页和收集册右上角都可以复制或保存分享图（540pt 宽，2x PNG）。分享图底部可附项目二维码（`https://github.com/Gary23333/agent-meter`，CoreImage 本地生成）：收集分享图的开关在详情页的二维码按钮和收集册分享菜单里（UserDefaults `trophyShareQR`，默认开）；用量报告分享卡在报告窗口勾选「项目二维码」（`ShareOptions.qrCode`，默认开，旧设置读取时补默认值）。开启「减弱动态效果」时只显示静态画面。

## 测试分层

1. 人工可核算的固定样例：缓存语义、重复记录、时间边界、零与未知、截断卡片及货币。
2. 接口与生命周期测试：本机 HTTP 认证、Host 和 Origin、超时、子进程关闭、缓存并发和失败保留。
3. 本机账本对账：每个本机来源（ZCode、WorkBuddy、OpenCode、Codex/Claude/Gemini/MiniMax Code 直读、Kimi Code、Kimi 桌面端、Antigravity、DeepSeek Harness）从自己的文件或数据库独立重算；`imported_history` 从 `<runtime>/imported-history.json` 独立重算四个周期的 totals 与记录数。ZCode 另与 `turn_usage` 做容差交叉校验（上游记账存在约 0.0001% 漂移）。不再有 CC Switch SQL 对照或跨账本剔除日期一致性检查。
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

历史 schema 1/2 证据文件保留原版本；当前快照和 health 为 5。

## 全员重置预测（schema 4）

独立来源 `reset_forecast`，scope `external_forecast`。它记录 OpenAI Codex 负责人在 X 上不定期宣布的**全员额度重置**（社区称 Tibo 重置），与各账户自身的 5 小时 / 每周窗口是两类事件：本来源**永不写 `reset_time`**，也不进入账户卡片、菜单栏滚动和本机消耗，只在面板「重置预测」页展示。

三家追踪站各自的字段由 `agent_meter/reset_forecast.py` 归一化到同一行结构：`raw_24h/raw_48h`（站内模型值）、`headline_24h/headline_48h`（该站对外公布的答复）、`band_24h/band_48h`（该站自评区间）、`self_reported`（信心、注记、Brier/回测样本与状态）、`cadence`（间隔统计与样本口径）、`promise`（承诺横幅）、`typical_window`（常见公告时段）、`last_reset`、`updated_at`、`provenance`。

合成规则：`ensemble.horizons.<24h|48h>` 的区间与加权中位数**只用各站自己公布的数值**（`basis=published_answer`；某站没公布时才回退到站内模型值并标 `cadence_model_fallback`）。权重完全取自各站上报的质量字段——自报信心、校准状态、样本量、数据新鲜度——系数常量在模块顶部，逐行随 `weight_components` 下发，便于核对。超过 48 小时未更新的来源整体剔除（`forecast_source_stale`），不按 0 处理。

`known_reset_countdown.targets[]` 每项带 `kind`（`promised_reset` / `typical_window`）、`precision`（`window` / `label_only`）、`open_at/close_at`、`state`（`upcoming` / `inside_window` / `elapsed_awaiting_landing` / `no_clock` / `label_only`）与 `sources`。只有拿到可机读的时间或时段才给 `seconds_remaining_*`；公告只说"会重置"没给时间时保留 null 并在面板显示"未给时间"，与日精度续费倒计时不给秒数同一原则。时段类目标按"下一个每日出现窗口"滚动。

历史 `history_events[]` 按各站共享的 X 状态 ID 去重合并，`sources` 列出印证家数；`announced_at`（公告）与 `effective_at`（观测落地）、`official_window`（官方窗口）是三个不同事实，不相加也不互相覆盖；推文正文不进快照，只留各站的摘要文本（截断 240 字）。

失败与节流：三家全挂且无缓存时来源为 `error`、code `reset_forecast_sources_unavailable`；有缓存则按 `stale` 返回旧值并保留原观测时间。默认 45 分钟抓一次（`reset_forecast_refresh_minutes`），有来源失败时缩短到 5 分钟重试，缓存写在 `.runtime/reset-forecast.json`（0600）。三家都拒绝默认 User-Agent，请求固定带应用 UA；纯公开只读 GET，不发送任何本机数据、不带 Cookie。

`codexreset.org` 没有 JSON 接口，预测对象内嵌在页面脚本里且 `score24h` 在历史序列中重复 400+ 次，解析锚定 `forecast:$R[` 到 `semanticSignals` 的区间；锚点缺失即 `forecast_object_not_found`，字段缺失即 `unsupported_forecast_contract`，两者都只让该源降级，不影响其余两源。

预测类两个指标不计入应用覆盖矩阵（`COVERAGE_METRICS` 排除），否则每个应用都会凭空多出两项"缺失"。`verify` 对每条区间、中位数、分歧标签、去重与倒计时状态做独立重算，共 33 项。


## 2026年10月30日 价格预览与人民币展示

新增认证只读端点 `GET /v1/prices/USD` 与 `GET /v1/prices/CNY`，响应形状同 `GET /v1/prices`，额外返回 `user_patterns` 标记已保存的自定义价格。预览按请求币种读取内置/同步价，自定义覆盖按固定 7.25 汇率换算；不修改磁盘配置或快照。默认 `GET /v1/prices` 仍返回已保存币种，`PUT` 仍负责保存。

应用所有 USD/CNY 金额统一展示人民币，USD 先乘 7.25 再汇总（固定估算汇率，非实时汇率）。此规则取代前端旧的双币种分列；原始 API 金额保留原币种以便独立核对。Token 费用、生图费用和账户余额各自独立，不因统一币种而混成一个总数。
