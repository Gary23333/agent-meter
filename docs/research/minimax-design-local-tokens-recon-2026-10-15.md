# MiniMax Design 本机 token 用量勘察（2026-10-15）

勘察日期：2026-10-15（Asia/Shanghai）。全部为本机只读勘察：未发送任何外网请求，未修改任何数据，未读取凭据明文。仅对本机 Design 网关（127.0.0.1:8001）做了既有白名单模式的只读 GET（health / billing-current-scope / credit/wallet，另观察了 billing/pricing），以及对本机 SQLite 库与项目文件的只读查询。

背景：现有 `minimax_design.py` 只采钱包余额、订阅与积分刷新时间（design_local_gateway_wallet）。本轮回答"Design 的 token 用量能否统计"。

## 结论（按证据等级）

1. **Agent 对话侧的 token 账本真实存在、完整且非零，可采集。** Design.app 内嵌 opencode 运行时（进程 `Resources/opencode/opencode serve`，cwd 为 Hub 项目目录），把 LLM 会话写在自己的数据目录 `~/Library/Application Support/@hilo/desktop/ai-runtime/data-home/opencode/opencode.db`（约 175 MB，WAL 活跃写入中）。`message` 表与项目已接入的独立 OpenCode 库同构（`time_created` + `data` JSON），每条 assistant 消息带 `tokens{total,input,output,reasoning,cache{read,write}}`。截至 2026-10-15 02:13 快照：assistant 消息 11,115 条，带 tokens 的行 **0 条为零、0 条缺失**（与 Qoder 的全零陷阱相反），覆盖 2026-05-10 01:46 → 2026-10-15 02:13（实时）。
2. **必须按 session ID 剔除拷贝历史，否则与现有 `opencode` 来源双算。** @hilo 库中有 384 个会话与独立库 `~/.local/share/opencode/opencode.db` 完全同 ID、消息数几乎一致（11,720 vs 11,726）——这是用户自己的 OpenCode CLI 早期历史（全部非 Hub 目录）被整体拷贝进 Design 数据目录所致（两库第一条消息同在 2026-05-10 01:46:06）。这些 token 现有 `opencode` 来源已计。按 session ID 剔除后，Design 专属为 40 会话 / 402 条 assistant 响应（2026-06-21 22:45 起，cwd 全部为 `~/Movies/Hub/Projects/*`）。CC Switch 不读 @hilo 库（只记自己代理的 `proxy_request_logs`），无三方重叠。
3. **媒体生成（生图/生视频/音乐）按积分计费、不产生 token，本地无逐次积分扣费账本。** 钱包接口只有余额与过期分桶（`debit_credit="0"`，无历史）；项目目录 `.hilo/completed-results.json` 只记 `cloudTaskId/mediaType/assetPath/recordedAt`；`index.sqlite` 是素材索引；canvas 节点无成本字段。但网关 `GET /api/v1/billing/pricing` 返回每模型积分单价（如 wan3.0-video：480p 32 积分/秒、720p 56、1080p 120），可与本地任务纪录＋媒体元数据组合做 `basis=local_price_table` 的积分估算；估算不等于真实扣费。`/api/v1/models/concurrency/usage` 对 GET 返回 404。

## token 账本明细（真实只读聚合，2026-10-15 02:13 快照）

| 项 | 全库（含拷贝历史） | 剔除 384 个共享会话后（Design 专属） |
|---|---|---|
| 会话数 | 424 | 40（全部 `~/Movies/Hub/Projects/*`） |
| assistant 消息（带 tokens） | 11,115 | 402 |
| fresh input | 42,553,263 | 3,029,563 |
| output | 5,019,908 | 222,797 |
| reasoning | 1,320,632 | 41,190 |
| cache read | 1,645,533,560 | 21,375,192 |
| cache write | 3,213,583 | 3,213,583 |

- 模型分布（全库 assistant，按条数）：`mimo-v2.5-pro` 6,044（providerID 多为 `xiaomi-token-plan-cn`）、`deepseek-v4-pro` 1,676（`deepseek`/`ddsds`）、`big-pickle` 922（`opencode`）、`mimo-v2-pro` 1,145、`mimo-v2.5` 656、`gamma`/`alpha` 系 401、`MiniMax-M3` 6、`MiniMax-M2.7` 1。即 Design Agent 主要烧小米 MiMo Token Plan 与 DeepSeek，少量 MiniMax 自家模型。
- agent 分布：build 7,506 / general 1,527 / explore 1,025 / plan 646 / media-agent 338 / video 35 / image 11 / planner 14 / router 3 / compaction 10 / executor 1。media-agent 与 video/image 即"设计Agent"业务会话。
- 共享会话在两库中的收笔时间：@hilo 侧 2026-06-08、独立库侧 2026-06-24；此后两库各自只新增自己的会话（@hilo 独有 40 个全为 Hub 目录，独立库独有 46 个全为其他项目目录），互相不写对方。
- 参照口径：现有 `opencode_tokens.py` 读的是独立库（本机 13,598 条消息 / 430 会话），与本轮 @hilo 库是两个文件、两条账本；重叠仅为上述 384 个同 ID 会话。
- 与 MiMo 网页来源的关系：Design 经 `xiaomi-token-plan-cn` 消耗的是现有 MiMo 来源所查的同一 Token Plan 账户额度；一处是账户余量、一处是本机消耗账本，互补呈现、不相加。

## 数据边界（实施时须保留）

- **tokens ≠ 媒体积分**：token 指标只覆盖 Agent 对话侧；生图/生视频按积分计费，两个指标分开呈现，不换算不相加。
- **剔除规则**：session id 出现在独立 `~/.local/share/opencode/opencode.db` 即剔除（精确、廉价）；备选"cwd 非 Hub 目录即剔除"。当前样本两规则等价（384 共享全部非 Hub，40 独有全部 Hub），实现时定案一种并声明。
- **本机 ≠ 全账户**：只覆盖本机 Design.app 的 Agent 会话；网页版、其他设备不在内。
- **私有路径风险**：`@hilo/desktop/ai-runtime/data-home` 为 Design 私有布局，升级可能变化；按字段存在性校验（`message.time_created`+`data.tokens`），缺失即报固定错误码。
- **活跃 WAL 库**：`mode=ro` 只读连接已实测可行；不持锁、不写。
- **失败≠零**：库不存在或 schema 不符时按既有惯例报错，不得计为零。

## 后续可选路线（研究建议，非自动执行指令）

1. 新增 `agent_meter/design_tokens.py`：只读 @hilo 库，排除与独立库重叠的 session id，指标结构对齐 `opencode_tokens`（`periods + daily_buckets + coverage + dedup_rule`），模型/agent 分项；可按现有 agy 先例作独立来源（scope `local_session_history`），或附着到 minimax_design 账户来源的 tokens 指标——实现时定案。fixture 需真实脱敏。
2. 媒体积分估算：`GET /api/v1/billing/pricing` + `.hilo/completed-results.json`（cloudTaskId 级任务计数）＋媒体时长/分辨率元数据，产出 `basis=local_price_table` 的估算积分参考值；仅参考，不与钱包余额对冲。
3. 真实逐次扣费账本本机不存在，保留缺口；如需精确到单次扣积分，只能走云端接口，本轮未探。

## 本轮证据等级

真实本机只读聚合（token 账本全部数字、两库 session 交集、Design 专属剔除后汇总）；本机网关只读 GET（health/scope/wallet/pricing，沿用既有白名单模式）；MCP bundle 静态字符串枚举端点。未做：外网请求、凭据读取、应用 UI 操作、代码改动、采购类调用。
