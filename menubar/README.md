# Agent 用量 · 菜单栏小组件

`agent_meter` 后端的原生 macOS 菜单栏前端（AppKit `NSStatusItem` + SwiftUI 弹出面板，macOS 14+，无第三方依赖）。

本机真实账户截图位于 `docs/screenshots/`，不随源码上传。

## 功能

- **菜单栏行情**：默认像股票大盘一样横向滚动，按顺序显示「图标 + 名称 + 剩余量 + 剩余时间」（额度百分比按余量变色，重置卡、积分余额及其更新/失效倒计时）。也可切换为逐条翻动、最紧张额度、今日 Token 或仅图标；滚动宽度 160/220/300。滚动由 Core Animation 完成，CPU 占用约 0.4%。
- **提醒通知**：额度剩余低于阈值（默认 20%，可选 10/30%）、低于 5%、用完时提醒；重置卡、积分包在 3 天内和 24 小时内到期时提醒；3 天内自动续费、7 天内会员到期（未开自动续费）提醒。每个事件只提醒一次；点击通知打开面板。
- **网页登录来源**：设置菜单「连接网页账户…」或「未接入」行的登录按钮，打开内嵌官方登录页（Qoder CN、WorkBuddy、TRAE CN）。点「完成连接」后 Cookie / 凭据只存入钥匙串，并通过 `PUT /v1/web-sessions` 交给本机后端内存使用，不写文件、不进快照。TRAE 为实验性：自动捕获页面自身请求中的 Cloud-IDE-JWT，也可手动粘贴。
- **多账号**：网页登录来源每个最多 5 个账号（「连接网页账户」里「添加账号…」，可填备注如「主号」「小号」）。每个账号单独成卡、单独进行情条和提醒，余额不相加。后端第一个账号仍用原来源 id（如 `qoder`），其余为 `qoder#2`… 并带 `account_label`。
- **即梦网页登录**：登录时记录页面接口的字段结构（`.runtime/dreamina-discovery.json`，不含值）。之后 App 每 30 分钟在隐藏网页视图里打开已登录的即梦页面，只从页面**自身**发出的 `subscription/user_info`、`benefits/user_credit` 响应中取白名单字段（会员等级、到期、续费、是否取消续费、会员 / 赠送 / 购买积分及各自失效时间），uid 只转成匿名账户指纹，经 `PUT /v1/observations` 交给后端内存。即梦只走网页登录：第一个登录账号为 `dreamina`，其余为 `dreamina#2`…（无备注时显示「账号 N」）；CLI 路线保留但默认关闭（配置 `enable_dreamina_cli`）。不伪造签名、msToken、x-bogus，也不重放请求。即梦没有单独的「积分更新时间」字段，会员积分失效时间按原值显示，不推算。
- **Kimi Code 本机 Token**：读取 `~/.kimi-code/sessions/**/agents/*/wire.jsonl` 中每轮唯一的 `usage.record`（`usageScope=turn`）；`step.end`、消息元数据、`subagent.completed` 是同一数据的重复，不计入；`session` 范围记录含义未确认，排除并计数。按文件 mtime / size 缓存（全量约 0.3 秒，增量约 0.05 秒）。
- **本机消耗合并**：「本机消耗」把全部本机账本合成一份（总量、构成、按应用、模型排行）：各直读账本（Kimi Code / Kimi 桌面端、ZCode、OpenCode、WorkBuddy、Codex / Claude Code + Claude 桌面端 local-agent / Gemini / MiniMax Code、Antigravity、DeepSeek Harness）加一次性历史导入 `imported_history`。每个账本独立计量，不做跨账本日期剔除；历史导入只补本地账本没有数据的日期或按模型补差。估算费用统一由本地价格表逐模型计算（USD 按固定汇率 1:7.25 换算为人民币后相加），按应用与模型排行各带金额，无定价模型按用量列名。
- **API 密钥**：「连接网页账户 / API 密钥」里填写 DeepSeek、MiniMax Code（Token Plan），存入钥匙串，经同一内存通道交给后端；MiniMax Code 还支持环境变量 `MINIMAX_TOKEN_PLAN_KEY` 与 `<runtime>/secrets/minimax_code.json`（迁移脚本一次性写入，0600），DeepSeek 仍兼容 `DEEPSEEK_API_KEY`。
- **ZCode**（实验性）：「连接网页账户」里登录智谱开放平台并打开 Coding Plan 用量页，自动捕获页面自己发往 bigmodel.cn 的查询凭据（只回放给同一允许的主机）；也可粘贴 Coding Plan API Key。显示 5 小时 / 每周额度（已用 / 总量、周重置时间）与 MCP 月度次数，最多 5 个账号。重置卡只在 ZCode 桌面端，当前路线不读取。
- **火山方舟 Coding Plan**：推荐在「连接网页账户」里登录火山引擎控制台并停在 Coding Plan 订阅页，App 记下页面自己的 `GetCodingPlanUsage` 请求（地址与 CSRF 头）和登录 Cookie，后端只回放这一个允许的查询，不需要任何密钥；也可填写访问控制里的 AccessKey（AK/SK）走签名的 OpenAPI。方舟控制台的 API Key 只能调用模型、无法查询用量，误填时会提示。两条路线都不发模型请求、不消耗额度，显示 5 小时 / 每周 / 每月三个窗口与重置时间，最多 5 个账号。
- **小米 MiMo API**：在内嵌窗口登录 MiMo 开放平台控制台，读取账户余额（现金 / 赠送）与 Token Plan 本月用量；只转发控制台自身的 Cookie。MiMo 的推理 API Key 无权查询余额。
- **阶跃星辰 (StepFun)**：「连接网页账户」里登录 `platform.stepfun.com` 并停在「订阅 / 用量」页，App 只保留页面自己的 `Oasis-Token`（控制台会话里其余 Cookie 会让查询接口拒绝请求），读取账户余额（充值 / 赠送）与 STEP plan 用量——老 Coding Plan 的 5 小时 / 每周窗口，或 Token Plan 的月度积分池——外加套餐名与到期日。也可粘贴开放平台 API Key，走官方 `GET /v1/accounts`，但只能读余额。最多 5 个账号。
- **Claude Code**：设置菜单「读取 Claude 额度」可单独关闭（经 `PUT /v1/preferences`，关闭后不读钥匙串也不请求）。本地 Claude Code 与 Claude 桌面端 local-agent 的 token 历史不受该开关影响，仍按本机账本计入。开启时优先用 claude.ai 网页登录，否则读 Claude Code 的钥匙串登录，查询 5 小时 / 7 天窗口；不刷新令牌。
- **界面风格**：面板标题栏的调色板按钮或设置菜单「界面风格」，在七套风格间切换（立即生效、记住选择）：「极简」「原生」「瓷白」「极光」「钛影」「霓虹」「棱镜」。瓷白固定浅色，钛影、霓虹和棱镜固定深色；其余跟随所选外观。主题定义见 [Theme.swift](Sources/AgentMeterBar/Theme.swift)。网页账户窗口跟随同一风格。
- **统一卡片结构**：各供应商账户卡按同一顺序显示：额度窗口（短窗口在前，均为进度条，「1 周」统一写作「7 天」）→ 余额与积分包（缩进）→ 积分更新 → 重置卡（明细紧跟其后）→ 续费 / 会员到期 → Token。倒计时 3 天内统一标橙，不按品牌色着色。
- **自定义排序**：设置菜单「调整卡片顺序…」，拖动或用箭头排序；账户卡片、顶部仪表、菜单栏行情、提醒都按此顺序。
- **签名与钥匙串**：在仓库根目录运行 `SIGN_IDENTITY="<证书名>" sh menubar/scripts/build-app.sh` 可指定固定证书。默认 `SIGN_MODE=dev` 优先使用 Apple Development 证书，找不到时才回退到 ad-hoc；`SIGN_MODE=adhoc` 显式使用临时签名。固定身份有助于保留钥匙串授权，ad-hoc 重建后可能需要重新授权。
- **界面**：极光渐变底 + 毛玻璃卡片（品牌色描边与光晕）、霓虹环形仪表与渐变进度条（入场动画）、顶部「驾驶舱」仪表条（每个账户一个同心圆仪表，外圈 5 小时、内圈 7 天，下方列出各窗口剩余）、滑动胶囊标签、Codex 近 30 个活跃日 Token 走势线、本机消耗环形图（Swift Charts）。卡片和行情条使用应用真实图标；行情条带 ▲/▼ 变化（绿=剩余增加，红=被消耗）。面板打开时 CPU 约 4%，空闲约 2%。
- **一键打开**：每张账户卡、「未接入」行、驾驶舱仪表、按应用行、应用覆盖列表都可直接打开对应应用（按后端发现的路径）；Qoder 有 CN / CN IDE 两个应用时弹出选择；没有桌面应用的即梦、DeepSeek 打开官网。
- **账户额度**：Codex 环形余量、重置倒计时、逐张重置卡到期；Kimi 多窗口进度条；MiniMax Design 钱包、积分包失效、积分更新与续费倒计时；即梦积分；DeepSeek 余额旁新增网页用量「今日 / 近 3 天 / 近 7 天」金额、Token 与请求数，附近 7 日金额柱图（仅展示、不计入本机消耗）；未接入来源及原因。
- **本机消耗**：全部本机账本今日 / 7 天 / 30 天 / 全部的 Token 总量、API 等价估算费用、输入/输出/缓存构成、按应用和模型排行（含金额、模型名去掉供应方前缀）；下界、无定价请求与未计价模型单独标注。
- **应用**页按应用归集近期会话和十一类指标。每张卡片显示今日 Token，展开后可查看累计直读、历史导入、指标状态和会话详情。无近期会话的已安装应用，以及只有本机账本的 CLI 同样可查看。
- 时间按北京时间显示，倒计时本地每 20 秒更新；每 5 分钟读取一次快照（后端缓存 120 秒），刷新按钮调用 `POST /v1/refresh`。失败时保留上次数据并提示。

## 报告与内存优化

报告窗口提供简洁晒用量与完整复盘，六个内容开关和七套主题；模式、开关与主题会记住。海报可展示 DeepSeek 专属峰谷及 Codex 生图独立统计，费用开关覆盖主数字、模型金额、峰谷金额与生图估算。金额统一人民币，USD 按固定汇率 1:7.25 换算后相加；后台来源原币种保持用于审计。模型单价配置可查看 USD / CNY，保存前不改写现有价格。

报告只在快照或时间段变化时重新聚合；关闭窗口释放视图，导出时及时释放临时位图。后台多来源日志解析共用 16 MiB 估算字节预算、最多 512 文件的缓存，淘汰只影响下次重读，不截断统计。完整改动与验证见 [优化记录](../docs/performance-sharing-review-2026-10-30.md)。

## 构建

以下命令均从仓库根目录执行，需要 macOS 14+、Xcode / Swift 5.10+ 和 Python 3.9+。打包依赖与完整流程见[根 README](../README.md#方式二从源码构建原生应用)。

```sh
python3 -m pip install -r requirements-build.txt
sh menubar/scripts/build-app.sh
```

产物为 `release/Agent 用量.app`（包含独立 Python 后端，设置 `LSUIElement`，不显示 Dock 图标）。运行 `sh scripts/build-dmg.sh` 生成 DMG。默认开发签名与正式分发签名不同；`SIGN_MODE=dist` 需要自己的 Developer ID 身份，公证还需相应凭据。`AGENT_METER_HOME` 只用于运行时开发覆盖，不写入发布包。

仅验证 Swift 前端可运行 `swift test --package-path menubar` 和 `swift build -c release --package-path menubar`。这些检查不代表真实账户、钥匙串或安装包公证已通过验证。

## 与后端的关系

- 启动时若 `127.0.0.1:8769` 没有后端，就启动 App 内的独立后端，工作目录为 `~/Library/Application Support/AgentMeter`；源码开发时可用 `AGENT_METER_HOME` 覆盖，运行 `python3 -m agent_meter serve --start-kimi-server`。退出（含 SIGTERM）时关闭自有进程；已有后端则用同目录 token 验证后复用。
- 子进程 PATH 额外加入 ChatGPT 内置 Codex CLI、`~/.local/bin`、`~/.kimi-code/bin`、Homebrew 路径；登录 shell 让 profile 中导出的 `MINIMAX_TOKEN_PLAN_KEY` / `DEEPSEEK_API_KEY` 生效。
- token 只从 `.runtime/api.token` 读取并放入请求头，不显示、不记录。后端日志写到 `.runtime/menubar-backend.log`。
- Info.plist 设置 `NSAllowsLocalNetworking`，否则 ATS 会拦截对 127.0.0.1 的 HTTP 请求。

## 离线预览

预览遍历当前全部标签页（账户额度、应用、重置预测、本机消耗、桌宠）和七套主题，输出浅色 / 深色 PNG；固定外观主题仍使用其指定配色。还会生成 `ticker-*.png`（行情条）、`share-<主题>-<预设>.png`（分享卡）和 `alerts.txt`（以当前快照在 现在、+10 天、+11.5 天、+13.2 天 试算的提醒）。项目归因折叠在「应用」页底部，预览展开态可先 `defaults write AgentMeterBar projectsSectionExpanded -bool YES` 再渲染。

```sh
swift build --package-path menubar
menubar/.build/debug/AgentMeterBar --preview /path/to/snapshot.json out/
```

预览不连接后端，把各标签页按浅色 / 深色渲染为 PNG。公开截图请使用[合成演示快照](../docs/images/README.md)，不要输入真实账户快照；已有截图的版本来源与当前生成结果应分别记录。

加 `--tab pet`（只渲染一个标签页，约 12 秒一套风格）、`--theme aurora`（只渲染一套风格）、`--pet-state alarm`（让舞台试玩某个状态）可以快速看「桌宠」页；`-petPack cat` 换形象（命令行参数只对本次运行生效，不写偏好）。桌宠页里的 web view 不在屏幕上时拿不到动画帧，所以预览里舞台由页面主动「画一张」再合成进截图。

## 在已安装的 App 旁边运行开发构建

已安装的 App 占着 8769 端口。开发构建用环境变量换一个端口、跳过钥匙串，并把面板放进普通窗口：

```sh
swift build --package-path menubar
ln -sf AgentMeterBar menubar/.build/debug/AgentMeterBarDev        # 进程名不同 → 偏好域不同，不碰 AgentMeterBar / 已安装 App 的设置
AGENT_METER_HOME="$PWD" AGENT_METER_PORT=18769 AGENT_METER_NO_KEYCHAIN=1 \
  menubar/.build/debug/AgentMeterBarDev --panel-window -petEnabled YES -claudeEnabled NO -forecastEnabled NO
```

后端在 `$AGENT_METER_HOME/.runtime`（已忽略）；退出开发实例用面板里的「退出」，或对它自己的 PID `kill`（不要 `pkill AgentMeterBar`，会把已安装的 App 一起结束）。`--selftest` 会在这个窗口里跑一组真实事件的自检并退出。
