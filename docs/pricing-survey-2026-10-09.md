# 全量模型定价摸排与本地价格表

日期：2026-10-09。本摸排回答"现有统计的模型按 API 牌价折算要多少钱"。**API 等价估算不是订阅账单**：ZCode/Kimi/Claude 等Coding 套餐内的调用不按 API 价计费，估算仅用于横向比较量级。

背景：此前唯一的费用数字来自 CC Switch 自带的 USD 估价（它库里的 `total_cost_usd` 列）；ZCode/OpenCode/WorkBuddy/Kimi/Antigravity 及四家直读 CLI 来源没有任何费用。本轮新增本地价格表（`agent_meter/prices.py`，默认价 + 用户可改 + USD/CNY 双币种），对这些来源的 token 分组做 API 等价估算。

## 模型清单（本机九个本地来源，51 个模型）

### 有公开刊例价、已内置默认值的（18 个 pattern）

| Pattern | 覆盖的本机模型 | USD 刊例（每 1M tokens：输入/缓存读/输出） | 来源 |
|---|---|---|---|
| glm-5.3-flash | builtin/account:…/GLM-5.3-Flash、glm-5.3-flash | $0.15 / $0.03 / $0.50（Z.ai）；CNY 刊例 0.8/0.23/2.8 元 | [智谱定价](https://docs.bigmodel.cn/cn/guide/start/pricing)、[qcode.cc](https://qcode.cc/glm-5-3-flash-pricing) |
| glm-5.3 | …/GLM-5.3 | CNY 刊例 8/–/28 元；USD 折算 1.10/–/3.90 | [智谱定价](https://docs.bigmodel.cn/cn/guide/start/pricing)、[SegmentFault 实测](https://segmentfault.com/a/1190000048258886) |
| k3 | kimi-code/k3、k3-256k | $3.00 / $0.30 / $15.00 | [Moonshot 定价](https://platform.kimi.ai/docs/pricing/chat)、[BenchLM](https://benchlm.ai/moonshot/api-pricing) |
| deepseek-v4-pro | deepseek-v4-pro | $0.66 / $0.022 / $1.98（谷时；峰时×2） | [DeepSeek 官方](https://api-docs.deepseek.com/quick_start/pricing) |
| deepseek-v4.1-flash / deepseek-v4-flash / deepseek-flash | deepseek-v4.1-flash…、deepseek-v4-flash | $0.15 / $0.003 / $0.60（谷时；旧名按 Flash 计价） | [DeepSeek 官方](https://api-docs.deepseek.com/quick_start/pricing) |
| gemini-3.7-flash / gemini-3.8-flash | gemini-3.7/3.8-flash | $0.75 / $0.075 / $3.75（3.7 为刊例；3.8 沿用 3.7，待官方更新） | [Google 定价](https://ai.google.dev/gemini-api/docs/pricing) |
| gemini-3-flash | gemini-3-flash-preview/-a/-medium-a、gemini-default | $0.30 / $0.075 / $2.50（Flash 档） | [Google 定价](https://ai.google.dev/gemini-api/docs/pricing) |
| gemini-3.1-pro | gemini-3.1-pro-preview | $2.00 / $0.50 / $12.00 | [Google 定价](https://ai.google.dev/gemini-api/docs/pricing) |
| claude-opus-5-5 | claude-opus-5-5 | $4 / $0.20 / $20 | [Anthropic 定价](https://platform.claude.com/docs/en/about-claude/pricing) |
| claude-opus-5 | claude-opus-5 | $5 / $0.50 / $25 | 同上 |
| claude-sonnet-5 | claude-sonnet-5/-5-5 | $2 / $0.10 / $10 | 同上 |
| claude-haiku-5 | claude-haiku-4-5-20251001 之外的 haiku-5 档 | $0.10 / $0.01 / $0.50（Haiku 5.5 刊例） | [Anthropic 公告](https://www.anthropic.com/claude-haiku-5-5) |
| claude-haiku-4-5 | claude-haiku-4-5-20251001 | $1 / $0.10 / $5 | [Anthropic 定价](https://platform.claude.com/docs/en/about-claude/pricing) |
| mimo-v2.5-pro | mimo-v2.5-pro | $0.435 / $0.0036 / $0.87；CNY 刊例 3/0.025/6 元 | [MiMo 定价](https://mimo.mi.com/docs/zh-CN/price/pay-as-you-go)、[调价公告](https://mimo.mi.com/docs/zh-CN/news/latest/v2.5-price-update) |
| minimax-m3 | MiniMax-M3 | $0.30 / – / $1.20（≤512k 永久五折价） | [MiniMax 定价](https://platform.minimax.io/docs/pricing/overview) |

CNY 默认值规则：有国内刊例的用刊例；仅 USD 刊例的按 7.25 汇率折算并在配置页标"折算"。峰谷价（DeepSeek）默认取谷时价，可在配置页改。

### 未能定价的（不猜，留空待用户填写）

| 模型 | 出现量级 | 说明 |
|---|---|---|
| unknown（codex/minimax_code/antigravity 部分行） | 44.5 亿 tok | Codex 会话文件的 token 事件不带模型名（session_meta 级归属已在实现中说明）；mcode/agy 少量行模型名缺失 |
| claude-fable-5 / -5-1、claude-opus-4-8 | 3.5 亿 tok | 未见公开刊例（fable 系列与 opus-4-8） |
| ark-code-latest（火山方舟） | 2.2 亿 tok | 方舟 ark-code 打包价未公开刊例 |
| mimo-v2-pro / v2.5 / v2.6-pro | 6.7 亿 tok | 仅 v2.5-pro 有公开调价公告；v2.6 系新价未查到 |
| gpt-5.6-sol / gpt-5.6-luna、x-preview-f-free、space-bunny-free、big-pickle、qwen3.8、gemini-3.6-flash | 合计 <1.2 亿 tok | 未查到刊例；名字含 free 的疑似免费模型（未知≠零，仍留空） |
| <synthetic> | 0 tok | Claude Code 内部合成消息，无消耗 |

## 本机估算结果（默认 USD 价，all 期间）

- ZCode 全部历史约 5.0B tokens ≈ **$751**（约 94% 为 GLM-5.3-Flash 牌价折算；ark-code-latest 无价未计，status=partial）
- 其余来源的估算显示在菜单栏"本机消耗"标签页的费用卡片（按币种分行，与 CC Switch 自带的 USD 估价分列展示）。

价格表入口：菜单 → API 价格表（本机估算）…。修改保存后自动重新估算。匹配规则：先精确、再最长子串（如 `builtin:bigmodel-coding-plan/GLM-5.3-Flash` 命中 `glm-5.3-flash`）。无分项构成的来源（如 Kimi 只有总量分组）不做估算，避免把未知拆分当成零价。
