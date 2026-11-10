# Harness 接入完善与升级计划（2026-11-08）

> **执行状态（2026-11-09 04:50 CST）**：A 组、B4、B5、C 组、D 组、E 组已全部落地并验收（Python 479 项、Swift 37 项、真机 verify 3,185 项零失败；v0.10.0 已构建、签名与冒烟验证通过，未公证/未发布/未安装）。B1（qoder/workbuddy/mimo 登录态过期）与 B3（stepfun/volcengine 无真实账号）属用户凭据操作，代码侧无缺口，步骤与验收入口见[批次验收](harness-batch-acceptance-2026-11-08.md)。本文件其余内容保留为计划原文。

本文件是计划，不作为自动执行指令。依据：v0.9.9 源码、当日本机只读复核（证据在 `.runtime/plan-recon-2026-11-08/`）、2026-10-18 候选来源复勘、2026-10-26 harness 接入与钥匙串审计、2026-10-30 性能复盘的下一步建议。

## 一、现状快照（当日实测）

- 版本 0.9.9，schema 5；安装版后端运行中。实时覆盖：**19 个应用（18 已安装），37 项字段可用、6 项部分、166 项缺失**（`GET /v1/coverage`，缺失含产品本来不提供的指标，不是故障数）。
- 22 个来源。账户类 `not_connected`：**claude、qoder、workbuddy、mimo、stepfun、volcengine**；antigravity 为 `partial`（额度依赖运行中的 language_server，应用没开属预期）。本机账本全部正常。
- Qoder CN 已升到 **0.5.6**：抽查近 3 天 4 个日志文件，238 条 assistant、79 条带 usage，**token 字段非零为 0**，credits 正常——「只记积分不记 token」结论在当前版本仍成立，不臆造 token。
- A 级候选账本仍在盘上：`mimocode.db`（228 MB，mtime 09-27）、`~/.kimi/sessions` 80 个 wire 文件、DevECo 库仅 4 条有效记录（观察项）。
- 10-26 审计的校验器问题已修复：verify 已支持价格别名（`verify.py:674`），0.9.9 安装版验收 2,906 项零失败；Kimi 桌面覆盖映射已正确。**审计的签名/钥匙串建议 1、2 仍未实现**（见下 C 组）。

## 二、缺口清单（按组编号，后文阶段引用）

### A 组｜本机历史账本缺口（可直读、有真实数据）

| 编号 | 来源 | 证据与口径 | 成本 |
|---|---|---|---|
| A1 | MiMo Code `~/.local/share/mimocode/mimocode.db` | 868 条 assistant / 2.26 亿 token，2026-09-10→09-22 后停写；opencode 同构 sqlite，带模型与毫秒时间戳、cache 拆项 | 低：复用 `opencode_tokens.py` 解析模式 |
| A2 | Kimi 旧 CLI `~/.kimi/sessions` | 3,971 轮 / 3.96 亿 token，2026-02-13→06-17；与现 kimi-code 会话零重叠；**无模型字段（一律 unknown、不估价）**；时间戳是秒级浮点 | 中：递归 glob、去重键需定案 |
| A3 | DevECo `deveco-stable.db` | 仅 4 条 / 7.6 万 token | 不单独实现，留观察清单 |

### B 组｜账户连接与真实验收缺口

| 编号 | 事项 | 现状 |
|---|---|---|
| B1 | qoder / workbuddy / mimo 登录恢复 | 适配代码在、凭据未连；属用户操作，不是代码缺口 |
| B2 | claude 账户 | 用户主动关闭；桌面会话复用方案已存档、用户决策暂缓，维持暂缓 |
| B3 | stepfun / volcengine 真实账户端到端验收 | 从未用真实账户验证（本机无账号）；只有契约测试通过 |
| B4 | ZCode 重置卡与本机登录自动读取 | 10-09 起明确未接入，需先复勘 |
| B5 | 即梦 CLI 路由漂移 | 本机 CLI 已是 `dreamina-canvas`，后端旧路由找 `dreamina` 且默认关闭；网页采集不受影响 |

### C 组｜凭据与签名体验（10-26 审计建议，今日代码复核仍未修）

| 编号 | 问题 | 位置 |
|---|---|---|
| C1 | dev 构建找不到证书时静默回退 ad-hoc，二进制身份变化导致钥匙串重新弹窗 | `menubar/scripts/build-app.sh:64-67` |
| C2 | 保存凭据先 `SecItemDelete` 再 `SecItemAdd`，重建项目丢旧授权 | `menubar/Sources/AgentMeterBar/Keychain.swift:54-61` |
| C3 | 启动枚举全部槽位读秘密，不按来源启用状态过滤、不先尝试无交互读取 | `menubar/Sources/AgentMeterBar/WebConnections.swift:194-203` |

### D 组｜版本漂移与复勘机制

- D1 Qoder：每次大版本升级后抽样复核 usage 字段（本轮 0.5.6 已查，仍全 0）；BYOK 真实 token 只能靠调用链保存 usage，代理日志路线（qoder-credits-inspector 能力）需用户决定是否启用，不补造历史。
- D2 dsh 0.2.2-rc.1：v4 已支持；新版本 schema 出现时按固定错误码报错、不猜。
- D3 TRAE CN 3.4.11 与豆包 2.35.4（2026-11-08 复勘，证据 `trae-doubao-recheck-2026-11-08.json`）：TRAE 扫了 529 个近 7 天日志文件零用量字段、全部 workspaceStorage 无 usage/token 键、新增 memory/hub_event_cache/work 目录均非账本——本地无账本，用量在云端；唯一可研究路线是复用已连的网页会话探测控制台有无用量明细只读 API（DeepSeek 网页用量同款模式），TraeUseToken 扩展 + CDP 属侵入式不做。豆包 messages.db/im.db 为加密库（表结构不可读）、Tea 仍是埋点，且消费级免费聊天无用户侧 token/额度指标——不接。

### E 组｜功能升级（沿用 10-30 性能复盘优先级）

- E1 预算与异常消耗提醒（日/周预算、API 等价口径、定位到应用/模型、补记去重）。
- E2 按项目归因（activity 已有 cwd 证据：dsh/ZCode/OpenCode/Claude；Gemini 项目哈希不可解进「未归属」；分享默认只用别名）。
- E3 周报与环比（后端先补自然周/月同口径日汇总，不拿滚动 7 日冒充自然周）。
- E4 数据状态面板与省资源模式（最近成功采集时间、故障、未计价模型、未归属记录；按来源降频）。

### 明确不做（维持边界）

C 级候选（TRAE 本地、CodeBuddy、Cursor、Cherry Studio LevelDB、豆包、Qoder 全球版、MiniMax Agent CN、DeepSeek 旧 TUI）不接；LM Studio 属本地算力语义，如接须独立 `local_compute` scope；Claude 桌面会话复用维持暂缓；Qoder token 全 0 不当零消耗、不反推。

## 三、接入契约（Stage 0 冻结，新来源一律照此注册）

新增本机 token 账本的注册点（今日代码核对）：

| 注册点 | 位置 |
|---|---|
| 采集调度 | `agent_meter/collector.py:184-224` jobs 字典，scope `local_session_history`；开关门 :246-249，local_only 门 :250-256 |
| 指标结构 | `agent_meter/model.py`（METRICS:10、COVERAGE_METRICS:14、source():105）；tokens 指标沿用 periods + daily_buckets + coverage + dedup_rule + 峰谷分项 |
| 覆盖署名 | `agent_meter/applications.py:43-68` coverage_matrix；APP_IDS:4-5 分组映射 |
| 独立重算 | `agent_meter/verify.py:370 verify_snapshot` 内加来源块（dsh 例 :796-804） |
| 应用发现 | `agent_meter/discovery.py:5-16` KNOWN；无 .app 的 CLI 走 `local_ledger` 发现（gemini 先例） |
| 活动页 | `agent_meter/activity.py` 写适配器 + `collect_activity:791` 加一行 run |
| Swift 展示 | `menubar/Sources/AgentMeterBar/Catalog.swift`：brand:25-56、shortName:58-65、appLabel:301-306、appTint:323-338、错误码文案:104-219 |
| 缓存复用 | `agent_meter/record_cache.py:50 read()` + `prune(namespace)`；文件型按 cli_sessions 范式 |
| 配置 | `collector.py:46-95 default_config` 加目录键；只读打开、固定错误码 |
| 测试 | `tests/test_<source>_tokens.py`（契约/周期/模型组/daily/缺目录/坏行）+ `test_activity.py` + `test_verify.py` |
| 文档 | `docs/backend-api.md` 新增来源一节 |

冻结约定：指标结构与 scope 取值不变；每账本独立汇总、不跨账本剔除；未知 ≠ 0；只读 usage 字段、不读正文与凭据；错误码命名 `<source>_sessions_not_found` / `unsupported_<source>_schema` 风格。

## 四、阶段与并行矩阵

| 阶段 | 内容 | 依赖 | 可并行 |
|---|---|---|---|
| **Stage 0** | 冻结上表契约；定案 A1/A2 口径（见决策点）；证据归档（已完成大半） | 无 | — |
| **Stage 1A** | A1 MiMo Code 采集器全链路 | Stage 0 | 与 Stage 2 并行 |
| **Stage 1B** | A2 Kimi 旧 CLI 采集器全链路 | 1A 合入后（共享 collector/Catalog 注册行，避免冲突） | 与 Stage 2 并行 |
| **Stage 2** | C1/C2/C3 签名与钥匙串加固 | 无；纯 Swift/脚本，与 Stage 1 文件不相交 | 与 Stage 1 并行 |
| **Stage 3** | B1 登录恢复、B3 真实验收、B4 复勘、B5 CLI 路由更新 | 需要用户登录/提供账号 | 随时插入 |
| **Stage 4** | E1→E2→E3→E4 逐项独立轮次 | Stage 1 发布后；E3 依赖后端日汇总扩展 | 每轮内部再拆 |

文件所有权（冲突点已标明）：

- Stage 1A 独占：`agent_meter/mimocode_tokens.py`（新）、`tests/test_mimocode_tokens.py`（新）；共享注册行：collector.py、applications.py、discovery.py、verify.py、Catalog.swift、backend-api.md。
- Stage 1B 独占：`agent_meter/kimi_legacy_tokens.py`（新）、对应测试；共享同上 → **1A、1B 串行合入**。
- Stage 2 独占：`build-app.sh`、`Keychain.swift`、`WebConnections.swift`（仅凭据读写段，不碰 ConnectionManager 业务）。
- Stage 4 各轮启动前另出细案，不在本计划预分配文件。

## 五、各阶段验收门槛

通用（每轮合入前）：

```sh
python3.14 -m unittest discover -v
swift test --package-path menubar
python3.14 -m agent_meter verify --local-only --output .runtime/verification.json
```

- 新来源另须：真实脱敏 fixture（正常/明确零/缺字段/坏行/轮转）；本机只读对账数字写入 docs；输出无凭据无正文；失败隔离不影响其他来源。
- Stage 1 发布门槛：安装版快照 verify 零失败；应用页/本机消耗页数字与 API 逐位一致；停写账本声明覆盖边界（MiMo Code 09-22 后、Kimi 旧 CLI 06-17 后）。
- Stage 2 验收沿用审计清单：两次连续构建代码身份规则相同；重装重启后已有九个凭据不再弹窗；关闭的来源不触发凭据读取；主动断开重连正常。dev 构建无证书时明确失败，只有显式 `SIGN_MODE=adhoc` 才允许临时签名。
- Stage 3 门槛：每个账户来源区分「契约测试通过」与「真实账户已验收」，后者必须有本机真实读数记录；无账号的维持未验收标注，不冒充已接通。
- 发布：`sh scripts/build-dmg.sh`（dist 签名 + 公证）→ `scripts/smoke-release.py` → 发布说明。

## 六、决策点（一次性列出，默认按推荐执行）

1. **A1/A2 来源形态**：推荐均为独立来源（`mimo_code`、`kimi_legacy`，scope `local_session_history`），应用页各自成行（kimi_desktop/dsh 先例）；不附着账户卡片。Kimi 旧 CLI 模型一律 unknown、按用量列名不估价。
2. **启动顺序**：推荐 Stage 1A 与 Stage 2 并行开工（文件不相交），1A 合入后接 1B；Stage 1 完成后发一个版本（建议 v0.10.0）。
3. **B3 真实验收**：stepfun/volcengine 需要你提供真实账号登录才能验收；没有就长期标注「仅契约验证」。
4. **Stage 4 取舍**：默认按 E1→E4 顺序；若你更想先要项目归因（E2），可在 Stage 1 发布后调换。

## 七、证据索引

- `.runtime/plan-recon-2026-11-08/`：health.json、coverage.json、sources.json（当日实时 API）、qoder-0.5.6-usage-sample.json、candidate-ledger-check.json（均只读聚合，无正文无凭据）。
- 历史依据：`docs/research/local-usage-sources-recon-2026-10-18.md`、`docs/research/harness-integration-keychain-audit-2026-10-26.md`、`docs/research/qoder-byok-local-usage-recon-2026-10-26.md`、`docs/performance-sharing-review-2026-10-30.md`、`docs/local-accounting-0.9.9.md`。