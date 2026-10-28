# 本机 Harness 接入与钥匙串授权检查

检查日期：2026-10-26，Asia/Shanghai。统计基准为已安装 AgentMeter 后端在 **22:25:04** 生成的快照；签名与钥匙串元数据为本轮现场检查。这里的“接入”指 AgentMeter 能否读取各工具的用量，并正确区分本机账本、账户额度与创作积分。

**DeepSeek Harness 的本机 Token 接入正常；整体来源尚未全部接通，覆盖页和校验器也有遗漏。当前主 App 的开发者签名有效。重建后再次要求密码，最值得优先修正的是构建时签名身份可能变化，尤其是沙箱查不到证书后自动回退到临时签名。**

用户已明确：弹窗属于钥匙串访问请求，发生在重新构建安装后打开，而非同一安装版本单纯退出重开。

## 已安装工具的实际接入情况

实际运行路径为 `/Applications/Agent 用量.app/Contents/MacOS/AgentMeterBar`，子进程为包内 `Contents/Resources/backend/agent-meter-backend`。App 版本为 0.9.1。安装目录与项目 `release/` 中主程序 SHA-256 相同，没有发现本轮运行的是另一份旧主程序。

| 工具或来源 | 当前状态 | 具体边界或问题 |
| --- | --- | --- |
| DeepSeek Harness 0.2.1-rc.3 和 dsh CLI | 本机 Token、费用估算可用 | 114 个会话文件，11 个 v3、103 个旧格式，跳过 0 个；Token 汇总复核 24 项通过 |
| Codex 桌面端和 CLI | 账户额度、重置时间、重置卡、积分可用；本机历史已采集 | 本机历史以 CC Switch 为主，直读仅补未导入日期；两套历史账本的交叉核对仍有明显差异，不能宣称全量对账通过 |
| Claude Code | 账户额度读取被用户关闭 | CC Switch 中的 Claude 历史仍可展示；这不等于 Claude 桌面普通聊天的全部消耗已接通 |
| Kimi Code | 账户额度、本机 Token、费用估算可用 | 读取当前 kimi-code 账本；旧 `~/.kimi/sessions` 历史未覆盖 |
| Kimi 桌面端 Agent 模式 | Token、费用估算可用 | 来源 `kimi_desktop` 已在安装版工作；覆盖页仍将 Kimi 映射为 `kimi_chat`，错误显示未支持；普通聊天不在该账本范围 |
| MiniMax Code | 套餐额度、Token、费用估算可用 | 本机历史按 CC Switch 优先规则合并 |
| MiniMax Design | 积分钱包、刷新日期、续费日期、Agent Token 可用 | Token 与独立 OpenCode 库按会话 ID 去重，本次剔除 430 个共有会话；金额部分模型未定价 |
| WorkBuddy | 账户额度、积分、本机 Token、费用估算可用 | 当前快照可用，不代表全部其他设备历史 |
| ZCode | 账户额度、本机 Token、费用估算可用 | 活跃库会在快照之后继续写入；同一事务内四周期 28 项 Token 算术复核通过 |
| OpenCode | 本机 Token、部分费用估算可用 | 属本地历史，不是账户总额度 |
| Antigravity CLI | 本机 Token、部分费用估算可用 | 缓存字段语义仍未确认；Gemini CLI 已不在当前 PATH，其旧历史仍单独保留 |
| Qoder CN | 本地积分账本可用；账户额度未连通 | 当前原因 `not_authenticated`；已有积分不是 Token。后续找到 DeepSeek/MiniMax 第三方响应，但没有保存 usage，见[专项复核](qoder-byok-local-usage-recon-2026-10-26.md) |
| TRAE CN | 账户额度、积分可用 | 当前接口未提供 Token；本地 Token 采集尚未实现 |
| 即梦 | 网页积分可用，第二账号有续费日期 | 当前 CLI 为 `dreamina-canvas`；后端旧 CLI 路由寻找 `dreamina`，且默认关闭，不影响目前工作的网页采集 |
| DeepSeek API | 余额可用 | 与跨模型的 dsh 本机会话账本独立 |
| 小米 MiMo | API 账户未登录 | 当前原因 `mimo_not_authenticated`；MiMo Code 本地数据库仍有 868 条带 Token 的 assistant 消息，但尚无独立采集器 |
| 阶跃星辰、火山方舟 | 尚未连接凭据 | 适配代码存在不等于真实账户已经连通 |
| KimiCU、AutoGLM、Cherry Studio、豆包、妙手、LM Studio 等 | 当前无对应有效适配 | 被发现为已安装应用不等于能采集用量；本轮未重新逆向这些产品的数据格式 |

覆盖快照包含 22 个识别到的已安装应用和 1 个历史条目。这是发现白名单的结果，不是“22 个工具全部接通”。应用覆盖矩阵里的 210 个缺失字段包含产品本来就不提供的指标，不能当作 210 个故障。

### DeepSeek Harness 的验收数据

| 周期 | 请求数 | 总 Token |
| --- | ---: | ---: |
| 今日 | 109 | 9,465,982 |
| 近 7 天 | 543 | 82,207,404 |
| 近 30 天 | 1,750 | 284,656,497 |
| 全部 | 11,979 | 3,091,168,155 |

安装版使用 Python 标准库 zstd 解压，来源为 `~/.dsh/sessions`，按每个会话的 `(turn, step)` 保留最终用量，排除渐进与重复副本。该来源可跨供应商、跨模型，正确地放在“本机消耗”，不归入单一 DeepSeek 账户。这里验证了读取、去重后的周期汇总与安装版输出；不代表服务商账单对账。

### 尚未通过的对账项

对安装版快照运行现有 `verify_snapshot`，结果为 **779 通过、49 失败**。失败可分为三类，不能合并解释为所有接入都坏了：

| 类型 | 数量 | 复核结果 |
| --- | ---: | --- |
| ZCode 快照与活跃数据库差异 | 20 | 四个周期各相差 1 条请求及其 Token；在同一只读数据库事务内比较生产汇总与独立公式，28 项全部一致。符合快照与后续账本时点不同，未见汇总公式错误 |
| 模型费用校验不认识别名 | 28 | 生产 `PriceTable.match` 支持用户模型绑定，但 `verify.py` 独立匹配代码没有处理 `aliases`。按绑定规则另行复算全部 40 个来源周期，金额与未定价模型集合均一致；这是校验器功能落后 |
| Codex 与 CC Switch 历史交叉对账 | 1 | 19 个共同历史日中，直读比 CC Switch 少 3,460 条请求、13,768,855 新鲜输入 Token、1,468,389 输出 Token、321,677,184 缓存读取 Token。原因尚未查清，不能以实时同步的小幅漂移解释后直接忽略 |

CC Switch 当前安装版本为 4.0.17，数据库仍为受支持的 schema 20；代码中的参考行为版本为 4.0.5。其数据库聚合相关 45 项检查通过，但这不证明与 Codex 原始文件的导入语义仍然完全一致。应对上述 19 天逐日核查导入去重、文件保留与解析语义，再决定是否调整采集器。

## 为什么有开发者证书仍然弹钥匙串密码

### 当前主 App 签名有效

宿主环境执行 `codesign --verify --deep --strict` 返回 `valid on disk` 和 `satisfies its Designated Requirement`。当前主 App 使用 **Apple Development** 开发证书，Team ID 为 `WTTNX5S72B`，Bundle ID 为 `local.agent-meter.menubar`。它与 Developer ID Application 分发证书是不同身份。

首次在受限沙箱内执行验证曾返回信任错误，宿主环境复核通过；不能把沙箱缺少系统信任服务的结果误判为 App 签坏。

签名确认应用身份和完整性，钥匙串另按每个凭据项目保存的访问控制规则判断能否放行。同一个受信任身份可以跨版本复用授权；拥有证书本身不会替换旧项目的授权。[Apple 代码签名与钥匙串访问控制说明](https://developer.apple.com/library/archive/documentation/Security/Conceptual/CodeSigningGuide/AboutCS/AboutCS.html)

### 构建脚本存在可复现的身份回退条件

本轮执行同一条只读命令 `security find-identity -v -p codesigning`：

| 执行环境 | 结果 |
| --- | --- |
| 当前受限沙箱 | 0 个有效身份 |
| 正常宿主环境 | 3 个有效身份，包含本地自签证书、Apple Development、Developer ID Application |

[`build-app.sh`](../../menubar/scripts/build-app.sh) 第 63–66 行在找不到 Apple Development 时，会警告并设置 `sign_id="-"`，继续生成 ad-hoc 临时签名包。这形成明确的触发链路：**机器有证书 → 构建环境看不到证书 → 脚本回退临时签名 → 新二进制身份随构建改变 → 旧钥匙串授权不再匹配**。

历史授权中同时出现 ad-hoc 的 `cdhash` 规则、本地自签证书、Apple Development 和 Developer ID Application，证明确实使用过多种身份。不能仅凭“当前这一份正确签名”推断所有过往或后续重建都保持相同身份。本轮没有重放用户每次构建，因此不把该触发条件说成每次历史弹窗唯一经过的路径。

### 当前九个凭据都已匹配主 App

只读查看服务 `local.agent-meter.web-sessions` 的访问控制元数据，未请求密码内容；查询工具明确禁止交互。登录钥匙串检查时处于解锁状态。

| 凭据槽位 | 已保存受信任应用记录数 | 与当前 App 匹配的代码身份规则 |
| --- | ---: | ---: |
| dreamina | 27 | 1 |
| dreamina#2 | 27 | 1 |
| deepseek_api | 25 | 1 |
| zcode | 24 | 1 |
| minimax_code | 16 | 1 |
| qoder | 13 | 1 |
| mimo | 12 | 1 |
| workbuddy | 5 | 1 |
| trae_cn | 1 | 1 |

九个槽位的分区列表均含当前 Team ID；逐条提取保存的代码要求，再用当前安装 App 检查，均至少有一条匹配的 Apple Development 规则。大量旧记录说明反复授权的历史，本身不等于当前授权损坏。

**保持当前证书、Bundle ID 和代码身份规则不变，后续正常重建应复用已有授权。** 尚未进行重建安装与重启的端到端验证，因此目前不能宣称“反复弹窗已修复”。若同一身份下仍重复，应记录具体槽位及系统拒绝原因再定位。

“允许一次”只对当次访问有效，“始终允许”才保存持续访问许可；不能把输入过密码等同于已保存持续许可。[Apple 钥匙串授权选项说明](https://support.apple.com/en-euro/guide/keychain-access/kyca1243/mac)

### 程序还有两处会放大授权问题

1. [`Keychain.swift`](../../menubar/Sources/AgentMeterBar/Keychain.swift) 的保存逻辑先 `SecItemDelete` 再 `SecItemAdd`，会重建凭据项目，而非保留现有访问控制后只更新值。在不同签名身份交替运行和保存时，旧身份许可可能丢失。
2. [`WebConnections.swift`](../../menubar/Sources/AgentMeterBar/WebConnections.swift) 启动时枚举全部保存槽位并读取秘密，没有先按来源启用状态过滤，也没有先尝试无交互读取。某个旧槽位缺少当前许可，就会在启动阶段直接弹框。读取失败被折叠为 `nil`，无法区分未授权、钥匙串锁定和数据不存在。

包内 Python 后端目前仍为 ad-hoc 签名，这是打包一致性与分发时应处理的事项，但不是本轮这些网页凭据弹窗的直接证据：这些凭据由已签名 Swift 主 App 直接读取。Claude 账户来源当前关闭，目标钥匙串服务也未找到，不能把问题归因于 Claude 的 `security` 子进程。

## 建议的修正顺序

以下为后续实施建议，本轮只分析并保留证据，没有修改业务代码、签名、钥匙串或账户连接。

1. **固定构建身份并禁止自动降级。** 为本机开发构建固定 Apple Development 身份，在可访问系统签名服务的环境执行；证书不可用就明确失败，不继续输出 ad-hoc 包。分发构建使用明确的 Developer ID 身份，并核验产物的代码身份规则，避免无意切换。
2. **更新凭据时保留授权。** 保存改为优先 `SecItemUpdate`，仅不存在时新增；处理错误状态。启动先无交互读取所需槽位，需要许可时提供明确的连接操作。无需清空整个钥匙串或向所有应用开放凭据。
3. **修正 Kimi 覆盖页与费用校验器。** 将 Kimi 桌面 Agent 账本映射到对应 Token 字段，保留普通聊天的边界；独立费用校验同步模型别名规则。
4. **核查 Codex 历史差异。** 对齐 CC Switch 4.0.17 与本机 rollout 统计语义，处理上面的 19 个历史日差异，再宣称全量验收通过。
5. **分别处理账户与历史缺口。** Qoder、MiMo 需要恢复账户登录；旧 Kimi 的 80 个 wire 文件、MiMo Code 的 868 条账本消息需要独立新增历史采集，不能靠重新登录解决。

完成签名与凭据改动后，验收应包括：两次连续构建的主 App 代码身份规则相同；安装两次后各重启一次；已有九个凭据无需再次授权；主动断开后重新连接仍正常；关闭的来源不触发凭据读取。

## 本地复核证据

详细证据保存在已忽略的 `.runtime/harness-audit-2026-10-26/`，用于后续复核，不作为公开发布附件：

- `installed-snapshot.json`：固定的安装版快照。
- `installed-verification.json`：779 通过、49 失败的原始检查报告。
- `alias-aware-price-checks.json`：40 个周期的别名感知费用复算。
- `zcode-transaction-checks.json`：ZCode 同事务 28 项复核。
- `keychain-summary.json`：九个项目的授权数量、分区类型与匹配结果。
- `keychain-requirements.txt`：代码要求与当前 App 匹配结果，只有授权元数据。
- `keychain_metadata.c`、`keychain_requirements.c`：只读诊断程序，禁止钥匙串交互，不查询秘密内容。

源码定位：[`collector.py`](../../agent_meter/collector.py)、[`discovery.py`](../../agent_meter/discovery.py)、[`verify.py`](../../agent_meter/verify.py)、[`prices.py`](../../agent_meter/prices.py)、[`dsh_tokens.py`](../../agent_meter/dsh_tokens.py)、[`Keychain.swift`](../../menubar/Sources/AgentMeterBar/Keychain.swift)、[`build-app.sh`](../../menubar/scripts/build-app.sh)。
