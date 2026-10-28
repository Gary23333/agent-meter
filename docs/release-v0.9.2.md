# v0.9.2 发布说明

2026-10-28 发布；App 内部版本为 0.9.2。适用于 macOS 14+、Apple Silicon（arm64）。

## DeepSeek 网页用量与单日窗口

- DeepSeek 账户卡在余额下方新增「网页消耗」区：今日、近 3 天、近 7 天的金额、Token 与请求数，另附最近 7 个有消耗日的金额柱图；近 30 天合计继续保留。
- 后端网页用量契约新增 `windows{today,3d,7d,30d}`，按北京时间日历日（含今天）计算；该数据仍只作展示，不计入本机消耗。

## 峰谷定价与本机消耗视图

- 按 DeepSeek 官方口径实现峰谷计价：北京时间工作日 09:00–12:00、14:00–18:00 为峰时（峰时价 = 谷时价 ×2），周末全天谷时；中国法定节假日未内置日历，按工作日保守处理。
- 所有带逐请求时间戳的本机账本（dsh、Codex、Claude、Gemini、MiniMax Code、Antigravity、ZCode、Kimi/Kimi 桌面端、OpenCode/Design、WorkBuddy）在周期汇总与按模型分组中新增 `peak` / `offpeak` 分项，并保持「峰 + 谷 = 父级」。
- 「本机消耗」页新增峰谷定价卡片：当前状态、峰/谷 Token 与金额、谷时占比、已拆分比例；无时间戳或只有日汇总的 CC Switch 按谷价计入价格表估算，并在卡片中点名说明。
- 价格表新增峰时倍率（默认 DeepSeek 系 2×，可在「模型与计费」逐行修改）；拆得开的按峰/谷分别计价，拆不开的按谷价，未知价格仍然不是零。

## 全量官方定价复核

- 逐家核对 39 个内置 pattern 的官方刊例，并按官方页面更新 4 项：GLM-5.3 CNY 缓存读、Gemini 3 Flash、MiniMax M3 CNY、MiMo v2.6 Flash USD。
- 新增 8 个有官方按量价的 pattern：Claude Mythos 5 / 5.1、GPT-5.3-Codex、GLM-5.3-FlashX、MiMo v2.6 Pro UltraSpeed、Step 3.7 Flash、MiniMax M2.7 HighSpeed、Gemini 4 Argon；无法核实的型号保持未定价，不猜价。
- 修复 CNY 价格表：官方人民币刊例优先于 models.dev 的美元折算值，避免国内价被跨币种换算覆盖。

## 其他来源与加固

- 新增 Kimi 桌面端 Agent 模式 Token 账本（`kimi_desktop`），与 Kimi Code CLI 账本按会话与逐条记录比对零重叠，只进「本机消耗」。
- MiniMax MCP 探针迁移到正式 `http://127.0.0.1:18810/mcp`，仅做 initialize / tools/list 元数据读取，不启动旧 stdio 进程。
- 新增 Qoder BYOK、Kimi 桌面端、Harness 钥匙串等只读研究文档与回归测试。

## 签名与公证

- App 使用 Developer ID Application 签名，启用 hardened runtime 与安全时间戳；内嵌 Python 后端及其 Mach-O 文件逐个签名。
- App 与 DMG 均提交 Apple notarytool 公证并装订，正常双击即可打开，无需在隐私与安全性中手动放行。

## 验证

- Python 3.14 全量 303 项单元测试通过。
- `agent_meter verify` 2,132 项检查通过；其中峰谷金额对账 80 项、`peak + offpeak = 父级` 不变量 1,213 项全部通过。唯一失败为既有的 `codex_local.ccswitch_cross` 漂移，与本版本改动无关。
- Swift debug 构建、Developer ID release 构建、公证与 DMG 打包完成；浅色/深色账户页与本机消耗页渲染检查通过。
