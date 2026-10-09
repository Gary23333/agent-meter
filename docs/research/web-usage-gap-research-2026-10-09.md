# 未接通来源、类似方案与网页采集研究

研究日期：2026-10-09（Asia/Shanghai）。本轮接续后端实现，重点研究尚未实现的来源，没有安装或运行第三方统计应用，没有修改 Agent 启动参数、兑换重置卡或发送模型请求。

## 结论与验证层级

网页获取有可行路线：优先读取网页自身的 JSON 查询接口，页面 DOM 读取作为后备。部分产品可以复用桌面登录态，不必先打开网页登录；这取决于具体版本的凭据格式，不能统一假设。

本轮最大进展是 **ZCode 两个接口均在本机当前中国区账户上完成真实只读查询**：套餐额度、周重置时间、10 张重置卡及各卡有效期可以读取。它们是研究探针结果，尚未注册到持续采集后端。其他新接口仅完成公开源码检查，未声称已成功读取本机账户。

原后端可用来源仍为 CC Switch、Codex、Kimi；Qoder SDK 初始化问题仍存在。2026-10-09 02:40 的覆盖矩阵为 25 个候选、150 个字段槽位，12 可用、6 部分可用、132 缺失。研究证据没有自动改变该矩阵，正式接入后才更新。

- 本轮脱敏实测证据（本机文件 `web-usage-probe-evidence-2026-10-09.json`，不随源码上传）
- [开源项目固定版本和许可证](web-usage-source-reference-2026-10-09.json)
- [原后端真实测试报告](../backend-test-report.md)

## 已有类似方案

| 方案 | 实际检查的能力 | 对本项目的价值与边界 |
|---|---|---|
| [CodexBar](https://github.com/steipete/CodexBar) | Qoder 网页额度、WorkBuddy 网页积分、MiniMax Coding Plan 及可选账单历史 | 可借鉴来源适配或使用已有 CLI 桥接；不保证覆盖 MiniMax Design 钱包、ZCode 卡和全部国产 Agent。本机 CLI 桥尚未实测。 |
| [UsageBar-tauri](https://github.com/rayelzz/UsageBar-tauri) | ZCode 本机凭据解析及重置卡状态查询 | 本轮 ZCode 真实探针验证了接口路线；参考实现会把卡列表截断至 6 张，并在部分失败时返回空列表，统计后端不能照搬这些行为。 |
| [token-monitor](https://github.com/Javis603/token-monitor) | TRAE CN 额度、WorkBuddy 桌面认证与个人/企业积分、ZCode 当前账户选择、MiMo 桌面/控制台 | 中国区来源覆盖较有参考价值；需按本机版本逐项验证，不把 README 的应用数量当作全部账户实测数量。 |
| [usageBar](https://github.com/ChanningYuan/usageBar) | WorkBuddy 本机 JSONL token、Qoder 系列用量暴露开关、原生菜单栏 | 对本地 token 增量采集有参考价值；开关影响后续请求，不能补回历史。产品名称和环境变量映射仍须按本机版本确认。 |
| [TraeUseToken](https://github.com/firerlAGI/TraeUseToken) | TRAE 任务事件、会话账单 `credits_float`、可选 CDP 详细 token 监听 | 会话积分与详细 token 的实际采集案例；上游验证版本为 TRAE CN 3.3.95，本机为 3.3.103，不能直接宣布兼容。 |
| [QuotaBar](https://github.com/QuotaBar/QuotaBar) | 原生菜单栏、`--json`、本机 `/v1/limits` 与 `/v1/spend`；多种控制台来源 | 可作为补充桥接候选和菜单栏参考；Qoder、MiMo 等标为 experimental，本机未安装验证。不能叠加它与 CC Switch 的同一份消耗。 |

六个项目在固定版本上的许可证均为 MIT。适合按具体采集器借鉴，若移植源码需保留版权及许可；本轮仅研究，未把第三方实现加入运行时。固定提交、路径与许可链接见源清单，避免后续根据浮动 `main` 实现。

## 逐项接入路线

### ZCode：真实查询已成功，可优先接入

读取范围限定为 `~/.zcode/v2/setting.json`、`config.json`、`credentials.json` 中当前账户相关字段。当前凭据为 `enc:v1:` AES-256-GCM 信封，本机兼容解析成功，密钥及明文凭据只在探针内存中使用，没有写入研究文件。账户切换要优先解析当前身份对应的凭据，避免使用旧配置中其他账户的镜像 key。

1. 套餐：`GET https://open.bigmodel.cn/api/monitor/usage/quota/limit`，当前中国区账户对应的 Bearer API Key。海外的 `api.z.ai` 是另一地区路线，不能拿中国区凭据交叉试探。
2. 卡片：`GET https://zcode.z.ai/api/v1/coding-plan/reset/status`，ZCode JWT 加 `X-Bigmodel-Authorization`，`Bigmodel-Target-Type: PERSONAL`。这是查询，不是兑换。

03:05:45 +08 实测卡库存：5 小时卡 5 张、周卡 5 张，总计 10 张。每类均为 1 张到期于 **10 月 19 日 05:25:50**，4 张到期于 **10 月 29 日 06:59:18**。同到期时间的卡必须保留数量，不能按到期时间去重。上游截断 6 张会漏计本机库存。

03:07:45 +08 实测额度：5 小时总量 2000、已用 0、剩余 2000；周总量 10000、已用 579、剩余 9420、返回百分比 5，周重置 **10 月 15 日 02:27:52.974**。返回类型为 `CREDIT_LIMIT`，不是 token。周字段有 1 单位差异（10000−9420=580），百分比也不能据此当精确消耗率；保留服务端原值并记录差异，后续与应用界面核对。5 小时响应未提供下一重置时间，不能编造。

库存响应 HTTP 200 / code 0，额度响应 HTTP 200 / code 200；两个接口的成功码不同。失败、缺少数组、实际零库存须分别建模。现在只验证当前个人 Coding Plan，不承诺团队、Start Plan 或其他账户。

依据：[ZCode 卡片源码](https://github.com/rayelzz/UsageBar-tauri/blob/2605fd5f782c5044743e1d2fad681935844bebb3/src-tauri/src/providers.rs)、[当前账户发现](https://github.com/Javis603/token-monitor/blob/c62544e7ffae8dfa863c92a4e81571ad381110f0/src/shared/providers/zai/zcodeDiscovery.js)、[套餐查询](https://github.com/Javis603/token-monitor/blob/c62544e7ffae8dfa863c92a4e81571ad381110f0/src/shared/providers/zai/limits.js)。

### Qoder：中国区网页接口可绕开 SDK 初始化

看板为 `https://qoder.com.cn/account/usage`，查询为 `GET https://qoder.com.cn/api/v2/me/usages/big_model_credits`。全球对应 `qoder.com`，不是把 `.cn` 凭据发送到全球端点。

已检查解析器：`totalQuota.quotaSummary`、可选 `sharedQuota.quotaSummary`，包括 `usedValue`、`limitValue`、`remainingValue`、`usagePercentage`，以及 `nextResetAt`；兼容 snake_case。认证使用网页 Cookie，Origin/Referer 与区域一致。手动导入完整 cURL 时要只提取允许字段，绝不执行粘贴的命令；仅 Cookie 字符串缺少地区上下文，容易误选全球站。

这条路线适合替代当前失败的 SDK 初始化采集，但还未验证本机网页登录态。网页额度也不自动提供历史 token；Qoder 本地用量开关是另一条路线，不能补回启用前日志。

依据：[网页文档](https://github.com/steipete/CodexBar/blob/b0aa7fe0add90b06e3614328715d827f1c898a0f/docs/qoder.md)、[字段解析器](https://github.com/steipete/CodexBar/blob/b0aa7fe0add90b06e3614328715d827f1c898a0f/Sources/CodexBarCore/Resources/Plugins/qoder.js)。

### WorkBuddy：网页积分与本地 token 分开

网页：`https://www.workbuddy.cn/profile/plans-usage`；查询为 `POST /billing/meter/get-user-resource-summary`，body `{}`。虽然是 POST，检查源码确认用途为读取资源汇总。使用网页 Cookie，且上游发现 Cookie 与 Chrome UA 版本相关，不能硬编码一个永久 UA。

`data.Packages[]` 提供 `CycleTotalCapacity`、`CycleRemainCapacity`、可选 `CycleFrozenCapacity`、`CapacityUnit`。付费/免费包查询可提供 `CycleEndTime`，但需要 `PackageCodes` 与分页，旧版本固定包码可能漏掉新套餐。冻结积分单独保留；包的到期时间不是全账户统一重置时间；中国区无时区日期需要按该接口契约转换。

另一套桌面路线是 `https://copilot.tencent.com/v2/billing/meter/get-user-resource`（个人）或 `get-enterprise-user-usage`（企业），Bearer、账户身份与企业上下文各有要求，不与网站响应混用。本机 `CodeBuddyExtension/Data/Public/auth/workbuddy-desktop.info` 存在，但 accessToken 确认为 `$wbEncrypted` 信封，本轮未解密；旧版明文适配不能直接使用。

本地历史可参考 `~/.workbuddy/projects/**/*.jsonl` 的 `providerData.rawUsage`：prompt_tokens 已含缓存子集，不能再加缓存导致重复；时间为 epoch 毫秒。该路径/字段的上游实测版本较旧，本机 5.7.6 尚未核对实际记录。WorkBuddy 与 CodeBuddy 可能共享账户积分，不能按应用相加。

依据：[网页实现说明](https://github.com/steipete/CodexBar/blob/b0aa7fe0add90b06e3614328715d827f1c898a0f/docs/workbuddy.md)、[桌面认证格式](https://github.com/Javis603/token-monitor/blob/c62544e7ffae8dfa863c92a4e81571ad381110f0/src/electron/providers/workbuddy/localAuth.js)、[本机 token 解析](https://github.com/ChanningYuan/usageBar/blob/858715610fda819db3407cd29bc1694b879afd0e/app/Sources/usageBarProviders/WorkBuddyProvider.swift)。

### TRAE CN / SOLO：账户积分与单次会话消耗两条链

账户积分：`POST https://api.trae.cn/trae/api/v2/pay/ide_user_ent_usage`，body `{}`；`Authorization: Cloud-IDE-JWT ...`、`X-User-Region: CN`，可选 `X-Device-Id`。开源解析器从 `user_entitlement_pack_list` 的 `credits_limit` 与 `usage.credits_amount` 汇总。无积分配额的功能权益不能作为积分包；不能按旧套餐知识自行计算重置时间。

会话账单：TRAE 自身请求 `POST /api/v1/commercial/get_session_usage`，响应 `user_usage_group_by_session.credits_float` 是实际积分消耗。此接口不是完整 token 历史接口。TraeUseToken 使用任务完成事件记录调用及事件中可用的明细；增强模式通过本机 CDP 定位详细调用，并监听已有账单请求。未安装扩展、未打开调试端口、未重启用户 TRAE，本轮也没有运行上游会重载页面的探针。

建议先接账户积分查询，再支持已安装扩展的只读本地账本。只有取得具体事件契约、兼容版本并验证去重之后，才考虑自己实现详细监听。TRAE IDE 与 SOLO 是否共享同一积分账户应以返回身份核对，不按两个安装包各算一次。

依据：[TRAE 账户额度源码](https://github.com/Javis603/token-monitor/blob/c62544e7ffae8dfa863c92a4e81571ad381110f0/src/shared/providers/trae/limits.js)、[TraeUseToken 文档](https://github.com/firerlAGI/TraeUseToken/blob/6cac5c6cb044e3f4c3e18a2dadf50a36c7c002e4/README.md)、[会话账单监听](https://github.com/firerlAGI/TraeUseToken/blob/6cac5c6cb044e3f4c3e18a2dadf50a36c7c002e4/src/cdp.mjs)。

### MiniMax：Coding Plan 与 Design 钱包不能混用

现有后端已有 Coding Plan API Key 解析器，未连接有效凭据。CodexBar 另有网站登录态路线 `/v1/api/openplatform/coding_plan/remains`，Cookie 与页面 access token 上下文结合，可选账单历史 `account/amount`。只读取自己的区域与产品，账单失败不应抹去已成功的额度。

MiniMax Design 3.0.21 安装包 `mcp-tools/dist/main.js` 第 36245–36247 行确认 `/api/v1/credit/balance` 和 `/api/v1/credit/wallet`，源码注释说明余额按认证计费 scope 查询。当前只看到路由常量，没有确认注册查询工具、请求方法、认证上下文或响应字段，不能据此构造一个声称可用的接口。下一步应检查 Desktop 主进程余额实现及当前个人/团队 scope；无需通过生成任务验证余额，不碰钱包转移、充值、试用领取。

依据：[MiniMax 网页/API 实现](https://github.com/steipete/CodexBar/blob/b0aa7fe0add90b06e3614328715d827f1c898a0f/Sources/CodexBarCore/Providers/MiniMax/MiniMaxUsageFetcher.swift)。Design 路线为本机安装资源静态检查，未完成真实余额查询。

### 小米 MiMo：现成 SSO 路线，但桌面会员与 API 控制台是两种产品

token-monitor 已实现两条独立来源：控制台 `https://platform.xiaomimimo.com/api/v1` 下 `/balance`、`/tokenPlan/detail`、`/tokenPlan/usage`、`/usage`；桌面会员 `https://mimo-server-cn.xiaomimimo.com/api/user/xiaomi/subscription/self`。

上游从 MiMo 自己的 `Partitions/xiaomi-account/Cookies` 中，只查询 `.account.xiaomi.com` 的 `passToken`、`userId`，按服务进行 SSO 交换，服务 Cookie 只存内存。控制台 service id 为 `api-platform`，桌面会员为 `mimopc`，不能把不同服务 Cookie 混用。此路线复杂度高于直接 API，需要受控重定向、正确 Cookie domain/path、全程 HTTPS 和账户切换检查。

上游已说明其真实会员观察仅覆盖无会员账户，付费会员值来自 fixtures；本轮未验证本机账户。会员 `percent` 表示剩余比例，不能按“已用比例”直接显示；无会员不等于查询失败。MiMo 桌面会员不能用控制台现金余额代替。

依据：[MiMo 来源与未验证条件](https://github.com/Javis603/token-monitor/blob/c62544e7ffae8dfa863c92a4e81571ad381110f0/docs/providers/mimo.md)。

## 其余应用的未实现边界

- Claude：CodexBar/QuotaBar 有 Claude Code OAuth 用量路线，但不能推定 Claude Desktop 与 CLI 始终同账户。先验证 CLI 配额，再核对 Desktop 身份。
- OpenCode、Cherry Studio、LM Studio：本机记录/聚合可以统计消耗，但上游套餐通常属于具体供应方。LM Studio 本地模型不一定有云套餐；“不适用”与“未知”分别呈现。
- DeepSeek Harness：现有余额 API 适配待连接 Key；余额不能补出桌面 Harness 的历史 token 或未公开免费限制。
- Kimi、KimiCU、AutoGLM、Doubao/豆包浏览器、妙手、Agent Launcher：本轮没有新获得对应产品的、已实测读取契约。不能把 Kimi Code 配额覆盖到所有 Kimi 产品，也不能把 ZCode 卡覆盖到 AutoGLM；启动器不必有独立计费账户。保留缺口，继续查官方支持及产品内来源。
- 没有“全部应用都支持全部指标”的可信现成方案。一个账户可被多个应用共用；并非每种产品存在重置卡、token 明细或付费积分。

## 网页获取的实施设计

优先顺序为：已有官方/应用查询接口 → 网站 JSON 查询接口 → 已安装扩展/本地账本 → DOM 显示值。网页自动化适合建立会话和验证显示，常驻统计优先使用稳定查询接口；脚本不要点击生成、重置、购买按钮。

建议增加独立的网页来源适配层，而非每个 collector 读取完整浏览器 profile。账户连接记录保存 provider、产品、地区、会话来源、观测时间及稳定账户指纹；敏感会话通过桌面主进程的安全存储交给后端，JSON/API/日志不包含 Cookie、JWT、完整 cURL 或网页正文。网页与桌面连接同账户后只选一个额度主来源；token 历史维持独立 scope。

接口按 host + path + method 白名单，拒绝凭据跨区域和意外重定向；明确区分 401/403、429、网络失败、业务失败、字段变化、明确空库存。网页 Cookie 过期需要重新连接，不能以后台自动登录/换号当常规采集步骤。轮询沿用缓存与退避，不让重叠来源重复请求。

本轮 CUA 浏览器工具两次初始化超时，未取得任何浏览器截图、页面状态或登录会话。因此不能宣布 Qoder、WorkBuddy、TRAE、MiniMax、MiMo 网页已实测接通；源码确认与 ZCode 真实探针是不同证据等级。

## 接入顺序与正确性验收

1. **ZCode**：正式 collector、当前账户/地区解析、全卡库存与逐卡有效期。以本轮真实脱敏结构形成 fixture，再进行应用界面对账。
2. **Qoder 网页 + WorkBuddy 网页**：明确账户连接及地区、UA 约束，绕开当前 SDK/加密认证障碍。独立测试积分包分页、冻结量与包有效期。
3. **TRAE CN**：先积分包与身份，再本地事件/扩展账本；避免为采集重启工作中的应用。
4. **MiniMax Coding Plan 网页**：额度与账单独立；**Design** 先厘清钱包 scope，再实现余额读取。
5. **MiMo**：SSO 与两种产品分开；无会员及付费套餐分别验收。其余应用按实际有无指标继续补齐。

每个新来源必须完成以下验证，才进入“可用”覆盖矩阵：

| 检查 | 应证明的行为 |
|---|---|
| 真实账户对账 | API 与产品自身页面/账本同账户、同地区、同时间窗；记录时间差，动态变化不能误报固定错误 |
| 独立解析样例 | 正常、明确零、缺字段、字段变形、业务失败、过期、429；失败绝不变成零 |
| 卡与包 | 10 张不截断；同到期时间保留数量；查询不兑换；未知到期时间保留未知；逐包分页不漏项 |
| 数字与单位 | Decimal 积分金额；quota 与 token 分离；percentage 取整、剩余与已用差异保留证据 |
| 时间 | 秒/毫秒、ISO/无时区日期、中国区时区、包到期与额度重置分别测试 |
| 本地历史 | 同一消息/流式更新去重、输入内含缓存不重复、文件轮转/删除、断点续读、范围边界 |
| 身份与会话 | 账户切换旧缓存隔离；China/global 严格路由；加密不可读与已退出登录分开 |
| 输出与故障 | 响应和日志无凭据；禁止非查询接口；部分来源失败不损坏已有成功快照；旧值标记 stale |

本轮已有：公开源码定版、凭据格式检查、ZCode 双接口真实读取和脱敏证据。仍缺：新 collector 的自动化测试、页面对账、网页会话失效/跨账户实测、付费会员/团队与包分页实测。原后端的 66 个测试及 80 项对账是此前完成结果，不作为这些新来源已通过的证据。
