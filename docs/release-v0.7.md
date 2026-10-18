# v0.7.0 发布说明

2026-10-19 发布；App 内部版本为 0.7.0。适用于 macOS 14+、Apple Silicon（arm64）。

## 新增：DeepSeek Harness（dsh）本机 Token 账本

面板的「本机消耗」页新增一个来源：**DeepSeek Harness（CLI 与桌面端共用一套账本）**。

- **读取位置**：`~/.dsh/sessions/<项目>/<会话>/` 下的 `session*.jsonl.zstd` 会话日志。这些日志是 zstd 压缩的 JSONL，逐条记录每次模型响应。
- **两代格式兼容**：新版（v3）读 `assistant/message` 的 usage；旧版读流式 chunk 携带的 usage，并按 `(turn, step)` 保留时间戳最新的一条（同一条响应在流式过程中会先出现渐进值、最后才给出最终值），因此同一请求不会被重复计。
- **字段口径**：`inputTokens` 是**未命中缓存的新鲜输入**；`cacheReadTokens` 单独统计；`reasoningTokens` 属于 `outputTokens` 的子集，因此按 `output = outputTokens − reasoningTokens` 拆分，思考量单列而不重复计入总量；该 harness 不记录缓存写入，按 0 处理。
- **全部模型计入**：跨 deepseek-official、小米 MiMo、火山方舟等供应方，不做筛选——账本记的是这套 harness 自己的消耗，**不挂到任何单一账户卡片**，只在「本机消耗」页按应用 / 模型汇总。
- **与 CC Switch 不重叠**：CC Switch 不导入 dsh，故无需剔除日期；但仍保留与其他本机来源一致的诊断字段。
- **无需额外工具**：解压优先使用内置 Python 的标准库 zstd；若运行环境不支持，则回退到本机的 `zstd` 命令行工具；两者都没有时该项显示「未接入」而不是报错。
- 本机实测：约 100 个会话文件、去重后近 1.1 万条响应、合计约 29 亿 token；此处只展示，不同来源之间不叠加计算。

## 内置后端升级至 Python 3.14

发布包内嵌的独立 Python 运行时升级到 **3.14**，以便内置标准库的 zstd 解码能力——上面这个来源因此在**任何机器上都开箱可用**，不需要用户额外安装解压工具。后端仍为纯标准库实现，接口契约不变。

## 文档

新增《本机候选来源复勘》研究文档：对 TRAE CN、CodeBuddy、Cursor、Cherry Studio、豆包、Kimi 家族、Qoder 家族、MiniMax Agent CN 等十多项本机数据做了只读勘察，给出「可直接接 / 需逆向 / 无账本」的分级结论，供后续版本选型参考。

## 验证

- 单元回归 277 项通过（新增 11 项 dsh 测试），并在 Python 3.14 运行时下重跑通过。
- 真实对账 `verify` 中 dsh 独立重算 24 项逐位一致。
- DMG 内置后端冒烟测试通过，且已验证发布包内后端能直接读取真实 dsh 账本（走标准库 zstd 路线）。
