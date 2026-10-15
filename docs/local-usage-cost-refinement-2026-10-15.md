# 本机消耗：WorkBuddy 接入、模型名归一化与金额计算完善

日期：2026-10-15。用户要求：① 把 WorkBuddy 的 token 消耗接入本机消耗模块；② 完善本机消耗的模型名称与金额计算。本轮不新增来源，只补齐既有账本的模型维度与费用口径。

## 1. WorkBuddy：模型归属与本机消耗可见性

`~/.workbuddy/projects/**/*.jsonl` 的 `providerData` 除 `rawUsage` 外还带模型字段。取值顺序 `providerData.model`（厂商 id，如 `deepseek-v4.1-flash`、`hy4-preview`）→ `requestModelName`（展示拼写）→ `unknown`，缺失计数入 `unknown_model_records`。

语义核验（本机 6,701 条 rawUsage 记录）：

- `completion_tokens` 已包含思考：全部记录满足 `completion_tokens ≥ completion_thinking_tokens`，且 `completion_tokens_details.reasoning_tokens == completion_thinking_tokens`。因此 `thinking_tokens` 作为 output 的子部分单列展示，**不计入 total_tokens**（与其他来源"reasoning 另计"的口径不同但总量等价，思考都只算一次），并在指标里声明 `thinking_in_output: true`。
- `prompt_cache_write_tokens` 字段存在但全机 6,397 条 doubao 方言记录全为 0，纳入 fresh/read/write 之外的 cache_write 读取（当前不影响数字）。
- 每周期新增 `groups`（app=workbuddy，按模型 requests/fresh_input/output/cache_read/cache_write/thinking_tokens/total_tokens），分组求和与 totals 逐字段相等（单测断言 + verify 独立重算）。
- CC Switch 不导入 WorkBuddy（其 `app_type` 无 workbuddy 行，本机已验证），本来源与其无重叠、不需要剔除日。

效果：WorkBuddy 此前在本机消耗页只进总量、不进「按应用/模型 Top」也无法估价；现在三者都进。

## 2. Kimi Code：分组拆项，纳入费用估算

`kimi_tokens.summarize` 的按模型分组原先只有 `requests/total_tokens`，价格表因无拆分不估算。现将记录里本就存在的 `inputOther/output/inputCacheRead/inputCacheCreation` 聚合进每个分组（字段与 totals 同名同和），`k3`（有刊例）由此可价，`kimi-for-coding`（无刊例）保持未计价并列名。totals 数值不变。

## 3. 价格表：模型名归一化 + 新刊例 + 双向折算

- `normalize_model`：两侧（模型名与 pattern）都取最后一个 `/` 之后的 id、转小写、`.` 统一为 `-`，再精确→最长子串匹配。解决 `account:…/GLM-5.3-Flash`、`kimi-code/k3`、`custom_provider:…/mimo-v2.5-pro`、WorkBuddy 的 `glm-5-3-flash` 各说各话的问题；快照 `model` 字段保留原始拼写。
- 新刊例 8 个 pattern（混元 hy4/hy3、阶跃 step-5、claude-opus-4-8、fable-5/-5-1、minimax-m2.7、mimo-v2.6-pro/flash），来源与「仍未定价」清单见[定价摸排 2026-10-15 增补](pricing-survey-2026-10-09.md)。
- 折算规则对称化：仅 CNY 刊例的国产模型在 USD 表按 1/7.25 折算并标「折算」（原规则只做 USD→CNY）。`converted_patterns` 变为按币种取值。
- `estimate_source_cost` 每周期新增 `models: {原始模型名: 金额}`，供 UI 按模型/按应用显示金额；`unmatched_models` 语义不变。
- 变体说明：`hy4-preview-f`、`step-5-preview-free` 无独立刊例，被子串匹配带入口刊价（本机 19 万 / 1050 万 tokens，影响可忽略），文档已注明。

## 4. 菜单栏「本机消耗」金额与模型名

- 修复：CC Switch 自带 USD 估价此前没有进入合并视图，费用卡恒为「—」。现在合并 totals 携带 `estimated_cost_usd` 与 `unpriced_detail_requests`。
- 合成总数：价格表为 USD 时 `CC Switch + 价格表` 相加为标题数；价格表为 CNY 时两者分列、不跨币种相加。全零估算显示「—」，不把未知价格当零。
- 构成行（`CC Switch $7,120 · 价格表 $3,152.78 · 1519 次无定价`）与「未计价模型：…」行（按该周期 token 量排序、最多 8 个，过滤 `unknown`）。
- 按应用行与模型排行各自显示金额：CC Switch 组用自带 `estimated_cost_usd`，本地来源查来源的 `models` 金额表（组带 `source` 标记）。模型排行按「app + 归一化模型键」聚合，同一模型的不同拼写（`glm-5.3-flash` / `glm-5-3-flash`）并作一行；显示名去掉供应方前缀（`Catalog.modelLabel`，价格表「从当前统计补模型」同样改用归一化键判重）。
- 界面已用 `--preview` 全主题渲染并逐屏核对（浅色/深色 × 极简/原生/极光/霓虹）。

## 5. 验收

- 单测 207 项全过（新增 WorkBuddy 分组/思考语义、Kimi 拆项、归一化与双向折算断言）。
- `python3 -m agent_meter verify` 588 项全过，新增：WorkBuddy today/all 逐模型 60 项独立重算、Kimi 四周期 totals+分组 65 项、每个 `basis=local_price_table` cost 的金额与未定价名单独立重算 64 项。
- 本机效果（默认 USD 价，all）：价格表估算 $2,547 → $3,152.74（Claude +$550、WorkBuddy $13.59→$66.38、Kimi $0→$646.70）；「本机消耗」费用卡首次给出合成总数 $10,273.25 = CC Switch $7,120 + 价格表 $3,153。

数据边界不变：未定价 ≠ 零（全零显示「—」并列名）；API 等价估算 ≠ 订阅账单；不跨币种相加；WorkBuddy/Kimi 本机日志 ≠ 全账户用量。
