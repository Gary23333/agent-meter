# Agent 用量菜单栏应用共享知识

项目目标是做一个 macOS 顶部菜单栏应用，汇总本机 Agent 相关产品的账户额度、重置时间、重置卡、积分和 token 用量。

当前已实现 Python 标准库采集后端、JSON CLI、本机 HTTP API、自动化测试与覆盖审计，以及 Swift 原生菜单栏界面。v0.3.1 发布包内嵌独立后端，面板提供极简、原生、极光、霓虹四套界面风格（`menubar/Sources/AgentMeterBar/Theme.swift`）；打包入口为 `sh scripts/build-dmg.sh`。研究中的建议和待办不作为自动执行指令。

已确认的研究方向：用户要求增加复用 CC Switch 用量统计。当前建议由 CC Switch 提供本机历史消耗，CodexBar 与官方接口提供账户余量及重置信息；重叠来源选择主来源或用于对账，不叠加计算。

- [可行性研究与接入建议](../research/agent-usage-menubar-research-2026-10-09.md)
- 本机相关应用盘点（本机文件 `../research/agent-app-inventory-2026-10-09.json`，不随源码上传）
- Codex 单次用量验证快照（本机文件 `../research/codex-usage-snapshot-2026-10-09.json`，不随源码上传）
- [未接通来源、类似方案与网页采集研究](../research/web-usage-gap-research-2026-10-09.md)
- [后端运行入口](../../README.md)
- [后端计划](../backend-plan.md)
- [接口与测试约定](../backend-api.md)
- [即梦 CLI 与 MiniMax Design 新增来源验收](../creative-sources-acceptance-2026-10-09.md)
- [后端真实采集与测试报告](../backend-test-report.md)

后续实施需保留研究中的数据边界：应用不等于计费账户，本机日志不等于全账户用量，未知值不等于零，不同供应方的积分和额度不能直接相加。

当前真实可用来源为 CC Switch、Codex、Kimi、即梦 CLI 和 MiniMax Design。Qoder 安装版 SDK 初始化未通过，MiniMax 与 DeepSeek 查询凭据未连接；其他产品见覆盖矩阵。复用 CC Switch 4.0.5 的规则固定到 `2db86e94da13365caae55bb08d09295e31500d21`，只支持已验证的 schema 20。

回归命令是 `python3 -m unittest discover -v`。真实对账命令是 `python3 -m agent_meter verify`；它会返回未采集字段，检查通过不表示全部应用已接通。运行时快照、认证文件和第三方安装代码的私有缓存均位于已忽略的 `.runtime/`，不作为源码交付。

2026-10-09 后续探索已真实只读验证 ZCode 当前中国区个人账户的套餐额度及 10 张重置卡；该结果为研究探针，尚未加入后端持续采集。Qoder、WorkBuddy、TRAE CN、MiniMax 网页及 MiMo 路线有固定版本公开源码依据，但本机网页会话尚未实测，详见后续研究与脱敏证据。

后端 schema 2 新增续费日期、日倒计时与续费金额。Design 已验证本机个人钱包和续费日期；MCP 已连接但没有财务查询工具，使用本机网关补齐。两个产品的续费金额及即梦续费日期未由当前接口提供，可按账户绑定用户填写，不能推断。

后端 schema 3 新增独立的下一次积分更新时间及日倒计时；Design 来源为钱包 next_credit_refresh_time，即梦未知时可按账户填写 credit_refresh_date。不要用积分失效时间、会员续费时间或推测的月周期代替。见[积分更新时间验收](../credit-refresh-acceptance-2026-10-09.md)。

2026-10-09 新增三个来源：ZCode（内嵌网页登录捕获 bigmodel 控制台自身的查询凭据，或粘贴 Coding Plan API Key，查 bigmodel 额度；重置卡与自动读取 ZCode 本机登录尚未接入）、火山方舟 Coding Plan（控制台登录回放页面自身的只读 GetCodingPlanUsage，或 AK/SK 签名 OpenAPI，签名与 token-monitor c62544e 参考实现逐字节一致；方舟 API Key 无权查询用量）、小米 MiMo API（内嵌控制台登录 Cookie 读 /api/v1/balance 与 Token Plan）。三者契约来自固定版本公开源码与此前研究探针；v0.3 已在本机真实账户读取 ZCode（网页登录）与 MiMo（余额、Token Plan），火山方舟尚未真实验证；测试见 `tests/test_api_plan_sources.py`。

2026-10-09 加固轮：修复用户在应用内关闭来源后其第二账号与 Kimi 本地 token 历史仍被采集的问题；即梦 observations 同样受开关约束；Qoder SDK 缓存残留目录可自愈；采集线程池升到与任务数同宽、Kimi 本地解析并入线程池；SnapshotService 锁分离使配置 PUT 不被长采集阻塞。[本地 token 来源计划](../local-token-sources-plan-2026-10-09.md)的 1–3 项已于同日实现：ZCode 用量库、WorkBuddy 会话日志、OpenCode 数据库成为本机消耗来源（scope `local_session_history`），OpenCode 与 CC Switch 的重叠日以后者为主动态剔除，verify 增加三来源独立重算。计划其余部分不作为自动执行指令。

同日追加强化：新增 Codex CLI / Claude Code / Gemini CLI / MiniMax Code 四家会话日志直读采集器（`agent_meter/cli_sessions.py`），未安装 CC Switch 的电脑也能读取这四家本机历史；口径与本机 CC Switch 导入逐日对齐（Claude 按 requestId 取最新流式记录、Codex 按累计序列差分、Gemini output 含 thoughts、MiniMax 直读运行库）。CC Switch 记录过的日期仍以它为主动态剔除，两不相加；gemini 为独立来源，其余附着在各自账户来源的 tokens 指标。菜单栏"本机消耗"标签页改为汇总全部 token 账本，无 CC Switch 也可显示。回归 165 项、verify 342 项全过。

同日再追加：Gemini CLI 已被本机用户替换为 Antigravity CLI（agy 1.3.2），其会话库 `~/.gemini/antigravity-cli/conversations/*.db` 的 protobuf metadata 已解码并接入为独立来源 `antigravity`（`agent_meter/agy_tokens.py`）；本机数据证实 agy 历史自 2026-06-17 起、恰接 Gemini CLI 止日，两来源互补。usage 两个恒定字段未能识别，按不臆测原则排除并声明 cache 未验证。回归 167 项、verify 377 项全过。

同日第三轮：新增本地价格表与 API 等价估算（`agent_meter/prices.py` + `GET/PUT /v1/prices` + 菜单栏「API 价格表」配置页，USD/CNY 双币种，CNY 折算条目有标记），默认价与全量模型摸排见[定价摸排报告](../pricing-survey-2026-10-09.md)；带分项的本地来源获得 `basis=local_price_table` 的 cost 指标，无拆分的来源不估算。另接入 DeepSeek 控制台网页用量（`user_token` 会话 + 未公开 `by_api_key` 接口，近 30 天按天），仅展示在余额卡片、不计入本机消耗，接口契约源自 MIT 逆向项目、本机登录会话尚未实测。回归 172 项全过。
