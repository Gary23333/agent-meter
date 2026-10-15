# 全量模型定价摸排与本地价格表

日期：2026-10-09（2026-10-15 增补见文末）。本摸排回答"现有统计的模型按 API 牌价折算要多少钱"。**API 等价估算不是订阅账单**：ZCode/Kimi/Claude 等Coding 套餐内的调用不按 API 价计费，估算仅用于横向比较量级。

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

---

## 2026-10-15 增补：第二轮摸排（联网核实刊例 + 匹配归一化）

背景：WorkBuddy 直读来源补上了按模型分组、Kimi Code 分组补上了输入/输出/缓存拆项，两者首次可被价格表估算；同时价格表匹配改为「取最后一个 `/` 后的模型 id、小写、`.`/`-` 等价」的归一化匹配（`glm-5-3-flash` 与 `account:…/GLM-5.3-Flash` 都命中 `glm-5.3-flash`）。为此重新核实了一批原「未定价」模型的官方刊例。

### 新增默认价（8 个 pattern）

| Pattern | 官方刊例（每 1M tokens：输入/缓存读/输出） | 币种 | 来源 |
|---|---|---|---|
| claude-opus-4-8 | $5 / $0.50 / $25（发布时与 Opus 5 同价；缓存读按官方 0.1×输入） | USD | [Anthropic 公告](https://www.anthropic.com/news/claude-opus-4-8)、[Finout 汇总](https://www.finout.io/blog/claude-opus-4.8-pricing-2026-everything-you-need-to-know) |
| claude-fable-5 | $10 / $1.00 / $50（缓存读 1.00，由 5.1「便宜 75%」反推） | USD | [Anthropic Fable 页](https://www.anthropic.com/claude/fable)、[平台文档](https://platform.claude.com/docs/en/models/fable-5/overview) |
| claude-fable-5-1 | $10 / $0.25 / $50 | USD | 同上 |
| minimax-m2.7 | $0.30 / $0.06 / $0.375 写 / $1.20（四项全官方） | USD | [MiniMax 按量定价](https://platform.minimax.io/docs/guides/pricing-paygo) |
| mimo-v2.6-pro | $0.435 / $0.0036 / $0.87；CNY 3 / 0.025 / 6 | USD+CNY | [MiMo 定价页](https://mimo.mi.com/docs/zh-CN/price/pay-as-you-go)、[模型页](https://mimo.mi.com/models/zh-CN/mimo-v2.6-pro) |
| mimo-v2.6-flash | CNY 1 / 0.02 / 2（官方只给人民币价；USD 侧按 1/7.25 折算并标「折算」） | CNY | [MiMo 定价页](https://mimo.mi.com/docs/zh-CN/price/pay-as-you-go) |
| hy4-preview（混元） | CNY 6 / 0.3 / 18 | CNY | 网易报道上线路价（2026-08-28）、[腾讯云 TokenHub 价目](https://cloud.tencent.com/document/product/1823/130055) |
| hy3（混元） | CNY 1 / 0.25 / 4 | CNY | 同上 |
| step-5-preview（阶跃） | CNY 7 / 0.7 / 20（2026-10-14 起缓存命中价 0.35→0.7，取新价） | CNY | [阶跃调价报道](http://m.bbtnews.com.cn/content/21/55/243344.html)、[PPIO 报价](https://ppinfra.com) |

规则补充：仅 CNY 刊例的国产模型在 USD 表按 1/7.25 折算并标「折算」（与原 USD→CNY 规则对称）。`hy4-preview-f`、`step-5-preview-free` 等 `-f`/`-free` 变体无独立刊例，被子串匹配带入口刊价（量极小：本机分别 19 万 / 1050 万 tokens），如需精确请在本机价格表单独加行。

### 仍未定价（不猜，UI 按用量列出提示补充）

| 模型 | 说明 |
|---|---|
| kimi-code/kimi-for-coding（2.4 亿 tok） | Coding 套餐内模型，无独立按量刊例（K3 有） |
| ark-code-latest（2.4 亿 tok） | 方舟 Coding Plan 按订阅计费（Lite ¥40/月起），无按量刊例 |
| mimo-v2-pro / mimo-v2.5 / mimo-v2.5-free（约 4.6 亿 tok） | [官方定价页](https://mimo.mi.com/docs/zh-CN/price/pay-as-you-go)已无 v2-pro 行，v2.5 系 2026-10-21 下线、价格列已移除；第三方聚合价不作数 |
| gpt-5.5 / gpt-5.6-sol / codex-auto-review 等 | 刊例来源冲突（$2.50/$15 与 $5/$30 并存），且在本机直读来源中合计 <1 亿 tok（CC Switch 自带估价不受影响），留空 |
| space-bunny、big-pickle、x-preview-f、qwen3.8、gemini-default | 客户端内部代号或免费层，无公开刊例 |
| LongCat-2.0 | 有官方刊例（CNY 5 / 0.10 / 20，限时折扣 2/0.04/8，[官方文档](https://longcat.chat/platform/docs/zh/api-pay-as-you-go)），但本机只出现在 CC Switch（自带估价、不消费本地价格表），不入默认表 |

### 本机估算结果变化（默认 USD 价，all 期间）

- 价格表合计 $2,547 → **$3,152.74**：Claude 直读 +$550（fable-5/-5-1、opus-4-8），WorkBuddy $13.59 → $66.38（混元/阶跃按折算价），Kimi Code $0 → $646.70（拆项补全后 k3 可价）。
- 菜单栏「本机消耗」的费用卡显示合成总数（CC Switch $7,120 + 价格表 $3,153），无定价模型按用量排序列出；按应用行与模型排行各自带金额。
