# 本机 AI Agent 产品数据源扩展勘察（2026-10-18）

勘察日期：2026-10-18（Asia/Shanghai）。全部为本机只读勘察：未修改任何数据、未发送网络请求、未读取凭据明文、未读取对话正文（只看结构化 usage/tokens/credits 字段与表结构）。sqlite 一律 `file:...?mode=ro` 只读打开；LevelDB 只做 strings 级字段探查，不做深挖。

勘察动机：后端已有 CC Switch、Codex、Claude、Kimi Code、即梦、MiniMax Design、ZCode、WorkBuddy、OpenCode、Antigravity、MiMo API、StepFun、火山方舟、DeepSeek 网页、Tibo 预测等来源（及实现中的 DeepSeek Harness `~/.dsh`）。本文回答"还有哪些本机数据能接入"。

数据边界（沿用项目铁律）：应用 ≠ 计费账户；本机日志 ≠ 全账户用量；未知 ≠ 零（字段全 0 只能说"无有效 token 记录"）；不臆测；积分与 token 不相加。

## 结论速览

| 候选 | 路径 | 账本形态 | 分级 | 一句话依据 |
|---|---|---|---|---|
| TRAE CN | `~/.trae-cn`、`~/Library/Application Support/Trae CN` | 无逐请求账本 | C | 本地仅 UI 状态/横幅标记/自建管道遥测 7 条，聊天用量在云端 |
| CodeBuddy | `~/.codebuddy`、`~/Library/Application Support/CodeBuddyExtension` | 无账本 | C | 前者仅内存监控日志；后者仅 WorkBuddy 加密认证存储（WorkBuddy 已接入） |
| Cursor | `~/.cursor` | 无账本 | C | 应用主数据目录不存在；`ai-tracking.db` 全空表（仅 1 行 tracking_state） |
| Cherry Studio | `~/.cherrystudio`、`~/Library/Application Support/CherryStudio` | LevelDB 内嵌 usage 块 | C | usage 结构存在（`type_ "usage"` + prompt_tokens）但现存仅 3 条，且 LevelDB 需逆向 |
| 豆包 | `~/.doubao`、`~/Library/Application Support/Doubao` | 无账本 | C | `chats/` 是媒体导出（244 文件，06-25→07-17 已停）；桌面端为 Chromium 壳，用量在云端 |
| Kimi 旧 CLI | `~/.kimi/sessions` | 逐轮 token 账本（旧格式） | **A（新增）** | 3,971 条逐轮记录、3.96 亿 token、2026-02-13→06-17，标准库可读，现后端未覆盖 |
| Kimi Code | `~/.kimi-code/sessions` | 已接入（usage.record） | 已覆盖 | `agent_meter/kimi_tokens.py` 读 `**/agents/*/wire.jsonl`，无需处理 |
| Kimi 其余 | `~/.kimi-cu`、`~/.kimi-work`、kimi-desktop、kimi-code-app、KimiCU | 无账本 | C | 身份/更新状态/二进制/Electron 壳，本地存储无 usage 字段 |
| Qoder 全球版 | `~/.qoder`、`~/.qoder-cli`、`~/.qodersec`、`~/.qoder-scratch` | 无账本 | C | 全球版 18 个 jsonl 仅 transcript；qodersec 13 个执行文件无 usage；ai-stats 是行数统计；scratch 是本项目自建探针目录 |
| MiniMax Agent CN | `~/.minimax-agent-cn` | 空 | C | 目录存在但 0 字节 |
| MiMo Code | `~/.local/share/mimocode/mimocode.db`（配置在 `~/.config/mimocode`） | 逐消息 token 账本（opencode 同构） | **A（新增）** | 868 条 assistant 记录、2.26 亿 token、带模型与毫秒时间戳，标准 sqlite |
| DevECo | `~/.local/share/deveco/deveco-stable.db`（配置在 `~/.config/deveco`） | 同构但近空 | C | 仅 6 条 message / 4 条 tokens（76,621 token，单日 2026-09-17），留观察 |
| OpenCode 桌面端 | `~/Library/Application Support/@opencode-ai`、`ai.opencode.desktop` | 无独立账本 | C | `@opencode-ai/desktop` 为空；桌面壳仅 drafts.sqlite（草稿）；运行库即已接入的 `~/.local/share/opencode/opencode.db`（13,598 条消息，10-14 仍在写） |
| DeepSeek 旧 TUI | `~/.deepseek` | 仅会话级累计 | C（归档） | 核实：10 个会话文件只有 `metadata.total_tokens`，无逐请求字段，最后写入 2026-07-28 已停用 |

**A 级新增 2 项：Kimi 旧 CLI（`~/.kimi/sessions`）与 MiMo Code（`~/.local/share/mimocode/mimocode.db`）。**

## 逐项勘察

### 1. TRAE CN（`~/.trae-cn` 2.1G、`~/Library/Application Support/Trae CN` 6.9G）

- `~/.trae-cn/631551464320604/<workspace>/`：仅 refactor 元数据（blame_files.json 等），无 usage。
- `~/Library/Application Support/Trae CN/User/globalStorage/state.vscdb`（ItemTable 347 键）：credits 相关键只有横幅弹窗触发标记（`credits.monthlyGranted…`、`credits.dailyCheckin…`，含 lastWriteDay，无积分数值）；无 token/usage 键。
- 全部 22 个 workspaceStorage `state.vscdb`：`ChatStore`/`chat.ChatSessionStore.index` 均为 UI 状态（气泡高度等）；IndexedDB 仅 1KB。
- `~/.trae-cn/telemetry/telemetry.log`：7 条记录（2026-07-22→08-04），字段 `tokenUsage{promptTokens,completionTokens,totalTokens}`+`costCNY`，但 bookId/pipelineRunId/agent 表明这是用户自建"写书管道"的遥测（providerId 指向 api.deepseek.com），不是 TRAE 自身对话账本；按不臆测不计入 TRAE 用量。
- **分级：C。** TRAE 对话用量在云端；账户额度沿用既有网页会话路线（见共享知识 README，本机未实测）。若接：无本地账本可接。

### 2. CodeBuddy（`~/.codebuddy` 700K、`~/Library/Application Support/CodeBuddyExtension` 12K）

- `~/.codebuddy/logs/memwatch/*.log`、`diagnostics/cli-high-heap`：内存监控，grep 无 usage/token/credits。
- `CodeBuddyExtension/Data/Public/auth/workbuddy-desktop.info`：WorkBuddy 桌面端认证存储（uid/uin/加密 envelope 的 accessToken/refreshToken，auth.domain=www.workbuddy.cn），无任何用量字段。WorkBuddy 会话日志后端已接入。
- **分级：C。** 无账本；认证存储按项目规范不读取凭据。

### 3. Cursor（`~/.cursor` 216K）

- `ai-tracking/ai-code-tracking.db`：6 张表（ai_code_hashes/scored_commits/conversation_summaries/tracked_file_content/ai_deleted_files）**全部 0 行**，仅 tracking_state 1 行（trackingStartTime≈2026-02-13）；该库即使有数据也是"AI 代码行数归属"，非 token。
- `~/Library/Application Support/Cursor` 不存在（主应用数据不在本机）。
- **分级：C。** 无账本、样本为零。

### 4. Cherry Studio（`~/.cherrystudio` 2.4G、`~/Library/Application Support/CherryStudio` 1.2G）

- `~/.cherrystudio/install` 2.3G 为安装器/二进制缓存；`bin/` 为捆绑的 claude/uvx/opencode 等 CLI；无会话数据。
- 聊天数据在 `CherryStudio/IndexedDB/file__0.indexeddb.leveldb`（共 1.4M，最后写入 2026-09-02）。strings 探查：压缩库 `000090.ldb` 中有 3 处 `type_ "usage"` + `prompt_tokens/completion_tokens` 记录，活动 `000088.log` 中 0 处；Local Storage（132K）0 处；其余为上传图片的文件元数据。
- **分级：C。** usage 块结构确认存在，但现存样本仅 3 条记录、9 月初后停写，且 LevelDB 无标准库读取方案（需逆向，如 node 层辅助）；价值不抵成本。若未来重度使用可复评：实现路径同 Claude 桌面端 cookie 的 node 辅助脚本模式。

### 5. 豆包（`~/.doubao` 116M、`~/Library/Application Support/Doubao` 2.2G）

- `~/.doubao/chats/YYYY-MM-DD/`：244 个文件全部为生成的媒体（mov/mp4 等），2026-06-25→07-17，非账本。
- 桌面端为 Chromium 壳：`Tea/tea.db`（应用埋点，ro 打开报 disk I/O error，且为应用分析非模型用量）、`telemetry/events.json` 为空数组、`BulitinExtensions/ai-views/stats.meta.json` 为前端构建清单。无逐请求模型用量。
- **分级：C。** 无账本；豆包用量在云端。若接：只能走账户/网页路线，超出本次本地勘察范围。

### 6. Kimi 家族去重盘点

后端现状（grep 确认）：`agent_meter/kimi_tokens.py` 读 **`~/.kimi-code/sessions/**/agents/*/wire.jsonl`**（`usage.record`/usageScope=turn）；`agent_meter/kimi.py` 读 `~/.kimi-code/server/instances/*.json` 与 `server.token`。

| 目录 | 内容 | 判定 |
|---|---|---|
| `~/.kimi`（296M） | `.migrated-to-kimi-code`（2026-06-17 迁移标记）、plans/、logs/、credentials/、telemetry/、**sessions/** | sessions 为**旧版 Kimi CLI 逐轮账本，见下**；其余非账本 |
| `~/.kimi-code`（817M） | 已接入来源 | 已覆盖 |
| `~/.kimi-cu`（8K） | identity.json、update-state.json | 身份/更新状态，C |
| `~/.kimi-work`（122M） | 仅 bin/（kimi-slides、kimi-tools 二进制），非 bin 文件 0 个 | C |
| `kimi-code-app`（142M） | Electron 壳；Local Storage 76K | 本地存储无 usage 字段，C |
| `kimi-desktop`（1.4G） | Electron 壳；Local Storage 88K、IndexedDB 2.4M | 本地存储无 usage 字段，聊天在云端，C |
| `KimiCU`（4K） | runtime.sock、runtime.token | 运行时套接字/令牌，C |

**`~/.kimi/sessions` 明细（本轮唯一 A 级新缺口之一，真实只读聚合）：**

| 项 | 值 |
|---|---|
| wire.jsonl | 80 个（含会话根与 `subagents/`、`tasks/agent-*/` 深层路径） |
| 记录形态 | 每行 `{message:{payload:{...}}, timestamp}`；usage 在 `message.payload.token_usage`，字段 `input_other / output / input_cache_read / input_cache_creation`（与 kimi_tokens.FIELDS 语义一致，snake_case）；另有同义重复字段 `context_tokens / context_usage / max_context_tokens` |
| 记录数 | 3,971 条（非零 3,960，无一条例外为 0 消耗） |
| 总 token | 396,282,036 |
| 时间范围 | 2026-02-13 14:59 → 2026-06-17 16:26（顶层 `timestamp` 为**秒级浮点**，与 kimi-code 的毫秒整数不同） |
| 模型字段 | payload 无 model 字段（**记录不可归因到模型**） |
| 去重键 | 无 request_id；需按 (文件, 行偏移) 或 (session, timestamp, 数值元组) 去重 |
| 与现来源重叠 | 与 `~/.kimi-code/sessions` 会话 ID 零重叠（hex vs `wd_*` 前缀）；CC Switch `usage_daily_rollups` 的 app_type 仅 claude/claude-desktop/codex/gemini/mcode/opencode，**无 kimi**，无双算 |
| 停写情况 | 2026-06-17 迁移后停写（另有 1 个 2026-09-01 会话文件，无 token_usage 记录） |

- **分级：A（历史账本）。** 若接：扩展 kimi_tokens 或新模块递归 glob `~/.kimi/sessions/**/wire.jsonl`，解析 `message.payload.token_usage` 四字段；模型一律 `unknown`（价格表不可估价，保持"未知不臆测"）；秒级时间戳 ×1000 对齐；与 kimi-code 两代账本分列或合并时声明口径。风险：旧格式属私有 schema，升级不会再写（已停用），回归风险低。

### 7. Qoder 家族（已覆盖：`~/.qoder-cn/projects` 积分账本）

| 目录 | 内容 | 判定 |
|---|---|---|
| `~/.qoder`（121M，全球版） | `projects/` 18 个 jsonl（2026-08），无 credits/usage；`cache/projects/*/conversation-history/` 6 个 jsonl（2026-08-03→08-28）无 usage | 仅 transcript，C（与 2026-10-15 复勘结论一致） |
| `~/.qoder-cli`（19M） | `ai-stats/`（verified-*.json、snapshots） | AI 改动行数统计，非用量，C |
| `~/.qodersec`（206M） | `state/*/*.session.execution.json` 13 个（transcript，无 usage/token/credits）；`state/telemetry/spool.jsonl`；bin/ | 独立安全产品，无账本，C |
| `~/.qoder-scratch`（2.1M） | `willreset/` 探针文件 | 本项目 Tibo 研究自建目录，非产品数据，不适用 |

- **分级：C。** Qoder 家族可采信号仍只有 CN 版积分账本（已接入）。

### 8. MiniMax Agent CN（`~/.minimax-agent-cn`）

- 仅 `projects/pocket` 空目录，0 字节。
- **分级：C。** 无数据。MiniMax Design 的 opencode 运行库已由 `design_tokens.py` 接入，此处无补充。

### 9. `~/.config/deveco` 与 `~/.config/mimocode`

两目录均只含 node_modules（运行时依赖：`@opencode-ai` / `@mimo-ai`）与配置；**真正的账本在 `~/.local/share/` 下的数据目录**。

**MiMo Code（`~/.local/share/mimocode/mimocode.db`，本轮唯一 A 级新库）：**

| 项 | 值 |
|---|---|
| 格式 | sqlite（drizzle 迁移，opencode 同构 schema：message/part/session/event…） |
| message | 900 行（user 32 / assistant 868），`data` JSON 内 `tokens{total,input,output,reasoning,cache{read,write}}` |
| 有效记录 | 868 条 tokens（非零 858），合计 225,616,716 token |
| 时间范围 | 2026-09-10 03:52 → 2026-09-22 18:07（`time_created` 毫秒；此后停写 26 天） |
| 模型 | mimo-x-pro-preview 432 / deepseek-flash 395 / mimo-v2.6-pro 41 |
| 与现来源关系 | 独立产品独立库；与 `~/.local/share/opencode/opencode.db`、`@hilo` Design 库互不重叠；后端 MiMo 现只有 API 控制台余额（账户级），此为**本机消耗账本**，无重叠 |
| 与 CC Switch 重叠 | CC Switch 无 mimo-code 类 app_type，无双算 |

- **分级：A。** 若接：标准库 sqlite ro 打开，解析 message.data.tokens（结构同 `opencode_tokens.py`，可复用解析逻辑）；scope 列入 `local_session_history`；需在停写期间容忍"账本不增长"。风险：私有 schema 升级可能变结构，按字段存在性校验、缺失报固定错误码。

**DevECo（`~/.local/share/deveco/deveco-stable.db`）：**

- 同构 schema；session 表含 tokens_input/tokens_output/cost 等列，但全库仅 1 session、6 message（4 条 tokens 非零，76,621 token，单日 2026-09-17 17:38–17:43）。
- **分级：C（样本过小，留观察）。** 若后续使用恢复，可按 MiMo Code 同一解析路径并入。

### 10. OpenCode 桌面端（`~/Library/Application Support/@opencode-ai`、`ai.opencode.desktop`）

- `@opencode-ai/desktop`：仅空子目录 `desktop/`，0 字节。
- `ai.opencode.desktop`（297M）：Electron 壳（缓存为主）；`drafts.sqlite` 12 条 document + 4 blob，为输入框草稿，无 usage；无独立运行库。
- 桌面端驱动的是已接入的 `~/.local/share/opencode/opencode.db`（13,598 条 message，mtime 2026-10-14 仍在活跃写入）——**同一库，无新增数据、无双算**。
- **分级：C。** 无需任何动作。

### 11. DeepSeek 旧 TUI（`~/.deepseek` 770M）

- 核实任务给定前提：10 个 sessions/*.json（含嵌套 artifacts）均只有**会话级 `metadata.total_tokens`**（样本：一个会话 3,247,753），逐请求字段（prompt_tokens 等）全库 0 处；`tasks/runtime/{threads,items,events,turns}` 全空；最后写入 2026-07-26/28，已停用约 3 个月；770M 主体为 snapshots（代码快照，非用量）。
- **分级：C（归档"不值得接"）。** 仅有会话级累计、无时间戳粒度、已停写；新 DeepSeek Harness（`~/.dsh` 会话账本）实现后此目录无补充价值，避免双算时注意两者是不同代际产品。

## 建议接入顺序（研究建议，非自动执行指令）

1. **MiMo Code（`~/.local/share/mimocode/mimocode.db`）**：实现成本最低——标准 sqlite、opencode 同构解析可复用 `opencode_tokens.py` 模式、带模型/毫秒时间戳/含 cache 拆项，可直接进"本机消耗"与价格表估价（mimo-x-pro-preview、mimo-v2.6-pro、deepseek-flash 三模型）。注意声明"2026-09-22 后停写"的覆盖边界。
2. **Kimi 旧 CLI（`~/.kimi/sessions`）**：价值最高（3.96 亿 token 的历史缺口，kimi 早年本机消耗完全缺失），实现要点：递归 glob、snake_case 四字段、秒级时间戳、模型一律 unknown、按 (文件,行偏移) 增量缓存；与 kimi-code 按代际声明为同一 app 的两段账本或独立分项，二选一需在实现时定案。
3. **DevECo**：并入观察清单，用量起来后按 MiMo Code 路径接入，单独实现无性价比。
4. 其余候选（TRAE、CodeBuddy、Cursor、Cherry Studio、豆包、Qoder 全球版/qodersec、MiniMax Agent CN、OpenCode 桌面端、DeepSeek 旧 TUI）：维持 C，不接入；Cherry Studio 仅在用户重度使用后复评 LevelDB 逆向路线。

## 本轮证据等级

- 真实本机只读聚合：`~/.kimi/sessions`（3,971 条逐轮记录全部数字）、`~/.local/share/mimocode/mimocode.db`（868 条）、`~/.deepseek`（10 个会话文件字段核实）、CC Switch `usage_daily_rollups`/`session_log_sync` 只读查询。
- 静态检查（表结构/键名/strings）：TRAE CN 全部 vscdb 与 telemetry、CherryStudio/豆包/Kimi 桌面壳 LevelDB、Cursor ai-tracking、qodersec、OpenCode 桌面端 drafts。
- 未做：网络请求、凭据读取、应用 UI 操作、代码改动、LevelDB 完整逆向。
