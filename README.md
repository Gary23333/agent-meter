<p align="center">
  <img src="docs/images/logo/agentmeter-icon.svg" alt="AgentMeter logo" width="128" />
</p>

# AgentMeter · Agent 用量

<p align="center">
  <img src="docs/images/accounts-light.png" alt="AgentMeter 账户额度浅色界面，使用演示数据" width="420" />
</p>

<p align="center">
  <strong>专为开发者与创作者打造的 macOS 菜单栏 AI Agent 用量与额度大盘</strong><br />
  实时聚合账户额度 · 重置倒计时 · 重置卡库存 · 创作积分 · 本机 Token 消耗流 · Tibo 全员重置预测
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Platform-macOS%2014%2B-black?logo=apple" alt="Platform: macOS 14+" />
  <img src="https://img.shields.io/badge/Frontend-Swift%20%2F%20SwiftUI-orange?logo=swift" alt="Frontend: Swift Native" />
  <img src="https://img.shields.io/badge/Backend-Python%203.9%2B%20(Stdlib%20Only)-blue?logo=python" alt="Backend: Python 3.9+ No Third-party Deps" />
  <img src="https://img.shields.io/badge/Schema-v4-success" alt="Schema: v4" />
  <img src="https://img.shields.io/badge/Tests-266%20Passed-brightgreen" alt="Tests: 266 Passed" />
  <img src="https://img.shields.io/badge/Security-100%25%20Read--Only-red" alt="Security: 100% Read-Only" />
  <img src="https://img.shields.io/badge/Release-v0.6.0-blue" alt="Release: v0.6.0" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green" alt="License: MIT" /></a>
</p>

> 下方截图由 App 离线预览生成，所有账户、余额和用量均为虚构演示数据，不代表真实账户或全部来源的接入情况。

---

## 💡 为什么需要 AgentMeter？

在使用各类 AI 辅助编程与创作工具（Codex、Claude Code、Kimi Code、Qoder、TRAE、MiniMax、即梦等）时，你是否常遇到以下痛点：

- 📉 **用量焦虑与分散查询**：额度分散在各种网页后台、控制台或本地配置里，每次查询都要反复登录或点开多个面板；
- ⏳ **重置卡悄然过期**：好不容易领到的 5 小时卡、周重置卡还没来得及用，就已经过了有效期；
- 🚨 **额度突发告急**：编码正处于关键思路阶段，工具突然触发限流，打断专注心流；
- 💰 **会员续费与扣费遗忘**：多平台的月付、年付会员何时扣款、何时刷新积分缺乏统一跟踪；
- 📊 **缺少统一视角的本地开销账本**：不同 Agent 客户端的 Token 消耗、缓存命中率与估算费用散落各处，难以聚合。

**AgentMeter（Agent 用量）** 正是为此而生：以极低资源开销常驻 macOS 菜单栏，像**股票大盘**一样滚动轮播你的所有 Agent 核心额度，支持多级阈值告警，并在本地建立精准去重的 Token 与费用透析大盘。

---

## ✨ 核心亮点

```
┌────────────────────────────────────────────────────────────────────────┐
│  Menubar:   [Codex 82% 2h31m]  [Claude 65% 4d]  [Kimi 91% 1d]  ...   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ 点击弹出
┌───────────────────────────────────▼────────────────────────────────────┐
│ ✦ 四套界面风格面板：极简 · 原生 · 极光 · 霓虹 (AgentMeterBar)          │
│ ├─ 顶部驾驶舱：每个账户一个同心圆仪表（5 小时 / 7 天合一），一键直达应用 │
│ ├─ 账户额度：各供应商统一卡片——额度窗口、积分钱包、重置卡、续费提醒    │
│ ├─ 重置预测：Q 版 Tibo + 重置器，三家追踪站交叉的全员重置概率与倒计时  │
│ ├─ 本机消耗：CC Switch 历史 + Kimi Code 真实会话 Token 双流去重合并     │
│ └─ 应用覆盖：已检测 24+ Agent 应用的原生状态矩阵                       │
└────────────────────────────────────────────────────────────────────────┘
```

### 1. 📈 股票大盘式菜单栏行情条（Ticker）
- **Core Animation 硬件加速横向滚动**：默认平滑滚动显示「图标 + 名称 + 剩余量 + 剩余时间」，CPU 占用仅约 **0.4%**。
- **动态涨跌感**：额度百分比根据余量自动变色，当余量变动时带 ▲ / ▼ 提示（绿色代表余量充裕/恢复，红色代表被消耗）。
- **多种呈现模式自由切换**：支持滚动轮播（宽度 160/220/300 自选）、逐条翻动、最紧张额度优先、今日 Token 汇总或极简图标模式。

<p align="center">
  <img src="docs/images/ticker.gif" alt="菜单栏行情条滚动动画（浅色与深色菜单栏），使用演示数据" width="640" />
</p>

### 2. 🔔 阶梯式预警与系统通知（Notifier）
- **额度告急提醒**：剩余低于阈值（默认 20%，可选 10%/30%）、跌破 5%、耗尽时自动发送原生系统通知；
- **重置卡/积分临期提醒**：3 天内与 24 小时内即将过期的重置卡或临时积分包重点提醒；
- **订阅周期提醒**：3 天内自动续费扣款提醒、7 天内会员到期（未开启自动续费）提醒；
- **防打扰机制**：同一事件仅提醒一次，点击通知即可直接定位打开面板。

### 3. 🎨 四套界面风格，一键切换（SwiftUI + AppKit）
- **从极简到绚丽**：面板标题栏的调色板按钮或设置菜单「界面风格」随时切换，立即生效并记住选择：
  - **极简**：黑白排版，无卡片、无阴影，只在额度紧张时出现颜色；
  - **原生**：macOS 系统实色卡片与系统色，干净克制；
  - **极光**（默认）：流光底色、毛玻璃卡片与品牌色微光；
  - **霓虹**：赛博深色、彩虹描边与 HUD 角标、分段 LED 进度条，背景光效由 Core Animation 驱动，打开面板几乎不增加 CPU；
- **统一的供应商卡片**：各来源按同一顺序展示「额度窗口 → 积分钱包 → 积分更新 → 重置卡 → 续费 → Token」，额度窗口从短到长排列，倒计时按紧急程度而非品牌色着色；
- **Swift Charts 消耗分布图**：将输入、输出、缓存命中等构成以环形图直观呈现，深色/浅色模式自适应。

<p align="center">
  <img src="docs/images/themes-light.png" alt="四套界面风格对比（浅色模式）：极简、原生、极光、霓虹，使用演示数据" width="100%" />
  <img src="docs/images/themes-dark.png" alt="四套界面风格对比（深色模式）：极简、原生、极光、霓虹，使用演示数据" width="100%" />
</p>
<p align="center"><sub>从左到右：极简 · 原生 · 极光 · 霓虹（霓虹固定深色）</sub></p>

<p align="center">
  <img src="docs/images/accounts-dark.png" alt="账户额度深色界面：演示额度、重置卡和积分" width="48%" />
  <img src="docs/images/usage-dark.png" alt="本机消耗深色界面：演示 Token、费用和模型排行" width="48%" />
</p>

<details>
<summary>查看更多截图：本机消耗、应用覆盖与菜单栏行情</summary>

<p align="center">
  <img src="docs/images/usage-light.png" alt="本机消耗浅色界面，使用演示数据" width="48%" />
  <img src="docs/images/apps-light.png" alt="应用覆盖界面，使用演示数据" width="48%" />
</p>

<p align="center">
  <img src="docs/images/ticker-light.png" alt="菜单栏行情条，使用演示数据" width="100%" />
</p>

截图生成方式见 [截图说明](docs/images/README.md)。

</details>

### 4. 👥 多账号隔离支持（Multi-Account）
- 每个网页登录来源支持最多 **5 个独立账号**（如「主号」、「小号」、「工作号」）；
- 每个账号**独立成卡、独立进大盘行情条、独立计算提醒阈值**，严禁将不同账号的额度粗暴相加；
- 后端规范命名通道（首个账号保持原源名，后续账号分配 `provider#2` 并关联备注）。

### 5. 🔀 智能双流合并本机消耗（Dual-Stream Accounting）
- **历史主库**：通过只读事务与一致性连接读取 **CC Switch (Schema 20)** 历史数据库；
- **增量会话**：毫秒级解析 **Kimi Code** 本机 `~/.kimi-code/sessions/**/wire.jsonl`，提取唯一 `turn` 作用域真实 Token；
- **严密去重**：明确区分 CC Switch 路由的 `kimi-for-coding` 与独立的 Kimi Code 桌面端，相加绝不重叠；对缺少定价的记录或下界统计明确标注，绝不捏造虚假账单。

### 6. 🎨 创作类工具专属指标支持（Creative Metering）
- **MiniMax Design**：读取当前个人 Media Plan 钱包余额，精准追踪积分包失效时间与次月积分刷新倒计时；
- **即梦 (Dreamina)**：内置隐藏 Web 监控视图，定期在后台拦截自身发出的安全查询响应，直观展现会员等级、积分明细与续费倒计时。

### 7. 🔮 Tibo 全员重置预测 + Q 版重置器（Reset Forecast）
- **独立的「重置预测」标签页**：只读抓取三家第三方追踪站（Will Codex Reset、Tibo Radar、Codex Reset Monitor）公布的 ChatGPT / Codex 全员重置概率，给出 24 / 48 小时**区间 + 加权中位**，并标出各站「接近 / 分歧」；
- **Q 版 Tibo 与重置器**：大头小身的 Tibo 会随数据换表情——犯困（概率低）、等待、手按按钮（站内挂着承诺）、拍下按钮（公告时段进行中）、星星眼庆祝（追踪站刚记录到落地）；旁边的复古「重置器」屏幕显示 48 小时中位与 LED 进度条，出票口打印下一个已知时段的倒计时；
- **四套主题各有造型**：极简为黑白线稿，原生用系统色，极光是粉彩渐变与微光，霓虹是发光线框；
- **口径克制**：只汇总各站自己公布的数值，不写入账户重置时间、不进菜单栏行情条；通知只在**已公告**的时段开始 / 结束或追踪站记录到落地时触发，概率永远不弹通知；可在设置菜单一键关闭联网抓取。

<p align="center">
  <img src="docs/images/forecast-themes-light.png" alt="Tibo 重置器四套主题对比（浅色模式）：极简、原生、极光、霓虹，使用演示数据" width="100%" />
</p>
<p align="center"><sub>从左到右：极简 · 原生 · 极光 · 霓虹（演示数据，非真实预测）</sub></p>

<details>
<summary>查看完整的重置预测页</summary>

<p align="center">
  <img src="docs/images/forecast-light.png" alt="重置预测浅色完整页面：Tibo 重置器、概率区间、承诺、倒计时、各站口径与历史记录，使用演示数据" width="48%" />
  <img src="docs/images/forecast-dark.png" alt="重置预测深色完整页面，使用演示数据" width="48%" />
</p>

</details>

### 8. 🖼️ 用量报告与一键分享图（Usage Report）
- **本机消耗页一键打开报告窗口**：时间段筛选与本机消耗页共用，今日 / 7 天 / 30 天 / 全部即时联动；总览、Token 构成、按应用 / 模型 Top 排行口径逐位一致，只含本机消耗、不含账户余额。
- **四套风格横版分享卡**：极简、原生、极光、霓虹，宽度固定、高度随内容自适应；一键复制 2x PNG 到剪贴板，或直接保存为图片，适合分享到微信 / 飞书 / 小红书。
- **口径标注**：页脚标明「数据来自本机账本 · 只读聚合 · 不含对话内容」「费用为 API 等价估算」，不含凭据与对话正文。

<p align="center">
  <img src="docs/images/share-aurora-landscape.png" alt="用量报告分享卡：极光风格横版，展示 Token 总量、估算费用、Top 应用与模型，使用演示数据" width="49%" />
  <img src="docs/images/share-neon-landscape.png" alt="用量报告分享卡：霓虹风格横版，使用演示数据" width="49%" />
</p>
<p align="center"><sub>左：极光 · 右：霓虹（演示数据，非真实消耗）</sub></p>

---

## 🛡️ 安全与设计原则（Security First）

我们深知开发者对**隐私与凭据安全**的极高要求。AgentMeter 遵循以下铁律设计：

> [!IMPORTANT]
> 1. **100% 只读保障 (Strictly Read-Only)**：核心逻辑绝不包含任何买入、兑换重置卡、更改套餐、发送模型 Prompt 的操作。
> 2. **凭据零泄露 (Zero Credential Leakage)**：
>    - 网页 Session 与 API Key 仅保存在 macOS 系统的钥匙串（Keychain）中；
>    - 传输给本机后端时仅通过 loopback 内存通道（`PUT /v1/web-sessions`），不写入快照文件或日志；查询时仅发送给对应服务的官方端点；
>    - 快照与对外接口中，账号标识一律经过 SHA-256 散列并截断（`account_key`），绝不泄漏原始用户 ID。
> 3. **数据诚实性 (Honest Metrics)**：
>    - **未提供 ≠ 0**：接口未返回的字段明确标为 `not_provided`，严禁脑补为 0；
>    - **不同质不相加**：不同服务商的积分、Token、重置卡绝不机械求和；
>    - **时间精度保真**：天级精度的续费日期不伪造秒级时刻，过期日期真实呈现 overdue 状态。

---

## 📋 数据源支持矩阵

| 数据源 | 覆盖应用 / 场景 | 获取方式 | 支持指标 | 账号隔离 |
| :--- | :--- | :--- | :--- | :---: |
| **Codex** | ChatGPT / Codex CLI | 本机配置与官方端点只读解析 | 额度余量、周重置时间、重置卡库存及到期、Token 汇总 | 独立账户 |
| **Claude Code** | Claude Code CLI | 钥匙串 OAuth 令牌只读获取 | 5 小时 / 7 天窗口额度与重置时刻 | 独立账户 |
| **Kimi Code** | Kimi 编程助手 | 本机 REST + 本机 `wire.jsonl` | 周/5小时额度、Token 消耗流（turn 级精准解析） | 独立账户 |
| **Qoder CN** | Qoder 中国区 | 内嵌安全网页登录 / Cookie | 总体额度、共享额度、已用/剩余、下次重置时间 | 最多 5 账号 |
| **WorkBuddy** | WorkBuddy 腾讯协作 | 内嵌安全网页登录 / Cookie + 本机会话日志直读 | 资源包总量、剩余量、冻结积分、周期截止时间、本机 Token/费用估算 | 最多 5 账号 |
| **TRAE CN** | 字节 TRAE IDE / SOLO | 内嵌安全网页登录 / Cloud-IDE-JWT | 权益包额度汇总、已用额度、有效积分 | 最多 5 账号 |
| **MiniMax Code** | MiniMax Coding Plan | 环境变量 / 钥匙串 API Key | 周套餐余量百分比、到期时间 | 独立账户 |
| **MiniMax Design** | MiniMax 创作工作台 | 本机安全网关 `127.0.0.1:8001` | 个人钱包、积分包失效期、月积分刷新日、年费续费倒计时 | 个人 Media Plan |
| **即梦 (Dreamina)** | 剪映即梦创作平台 | 内嵌隐藏 Web 视图白名单捕获 / CLI | 会员等级、积分总额、多积分包到期、续费状态 | 最多 5 账号 |
| **DeepSeek API** | DeepSeek 开放平台 | 环境变量 / 钥匙串 API Key | 货币余额（CNY/USD 独立保留） | 独立账户 |
| **ZCode / 智谱 Coding Plan** | ZCode、GLM Coding Plan（中国区） | 内嵌网页登录捕获控制台凭据 / 钥匙串 API Key | 5 小时 / 每周额度（已用/总量）、周重置时间、MCP 月度次数 | 最多 5 账号 |
| **火山方舟 Coding Plan** | 火山引擎方舟 | 内嵌控制台登录（回放页面自身的只读 `GetCodingPlanUsage`）/ 钥匙串 AccessKey 签名 | 5 小时 / 每周 / 每月额度与各自重置时间 | 最多 5 账号 |
| **小米 MiMo API** | MiMo 开放平台控制台 | 内嵌安全网页登录 / Cookie | 账户余额（现金 / 赠送）、Token Plan 本月用量 | 最多 5 账号 |
| **阶跃星辰 (StepFun)** | 阶跃星辰开放平台 | 内嵌安全网页登录 / Cookie + 开放平台 API Key | 账户余额（充值 / 赠送）、STEP plan 5 小时 / 每周窗口或月度积分池、套餐名与到期日 | 最多 5 账号 |
| **CC Switch** | 本机多模型路由历史 | 本机 SQLite 数据库只读事务 | 今日/7天/30天/全部 Token、缓存命中率、估算费用 | 本机聚合 |
| **本机 Agent 会话账本** | Codex CLI、Claude Code、Gemini CLI、Antigravity、OpenCode、MiniMax Code、Kimi Code、ZCode、WorkBuddy、**DeepSeek Harness (dsh)** | 本机会话日志 / SQLite / zstd 会话日志只读直读（未装 CC Switch 也可读） | 今日/7天/30天/全部 Token、按模型分组、缓存命中率、估算费用 | 本机历史 |

---

## 🏗️ 架构概览

```mermaid
flowchart TD
    subgraph macOS UI ["macOS 原生前端 (SwiftUI / AppKit)"]
        MB["菜单栏股票行情 (Ticker)"]
        PN["四风格面板 (PanelView)"]
        KC["macOS 钥匙串 (Keychain)"]
        WV["即梦隐藏 Web 监听 (WKWebView)"]
    end

    subgraph Core ["本机只读采集核心 (agent_meter)"]
        SRV["HTTP 本机服务 (127.0.0.1:8769)"]
        COLL["多源调度采集器 (Collector)"]
        SNAP[".runtime/snapshot.json (Schema v4)"]
    end

    subgraph Sources ["数据源通道 (只读)"]
        S_SQL[("CC Switch 历史\nSQLite (Schema 20)")]
        S_LOG["Kimi Code 会话日志\nwire.jsonl"]
        S_GW["MiniMax 本机网关\n127.0.0.1:8001"]
        S_NET["各官方 REST 接口\n(Codex, Kimi, Claude, Qoder...)"]
    end

    MB --> PN
    KC --"PUT /v1/web-sessions (内存传递)"--> SRV
    WV --"PUT /v1/observations (白名单指标)"--> SRV
    PN --"GET /v1/snapshot (Bearer Token)"--> SRV
    SRV --> COLL
    COLL --> S_SQL
    COLL --> S_LOG
    COLL --> S_GW
    COLL --> S_NET
    COLL --> SNAP
```

---

## 🚀 快速上手

### 方式一：下载即用（推荐）

1. 从 [Releases · v0.8.0](https://github.com/Gary23333/agent-meter/releases/tag/v0.8.0) 页面下载最新的安装镜像：
   - 📦 `AgentMeter-0.8.0-macos-arm64.dmg`
2. 打开 DMG，将 `Agent 用量.app` 拖入 `Applications`（应用程序）文件夹；
3. 双击启动应用。菜单栏将立即出现小组件图标与默认行情条。
   - *App 包含独立 Python 后端，无需安装 Python、Xcode 或项目源码。各来源仍需对应客户端/登录态。*

当前使用 ad-hoc 签名，尚未做 Apple 公证；首次打开可能需要在系统设置中允许。详见 [安装说明](docs/INSTALL.md) 和 [发布说明](docs/release-v0.7.md)。安装版数据位于 `~/Library/Application Support/AgentMeter/.runtime/`。

### 方式二：从源码构建原生应用

环境要求：macOS 14.0+，Xcode / Swift 5.10+、Python 3.9+ 和固定版本的 PyInstaller。

```sh
# 1. 克隆代码仓库
git clone git@github.com:Gary23333/agent-meter.git "AgentMeter"
cd "AgentMeter"

# 2. 安装打包依赖，构建 App 和 DMG
python3 -m pip install -r requirements-build.txt
sh scripts/build-dmg.sh
```

构建产物输出至 `release/`：App、DMG 和 `SHA256SUMS`。`VERSION` 指定内部版本 0.8.0，发布标签为 v0.8.0；可用 `SIGN_IDENTITY` 指定签名身份，默认 ad-hoc。开发时可用 `AGENT_METER_HOME` 指定源码后端。

| 目录 | 内容 |
| --- | --- |
| `agent_meter/` | Python 后端 |
| `menubar/` | Swift 原生前端 |
| `scripts/` | 后端、DMG 打包和发布验证 |
| `tests/` | 自动化回归 |
| `docs/` | 共享知识、接口、研究及验收文档 |
| `examples/` | 无凭据配置示例 |
| `release/` | 本机发布产物；二进制上传到 GitHub Releases |
| `.runtime/` | 本机日志、缓存及构建中间产物，不上传 |

### 方式三：独立运行 Python 只读统计后端

后端使用 **Python 3.9+ 纯标准库** 实现，**无需安装任何 `pip` 第三方依赖**。

```sh
# 1. 采集单次快照并输出至本地
python3 -m agent_meter collect --output .runtime/snapshot.json

# 2. 仅采集本机 CC Switch 历史（跳过账户网络查询）
python3 -m agent_meter collect --local-only --output .runtime/local.json

# 3. 启动本地守护服务（默认监听 127.0.0.1:8769）
python3 -m agent_meter serve --start-kimi-server
```

> 服务启动后，认证 Token 将写入 `.runtime/api.token`（文件权限 0600，仅当前用户可读写）。所有 API 调用需在 Header 中携带 `Authorization: Bearer <本地 Token>`。

---

## 🔌 本机 API 接口速查

服务仅响应本机（127.0.0.1）请求，严禁跨域 Origin 访问。

| 接口 | 方法 | 说明 |
| :--- | :---: | :--- |
| `/v1/health` | `GET` | 检查服务运行状态与 Schema 版本（当前为 4） |
| `/v1/snapshot` | `GET` | 获取包含全部来源与应用覆盖矩阵的完整快照（默认缓存 120 秒） |
| `/v1/sources` | `GET` | 查询各个数据源的细分指标、提取范围及错误代码 |
| `/v1/coverage` | `GET` | 查询 24+ 应用在十一类关键指标上的覆盖状况矩阵 |
| `/v1/refresh` | `POST` | 强制穿透缓存立即采集最新数据并返回快照 |
| `/v1/web-sessions` | `PUT` | 前端将钥匙串中的凭据/Cookie 传入后端内存使用 |
| `/v1/observations` | `PUT` | 前端将网页抓取到的白名单结构化指标同步至后端内存 |

**Python 调用示例：**

```python
import json
from pathlib import Path
from urllib.request import Request, urlopen

token = Path(".runtime/api.token").read_text().strip()
req = Request(
    "http://127.0.0.1:8769/v1/snapshot",
    headers={"Authorization": f"Bearer {token}"}
)

with urlopen(req, timeout=30) as resp:
    data = json.load(resp)
    print("采集时间:", data["collected_at"])
    print("覆盖概览:", data["coverage_summary"])
```

---

## 🧪 自动化测试与对账验证

本项目拥有严格的质量保障体系，包含完整的单元测试、契约测试与真实对账校验器：

```sh
# 1. 运行全量单元测试（包含 277 项严格测试，零失败）
python3 -m unittest discover -v

# 2. 运行真实环境对账校验（核对 CC Switch 逐条计算与后端 SQL 一致性）
python3 -m agent_meter verify --output .runtime/verification.json
```

---

## 📝 更新日志

各版本的完整说明见 [发布说明](docs/)（`release-v*.md`）。

### v0.8.0 · 2026-10-21
- **新增「用量报告与分享」**：本机消耗页时间段筛选旁新增分享按钮，打开独立报告窗口；周期与本机消耗页联动，明细口径逐位一致，只含本机消耗、不含账户余额；四套风格横版分享卡高度自适应，一键复制 2x PNG 到剪贴板或保存为图片。详见[发布说明](docs/release-v0.8.md)。

### v0.7.0 · 2026-10-19
- **新增本机来源：DeepSeek Harness（dsh）Token 账本** —— 直读 `~/.dsh/sessions` 下的 zstd 压缩会话日志（CLI 与桌面端共用），兼容新旧两代格式并按 `(turn, step)` 去重；`reasoningTokens` 归入 `outputTokens` 拆分不双算，缓存写入按 0。**全部模型计入**（跨 deepseek-official、小米 MiMo、火山方舟等供应方），作为独立来源只进「本机消耗」页、不挂单一账户卡片；CC Switch 不导入 dsh，两不相加。详见[发布说明](docs/release-v0.7.md)。
- **内置后端升级至 Python 3.14**：发布包自带标准库 zstd 解码，dsh 来源在任何机器开箱可用，无需用户安装解压工具；接口契约不变。
- **新增研究文档**《本机候选来源复勘》：对 TRAE CN、CodeBuddy、Cursor、Cherry Studio、豆包、Kimi 家族、Qoder 家族等十多项本机数据做只读勘察并分级。

### v0.6.0 · 2026-10-15
- **新增「重置预测」标签页（Tibo 全员重置）**：只读抓取三家第三方追踪站，汇总 ChatGPT / Codex 全员重置的 24 / 48 小时概率区间与加权中位，列出站内承诺、已知时段倒计时、各站口径与已验证的重置记录；通知只按已公告事件触发。schema 升至 4。详见[发布说明](docs/release-v0.6.md)。
- **Q 版 Tibo 与重置器**：预测页顶部的吉祥物会随数据换表情，旁边的「重置器」显示 48 小时中位、LED 进度条和下一时段倒计时小票；四套主题各有造型，整页颜色改为跟随主题。

### v0.5.0 · 2026-10-15
- **新增来源：阶跃星辰 (StepFun) 开放平台** —— 内嵌窗口登录控制台读取账户余额（充值 / 赠送）与 STEP plan 用量（5 小时 / 每周窗口，或 Token Plan 的月度积分池），并显示套餐名与到期日；也可改用开放平台 API Key（按官方文档 `GET /v1/accounts`，只能读余额）。最多 5 个账号。详见[发布说明](docs/release-v0.5.md)。
- **Qoder CN 本机积分账本**：CLI 会话日志每请求带 `credits`（本机 token 字段恒为 0，不臆造），按 `request_id` 去重后折叠进 Qoder 账户卡片的「积分消耗 今日 / 近 30 天 / 全部」，**不写 tokens 指标**，绝不混入本机消耗。
- **MiniMax Design 本机 Token**：读取 Design.app 内嵌 opencode 运行时的账本，按 session ID 剔除与独立 OpenCode 库重复的拷贝会话后附着到 Design 账户卡，附模型 / agent 双分项。
- **本机消耗口径完善**：WorkBuddy 补上按模型分组、Kimi 补齐输入 / 输出 / 缓存拆项，两者首次进入「按应用 / 模型 Top」并获得价格表估算；价格表匹配先归一化（取最后一段 id、小写、`.`≡`-`），新增混元 hy4/hy3、阶跃 step-5 等 8 个刊例，仅 CNY 刊例的国产模型在 USD 表按 1/7.25 折算并标注。
- **修复**：Swift「估算费用」卡此前恒为「—」（CC Switch 估价没进合并视图）；账户额度页 token 行改读与本机消耗页同一个合并函数，不再显示 0。

### v0.4.1 · 2026-10-09
- 品牌更新：新 Logo（两圈 270° 仪表环绕 Agent 星芒）、应用包新增 `AppIcon.icns`、面板顶部标志按主题配色。

### v0.4.0 · 2026-10-09
- 本机 token 历史扩展到 10 个来源：新增 ZCode 用量库、OpenCode、WorkBuddy、Antigravity CLI，以及 Codex CLI / Claude Code / Gemini CLI / MiniMax Code 会话日志直读——**未安装 CC Switch 也能完整读取**；与 CC Switch 重叠的日期动态剔除、绝不叠加。
- API 等价费用估算（18 个模型家族默认价，USD/CNY 双币种）与菜单「API 价格表」配置页。
- DeepSeek 网页用量（近 30 天，仅展示、不计入本机消耗）。
- 加固：来源开关覆盖第二账号与本地历史、采集线程池与任务数同宽、配置 PUT 不再被长采集阻塞。

### v0.3.1 · 2026-10-09
- 顶部仪表合并：同一账户的多个窗口合成同心圆仪表。
- 火山方舟 Coding Plan 支持控制台登录（回放页面自身的只读查询，无需密钥）。
- 修复火山重置时间异常导致整卡失败、即梦多账号串卡等问题。

### v0.3.0 · 2026-10-09
- 新增 ZCode / 智谱 GLM Coding Plan、小米 MiMo API、火山方舟 Coding Plan 三个来源。

### v0.2.0 · 2026-10-09
- 本机 token 历史从 2 个来源扩展到 10 个；API 等价费用估算；DeepSeek 网页用量。

### v0.1.0 · 2026-10-09
- 首个版本：Swift 原生菜单栏应用 + 内嵌独立 Python 后端。

---

## 📄 开源许可与第三方致谢

- 本项目采用 [MIT 开源协议](LICENSE)，Copyright (c) 2026 Gary23333。
- CC Switch 衍生适配保留上游 MIT 版权声明；发布包中的 CPython 和 PyInstaller 使用各自协议。详见 [第三方声明](THIRD_PARTY_NOTICES.md)。

---

<p align="center">
  <sub>Made with ❤️ for AI Agent Power Users & Developers</sub>
</p>
