# 把「峰谷定价」移到 DeepSeek 账户卡并改为 DS 专属

## 一、需求确认

将「本机消耗」页中独立展示的「峰谷定价」卡片，移动到「账户额度」页的 DeepSeek API 卡片内，并改为只统计 DeepSeek 系模型的峰/谷数据。

已确认的三项口径：

1. **数据范围**：汇总所有本机账本（CC Switch、Claude Code、Codex、WorkBuddy、OpenCode、ZCode、dsh 等）中模型名属于 DeepSeek 的用量。
2. **时间段**：卡片内提供「今日 / 7 天 / 30 天 / 全部」切换，与「本机消耗」页共用同一个 `usagePeriod` 设置。
3. **金额拆分**：需要精确到 DS 模型的峰时/谷时金额，后端补按模型的峰/谷金额字段。

## 二、现状分析

- 峰谷卡片定义在 [UsageViews.swift](file:///Users/guanzizheng/Movies/项目/vibrcoding%20/NEW-agent%20统计/menubar/Sources/AgentMeterBar/UsageViews.swift#L333-L481) 的 `PeakPricingCard`，由 `PeriodSummary.body` 第 72 行渲染，展示全账本（所有模型）的峰/谷 token、金额与占比。
- `LocalUsage.merged`（同文件 489-623 行）已汇总：
  - `totals.peak_tokens` / `totals.offpeak_tokens`（来自各来源 groups 的 `peak`/`offpeak` 对象）；
  - `local_peak_cost` / `local_offpeak_cost`（按币种汇总，来自各来源 `cost.periods[period].peak_amount` / `offpeak_amount`）；
  - `peak_unsplit`（没有请求时刻、按谷价估算的来源）；
  - `peak_window`（后端 `agent_meter/peak.py` 的 WINDOW）。
- 后端 `agent_meter/prices.py` 的 `estimate_source_cost` 目前只写每个 period 的账户级 `peak_amount` / `offpeak_amount`，没有按模型拆分；因此前端无法只取 DeepSeek 模型的峰/谷金额。`agent_meter/verify.py` 660-707 行有对应的独立重算对账。
- DeepSeek 账户来源 `deepseek_api` 没有本地 `tokens` 指标；DS 用量分散在其他本机账本（模型名如 `deepseek-v4-pro`、`deepseek-v4-flash`、`deepseek-flash`、`custom_provider:deepseek/deepseek-v4-flash`）。`Catalog.modelKey` 已实现与后端一致归一化（去路径前缀、小写、`.`→`-`），可用于识别 DS 模型。
- `AccountCard`（[AccountViews.swift](file:///Users/guanzizheng/Movies/项目/vibrcoding%20/NEW-agent%20统计/menubar/Sources/AgentMeterBar/AccountViews.swift#L59-L80)）当前顺序为 header → quota → details → webUsage → dailyTokens；DeepSeek 卡的 `webUsage` 即「网页消耗」区。
- `PillTabs` 已支持 `small` 紧凑样式，可直接用作卡片内的时间段切换。

## 三、改动方案

### 1. 后端：`agent_meter/prices.py`

在 `estimate_source_cost` 中为每个 period 增加按模型的峰/谷金额：

- 新增两个按 period 的累加字典 `peak_models` / `offpeak_models`，键为 group 里的原始 `model` 字符串（与现有 `models` 键一致）。
- 拆分过的 group：分别累加 `peak_part`、`offpeak_part`；未拆分的 group：`peak_part = 0`，`offpeak_part` 为谷价金额。
- 只写入非零金额，值为字符串：`format(value, "f")`。
- 无 groups 的 period 也返回空的 `peak_models` / `offpeak_models`。
- 更新函数 docstring，说明新增字段用于前端只展示某一家供应商的模型。

保持现有 `amount` / `peak_amount` / `offpeak_amount` / `models` / `unsplit_models` 字段不变，不影响其他消费者。

### 2. 后端：`agent_meter/verify.py`

在 660-707 行的价格表对账循环里：

- 增加按模型的参考累加 `peak_models` / `offpeak_models`（同样的非零过滤）。
- 每来源、每 period 增加两项检查：
  - `prices.<source>.<period>.peak_models`：后端 map 的每个值转 `Decimal` 与参考 map 相等；
  - `prices.<source>.<period>.offpeak_models`：同上。
- 失败详情里同时输出 backend 与 reference。

### 3. 测试：`tests/test_prices.py`

- `test_split_group_bills_peak_and_offpeak_separately` 增加断言：
  - `period["peak_models"] == {"deepseek-v4-pro": "5.28"}`
  - `period["offpeak_models"] == {"deepseek-v4-pro": "1.32"}`
- `test_unsplit_group_prices_at_offpeak_base` 增加断言：
  - `peak_models` 为空；
  - `offpeak_models` 为 `{"deepseek-v4-pro": "0.66"}`。

### 4. 前端：`UsageViews.swift`

1. **移除独立卡片**
   - 删除 `PeriodSummary.body` 第 72 行的 `PeakPricingCard(data: data, now: now)` 调用。
   - 删除 `PeakPricingCard` 整个结构体（333-481 行）；其中的峰/谷状态判断辅助函数迁移到新视图（见第 5 点）。

2. **`LocalUsage.merged` 增加按模型峰/谷金额**
   - 将 `localPeakCosts` / `localOffpeakCosts` 两个 `[unit: Double]` 改为 `[unit: [model: Double]]`：`localPeakModels` / `localOffpeakModels`。
   - 读取每个 local_price_table 来源 `cost.periods[period]` 里新增的 `peak_models` / `offpeak_models`，按 `unit → model` 累加。
   - 输出改为 `local_peak_cost_models` / `local_offpeak_cost_models`（形如 `{USD: {model: amount}}`），删除已无人使用的 `local_peak_cost` / `local_offpeak_cost`。
   - `totals.peak_tokens` / `offpeak_tokens`、`peak_unsplit`、`peak_window` 保持不变（新 DS 视图复用）。

3. **新增 DS 专属数据聚合**（放在 `LocalUsage` 内）

```swift
struct DeepSeekPeak {
    let totalTokens: Double        // 该时间段 DS 模型总 token（含未拆分）
    let peakTokens: Double
    let offpeakTokens: Double
    let peakCosts: [String: Double]     // 币种 → 金额
    let offpeakCosts: [String: Double]
    let unsplitSources: [String]        // 无请求时刻、按谷价估算本地来源的展示名
    let hasUnsplitCCSwitch: Bool        // CC Switch 中有 DS 模型记录（自带估价不分峰谷）
    let window: JSON                    // peak_window
}

static func deepseekPeak(snapshot: Snapshot, period: Period) -> DeepSeekPeak?
```

实现规则：

- 调用 `merged(snapshot:period:)`；为 nil 时返回 nil。
- 遍历 `data["groups"]`，用 `Catalog.modelKey(model).contains("deepseek")` 判定 DS 模型。
- 有 `peak` 与 `offpeak` 对象：累加 `peak.total_tokens` / `offpeak.total_tokens`；否则该组计入未拆分总量，并记录来源：
  - `source == "ccswitch"` → `hasUnsplitCCSwitch = true`；
  - 其他来源 → `unsplitSources`（`Catalog.brand(source).name`，去重）。
- 从 `local_peak_cost_models` / `local_offpeak_cost_models` 逐币种、逐模型筛选同一 DS 规则并求和得到 `peakCosts` / `offpeakCosts`。
- `window = data["peak_window"]`。

### 5. 前端：`AccountViews.swift`

1. **挂载位置**
   - `AccountCard.body` 中 `webUsage` 与 `dailyTokens` 之间插入 `deepseekPeak`：
     - 仅 `source.baseID == "deepseek_api"` 时渲染 `DeepSeekPeakSection(snapshot: snapshot, now: now)`，不额外加 `Card`（避免卡片套卡片），仅 `.padding(.top, 2)`。

2. **新增 `private struct DeepSeekPeakSection: View`**
   - 输入：`snapshot`、`now`。
   - 状态：`@AppStorage("usagePeriod") private var periodRaw = Period.today.rawValue`，计算属性 `period`；与「本机消耗」页共用同一设置。
   - 主题：`@Environment(\.panelTheme) private var theme`。
   - 从原 `PeakPricingCard` 原样迁移并改为读取 `split.window` 的辅助成员：`intervals`、`windowNote`、`minutes(_:)`、`clock(_:)`、`nowMinutes`、`weekday`、`isWeekend`、`isOffPeak`、`hint`、`statusColor`。
   - 布局（全部位于 DeepSeek 卡内部）：
     1. 标题行：`Text("DeepSeek 峰谷定价")`（`theme.font(11.5, weight: .semibold)`，secondary）+ `Spacer` + 峰/谷状态胶囊（沿用原样式）+ 下一转换提示（9.5 tertiary）。
     2. 时间段行：`PillTabs(items: Period.allCases, title: { $0.label }, selection: binding, small: true)`，绑定 `usagePeriod`。
     3. 说明行：`Text("\(windowNote)；DeepSeek 系模型峰时 ×2")`（10.5 tertiary）。
     4. `splitRow("峰时", tokens: peak, amounts: peakCosts)`、`splitRow("谷时", tokens: offpeak, amounts: offpeakCosts)`；`splitRow` 沿用原实现（多币种按 key 排序逐行显示，空 map 显示「—」）。
     5. 当 `peak + offpeak > 0`：`Meter(fraction: offpeak / split, ...)` + 「谷时 Token 占比」+「已拆分 X / 总量 Y」。
     6. 当 `peak + offpeak == 0`：
        - 总量 > 0 → 「该时间段没有可拆分的 DeepSeek 请求时刻」；
        - 总量 == 0 → 「该时间段没有 DeepSeek 模型的本机记录」。
     7. 未拆分提示：
        - `unsplitSources` 非空 → 橙色文本「未拆分来源按谷价计入价格表估算：名称、名称」；
        - `hasUnsplitCCSwitch` → tertiary 文本「CC Switch 自带估价不分峰谷，未计入上面的价格表金额」；
        - 两条可同时出现。
   - 数据为 nil 时整段不显示（直接 `EmptyView`）。

### 6. 文档同步

- [docs/backend-api.md](file:///Users/guanzizheng/Movies/项目/vibrcoding%20/NEW-agent%20统计/docs/backend-api.md#L134) 的价格表 period 结构补充 `peak_models, offpeak_models`（按原始模型名的峰/谷金额字符串 map）。
- [README.md](file:///Users/guanzizheng/Movies/项目/vibrcoding%20/NEW-agent%20统计/README.md#L124) 的「峰谷计价视图」描述改为：位于账户额度页 DeepSeek 卡内，只统计各本机账本中的 DeepSeek 系模型。

## 四、假设与决策

- 「DS 专属」判定用 `Catalog.modelKey(model)` 是否包含 `deepseek`，与后端价格表归一化规则一致；用户把非 DS 模型绑定到 DS 价的情况不在本卡片中额外追踪。
- 峰/谷金额仅来自 `local_price_table` 来源（与现有口径一致）；CC Switch 自带 USD 估价依旧不分峰谷，不并入金额行，只给文字提示。
- DeepSeek 卡未接入（无余额指标）时不会出现在「账户额度」，因此该区也不显示；不额外在账户页单独挂载峰谷卡。
- 不修改 `ReportModel` / 分享卡 / 价格表窗口（`PricesWindow` 的峰时倍率列保持不变）。
- 不做版本号或发布说明更新（除非用户另行要求）。

## 五、验证步骤

1. 后端回归：
   - `python3 -m unittest tests.test_prices -v`
   - `python3 -m unittest discover -v`（确认 `verify` 相关测试不受影响）
2. 后端对账（运行时可用时）：`python3 -m agent_meter verify`，确认新增 `peak_models` / `offpeak_models` 检查通过。
3. Swift 构建：在 `menubar/` 下执行 `swift build`。
4. 离线渲染检查：
   - 用 `.runtime/real-snapshot.json` 复制一份临时快照，注入可用的 `deepseek_api` 余额指标，以及一个带 `peak`/`offpeak` groups 与 `peak_models`/`offpeak_models` 的本地来源，保存为 `.runtime/peak-preview.json`（仅本地临时文件，不提交）。
   - `.build/debug/AgentMeterBar --preview .runtime/peak-preview.json .runtime/preview-peak`
   - 检查 `accounts-light.png` / `accounts-dark.png`（aurora）及一个霓虹或棱镜主题截图：确认峰谷区在 DeepSeek 卡内、420px 宽度不溢出、时间段切换可见、金额与占比正确；确认「本机消耗」页不再出现峰谷卡片。
5. 清理临时快照与预览图（或保留在已忽略的 `.runtime/` 下）。
