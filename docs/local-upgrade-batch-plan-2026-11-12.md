# 本机升级批次规划（A–C）· 2026-11-12

用户决策：云端同步与会员暂缓（M0 留在 `claude/cloud-sync-m0` 分支不合入）；本批做
A 桌宠体验补完、B 数据补齐、C 本机数据能力。工作分支 `claude/local-upgrade-batch-20261112`（自 main / v0.10.4）。
版本目标 v0.11.0。本文是接口契约与文件所有权冻结件；研究建议不作为自动执行指令。

## 基线（S0）

- Python 3.14 `scripts/test-offline.py`：666 项（3.9 下 1 项已知 SQLite 环境错误，非代码缺陷）。
- Swift `swift test`（menubar/）：74 项全过。
- 集成完成后统一跑全量回归 + 真机 `verify`，并出可视化验收报告。

## 文件所有权（并行工作流互不越界）

| 工作流 | 拥有（可改/新建） | 禁止触碰 |
|---|---|---|
| A 桌宠体验包 | `menubar/Sources/AgentMeterBar/Pet*.swift`、`ShareCard.swift`、`ShareOptions.swift`、`ReportWindow.swift`、`ReportModel.swift`、`AppLauncher.swift`、`pets/runtime/**`、`agent_meter/pet.py`、`PetCatalog.swift`、相关测试 | collector/server/verify/prices/rewards |
| B1 媒体积分 | `agent_meter/design_credits.py`（新）、`tests/test_design_credits.py`（新） | collector.py、server.py、model.py、minimax_design.py、design_tokens.py |
| B2 签到扩展 | `agent_meter/rewards.py`、`tests/test_rewards*.py` | server.py（CLAIMABLE 由集成者加） |
| B3 Claude 桌面 | `agent_meter/claude_desktop.py`（新）、`helpers/claude_auth.mjs`（新）、`tests/test_claude_desktop.py`（新） | collector.py、claude_code.py、server.py |
| B4 预测增强 | `agent_meter/reset_forecast.py`、`agent_meter/reset_landings.py`（新，如需）、`tests/test_reset_forecast*.py` | server.py、pet.py、model.py |
| C1 本地导出 | `agent_meter/export_data.py`（新）、`tests/test_export_data.py`（新） | server.py、collector.py |
| 集成者（主 agent） | collector.py、server.py、model.py、verify.py、cli.py、Swift 面板 UI（B/C 功能）、prices.py、docs、知识入口 | — |

共享规则：所有工作流不改 `SCHEMA_VERSION`（集成时统一 5→6）、不改 `docs/agent-knowledge/README.md`、
不执行任何 git 写操作、不跑全量 test-offline（只跑自己的测试文件）、不做付费生成、
开发期用夹具测试，不读真实钥匙串、不打真实外网（真机验收由集成者安排）。

## 冻结契约

### B1 `design_credits.py` — Design 媒体积分估算

- 依据 `docs/research/minimax-design-local-tokens-recon-2026-10-15.md` 路线 2：
  网关 `GET /api/v1/billing/pricing`（沿用 `minimax_design.design_query` 的本地网关模式）
  + 本机任务计数（completed-results 账本，路径以研究文档与本机实测为准）+ 媒体元数据。
- 入口 `collect_design_media_credits(gateway_url, ledger_path, now, timeout, node_binary=None) -> metric`；
  纯函数 + 夹具测试；输出 `basis=local_price_table`、`unit=minimax_credits`、Decimal 定点字符串、
  periods today/7d/30d/all、按媒体类型（图/视频）与模型分项、任务数。
- **仅参考值，不与钱包余额对冲**；定价不可得时整体 `not_connected`，不猜单价。
- 集成：附着 `minimax_design` 账户源新指标 `media_credits`（加入 METRICS、排除 COVERAGE_METRICS，
  同 image_generation 先例），受同一来源开关约束；错误码前缀 `design_media_`。

### B3 `claude_desktop.py` + `helpers/claude_auth.mjs` — Claude 桌面会话复用

- 严格按 `docs/research/claude-desktop-session-reuse-2026-10-15.md` 存档方案：
  钥匙串 `Claude Safe Storage`/`Claude Key` → PBKDF2-HMAC-SHA1(值,"saltysalt",1003,16)
  → AES-128-CBC(key, IV=16 空格, blob[3:])，明文前 32 字节为 sha256(host_key) 校验
  → **完整 cookie 罐 + 真实 UA** 调 `GET /api/organizations/{uuid}/usage`（只带 sessionKey 会 401）。
- node helper 参照 `helpers/qoder_auth.mjs` 模式（用 Claude 自己的 Electron 运行时）；
  密钥经 env/stdin 传递、cookie 只走内存通道、不落盘、不进快照。
- 入口 `collect_claude_desktop(home, now, timeout, node_binary) -> source`，
  输出与 `collect_claude_web` 同契约；`diagnostics.credential_route="desktop_session"`。
- 集成：claude 来源凭据链 web 会话 → 桌面会话 → Claude Code 钥匙串；受同一 claude 开关约束
  （本机 token 账本独立性不变）。错误码前缀 `claude_desktop_`。
- 开发期不读真实钥匙串（会弹授权框）；真机端到端由集成者在用户在场的验收阶段做。

### B4 预测增强 — 落地校验层 + 手动公告录入

- 落地校验层：`.runtime/reset-forecast-landings.json`（0600）记录
  `{event_id, 公告时间, 预测快照(概率/区间/加权中位), 观测落地时间, 偏差}`；
  落地观测来自已有重置事件信号（先读 pet.py `recent_landing` 现有口径，复用不重复发明）。
  纯函数 `record_landing / landing_scorecard`，供端点与 UI 消费；不写 `reset_time`、概率永不弹通知。
- 手动录入：纯函数 `add_manual_announcement(store, announced_at, note)`，
  存 `.runtime/reset-forecast-manual.json`，合并进历史时 `origin="manual"`，按既有事件去重语义。
- 集成：`POST /v1/forecast/announcement`、`GET /v1/forecast/landings`（集成者接线）；
  预测页加录入与校验展示（集成者）。

### B2 签到扩展（rewards.py）

- WorkBuddy：`ug/work_lottery/*`（抽奖）与 `pay/query_birthday_bonus`（生日奖励）等可领取项，
  契约见 `docs/research/checkin-automation-and-collection-2026-11-09.md`；
  作为现有 workbuddy 适配器的新 item 类型，查询常开、领取仍走按平台 auto_claim 开关（默认关）。
- MiniMax Code 网页签到：新 provider `minimax_code`，会话形状 `{"cookie": ...}`（web_sessions 内存传递）；
  契约先研究（固定版本公开源码/既有研究），未实测前不进可用矩阵、错误码 `minimax_code_not_authenticated` 等。
- TRAE 领取接口实测：外部门槛（需一个未签到日），记录待办不阻塞。
- 集成：server.py `CLAIMABLE` 加 `minimax_code`；面板签到区展示新 item（集成者）。

### C1 本地导出（export_data.py）

- 纯函数 `export_payload(snapshot, now) -> dict` 与 `export_csv(snapshot) -> str`；
  只投影缓存快照，不触发采集。JSON 含 `schema/generated_at/timezone/usage_daily/quota_observations/cards`；
  usage_daily 行 = 各本机账本与 imported_history 的 daily_models 行（date/ledger/app/model/requests/各 token 分项），
  每行带 ledger 署名；CSV 为 usage_daily 平铺（英文表头）。
- 集成：`GET /v1/export/json`、`GET /v1/export/csv`（服务端拒绝 query，路径分段）；
  面板保存入口（NSSavePanel，集成者）。免费本机功能，不涉及云。

### A 桌宠体验包

- A1 拍照分享：分享卡新增「带上桌宠」开关（ShareOptions 新键，默认关），
  用现有 still/capture 机制抓当前形象 PNG 合成进 ShareCard；无桌宠/未开时开关禁用。
- A2 日报气泡：pet.py 每本地日一次，播报**昨日**用量（token/估算费用/最高产应用），
  数据全部来自已有快照投影；无昨日数据不播报；尽量不新增状态词汇，若新增必须同步
  `pet.py`、`pets/runtime/js/constants.js`、`pets/tools/petpack.py`、`PetCatalog.swift`（测试比对）。
- A3 漫游：PetPrefs 新键默认关；开启后悬浮窗在屏幕内缓慢随机走动，拖拽/交互/免打扰时暂停，
  位置记忆沿用现有机制；不抢焦点、不越屏。
- A4 拖拽安装：悬浮窗与桌宠页接受 `.agentpet` 拖入，走现有 `petpack.py install`，成功后刷新形象库；
  失败给出可读错误，不静默。
- A5 AppLauncher：会话标签/会话看板点击打开对应应用，复用现有 `AppLauncher.swift` 映射；
  未安装的应用给提示不崩溃。
- A7 手感：开发构建（`AGENT_METER_PORT=18769`、`AGENT_METER_NO_KEYCHAIN=1`）真实数据观察，
  保守微调阈值并记录改动理由；`--panel-window --selftest` 必过。

### C2 价格表维护（集成者）

- 只更新能联网核实官方刊例价的 pattern；不猜价；沿用 prices.py 结构与 CNY/USD 折算规则；
  出处记入 pricing-survey 文档。

## 门槛（一次性列出）

1. mochi 形象：付费生图，先报张数与费用，用户明确批准后才执行。
2. TRAE 领取实测：等一个未签到的日子。
3. Claude 桌面真机验收：钥匙串授权框需用户在场点允许。
4. 构建 / 公证 / 安装 / 上传：发布前单独征得用户同意；源码冻结后不再改代码（v0.10.0 重建 4 次教训）。
5. git 提交：完成后由用户决定。

## 集成清单（集成者）

- [x] collector.py：claude 凭据链（web→桌面→Code 钥匙串）、design media_credits 附着、forecast manual_store、record_landing（2026-11-12）
- [x] model.py：SCHEMA_VERSION 6、METRICS + media_credits、COVERAGE_METRICS 排除（2026-11-12）
- [x] server.py：/v1/export/{json,csv}（peek 投影不触发采集）、/v1/forecast/{announcement,landings}、CLAIMABLE + minimax_code
- [x] web_sources.py：SESSION_FIELDS minimax_code + cookie/user_agent
- [x] verify.py：design_media 独立任务重数 + 分组金额算术复核、reset_landings 存储一致性（30 项新检查；真机 verify 3,285 项 0 失败）
- [x] Swift：Design 卡媒体积分行、预测页录入/校验、导出入口、TRAE 附加奖励状态展示
- [x] tests/test_service.py：schema 断言改 SCHEMA_VERSION 动态引用 + 导出/预测端点测试
- [x] prices.py：第四轮 14 个 pattern（11 USD + 3 CNY），出处见 pricing-survey 第四轮
- [x] 全量回归（基线 Python 832 项通过，接入联网汇率后 Python 834 项、Swift 90 项通过）
- [ ] minimax_code 网页登录 UI 暂缓：公开契约需 token/Bearer+yy 头，cookie 不足，未实测不进可用矩阵（B2 结论）

## 真机验收（2026-11-12）

- 开发构建 `--panel-window --selftest` 的 10 项通过：舞台加载、滚轮滚动、点击气泡、7 个形象缩略图、状态试玩和标签切换。另用 `--pet-demo` 验证麻薯桌面浮窗可见，中心可交互，透明边角点击穿透。
- Claude 桌面会话直接实测成功。凭据路线为 `desktop_session`，官方额度和重置时间均返回 `available`。
- USD/CNY 接入 Yahoo Finance 行情。实际请求取得报价并验证了缓存回退，完整联网采集每 5 分钟最多更新一次，界面显示报价时间或离线参考汇率。用实际行情重算本机账本，3,301 项对账全部通过。
