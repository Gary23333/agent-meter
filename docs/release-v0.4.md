# v0.4 发布说明

2026-10-09 发布；App 内部版本为 0.4.0。适用于 macOS 14+、Apple Silicon（arm64）。

本版把 v0.3.x 的账户来源扩展与并行的"本机消耗全覆盖"工作合并为一个大版本：

- **本机 token 历史从 2 个来源扩展到 10 个**：新增 ZCode 本机用量库（附着在 ZCode 账户卡上）、OpenCode、WorkBuddy、Antigravity CLI（agy，protobuf 解码）独立来源，以及 Codex CLI / Claude Code / Gemini CLI / MiniMax Code 会话日志直读——**未安装 CC Switch 的电脑也能完整读取这四家历史**；与 CC Switch 重叠的日期动态剔除、绝不叠加。菜单栏"本机消耗"标签页汇总全部账本，无 CC Switch 也可显示。
- **API 等价费用估算**：内置 18 个模型家族默认价（USD/CNY 双币种，[定价摸排](pricing-survey-2026-10-09.md)），菜单新增「API 价格表」配置页；带分项的本地来源显示估算费用，未匹配模型如实标注 partial。
- **DeepSeek 网页用量**：连接页可存网页 userToken，余额卡片展示近 30 天消耗（仅展示，不计入本机消耗）。
- **加固与性能**：修复应用内关闭来源后第二账号、Kimi 本地 token 历史与即梦 observations 仍被采集的问题；Qoder SDK 缓存残留自愈；采集线程池与任务数同宽（最坏刷新约 60s → 20s）；配置 PUT 不再被长采集阻塞；stale 恢复保留新采集的本地 tokens。
- 保留 v0.3 的全部内容：四套面板主题、驾驶舱仪表、ZCode / MiMo / 火山方舟 Coding Plan 账户来源、动态行情条。
- 回归 172+ 项单测、真实对账 377+ 项检查全部通过。

安装方式与之前相同（见 [INSTALL](INSTALL.md)）。二进制见 GitHub Release `v0.4.0`。
