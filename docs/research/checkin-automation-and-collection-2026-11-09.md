# 每日积分自动领取与用量集卡研究

研究日期：2026-11-09。第一轮只做了公开资料检索和项目代码阅读。第二轮（同日）由用户授权，用 App 钥匙串里已保存的登录态做了只读查询；随后经用户明确同意，只领取了一次 WorkBuddy 任务奖励来验证领取接口，其余领取、兑换、签到接口都没有调用。研究建议不作为自动执行指令。

## 第二轮实测：网页端签到接口（2026-11-09）

接口来自各家公开网页前端或本机安装包，查询用 App 已保存的登录态（服务 `local.agent-meter.web-sessions`）。下表中「已实测」只指查询接口，领取接口一律未调用。

| 平台 | 状态查询 | 领取 | 凭证 | 结论 |
|---|---|---|---|---|
| TRAE CN | `POST https://api.trae.cn/trae/api/v2/ug/checkin_credits/status`，已实测 200 | `POST …/ug/checkin_credits/claim`，body 含 `req_source`，未调用 | 现有网页 `Cloud-IDE-JWT` 即可，无需设备 ID | 可做。领取是否需要设备 ID 待验证（错误码 9095 `ErrCheckinCreditsDeviceAlreadyUsed` 说明领取按设备去重） |
| WorkBuddy | `GET https://www.workbuddy.cn/activity/growth/streak`、`/v2/activity/growth/tasks` 等，已实测 200 | `POST /activity/growth/tasks/{task_code}/claim`、`POST /activity/growth/redeem {tier, client_token}`，未调用 | 现有网页 Cookie + 绑定 UA | 可做。没有“签到按钮”：连续天数靠每天完成一次对话，能自动领的是已完成任务奖励和 7/14/28 天档位 |
| MiniMax Code | `GET /minimax-cloud/api/v1/signin/status`（agent.minimax.cn），未实测 | `POST /minimax-cloud/api/v1/signin/claim`，未调用 | 需要网页登录 `token` 头 + 前端自算的 `yy` 签名头；现有 `minimax_code` 槽只有 API Key，不能用 | 只能用隐藏网页让页面自己发请求；需新增 MiniMax 网页登录 |
| Qoder CN | 无 | 无 | — | 官网文案写“每日签到可领 100 积分”，但 qoder.com.cn 前端和本机 Qoder CN 安装包都没有签到接口，推测在未安装的 QoderWork 客户端里。暂不做 |

### TRAE 实测返回

```json
{"checked_in": true, "did_checked_in": false, "enable": true, "credits": 200, "extra_credits": 100, "code": 0}
```

- `checked_in=true`：今天已签到（用户已在客户端签过）。`did_checked_in` 含义未确认，可能是“本设备是否签过”。
- 返回里没有连续天数，连续签到只能由 App 自己按天记录。
- 官网定价页另有“会员签到多得 3000 积分（会员有效期内签满 31 天）”的限时福利。
- 同一 SDK 还有 `ug/work_lottery/*`（Work 抽奖）、`pay/query_birthday_bonus` 等可领取项，后续可一并做查询。

### WorkBuddy 实测返回（摘要）

- `streak`：当前连续 1 天，下一档 7 天还差 5 天；补签卡 0/4；档位奖励 7 天 0 积分 + 能量 2、14 天 50 积分、28 天 150 积分。成长体系 2026-06-17 上线，时区 Asia/Shanghai。
- `tasks`：18 个任务，其中 6 个已领、1 个已完成待领（「尝鲜热门技能」100 积分）、9 个未接受。
- `badges`、`energy`、`profile`（等级 7/18）都能读，可直接作为集卡体系的外部徽章来源。
- 注意：首次查询时 App 里保存的 Cookie 已过期（连额度查询也 401），用户重新登录后才通。自动领取必须先处理登录失效提醒。

### WorkBuddy 领取验证（用户授权，一次）

- 请求：`POST https://www.workbuddy.cn/activity/growth/tasks/skill_1/claim`，body `{}`，只带网页 Cookie、绑定 UA、`Origin` / `Referer`，不需要额外签名头。领取前先确认该任务 `accept_status=completed`。
- 返回：`code=0`，`already_claimed=false`，`credit=100`，`energy=5`，并附带徽章对象（名称「尝鲜达人」、图片 URL）。
- 复查：积分包剩余 3197.09 → 3297.09，总量 3600 → 3700；能量 33 → 38；任务状态变为 `claimed`。
- 结论：网页端直接调接口可以领取，奖励即时到账。返回里的 `already_claimed` 可用来保证重复调用不会出问题；徽章对象可以直接收进集卡册。

### 实现状态（同日）

已实现 TRAE 与 WorkBuddy：后端 `agent_meter/rewards.py`、快照 `rewards` 字段、`POST /v1/rewards/claim/<slot>`；菜单栏设置新增「自动领取每日积分」开关（默认关），账户卡显示签到 / 连续活跃 / 待领任务和「领取」按钮。契约见[后端 API 文档](../backend-api.md)「每日积分领取」。MiniMax Code 网页登录与 Qoder 尚未实现；TRAE 领取接口仍待在未签到的日子实测。

### 实现建议（网页端）

1. **TRAE**：后端新增 `checkin_status`（只读）；领取在用户开启开关后，每天首次采集时如 `checked_in=false` 调用 `claim`。复用现有 15 分钟自动续期的 JWT。
2. **WorkBuddy**：只读展示连续天数、补签卡和档位；开启后自动领取 `accept_status=completed` 的任务奖励和已解锁的档位。不自动“接受”任务、不使用补签卡、不抽奖。
3. **MiniMax Code**：新增 agent.minimax.cn 网页登录，用隐藏 WKWebView 打开页面让前端自己签名；先只读面板，再做领取。
4. 所有领取都放在独立模块，默认关闭、按平台开关，结果写入集卡账本（连续领取天数也来自这里）。README / SECURITY 的“只读”说法需同步改成“默认只读，可选开启自动领取”。

## 结论速览

| 方向 | 可行性 | 主要阻碍 |
|---|---|---|
| WorkBuddy 自动签到 | 中。已有网页登录态，可用隐藏网页自动点击 | 专业版签到 2026-05-10 已下线，只剩免费版；接口未实测 |
| TRAE 自动签到 | 低到中。签到在 TraeWork 客户端，需要设备签名 | 需真实设备 ID、ECDSA 设备密钥、客户端令牌解密，现有网页 JWT 不够 |
| Qoder 自动领取 | 暂无对象 | 没有长期每日签到，只有限时活动和新用户 14 天领取 |
| 额度集卡（5 小时 / 7 天用到 80%、90%、用满） | 高 | 需新增本地窗口峰值记录，现有快照不保存历史 |
| 单日 Token 奖章（1 亿 / 5 亿 / 10 亿） | 高，且可以按历史补发 | 只需读取现有 `daily_buckets` |
| 免费模型 / 免费积分集卡 | 中高 | 要定义哪些算“免费”，Qoder 账本有 `billable` 字段可直接用 |
| 连续签到天数 | 取决于签到能否接通 | 只读也可以记录“已签到”状态，但需要签到状态接口 |

**与项目原则的冲突：** README 写明“100% Read-Only”，`agent_meter/web_sources.py` 也写明“nothing here buys, redeems or writes”。自动领积分属于写操作。实现时必须单独建模块、默认关闭、按供应商逐个开启，并同步修改 README 和 SECURITY.md 的说法。

## 一、各家签到现状

### WorkBuddy（腾讯，与 CodeBuddy 共用积分）

- 规则（第三方攻略，未核实）：客户端左下角「Buddy 加油站」签到，第 1–6 天各 100 积分，第 7 天 1000 积分，断签清零。专业版签到 2026-05-10 已下线。免费版每月 1 日另有 500 积分自动到账。
- 已有基础：`WebProvider("workbuddy")` 保存了 workbuddy.cn 网页 Cookie，并绑定 UA。
- 未知：签到入口是否也在网页上，还是只在客户端里。接口路径没有找到公开说明。
- 建议路线：如果网页上能签到，就复用 `TokenRenewer` 的隐藏 WKWebView，打开签到页，由页面自己发请求，不去逆向签名。如果只能在客户端里签到，就先只做提醒。

### TRAE CN / TraeWork（字节）

- 本机证据：`~/Library/Application Support/Trae CN/User/globalStorage/state.vscdb` 有 `credits.dailyCheckin…` 键，带 lastWriteDay，但没有积分数值（见 2026-10-18 本机复勘）。
- 规则（社区帖子，口径不一）：每日签到 150 + 会员 50 = 200 Work 专属积分；另一说法是连续签到逐日递增，断签清零。
- 开源实现：[Trae-AutoCheckin](https://github.com/tuta8mail/Trae-AutoCheckin)、[Trae-Checkin](https://github.com/wallechfox/Trae-Checkin)。这些实现要求：
  - 带上客户端注册过的十进制设备 ID（15–16 位），伪造的会返回 9074；
  - body 为 `{"req_source":1}`；
  - 新版续期需要 ECDSA P-256 设备证明，否则返回 20405；
  - 令牌从客户端 `storage.json` 的 `iCubeAuthInfo://icube.cloudide` 解密取得；
  - 每台真实设备每天只能给一个账户签到；`checked_in=true` 或错误码 9004/9095 表示今天已签。
- 与本项目的差距：现有 `trae_cn` 只捕获网页的 `Cloud-IDE-JWT`，没有设备 ID 和设备密钥。要接通需要读写客户端的加密存储，并且续期会让客户端里的旧令牌失效，可能把用户的 TRAE 挤下线。
- 建议路线：近期只读本机 `state.vscdb` 的 `credits.dailyCheckin` lastWriteDay，判断今天是否已签到，未签就提醒，并据此记录连续签到天数。自动签到暂缓。

### Qoder（阿里）

- 没有找到长期的每日签到。出现过的是限时活动：2025-08-27 至 09-01 每天 10:00 领取 500 Qwen 专属积分；QoderWork CN 新用户注册后 14 天内领取 2000 积分（300 自动发放，1700 需手动领取）。
- 建议：先不做自动领取。可以在活动页做“可领取提醒”。

## 二、额度集卡（宝可梦式）

> 2026-11-09 已实现：后端 `agent_meter/collection.py`，菜单栏新增「收集」标签页（卡册、奖章墙、冲刺中、最新掉落）。实际规则以[后端 API 文档](../backend-api.md)「卡册与奖章」为准，下文为最初草案。

### 判定数据

- 额度窗口：Codex 和 Claude Code 的 `quota` 行带有 `bucket`（five_hour / seven_day 等）、`used_percent` 和 `resets_at`。
- 缺口：快照只反映当前状态，没有历史。需要新增本地账本 `<runtime>/collection.json`（0600），以 `(source, bucket, resets_at)` 为一个周期，记录这个周期里出现过的最高 `used_percent`。`resets_at` 一变，就把上一个周期结算出卡。
- 采样误差：在一个窗口内 `used_percent` 只增不减，所以最后一次采样就是周期峰值的下限。轮询间隔为几分钟，对 80%、90% 档位影响很小；“用满”按 ≥99.5% 判定，并展示采样时间。
- 重置卡：`reset_cards` 已有库存和过期时间。可以设一张「物尽其用」卡：重置卡在过期前用掉，并且使用前所在窗口已经用到 ≥90%。

### 卡池草案

| 稀有度 | 卡片 | 条件 |
|---|---|---|
| 普通 | 热身 | 5 小时窗口结算时 ≥50% |
| 稀有 | 八分饱 | 5 小时窗口 ≥80% |
| 史诗 | 九成功力 | 5 小时窗口 ≥90% |
| 传说 | 满载而归 | 5 小时窗口用满 |
| 稀有 / 史诗 / 传说 | 周榜三档 | 7 天窗口 80% / 90% / 用满 |
| 闪卡 | 物尽其用 | 用掉的重置卡没有浪费（见上） |
| 反面卡 | 白白过期 | 重置卡过期未用，灰色卡，不计分 |

同一张卡可以重复获得，记录次数，像宝可梦一样累积张数。各账户分开算，`provider#2` 小号的卡单独计入，不和主号相加，沿用项目“不跨账户相加”的原则。

## 三、Token 奖章（运动健康式）

- 数据：各本机账本都有 `daily_buckets: [{date, tokens}]`，`imported_history` 也有逐日汇总。**可以按历史一次性补发**，第一次打开就能看到已获得的奖章。
- 口径：先按每个账本分别统计。跨账本的总量只用于“全机”奖章，并标注“各账本相加，可能含同一请求在不同客户端的记录”。按项目原则，各账本本来就互不重叠，可以直接相加，但要在界面上说明。
- 奖章草案：
  - 单日峰值：1 亿 / 5 亿 / 10 亿 / 50 亿 tokens；
  - 累计里程碑：100 亿 / 1000 亿；
  - 连续活跃：连续 7 / 30 / 100 天，每天至少有 1 条记录；
  - 个人纪录：打破历史单日最高时给一枚「新纪录」，类似 Apple 健身的“个人最佳”；
  - 缓存大师：单日缓存命中率 ≥80% 且当天 ≥1 亿 tokens。

## 四、免费额度集卡

- 免费积分：Qoder CN 账本每条请求带 `billable`，`billable=false` 就是免费消耗，可以直接统计。WorkBuddy 和 TRAE 只有余额，没有逐条记录。可以用相邻两次快照的余额变化来估算，并标注“估算”。
- 免费模型：需要一份清单（例如限时免费的 Qwen Flash、Kimi 免费档）。建议在价格表里加 `free: true` 标记，复用现有价格窗口来编辑，不在代码里写死。
- 奖章：免费积分累计用掉 1 万 / 10 万；当月领到的免费积分全部用完（“一分没浪费”）；连续 N 天领取免费额度（依赖第一节的签到状态）。

## 五、建议实施顺序

1. **集卡底座（只读，无风险）**：`collection.json` 周期结算、额度卡、单日 Token 奖章，含历史补发；面板加「卡册」标签页。
2. **签到状态（只读）**：TRAE 读本机 `state.vscdb`；WorkBuddy 和 Qoder 在网页上确认签到入口和状态接口后再接。未签到时提醒，并据此计算连续天数。
3. **自动领取（写操作，默认关闭）**：先做 WorkBuddy，用隐藏网页自动点击签到；TRAE 等设备签名方案确认不会挤掉客户端登录后再考虑。上线前修改 README 和 SECURITY 里的“只读”说法。

## 待实测

- 用已登录的 WorkBuddy 网页会话，确认签到入口、状态字段和奖励字段（只看，不点击签到）。
- 读取本机 TRAE `state.vscdb` 中 `credits.dailyCheckin` 的完整键名和取值格式。
- 确认 Codex 和 Claude Code 在窗口重置前后，`resets_at` 是否稳定，可以用作周期主键。

## 资料来源

- [WorkBuddy 积分攻略（第三方）](https://www.ai-indeed.com/encyclopedia/26041.html)
- [Trae-AutoCheckin](https://github.com/tuta8mail/Trae-AutoCheckin)、[Trae-Checkin](https://github.com/wallechfox/Trae-Checkin)
- [TRAE 社区：TraeWork 自动签到](https://forum.trae.cn/t/topic/180147)
- [Qoder 新版上线活动](https://docs.qoder.com/events/newqoderlaunch)、[QoderWork CN 新用户领取条款](https://help.aliyun.com/zh/lingma/product-overview/qoderwork-cn-new-user-credits-claim-and-referral-reward-program-terms-and-conditions)
- 本机：[本机候选来源复勘](local-usage-sources-recon-2026-10-18.md)、[未接通来源研究](web-usage-gap-research-2026-10-09.md)

## 2026-11-10 本机实测：TRAE 网页端领取被拒

在打包后的 App 里把领取时间设为当前时间后两三分钟，自动领取按时触发（04:07:15、04:14:26）。TRAE `checkin_credits/claim` 两次都返回 `code=9004`，重新查询状态仍为 `checked_in=false`，即**只凭网页 Cloud-IDE-JWT 无法领取**，开源脚本提到的客户端设备标识（`X-Device-Id` / `X-Machine-Id`）是必需项。读取 TRAE 客户端本地存储中的设备标识被本机权限策略拦下，本轮未继续。

处理：领取后若重新查询仍可领取，该次结果记为 `rejected`、`final=true`、`reason=claim_refused_from_web`，当天不再重试，并发一条「未能自动领取，请在客户端签到」通知；账户卡显示「未能自动领取 · 请在客户端签到」。WorkBuddy 的网页领取此前已实测可用（2026-11-09）。

通知已确认送达系统通知中心（本机该 App 的提醒样式为“无”且静音，所以没有横幅）。

## 2026-11-12 本机实测：补齐设备 ID 后 TRAE 领取成功

2026-11-10 的结论修正一半：**缺的不是令牌，而是设备 ID**，且它不需要解密就能拿到。

- 稳定明文来源：`~/Library/Application Support/Trae CN/User/globalStorage/storage.json` 的键名 `iCubeAuthInfo://icube-dc:<15 位十进制 id>`。只读键名，加密的值与登录态完全不碰。
- 交叉验证：`logs/aha_log/aha_electron_<date>.log` 里客户端自己上报的 `device_id=` 与键名后缀一致；`telemetry.devDeviceId`（UUID）与 `machineid`（UUID）**不是**领取要的那个 ID，别用错。
- 实测：网页 `Cloud-IDE-JWT` + `X-Device-Id: <设备 ID>` 调 `checkin_credits/claim` 返回 `code=0`，重读状态 `checked_in=true`、`claimable=[]`，即当日 300 积分到账。此前同一令牌不带设备 ID 两次均 9004。
- 未验证项：开源脚本提到的 ECDSA P-256 设备证明（20405）只出现在*续期*路径，本次领取未触发；若日后领取开始要求证明，需要再读客户端设备密钥，属另一轮工作。
- 规则提醒：一台真实设备每天只能给一个账户签到（9095）。本机客户端登录账户与网页会话账户若不同，二者共用设备 ID 时后签的那个会被拒。

处理：`agent_meter/rewards.py` 的 `trae_device_id()` 只读上述键名，`tick` 在会话未显式带 `device_id` 时自动附上；读不到则退回纯网页凭据尝试。自动领取与「立即领取每日积分」按钮共用这条路径。

