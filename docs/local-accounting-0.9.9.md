# Agent 用量 0.9.9 后端与本机统计

## 一次刷新如何得到面板数字

| 层 | 代码入口 | 输入与输出 |
| --- | --- | --- |
| 采集调度 | `agent_meter/cli.py`、`collector.py` | CLI 与回环 HTTP 共用 SnapshotService。账户查询与本机账本并行。纯本地模式只运行文件与数据库采集，仍执行来源开关。 |
| 账户 | 各供应商适配器 | 上游返回额度、重置、钱包和订阅时间。Codex 官方累计用量与本机 rollout 分开保存。相同应用的多个账号保留独立来源。 |
| 本机 | `cli_sessions.py`、各 `*_tokens.py`、`zcode_local.py` | 各适配器将原始请求转换为可累加分项，计算北京时间今日、滚动 7 天、滚动 30 天、全部及逐日用量。 |
| 迁移历史 | `imported_history.py` | 读取项目自有 JSON。逐请求历史可按时刻定价，日汇总单列。迁移时已做过补日和补差，运行时保留这份历史。 |
| 费用与归属 | `prices.py`、`applications.py` | 按应用、原始模型、峰谷和价格表币种计算 API 等价估值。应用周期合计保留直读与导入来源，便于追溯。 |
| API 与缓存 | `collector.py`、`server.py` | 快照、覆盖与来源读取同一份结果。账户失败时可保留已标记的旧额度，新的本机读数及估价按本次采集时间呈现。 |
| 会话 | `activity.py`、`GET /v1/activity` | 独立查询最近窗口，按应用标识与覆盖行关联。取活动证据和明确的回合或调用状态，单独轮询。 |
| 界面与报告 | Swift 的 Snapshot、ActivityView、LocalUsage 和 ReportData | 应用页显示已安装客户端、账本、会话与覆盖；账户页使用同一应用投影。本机消耗与分享报告共用分组费用。 |

## 账本边界

| 应用 | 本机证据与处理 |
| --- | --- |
| Codex | 当前和归档目录的普通或压缩 rollout。按回合模型归因，首个请求优先使用其本次用量，后续从累计计数取增量。计数器提供总量时，以它区分含推理输出与独立推理。只有总量的部分记为 `unclassified`。普通会话读取 threads 索引；内置生图按调用和图片单独计量。 |
| Claude Code / 桌面 local-agent | 同一请求的流式修订取最终记录，缺 requestId 时依次使用消息 ID、UUID、文件内行号。桌面与 CLI 共用这一本地用量口径。 |
| Gemini CLI、MiniMax Code | Gemini 按消息去重，缺 ID 的行仅在本文件内标识。MiniMax 的运行库按请求计数，缓存随数据库或 WAL 更新。 |
| Antigravity | CLI 与桌面库按会话 UUID 选一份，读取已提交事务。输出总量已包含推理，分项按普通输出和推理分别显示。 |
| Kimi Code / Kimi 桌面端 | 各自读取 Agent 的 `usage.record` 回合记录。普通桌面聊天缺少此类账本。 |
| ZCode、WorkBuddy、DeepSeek Harness | 分别读取请求尝试表、响应 usage、按回合与步骤去重的压缩日志。WorkBuddy 的思考分项已含在输出内。 |
| OpenCode / MiniMax Design | 两个运行库共享消息用量解析，Design 排除独立库已拥有的会话。媒体生成的积分不进入 Token 合计。 |
| Qoder、网页控制台及预测 | Qoder 本机积分、控制台账单和外部重置预测各有自己的来源。 |

历史归因保留迁移时的粒度。已导入的日汇总缺少逐请求标识，后来恢复或复制旧日志时，无法逐请求证明它与历史补差的交集。应用详情分别列出这两部分。近期活动窗口中的 Token 已属于对应账本，会话行不再加进应用合计。

## 验证入口

```sh
python3.14 -m unittest discover -v
swift test --package-path menubar
python3.14 -m agent_meter verify --local-only --output .runtime/verification.json
```

`verify` 对照逐日合计、模型分组、来源与应用归属、峰谷分项和费用，并独立读取 Codex rollout 的上游总量。各 CLI 的分项重算仍会复用相应的记录解析器，关键格式分支另有可手算样例。真实账户的额度和付费端点需要该账户自身的授权才能验收。

## 0.9.9 发布验收

Python 回归 377 项、Swift 测试 15 项全部通过。从公证镜像替换 0.9.8 并启动后，安装版快照通过了 2,906 项校验，失败及待定均为零。

在菜单栏展开应用卡片，按同一刷新时点将今日与累计 Token、直读与迁移历史分项对照本地 API。最近 24 小时的活动按来源与原始会话 ID 核对，包含普通 Codex 会话和内置生图活动。另以残留的安装目录验证 Agent Launcher 已从发现规则中移除。
