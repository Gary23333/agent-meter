# macOS / Windows 功能对齐计划

2026-11-19 · 基线分支 `feat/windows-port`（`a231217`，含合并提交 `10bf712`）

## 1. 目标与原则

- **能力对齐**：两端功能集合一致；不要求同一套代码或同一套界面。
- **共享底座**：Python 采集层与同步协议共用；UI、凭据、托盘/菜单栏等按平台原生实现。
- **平台专属不算缺口**：菜单栏 vs 系统托盘、钥匙串 vs Windows 凭据管理器、Swift vs C#。
- **完成定义**：本文第 3 节对照表中，每一行的两端状态均为「支持」，或明确标注为「平台专属」；关键路径有自动化测试或可复现的验收步骤。

## 2. 当前基线

- 代码：`feat/windows-port` = 我们 main 的 4 个云同步提交 + FoxBai Windows 移植的 198 个提交。
- 构建：Windows 自包含包已产出（`windows/release/AgentMeter-Windows-x64.zip`）。
- 测试：Windows 官方测试清单 252 项通过；C# 测试通过；托盘/弹层/后台/应用页冒烟通过。
- 已知差异的根因：两端是**两套平台实现**，fork 只改了 C# 与 Windows 适配层，没有反向修改 Swift。

## 3. 能力对照表

| 能力 | macOS | Windows | 结论 / 动作 |
|---|---|---|---|
| 账户额度来源（Codex/Kimi/Claude/MiniMax/DeepSeek/智谱/火山/MiMo/Qoder/TRAE/WorkBuddy） | 支持 | 支持 | 已对齐；逐个 provider 做一次能力清单核对 |
| 应用页 / 本机活动 | 支持 | 支持 | 已对齐 |
| 用量：四周期、构成环、缓存命中、模型排行 | 支持 | 支持 | 已对齐 |
| 报告：自然周/月、分享图、Markdown/PNG 导出 | 支持 | 支持 | 已对齐 |
| 报告：已结束自然日同比对照 | 不支持 | 支持 | **P4 回移 macOS**；同时确认后端字段真实产出 |
| 重置预测（第三方 24/48h） | 支持 | 支持 | 已对齐；Windows 缺 macOS 的承诺摘要/插画等展示细节，列入 P5 |
| 桌宠：精灵图 + 3D、显示/切换 | 支持 | 支持 | 已对齐 |
| 桌宠：完整互动、通知效果、高 DPI/多屏 | 支持 | 待实机验收 | **P5 验收 + 补齐** |
| 收集册：本机用量/图片/花费徽章、额度掉落卡 | 支持 | 支持 | 已对齐 |
| 收集册：签到、创作积分等剩余类别 | 支持 | 部分 | **P5 补齐** |
| 七套主题 | 支持 | 支持 | 已对齐 |
| 预算、低额度提醒、重置卡提醒 | 支持 | 支持 | 已对齐 |
| 用量导出 JSON/CSV | 支持 | 支持 | 已对齐 |
| 登录启动 | 支持 | 支持 | 已对齐 |
| **自动领取每日积分**（TRAE/WorkBuddy/Qoder） | 支持 | **已实现**（TRAE/WorkBuddy；Qoder 不支持） | P1 已合并；真实领取暂不测试，后续可能重评 |
| **历史导入**（`imported_history`） | 支持 | **不支持** | **P2 新增 Windows** |
| **云同步**（配对、加密、跨设备历史合并） | 支持 | **已实现**（协议/UI/自动化；真实双机待联调） | P3 已完成主体 |
| 多账户 | 仅 MiniMax 做多账户 | 仅 MiniMax 做多账户 | 当前对等；是否扩展列 P5 |
| 平台形态 | 菜单栏、钥匙串 | 托盘、WebView2、凭据管理器 | 平台专属，不做统一 |

## 4. 缺口任务

### P1 · Windows 自动领取每日积分

**复用**：`agent_meter/rewards.py`（543 行，规则与幂等已存在）。
**实现**：
1. `windows/backend.py` 新增 `--rewards-status` / `--rewards-claim`，输入走 stdin（provider、账户标识、领取时刻），输出结构化结果。
2. C# 设置页：开关（默认关闭）、领取时刻、上次领取结果、手动「立即领取」；状态写入 `%LOCALAPPDATA%\AgentMeter\rewards.json`。
3. 规则保持 macOS 口径：TRAE 仅每日签到、WorkBuddy 仅已完成任务奖励、Qoder 仅每日活动；生日/抽奖等 bonus 只读；MiniMax Code 签到在契约确认前保持不可用。
**安全**：只读查询与写操作分链路；密钥不进入命令行/日志；领取失败不重试写操作。
**测试**：合成响应下的幂等、401/超时、跨天边界；C# 状态机。
**验收**：在 Windows 上用真实账户领取一次（需用户授权），并核对 Mac 端同日状态不冲突。

**实施记录（2026-11-20）**：
- `windows/rewards.py` + `windows/backend.py --rewards-status/--rewards-claim` 已接入；只读摘要不发请求，领取复用 `RewardsService.tick`。
- C# 新增「每日积分领取」窗口（开关默认关闭、领取时刻、今日状态、今日已领、上次检查、立即领取），托盘菜单入口；刷新结束后按开关自动 tick。
- 会话只走 stdin，不落盘、不进日志；输入严格校验，失败不重试写操作。
- **边界**：Qoder 每日活动的凭据只存在于 macOS 钥匙串与 Electron 解密，Windows 没有等价实现，界面明确显示「暂不支持」，不用网页 Cookie 冒充；MiniMax Code 同样暂不可用。
- 自动化：`tests/test_windows_rewards.py` 10 项通过；C# 测试已加入 `RewardsTests`（需在 Windows 上构建执行）。
- 构建验证：Windows 临时副本 `dotnet build windows/AgentMeter.Windows -c Release` 0 警告 0 错误；`AccountPreferences.Tests` 运行通过（含新增领取设置与结果检查）。
- **2026-11-20 产品决定**：自动领取后续可能重新评估，暂不做真实账户测试；实现保留，不作为发布阻塞项。

### P2 · Windows 历史导入

**复用**：`agent_meter/imported_history.py` 的解析、去重与来源标记。
**实现**：
1. backend 新增 `--import-history`：接收文件/目录，返回解析预览（条数、时间范围、重复数）。
2. C# 导入向导：选择文件 → 预览 → 确认导入 → 结果；重复记录跳过并提示。
3. 导入数据只进入本机账本，标记来源 `imported_history`，不参与账户查询、不上传云同步原始明细。
**测试**：格式错误、空文件、超大文件、重复导入、跨时区。
**验收**：用一份 macOS 导出的汇总文件导入，两端统计口径一致。

### P3 · Windows 云同步（最高工作量）

**协议不变**：沿用 macOS 的 X25519 配对、HKDF-SHA256、ChaCha20-Poly1305、pairing slot、space token；服务端 `sync_server` 不改，保证 Mac ↔ Windows 互通。
**Python 侧**：
1. 新增 `agent_meter/sync_crypto.py`：X25519/HKDF/ChaCha20-Poly1305、SAS、短码规范，对齐 Swift `SyncPairing.swift` 的 info 字符串与密钥派生。
2. 新增 CLI：`--sync-space-create`、`--sync-pair-create`、`--sync-pair-join`、`--sync-push`、`--sync-pull`、`--sync-devices`、`--sync-device-remove`、`--sync-reset`；复用 `sync_payload.py` / `sync_store.py`。
3. 依赖：`cryptography`（仅 Windows 构建 requirements 增加）。
**C# 侧**：Sync 页面（创建空间、输入短码配对、设备列表、上次同步、立即同步、断开设备）；配置 `%LOCALAPPDATA%\AgentMeter\sync.json`，主密钥存 Windows 凭据管理器。
**互操作测试**：与 Swift 客户端共用同一 `sync_server`；固定测试向量验证封装/解封；Mac 推送 → Windows 拉取 → 合并展示，反向再来一轮。
**安全**：payload 仅聚合（现有规则）；密钥不明文落盘；日志脱敏；设备删除走服务端接口。
**验收**：Mac ↔ Windows 双向同步成功；离线、重复推送、设备删除、损坏 store 四类异常可控。

**实施记录（2026-11-20）**：
- 协议以 Swift `SyncPairing.swift` / `SyncClient.swift` 为准：实际加密为 **ChaCha20-Poly1305**（计划早期写的 AES-GCM 是过时表述，已修正）；`authToken` 为标准 base64，配对封装用无填充 base64url。
- 新增 `agent_meter/sync_crypto.py`、`agent_meter/sync_remote.py`、`windows/sync_ops.py`；`windows/backend.py` 增加 `--sync-space-create` / `--sync-pair-create` / `--sync-pair-join` / `--sync-push` / `--sync-pull` / `--sync-devices` / `--sync-device-remove` / `--sync-reset`。
- C# 新增 `SyncPreferences` / `SyncSecrets` / `SyncBackendClient` / `SyncReport` / `SyncDialog`，托盘加入「多机同步」；Windows 主密钥存凭据管理器，`sync.json` 只存非密配置。
- 自动化：Python 固定向量、真实本地 `sync_server` 双设备端到端（创建/push/pull/devices/幂等/坏 blob/坏 base URL/配对 SAS/畸形设备标识/移除设备/断开本机）、Swift ↔ Python 向量互通，共 `988 passed, 1 skipped`；Swift 全量 `122 tests` 通过；Windows `dotnet build` 0 warnings / 0 errors，偏好与报告测试通过；打包后的 `AgentMeterBackend.exe` 已真实创建空间、完成 push、列出设备并由第二台设备 pull 成功。
- 剩余：真实 Mac ↔ Windows 双机联调（两端同时连同一 `sync_server`，核对 SAS 与双向账本合并）尚未执行；`SyncDialog` 布局与按钮状态需真机点验。

### P4 · macOS 回移「已结束自然日对照」

**现状**：`ReportComparison.cs` 读取 `comparable_days`、`current_comparable_tokens`、`previous_comparable_tokens`；Python/macOS 目前没有这些字段，需确认 Windows 真实后端是否只靠演示数据。
**实现**：
1. `agent_meter/report_periods.py` 统一产出可比字段（按自然日、排除未结束当天，处理闰月/时区）。
2. Swift `ReportView` 增加一行「已结束的前 N 个自然日」对比；Windows 保持现有展示。
**测试**：跨月、闰年、DST、空数据。
**验收**：两端对同一账本显示相同的天数与数值。

**实施记录（2026-11-20）**：
- `report_periods.py` 新增 `comparable_days` / `current_comparable_tokens` / `previous_comparable_tokens` / `comparable_basis`，与 `windows/backend.py` 共用 `comparable_span()`，排除未结束当天，上期较短时两边截到共同天数。
- Swift `PeriodReport` 解析这些字段；周期环比卡增加「已结束的前 N 个自然日」行；报告窗口新增「自然周期对照」卡（本周/本月）。
- 自动化：Python 跨月截断、首日零天数、Windows 原有字段测试；Swift 5 项解析与展示断言均通过。两端同一账本真机数值对照仍待验收。

### P5 · 体验对齐（验收 + 收尾）

1. **桌宠**：逐项验收透明穿透、拖动、视线跟随、多屏、高 DPI、性能；缺的互动按 macOS 清单补齐。
2. **通知**：Windows 系统通知、去重、点击行为；与 macOS 文案/阈值一致。
3. **收集册**：补齐签到、创作积分等类别，规则与 macOS 一致。
4. **预测展示**：Windows 补承诺摘要/插画等 macOS 细节（如仍缺）。
5. **多账户**：先核对 macOS 的实际范围（目前只有 MiniMax 多账户）；若扩展，再排期。
6. **平台专属差异**：记录在 `windows/PORT_PLAN.md`，不做强行统一。

## 5. 建议排期

| 阶段 | 内容 | 预估 |
|---|---|---|
| 阶段 1（快赢） | P1 自动领取 + P4 macOS 报告对照 | 2–3 天 |
| 阶段 2（核心） | P3 Windows 云同步（Python 加密/CLI + C# 页面 + 双向互操作） | 4–6 天 |
| 阶段 3（收尾） | P2 历史导入 + P5 桌宠/通知/收集册验收 | 3–4 天 |

顺序可按「先补能力缺口、再补体验细节」调整；P3 是唯一需要跨端协议联调的任务，建议单独留出联调窗口。

## 6. 风险与约束

- **协议互操作**：X25519/HKDF/ChaCha20-Poly1305 的 info 字符串、短码编码、SAS 必须逐字节对齐；固定向量已通过，真实双机联调仍需执行。
- **真实账户**：Windows 机器没有所有服务的登录态；P1 的真实领取、P3 的双设备同步需要用户授权或提供一台已登录的 Mac。
- **写操作合规**：自动领取默认关闭，逐平台确认；失败不重试写操作。
- **并行开发冲突**：`main` 上仍有 v0.12.0 未提交改动；本计划全部落在 `feat/windows-port`，待 v0.12.0 落地后再合并 main，避免 `server.py`/`report_periods.py` 冲突。
- **Windows 打包链路**：构建脚本已修 PowerShell 5.1 的 BOM/stderr 问题；后续新增 Python 依赖时同步更新 `windows/requirements.txt` 与 PyInstaller `--collect-all`。

## 7. 验收清单

- [ ] Windows 官方测试清单（252 项）与 C# 测试保持通过
- [ ] macOS 全量 Python 测试通过（平台专属断言除外）
- [ ] P1：Windows 真实账户自动领取一次，规则与 macOS 一致（暂不测试；实现与模拟测试已完成，后续重新评估）
- [ ] P2：历史导入样例两端统计一致
- [ ] P3：真实 Mac ↔ Windows 双向云同步与异常场景真机验收；协议固定向量、本地 `sync_server` 双设备端到端、打包后端创建空间／push 已验证
- [ ] P4：两端同一账本的自然日对照数值一致（字段与两端展示已自动化通过，真机同账本待对照）
- [ ] P5：桌宠/通知/收集册验收记录齐全
- [ ] `windows/PORT_PLAN.md` 与本对照表同步更新
