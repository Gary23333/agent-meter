# v0.8.1 发布说明

2026-10-21 发布；App 内部版本为 0.8.1。适用于 macOS 14+、Apple Silicon（arm64）。

## 修复：MiniMax Code 的模型名与费用

MiniMax Code 桌面端的用量表把 `model` 留空，而 CC Switch 又把这些代理请求记成 `model="unknown"`，因此「本机消耗」页里 MiniMax Code 的消耗既没有模型名，估算费用也一直是 0。

- **按请求还原模型**：从会话消息的 `context_usage_telemetry.model` 按 `(session_id, turn_id)` 取当次响应的真实模型，不做会话级猜测。
- **跨来源精确对齐**：CC Switch 的 `mcode:<session>:<row id>` 请求号可直接对到本机账本的同一行，仅对模型为空的 mcode 记录回填，其余来源与已有费用一律不动。
- **两处口径同时生效**：直读账本（CC Switch 未覆盖的日期）与 CC Switch 通道（已覆盖的日期）都能显示模型名，不再出现同一份消耗一处有名字、一处是 unknown。

## 新增：MiniMax M3.1 Flash 定价

- USD：输入 `$0.15` / 缓存读 `$0.015` / 输出 `$0.60`（每百万 token）。
- CNY：输入 `1` / 缓存读 `0.1` / 输出 `4` 元（每百万 token）。
- 匹配取最长模式，`MiniMax-M3.1-Flash` 与 `-Preview` 都按此档计价，不再被旧的 `minimax-m3` 抢先匹配。
- CC Switch 自己已给出非零费用的记录保持原值；只有费用为 0 且模型已解析的 mcode 记录才用本机价格表补估算，且仅在 USD 口径下补，避免混币。

## 验证

- 单元回归 279 项通过（新增 3 项：逐轮模型还原、CC Switch 回填与补价、M3.1 匹配优先级）。
- 实测本机快照：今日 MiniMax Code 组由 `unknown` / `$0` 变为 `MiniMax-M3.1-Flash` / 1.702 亿 token / 约 `$2.82`；近 7 天 `MiniMax-M3.1-Flash-Preview` 3.64 亿、`MiniMax-M3.1-Flash` 2.73 亿均可读。
