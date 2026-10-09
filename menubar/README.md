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
- **本机消耗合并**：「本机消耗」把 CC Switch 历史与 Kimi Code 本机记录合成一份（总量、构成、按应用、模型排行）。两者记录的是不同客户端（CC Switch 里的 `kimi-for-coding` 是经 CC Switch 路由到 Kimi 的 Claude Code，不是 Kimi Code 应用），相加不重复。估算费用只含 CC Switch 有定价的部分，Kimi 显示「—」。
- **API 密钥**：「连接网页账户 / API 密钥」里填写 DeepSeek、MiniMax Code（Token Plan）的 API Key，存入钥匙串，经同一内存通道交给后端；仍兼容环境变量。
- **Claude Code**：设置菜单「读取 Claude 额度」可单独关闭（经 `PUT /v1/preferences`，关闭后不读钥匙串也不请求）。开启时优先用 claude.ai 网页登录，否则读 Claude Code 的钥匙串登录，查询 5 小时 / 7 天窗口；不刷新令牌。
- **界面风格**：面板标题栏的调色板按钮或设置菜单「界面风格」，在四套风格间切换（立即生效、记住选择）：「极简」黑白排版、无卡片无阴影；「原生」macOS 系统实色卡片；「极光」毛玻璃与彩色光斑（默认）；「霓虹」赛博霓虹，固定深色，背景光效由 Core Animation 驱动。网页账户窗口跟随同一风格。
- **统一卡片结构**：各供应商账户卡按同一顺序显示：额度窗口（短窗口在前，均为进度条，「1 周」统一写作「7 天」）→ 余额与积分包（缩进）→ 积分更新 → 重置卡（明细紧跟其后）→ 续费 / 会员到期 → Token。倒计时 3 天内统一标橙，不按品牌色着色。
- **自定义排序**：设置菜单「调整卡片顺序…」，拖动或用箭头排序；账户卡片、顶部仪表、菜单栏行情、提醒都按此顺序。
- **签名与钥匙串**：`SIGN_IDENTITY="<证书名>" ./scripts/build-app.sh` 用固定证书签名，重新构建后钥匙串「始终允许」仍有效；默认 ad-hoc 签名每次构建都会重新弹窗。
- **界面**：极光渐变底 + 毛玻璃卡片（品牌色描边与光晕）、霓虹环形仪表与渐变进度条（入场动画）、顶部「驾驶舱」迷你仪表条、滑动胶囊标签、Codex 近 30 个活跃日 Token 走势线、本机消耗环形图（Swift Charts）。卡片和行情条使用应用真实图标；行情条带 ▲/▼ 变化（绿=剩余增加，红=被消耗）。面板打开时 CPU 约 4%，空闲约 2%。
- **一键打开**：每张账户卡、「未接入」行、驾驶舱仪表、按应用行、应用覆盖列表都可直接打开对应应用（按后端发现的路径）；Qoder 有 CN / CN IDE 两个应用时弹出选择；没有桌面应用的即梦、DeepSeek 打开官网。
- **账户额度**：Codex 环形余量、重置倒计时、逐张重置卡到期；Kimi 多窗口进度条；MiniMax Design 钱包、积分包失效、积分更新与续费倒计时；即梦积分；未接入来源及原因。
- **本机消耗**：CC Switch 今日 / 7 天 / 30 天 / 全部的 Token 总量、API 等价估算费用、输入/输出/缓存构成、按应用和模型排行；下界、无定价请求单独标注。
- **应用覆盖**：每个已发现应用十一类指标的接入状态。
- 时间按北京时间显示，倒计时本地每 20 秒更新；每 5 分钟读取一次快照（后端缓存 120 秒），刷新按钮调用 `POST /v1/refresh`。失败时保留上次数据并提示。

## 构建

```sh
sh scripts/build-app.sh
```

产物为 `../release/Agent 用量.app`（包含独立 Python 后端，ad-hoc 签名、`LSUIElement`，不显示 Dock 图标）。从项目根目录运行 `sh scripts/build-dmg.sh` 生成 DMG。`AGENT_METER_HOME` 只用于运行时开发覆盖，不写入发布包。

## 与后端的关系

- 启动时若 `127.0.0.1:8769` 没有后端，就启动 App 内的独立后端，工作目录为 `~/Library/Application Support/AgentMeter`；源码开发时可用 `AGENT_METER_HOME` 覆盖，运行 `python3 -m agent_meter serve --start-kimi-server`。退出（含 SIGTERM）时关闭自有进程；已有后端则用同目录 token 验证后复用。
- 子进程 PATH 额外加入 ChatGPT 内置 Codex CLI、`~/.local/bin`、`~/.kimi-code/bin`、Homebrew 路径；登录 shell 让 profile 中导出的 `MINIMAX_TOKEN_PLAN_KEY` / `DEEPSEEK_API_KEY` 生效。
- token 只从 `.runtime/api.token` 读取并放入请求头，不显示、不记录。后端日志写到 `.runtime/menubar-backend.log`。
- Info.plist 设置 `NSAllowsLocalNetworking`，否则 ATS 会拦截对 127.0.0.1 的 HTTP 请求。

## 离线预览

除三个标签页外，还会输出 `ticker-*.png`（行情条）和 `alerts.txt`（以当前快照在 现在、+10 天、+11.5 天、+13.2 天 试算的提醒）。

```sh
swift build
.build/debug/AgentMeterBar --preview /path/to/snapshot.json out/
```

不连接后端，把三个标签页按浅色 / 深色渲染为 PNG。
