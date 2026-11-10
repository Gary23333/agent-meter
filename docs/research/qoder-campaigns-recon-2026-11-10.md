# Qoder 每日积分活动（campaigns）复勘与实现 · 2026-11-10

## 结论

Qoder CN 的「每日领取 100 Credits」有真实可用的接口，且**需要桌面客户端的登录态**（不是网页 cookie）。本轮已实现并真机验收：只读查询、一次性真实领取、幂等复领全部通过。

## 接口

基址 `https://openapi.qoder.com.cn`。

| 用途 | 方法与路径 | 认证 | 实测 |
|---|---|---|---|
| 活动列表 | `GET /sash/api/v1/me/campaigns` | `Authorization: Bearer <token>` + `Cosy-ClientType: 10` | ✅ 200 |
| 领取 | `POST /sash/api/v1/me/campaigns/{campaignId}/claim`（空 body） | 同上 | ✅ 200 |

**关键请求头**：

- `Cosy-ClientType: 10` — 缺这个头时服务端返回**空活动列表**（参考实现的注释原话）。
- `Cosy-Version`（来自 App 内 `build-manifest.json` 的 `productVersion`）、`Cosy-MachineId`（来自 `auth.machine-id`）、`Cosy-MachineToken` / `Cosy-MachineCode` / `Cosy-MachineType`（来自 App 内 `Resources/umid/runtime-info`）。设备头是"尽力而为"：服务端更愿意给带设备标识的请求下发活动，缺失时降级为普通请求。

## 响应包络（真机抓取）

活动列表：

```json
{"uid": "…", "showCampaign": true, "claimable": false,
 "campaignUrl": "https://gateway.qoder.com.cn/growth-page/activity-iframe",
 "campaigns": [{"campaignId": "01a1bbe3-…", "campaignKey": "act-20261109-380",
                "actionType": "CLAIM_BENEFIT", "startAt": 1794276000, "endAt": 1794362340,
                "claimStatus": "CLAIMED",
                "benefit": {"kind": "CREDITS", "amount": 100,
                            "validity": {"mode": "RELATIVE_DAYS", "days": 30}}}]}
```

领取响应是**扁平结构**、**没有 `code` 字段**，成功与否看 HTTP 状态与 `status`：

```json
{"grantId": "01a1c34f-…", "status": "CLAIMED", "replayed": true,
 "benefit": {"kind": "CREDITS", "amount": 100, "validity": {"mode": "RELATIVE_DAYS", "days": 30}},
 "campaignId": "01a1bbe3-…", "campaignKey": "act-20261109-380",
 "claimedAt": "2026-11-10T02:35:54Z", "expiresAt": "2026-12-10T02:35:54Z"}
```

活动文案里写明规则：**「Daily reset: 10:00 (UTC+8). Valid for 30 days after claiming.」**——每日北京时间 10:00 刷新当日活动，领取后 30 天有效；错过的轮次不累计（官方活动页 docs.qoder.com/zh/events/100credits 同款规则）。

## 凭据来源

活动接口不接受网页 cookie 的会话，只认桌面客户端的 token。macOS 上它在：

```
~/Library/Application Support/com.qodercn.app.stable/auth.v1.dat
```

Chromium 的 `"v10"` 信封：AES-128-CBC，密钥 = `PBKDF2-HMAC-SHA1(钥匙串密码, "saltysalt", 1003 轮, 16 字节)`，IV 固定为 16 个空格。钥匙串密码取自 `Qoder CN App Safe Storage` / 账户 `Qoder CN App Key`。

标准库没有 AES，所以用 **Qoder CN 自己的 Electron 运行时**（`ELECTRON_RUN_AS_NODE=1`）解密：钥匙串密码经 stdin 进、token 经 stdout 出，不落盘、不打印（`agent_meter/helpers/qoder_auth.mjs`）。

**macOS 会就这条钥匙串条目弹一次授权框**（服务名 `Qoder CN App Safe Storage`）。本轮实测：点「始终允许」后读取耗时约 4 秒且不再弹窗；点「拒绝」会得到 `qoder_keychain_denied`。token 在后端进程内缓存 5 分钟，避免频繁读取钥匙串。

## 与 2026-11-09 研究结论的差异

当日结论是「qoder.com.cn 前端和本机 Qoder CN 安装包都没有签到接口，推测在未安装的 QoderWork 客户端里，暂不做」。该结论只覆盖了**网页前端**与**安装包前端**，没有覆盖 `openapi.qoder.com.cn` 这个 API 域。接口的实际形态是"活动（campaign）"而不是"签到按钮"，因此入口在活动列表而非签到页——两者不矛盾，但当日没查到。

## 本轮实测记录

| 步骤 | 结果 |
|---|---|
| 解 token | 27 字符（`dt-…` 前缀），密码 24 字节，耗时 4.2s |
| 设备头 | Cosy-Version 0.5.6 / MachineId / MachineToken / MachineCode / MachineType 全部取得 |
| `GET campaigns`（领取前） | 1 个活动：`CLAIMABLE`，100 积分，活动 id `01a1bbe3-…`，标题 `act-20261109-380` |
| `POST claim`（已授权一次性） | HTTP 200，`status=CLAIMED`，`replayed=true`，100 积分已入账，`expiresAt=2026-12-10` |
| `GET campaigns`（领取后） | `claimStatus=CLAIMED`，可领列表为空 |
| 重复领取 | 幂等：仍为 `CLAIMED` + `replayed`，不重复发放 |
| 后端快照 | `rewards.accounts` 出现 `qoder` 行，状态 `available`，`daily_refresh=10:00` |
| ledger | `rewards.json` 0600，不含 token / cookie |

## 实现位置

- 后端：`agent_meter/qoder_campaign.py`（凭据解析、设备头、状态与领取）、`agent_meter/helpers/qoder_auth.mjs`（解密助手）
- 框架接入：`agent_meter/rewards.py`（`ADAPTERS["qoder"]`、`DESKTOP_PROVIDERS`）、`agent_meter/collector.py`（传桌面 app 路径）、`agent_meter/server.py`（`CLAIMABLE`）
- 界面：账户卡「每日积分活动」行（待领个数 / 每份积分 / 每日刷新时刻）、设置项文案
- 测试：`tests/test_qoder_campaign.py`（23 项，含 node 端真实加解密往返与错误密码拒绝）

## 边界

- 只领当日的官方活动，不做任何兑换、抽奖、任务接受或补签。
- 默认关闭自动领取；开启后按全局领取时刻（默认 00:05 北京时间）尝试，但 Qoder 的活动 10:00 才出现，实际领取发生在 10:00 之后的首次采集（状态读取 30 分钟节流，最多延迟约 30 分钟）。
- 凭据只在内存中，不写盘、不进日志；关掉 Qoder 来源后该平台一并停止。
