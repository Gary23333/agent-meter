# Harness 接入批次验收（2026-11-08）

> **剩余两项只有用户能完成（B1/B3）。** 顺序如下：
> 1. 安装：打开 `release/AgentMeter-0.10.0-macos-arm64.dmg`，拖入「应用程序」并启动。
> 2. 重登：菜单栏面板设置菜单 →「连接网页账户 / API 密钥…」→ 依次登录 qoder、workbuddy、mimo；如愿意，再连接 stepfun / 火山方舟（B3 真实验收）。
> 3. 核验：`python3 scripts/check-account-connections.py --runtime "$HOME/Library/Application Support/AgentMeter/.runtime"`——五个账户源全绿退出 0，有缺口退出 2 并列出原因。
> 4. 可选（发布）：配置 `APPLE_ID / APPLE_APP_SPECIFIC_PASSWORD / APPLE_TEAM_ID` 后 `SIGN_MODE=dist sh scripts/build-dmg.sh` 重新公证；上传用 `gh release create v0.10.0 release/AgentMeter-0.10.0-macos-arm64.dmg release/SHA256SUMS --notes-file docs/release-v0.10.0.md`。两步都需要你明确同意后再做。
>
> 其余 A 组、B4、B5、C 组、D 组、E 组已全部完成并验收，见下文。

对应[计划](harness-integration-upgrade-plan-2026-11-08.md)的 A 组、B4/B5、C 组、D 组与 E 组后端。证据均在 `.runtime/plan-recon-2026-11-08/`（只读聚合，无正文无凭据）。

## A 组：本机历史账本（已合入并真机验收）

| 来源 | 实现 | 真机读数（全部周期） | 测试 |
|---|---|---|---|
| MiMo Code `mimo_code` | `agent_meter/mimocode_tokens.py`，复用 opencode 同构解析 | 868 条 / 225,790,138 token（分项和口径；库内 total 字段和为 225,616,716，差 173,422 来自 reasoning 归属不同的行），3 模型，2026-09-22 后停写 | 11 项 |
| DevECo `deveco` | 同模块共享路径 | 4 条 / 76,621 token（GLM-5.3，2026-09-17） | 含于上 |
| Kimi 旧 CLI `kimi_legacy` | `agent_meter/kimi_legacy_tokens.py`，message_id/文件行去重，秒级时间戳，模型 unknown 不估价 | 80 文件 / 3,971 条 / 396,282,036 token（2026-02-13→06-17），与 kimi-code 零重叠 | 7 项 |

注册全链路：collector jobs/config、cli --disable、discovery KNOWN、applications 分组、verify 独立重算、activity 适配器、Catalog 品牌/文案。最终真机 `verify --local-only`：**3,185 项通过、0 失败、0 待定**，其中 mimo_code 104 项、deveco 90 项、kimi_legacy 86 项（A 组合入当时的单轮数字为 3,169）。

## B4：ZCode 桌面端登录与重置卡（已合入并真机验收）

`agent_meter/zcode_desktop.py`：enc:v1 AES-256-GCM 信封经 node 内存解密（契约对照 UsageBar-tauri 2605fd5 / token-monitor c62544e），本机 ZCode 3.17.2 解密成功；重置卡 `GET zcode.z.ai/api/v1/coding-plan/reset/status` 只查询不兑换，全卡保留不截断。真机：**3 张周重置卡可用，最近到期 2026-12-22**；OAuth token 直读额度 2 行成功。网页会话优先、桌面补卡的路由集成进 collector。测试 15 项（含 node 加解密往返）。

## B5：即梦 CLI 路由（已合入）

旧 `dreamina` 优先；不存在时回退 `dreamina-canvas auth account`（本机实测信封 `{ok,data:{userId,isVip,vipLevel}}`，登录态有效、VIP maestro）。画布 CLI 无积分查询，credits 标 `not_provided`（`dreamina_canvas_cli_no_credit_query`）由网页 observations 补齐。测试 7 项。默认仍关闭 CLI 路由，不影响网页采集。

## C 组：签名与钥匙串（代码级验收完成）

- `build-app.sh`：dev/dist 找不到身份明确失败，ad-hoc 仅显式 `SIGN_MODE=adhoc`。
- `Keychain.swift`：SecItemUpdate 优先、仅缺失时新增、并发 duplicate 回退更新；失败原因枚举区分未授权/锁定/不存在。
- `WebConnections.swift` + `UsageStore.swift`：启动只读启用来源、无交互优先（kSecUseAuthenticationUIFail），需授权的槽位留给主动连接动作；开关重新打开时补读。
- Swift 测试 **23/23**（新增 KeychainHardeningTests 8 项）。
- **两轮连续 dev 构建身份一致（2026-11-09 04:31）**：两次产物的指定要求（designated requirement）逐字相同，均为 `identifier "local.agent-meter.menubar" + Apple Development: zizheng Guan (3RJW8ZR4Z2)`；`codesign --verify --deep --strict` 两轮均通过。证据：`.runtime/plan-recon-2026-11-08/dr-1.txt`、`dr-2.txt`。重装后钥匙串不弹窗的最终体验需在安装 v0.10.0 后确认（首次启动若旧槽位缺当前授权，只会记录原因、不弹框）。

## D 组：版本漂移机制（已合入）

- D1：`agent_meter/qoder_watch.py` + `scripts/recheck-qoder-usage.py`——版本变化/token 字段转非零/usage 消失三类漂移，退出码 2 告警；状态存 `.runtime/qoder-usage-watch.json`。测试 7 项；本机首跑 0.5.6、677 assistant、207 usage、0 非零 token、无漂移。
- D2：dsh 未知 schema 走 skipped 计数 + `dsh_sessions_unreadable` 固定码（既有行为核验，不臆测）。
- D3：TRAE 3.4.11 / 豆包 2.35.4 复勘收口——TRAE 529 个近 7 天日志零用量字段、workspaceStorage 无 usage 键；豆包 IM 库加密、无用户侧计量。无公开用量明细契约，维持缺口（证据 `trae-doubao-recheck-2026-11-08.json`）。

## E 组（后端 + 端点 + Swift UI 已合入）

- E1 预算提醒：`agent_meter/budget.py` + GET/PUT `/v1/budget` + `BudgetSettingsView` + Notifier 去重；Python 33 项、Swift 9 项。
- E2 项目归因：`projects.py` + `/v1/projects` + 「项目」页签（别名仅本机）。真机：95 个项目、归因 10.82B / 总 39.42B token。测试 2 项。
- E3 周报环比：9 条采集路径新增 `daily_models`，`report_periods.py` + `/v1/periods/week|month` + 本机消耗页「本周环比」卡；verify 16 项逐日一致性全过。测试 7 项。
- E4 状态面板/省资源：`status.py` + `/v1/status` + 「数据状态与省资源」窗口；preferences 增加 `low_resource_mode`（TTL×3）与 `skip_ledgers_low_resource`（原因 `skipped_low_resource`）。测试 5 项。
- UI 验收：离线预览出图后**抽查实图**——项目页（极光浅色/深色、极简浅色）、本机消耗页含环比卡（极光浅色）、数据状态窗口（浅色）、预算与异常提醒窗口（浅色，进度行 ¥32.5/¥50 与 ¥126.8/¥300 正确）均渲染正确；其余主题按同一套 Theme 取色（Swift 37/37）。**未目检**：七主题逐张全量比对、预算输入框真机点选与外发保存（离屏截图时输入框由异步任务预填，实机打开才填入现值）。

## 最终回归与发布（2026-11-09 04:30–04:45 CST）

- Python：`unittest discover` **479 项全过**（最终源码对齐：含 A/B/D/E 新增测试、Qoder 路由回退 5 项、账户验收脚本 3 项）。
- Swift：`swift test` **37 项全过**。
- 源码后端真机 `verify --local-only`：**3,185 项通过、0 失败、0 待定**（含 mimo_code 104、deveco 90、kimi_legacy 86、daily_models 16）。
- **分发构建 v0.10.0（最终产物，含 Qoder 回退与预算预览）**：`release/AgentMeter-0.10.0-macos-arm64.dmg`（SHA-256 `ab252b9b406a6b5c51b91bfa8b779321ff07debf193b1152824296ff7e23da25`），Developer ID 签名（Team WTTNX5S72B），DMG 与挂载后内嵌 App 的 `codesign --verify` 均有效，`shasum -a 256 -c SHA256SUMS` 通过；公证因本机未配置 `APPLE_ID / APPLE_APP_SPECIFIC_PASSWORD / APPLE_TEAM_ID` 跳过（发布页需如实标注）。
- **发布冒烟（最终包）**：包内后端搬家运行 + 合成数据 collect/verify + 鉴权 HTTP + token 0600 → PASS；另对包内后端逐条请求 `/v1/budget`、`/v1/projects`、`/v1/status`、`/v1/periods/week`、`/v1/periods/month`，全部 200 且返回结构正确 → PASS。
- **包内后端真机数据**：`verify --local-only` **3,122 项通过、0 失败、0 待定**。
- 两轮 dev 构建身份一致见 C 组。未做：安装到 /Applications、上传 GitHub（需用户确认）。

## 待用户操作（B1/B3，代码侧无缺口）

B1 代码侧补充（2026-11-09）：发现 Qoder SDK 实际已安装在 `Qoder CN.app/Contents/Resources/app.asar.unpacked/node_modules/@qoder-ai/qoder-cn-agent-sdk`，但原逻辑"有网页会话就只走网页"，过期会话会挡死 SDK 路线。已改为网页失败后回退 SDK（`collect_qoder_route`，5 项测试）；本机实测 SDK 自身登录也已过期（`qoder_not_authenticated`），因此仍需重登。MiMo 的 `MIMO_API_KEY`（环境变量）被账单接口拒绝（源码注释已注明），余额只能走控制台 Cookie。

安装版快照诊断：qoder/workbuddy/mimo 为 **not_authenticated（登录态过期）**，stepfun/volcengine 为 **credential_not_connected（从未连接）**，claude 为用户主动关闭（维持）。操作步骤：安装 v0.10.0 → 菜单栏面板设置菜单「连接网页账户 / API 密钥…」→ 依次重新登录 qoder、workbuddy、mimo；stepfun/火山方舟需在该窗口提供真实账号凭据后才能做端到端验收，否则维持"仅契约验证"标注。新版本启动时只记录无法无交互读取的槽位、不再弹钥匙串密码，登录动作会显式授权。

**登录后的验收入口**：`python3 scripts/check-account-connections.py --runtime "<应用数据目录>/.runtime"`——只读查询本机 /v1/sources，输出五个账户源的 connected/has_quota；全部接通退出码 0，仍有缺口退出码 2。测试见 `tests/test_account_check.py`（3 项）。脚本只在源码仓库使用，不随 App 分发。