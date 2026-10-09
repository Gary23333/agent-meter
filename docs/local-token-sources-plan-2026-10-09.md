# 本机消耗新增 token 统计来源计划

日期：2026-10-09。本文件只是计划，不作为自动执行指令；本轮未实现任何新采集器。

> **执行记录（2026-10-09 同日）**：建议顺序 1–3 已实现并合入——`agent_meter/zcode_local.py`、`agent_meter/workbuddy_tokens.py`、`agent_meter/opencode_tokens.py`，含 collector 集成、coverage 主来源优先级、verify 独立重算（156 项单测、真实 verify 231 项检查全部通过）。实现与本计划的差异：WorkBuddy 的 `credit` 字段以 `credit_charged`（all 期间、单位 workbuddy_credits）随 tokens 指标一并返回；OpenCode 重叠日剔除按"CC Switch 已导入的本地日期集合动态计算"，非固定日期；stale 恢复改为保留新采集的本地 tokens。第 4 节候选维持不接。接口契约见[后端 API 文档](backend-api.md)的"其他本机 token 记录"。
>
> **同日追加**：原"不建议直接解析 Codex/Claude 本地日志"的边界被新需求取代——为未安装 CC Switch 的电脑实现了四家 CLI 会话日志直读（`agent_meter/cli_sessions.py`：Codex/Claude Code/Gemini CLI/MiniMax Code，口径与本机 CC Switch 导入逐日对齐验证）。有 CC Switch 时按日剔除其已记录日期、互不叠加，因此不再是"重复计算"风险，而是互补覆盖。详见后端 API 文档"CLI 会话日志直读"一节。

现有"本机消耗"来源只有两个：CC Switch 导入历史（proxy 日志 + 各 CLI 会话同步）和 Kimi Code 会话日志。本文回答"还有哪些本机 token 用量可以统计"，全部结论基于本机只读勘察，未修改任何第三方数据。

## 边界原则（沿用现有约定）

- 本机日志不等于全账户用量；未知值不等于零。
- CC Switch 是本地 token 历史的主来源；与其重叠的新来源只做主来源选择或对账，不叠加。
- 同一消息的流式更新、重试、子代理汇总不能重复计数；输入内含缓存子集时必须扣除。
- 应用不等于计费账户；本地推理（如 LM Studio）与云账户消耗语义不同，不混入同一口径。

## 现状：哪些其实已经被覆盖

CC Switch 数据库（schema 20）`proxy_request_logs` 按 `data_source` 分类的实际内容：

| data_source | app_type | 行数 | 日期范围 | 说明 |
|---|---|---|---|---|
| codex_session | codex | 8,762 | 09-09 → 10-09 | CC Switch 增量同步 `~/.codex/sessions` |
| session_log | claude | 4,976 | 09-10 → 10-09 | 同步 Claude Code 会话日志 |
| proxy | claude / claude-desktop | 1,111 | 09-12 → 09-23 | 经 CC Switch 代理的请求 |
| gemini_session | gemini | 677 | 05-08 → 06-17 | Gemini CLI 会话（已停止出现，疑似不再使用） |
| opencode_session | opencode | 94 | 仅 09-29 | OpenCode 会话，仅同步了一天 |
| mcode_session | mcode | 6 | 10-02 | MiniMax Code 会话 |

`session_log_sync` 按 `file_path + last_byte_offset` 增量续读，当前仍在活跃同步。另有 `usage_daily_rollups` 675 天（03-11 → 09-09）。

**结论：Codex CLI（`~/.codex/sessions`，705MB）与 Claude Code（`~/.claude/projects`，699MB）的本地日志已被 CC Switch 覆盖且仍在增量同步。后端不应直接再解析这两个目录：重复计数、且全量解析 700MB 文件的代价远高于复用 CC Switch 的偏移量同步。** 仅当未来 CC Switch 不再安装时，才考虑把它们作为独立来源（届时须沿用 600 秒同数值去重规则并与旧库对账）。Kimi Code 会话日志已由 `kimi_tokens.py` 独立实现（usage.record/turn-only、mtime 缓存）。

## 勘察证据：建议新增的来源

### 1. ZCode 本地用量库（优先级最高）

`~/.zcode/cli/db/db.sqlite`（活跃 WAL 库，只读打开 + 事务快照即可）：

- `model_usage` 表 11,592 行（2026-09-09 → 10-09，持续到勘察当天），逐模型请求一行：`input_tokens / output_tokens / reasoning_tokens / cache_creation_input_tokens / cache_read_input_tokens / computed_total_tokens`，加 `provider_id、model_id、status（completed/cancelled/error）、started_at（毫秒，已建索引）、attempt_index、query_source（main_turn/subagent/session_title/compact…）、session_id/turn_id`。
- 口径已验证：`input_tokens` 为新鲜输入（不含缓存），`computed_total = input + output + reasoning`；缓存读写单列。样本 141438/567/0/0/139968 → 142005 吻合。
- `turn_usage` 表 284 行（回合级汇总，含 model_request_count）可做独立对账；当前两表合计差约 0.6%（title/subagent 等不归属回合的请求），须按规则说明而非强行抹平。
- 本月主模型 `builtin:bigmodel-coding-plan/GLM-5.3-Flash`：输入 24.6 亿、输出 661 万、缓存读 24.1 亿 token，量级真实可统计。
- 与 CC Switch 无重叠：CC Switch 库中无 zcode app_type，ZCode 请求直连 bigmodel。
- 实施要点：新建 `agent_meter/zcode_local.py`；tokens metric 复用 periods（today/7d/30d/all）+ daily_buckets + coverage + dedup_rule 结构；状态过滤规则（completed 必收，error/cancelled 是否计输入需先定案并用 turn_usage 对账）；`attempt_index>0` 的重试行是否累计需在实现时以真实重试样本验证（当前库中全部为 0）；并发参照 kimi 模式放进采集线程池。**隐私：只读 usage 列，绝不 SELECT message 正文表。**
- 风险：db 属于 ZCode 私有 schema，升级可能变结构——按 `PRAGMA table_info` 校验必要列，缺失即报 `unsupported_zcode_usage_schema`，不猜。

### 2. WorkBuddy 本地会话日志（研究文档已预判，本轮补齐本机证据）

`~/.workbuddy/projects/**/*.jsonl`（102 个文件，120MB）：

- 记录含 `providerData.rawUsage`，OpenAI 风格：`prompt_tokens / completion_tokens / total_tokens` 及 `prompt_tokens_details.cached_tokens`、`completion_tokens_details.reasoning_tokens`；`timestamp` 为 epoch 毫秒；每条记录有独立 `id` 可做去重键。
- **口径注意（研究文档已指出）：`prompt_tokens` 已包含 `cached_tokens` 子集**，新鲜输入 = prompt − cached，不能把缓存再加一遍。
- 实施要点：新建 `workbuddy_tokens.py`，沿用 kimi_tokens 的（mtime,size）文件缓存与增量解析；按记录 `id` 去重（流式更新/重写）；记录类型过滤需先盘点哪些 `type` 携带 rawUsage（勘察样本中工具调用记录也携带，不能只取 assistant）。与网页积分来源（已实现）同一 provider，scope 仍是 `local_session_history`，两者字段不混。
- 风险：与 CC Switch 无重叠（CC Switch 无 workbuddy 数据）；上游版本升级可能改字段，按固定 fixture 验收。

### 3. OpenCode 本体数据库

`~/.local/share/opencode/opencode.db`（drizzle schema，WAL 活跃库）：

- `message.data` JSON 中 12,324 条带 `tokens` 对象：`{total, input, output, reasoning, cache:{write,read}}`，口径与 ZCode 相同（input 为新鲜输入，缓存单列）。
- **重叠边界：CC Switch 于 09-29 同步过 94 行 opencode_session。** 同日两来源并存时须择一为主（建议 CC Switch 为主、OpenCode db 补未同步区间），或在 verify 中按 600 秒启发式对账，绝不叠加。
- 实施要点：新建 collector 只读打开；json_extract 仅取 tokens 与 role/time 字段；快照事务内一次聚合。优先级低于前两者（重叠处理成本高、近期使用量小）。

### 4. 不建议 / 暂不接的候选

| 候选 | 勘察结果 | 决定 |
|---|---|---|
| Codex CLI / Claude Code 本地日志 | 已被 CC Switch 增量同步覆盖；各约 700MB | 不直接解析；CC Switch 停用时再评估 |
| Gemini CLI | CC Switch 同步止于 06-17；`~/.gemini` 未发现独立 usage 文件 | 保留缺口；先确认为何停更 |
| TRAE CN | 应用支持目录无 token 账本；TraeUseToken 路线需装扩展 + CDP 监听 | 另立研究（事件契约、版本兼容、去重） |
| Qoder | 无本地用量账本；上游"用量暴露开关"只影响后续请求 | 无历史可补；不做 |
| LM Studio / Cherry Studio | 本地模型推理日志存在 | 语义不同（本地算力，非云账户）；如接入须用独立 `local_compute` scope，不与账户消耗并列求和 |
| MiMo / 豆包 / 妙手 / AutoGLM | 无已知本地 token 账本 | 保留缺口 |

## 聚合与去重规则（实现时落入 aggregation_policy）

1. 新来源各自成为独立 source（scope=`local_session_history`），tokens metric 结构对齐 ccswitch/kimi：`periods + daily_buckets + coverage + dedup_rule`，未知即未知。
2. 同一 provider 出现多个本机来源时（如 OpenCode），coverage 只允许一个主来源署名，另一来源仅出现在 diagnostics 用于对账。
3. 重叠区间的跨来源对账沿用 verify 的独立重算模式（不调用被测 SQL 表达式）。
4. 全部增量缓存（文件 mtime/size 或 sqlite 聚合）不得回写任何第三方数据；只读打开、失败即报固定错误码。

## 验收清单（每个新来源合入前）

- [ ] 真实脱敏 fixture（正常、明确零、缺字段、字段变形、坏行、文件轮转/删除）
- [ ] 单测覆盖：新鲜输入扣缓存、流式/重试/子代理去重、毫秒时间戳、时区
- [ ] verify 独立重算对账（ZCode 用 turn_usage；OpenCode 与 CC Switch 重叠日用 600 秒启发式）
- [ ] 输出与日志无凭据、无消息正文
- [ ] 与既有来源不叠加：快照中无任何跨来源求和字段
- [ ] 采集失败不影响其他来源（进线程池、固定错误码、stale 保留）

## 建议顺序

1. ZCode 本地用量（数据最全、无重叠、结构化、机器正在活跃使用）
2. WorkBuddy 会话 token（研究已预判，本机字段已验证）
3. OpenCode db（需先解决与 CC Switch 的重叠选择）
4. 其余按上表保留缺口或另立研究
