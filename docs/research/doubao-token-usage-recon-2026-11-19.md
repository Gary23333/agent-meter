# 豆包 / 豆包工作 Token 与额度可采集性勘察（2026-11-19）

勘察日期：2026-11-19（Asia/Shanghai）。范围为「豆包个人聊天」与「豆包工作」（豆包 2.36.10 内置入口）。本机部分只读；额度接口部分经用户明确授权，用本机登录态发送了少量只读 POST，未修改任何数据，未在源码或报告中保留 cookie/token 明文。本机账号的额度数值只保留到足以证明契约的程度。

## 结论速览

| 对象 | 真实 Token | 额度 / 点数 | 依据 |
|---|---|---|---|
| 豆包个人聊天（App/Web） | **不可得** | **可得**：套餐点数、已用百分比、窗口重置时间 | 本机无 token 账本；网页接口 `usage` 为占位值；额度接口已实测 |
| 豆包工作·个人 | **不可得** | **可得（与豆包订阅共用额度体系）** | 客户端只展示「AI 额度」「5 小时 / 7 天滚动用量」，单位为点 |
| 豆包工作·企业 | **不可得** | **可得（管理员后台，点数）** | 企业后台「AI 使用管理」导出的是权益点数，不是 Token |
| 火山方舟 API / Agent Plan | **可得**（`Unit=Tokens`） | 可得（套餐内 / 套餐外） | `GetUsageDetails`、`GetSeatUsageDetails`、`GetInferenceUsage`，AK/SK 鉴权 |

一句话：**豆包和豆包工作对外只暴露「额度点数 / 百分比」，不暴露 Token；只有火山方舟的调用才有真实 Token。**

## 数据边界

沿用项目铁律：

- 应用 ≠ 计费账户：本机只代表这台机器看到的客户端行为。
- 本机日志 ≠ 全账户用量：豆包聊天与豆包工作的用量都在云端。
- 点数 ≠ Token：额度点数是模型、工具、云端资源的综合计价，不能反推 Token，也不能与 Token 相加。
- 未知 ≠ 零：本机没有账本只能说明「本机无记录」，不能说明「没用过」。
- 不臆测：`window_type` / `item_type` 的窗口含义在只有单个窗口样本时不做猜测。

## 一、本机证据（只读）

本机安装 `Doubao.app 2.36.10`，豆包工作是内置入口（`Contents/Helpers/Doubao Browser.app/.../local_webcontents/apps/doubao-office`），没有独立安装「豆包工作」客户端。

### 1. 豆包工作本地 agent 会话

路径：`~/Library/Application Support/Doubao/Default/.doubao/agent_mode/workspace/`

- `.sessions/`：30 个会话目录、50 个 `trajectory.jsonl`，覆盖 2026-09-09 → 2026-11-19，共 4,759 条记录。
- 轨迹字段只有 `role`、`content`、`tool_calls`、`tool_call_id`、`image_link_list`，**没有** `usage`、`input_tokens`、`output_tokens`、`points`、`quota`。
- 50 个 `findings.jsonl` 全为 0 字节；30 个 `board.md` 只有表头；`assignment.md`、`briefing.md`、`MEMORY.md` 均无用量字段。
- `conversation/*/background_history_task/index.json` 只有 `taskId`、`toolCallId`、`status`、`exitCode`、`command`、`outputFilePath`，没有「本次消耗点数」。

结论：本地能采到**会话活动**（会话数、轮次、工具调用），采不到 Token，也采不到点数。

### 2. 浏览器存储

- `Local Storage/leveldb`：只有 `daily_credits_tooltip_data`（提示气泡展示次数）、`legacy_user_quota_cost_tip`、`quota_exhausted`、`common.context.membershiplevel`（会员等级），都不是消耗账本。
- `IndexedDB/chrome_doubao-chat_0`：约 2,025 个键，未发现 `usage` / `token` / `points` / `quota` 键。
- `IndexedDB/chrome_doubao-general-agent-cot_0`：无用量字段。
- `Session Storage`：只有 `/member/quota-package` 这类页面路由参数。
- `Tea/tea.db`：26 类事件，唯一与 token 相关的是事件参数里的 `max_tokens:25000`（上限值），没有实际消耗；但事件中出现了 `/alice/commerce/sale/subscription/quota/summary/` 路径，印证客户端确实调用该接口。
- `sdk_storage/.../messages.db`、`im.db`：文件已加密，SQLite 报 `not a database`，无可读表结构。
- `agent_infra/`：只有 `shell_selection` 与任务输出；`task_outputs` 里的 `input_tokens` 来自用户项目自己的 DDL，与豆包无关。

结论：本机没有豆包/豆包工作的逐次或按日 Token/点数账本，额度只存在于服务器端页面与接口。

## 二、官方与公开资料

### 1. 豆包聊天不返回真实 Token

- 公开逆向项目 `LLM-Red-Team/doubao-free-api` 明确注明：豆包后端不提供 token 计数，OpenAI 兼容响应里的 `usage` 固定为 `{prompt_tokens:1, completion_tokens:1, total_tokens:2}`，不代表真实用量。
- 《豆包付费服务协议》只承诺在客户端或网页查看「当月额度消耗统计数据」，没有 Token 查询承诺。
- 未发现任何官方个人 Token 用量查询接口。

### 2. 豆包工作的计费单位是点数

- 官方《豆包团队订阅、企业订阅额度消耗说明》：按模型、工具、云端资源综合计算点数；会议总结 0.5 点/分钟、企业知识问答 20 点/次等。
- 个人订阅文档：客户端左下头像 →「额度状态」查看 AI 额度消耗进度、重置/到期时间；有豆包订阅时显示 5 小时或 7 天滚动用量；另有「近 7 天额度消耗」入口。
- 企业后台「AI 使用管理」支持按成员、部门、应用查询用量并导出，但单位仍是权益点数。
- 未找到企业「AI 使用管理」的公开 OpenAPI。

### 3. 火山方舟是唯一真实 Token 路线

- `GetUsageDetails`：个人版 Agent Plan，AK/SK 签名，返回 `Usage + Unit=Tokens/Images + BillingType`。
- `GetSeatUsageDetails`：企业版 AgentPlanTeam 席位，按席位返回 Tokens。
- `GetInferenceUsage`：按日期、模型、Endpoint、ApiKeyID 查推理 Token 与请求数。
- 三者只覆盖火山方舟的模型调用，**不覆盖豆包 App 聊天和豆包工作客户端**。

## 三、额度接口契约（本机实测）

客户端 JS 中定位到 `AGWGetSubscriptionQuotaSummary`、`AGWGetQuotaBalanceDetail`（`.../ai-views/static/js/23247.js`），并通过本机登录态只读验证。

### 1. 公共约定

- Base：`https://www.doubao.com`
- 鉴权：仅 Cookie（实测无需额外签名头）；公共头至少 `Content-Type: application/json`、`Agw-Js-Conv: str`
- 公共 query 含 `aid`、`real_aid`、`pkg_type`、`web_id`、`device_id`、`region` 等客户端参数
- Cookie 来源：`~/Library/Application Support/Doubao/Default/Cookies`，`meta version=24`，doubao.com 的 cookie 为 Chromium `v10` 信封；钥匙串候选 service 为 `Doubao Safe Storage` / `Doubao Browser Safe Storage` / `Chrome Safe Storage`

### 2. 额度汇总

```http
POST /alice/commerce/sale/subscription/quota/summary/
{"product_line":"membership"}
```

实测：`200`，`code=0`，`data` 顶层键：

- `current_subscription`
- `member_info`
- `window_limit_section`
- `enterprise_window_limit_section`
- `incentive_quota_section`
- `enterprise_package_entitlement_groups`
- `enterprise_subscription`
- `switch_data`

`window_limit_section` 结构：

- `entitlement_count`、`usage_exhausted`
- `window_limit_groups[]` → `feature_group`、`feature_group_name`、`window_limits[]`
- 每个窗口：`start_time`、`end_time`、`total_amount`（字符串）、`used_amount`（字符串）、`used_percent`（整数）、`less_than_one_percent`、`item_type`、`window_type`

本机实测该账号只返回 1 个窗口（`used_percent=4`），因此**不能仅凭一次样本断定 `window_type` / `item_type` 与 5 小时 / 7 天 / 月的对应关系**；实现时必须按实际返回值映射，映射不出来就不标注窗口名。

递归检查整个响应，**没有任何 key 含 `token`**。

### 3. 额度余额明细

```http
POST /alice/commerce/sale/subscription/quota_balance/detail/
{"product_line":"membership"}
```

实测：`200`，`code=0`；`data` 含：

- `total_remaining_amount`
- `summaries[]`：`category`、`remaining_amount`、`title`
- `groups[]`：`category`、`title`、`items[]`
- `items[]`：`category`、`display_name`、`end_time`、`time_type`、`total_amount`、`used_amount`、`used_percent`

本机实测 `used_amount=425`、`used_percent=4`，标题为「套餐」。同样**没有 Token 字段**。

### 4. 用量流水

```http
POST /alice/commerce/usage/timeline/
{"category":1,"cursor":"","page_size":20}
```

实测：`category=1` 返回 `200/code=0`；`data` 含 `categories`、`category_tabs`、`consumption_column_title`、`entries[]`、`has_more`、`next_cursor`、`window_start_time_ms`、`window_end_time_ms`（窗口约 30 天）。单条 `entry`：

- `entry_type`
- `usage`：`display_name`、`item_id`、`model_display_name`、`occurred_at_ms`、`quota_source{display_name, display_text, quota_source_code}`

这是按模型 / 额度来源的流水，**没有 Token 数量**；`category=0` 返回 `710010202 unsupported usage category`。分类中文含义未在响应中显式给出，需要更多样本才能定名。

### 5. 豆包工作的 product_line

- `{"product_line":"doubao_office"}` 实测 `200/code=0`，但 `data` 基本为空（`usr_type=0`、无企业订阅、窗口额度为空）。
- `{"product_line":"membership"}` 实测有完整个人订阅额度。
- 结论：本机账号的豆包工作入口使用的是**豆包订阅（membership）**额度；`doubao_office` 可能只在企业 / 工作版权益下才有数据，本机无法验证。实现时不要把 `doubao_office` 的空响应当成「零用量」。

## 四、可落地的采集范围

### A. 可做：豆包账户额度卡（不写 Token）

- 来源 `doubao`（账户 scope），读 `quota/summary` + `quota_balance/detail`，`product_line=membership`。
- 展示：套餐额度总量、已用点数、已用百分比、剩余额度、窗口重置 / 到期时间。
- 指标用 `credits` / `quota`，**不写 `tokens`**，不进入「本机消耗」页，不参与 Token 合计。
- 豆包工作若与豆包订阅共用额度，可合并为同一张卡；企业额度需另测 `enterprise_window_limit_section` / `enterprise_package_entitlement_groups`。
- 错误码建议：`doubao_not_authenticated`、`doubao_quota_unavailable`、`unsupported_doubao_contract`。

### B. 可做但非用量：豆包工作会话活动

- 读 `.doubao/agent_mode/workspace/.sessions`，可统计会话数、agent 数、轮次、工具调用次数与最后活动时间。
- 只能进「会话活动」，不能进 Token / 费用；口径要明确写「活动 ≠ 用量」。

### C. 可做：火山方舟真实 Token（独立来源）

- 只覆盖方舟 API / Agent Plan，不覆盖豆包 App 与豆包工作。
- 需要 AK/SK；`GetInferenceUsage`（API Key 推理）、`GetUsageDetails`（个人版 Agent Plan）、`GetSeatUsageDetails`（企业版席位）。
- 应作为独立来源 `ark_usage`，与豆包额度卡分开，不混算。

### D. 不可做：从本机或聊天内容反推 Token

- 本机没有账本；网页 `usage` 是占位值；按文本长度估算 Token 不符合项目「不臆测」原则，也会把估算值伪装成真实用量。不建议实现。

## 五、风险与边界

1. **内部接口**：额度接口是客户端内部接口，不是公开 OpenAPI；可能随版本变化。需要固定契约测试与「结构不支持」错误码，不能静默返回 0。
2. **登录态**：依赖豆包客户端 cookie；会话过期、重新登录、钥匙串授权弹窗都会影响采集。实现时应沿用项目已有的 cookie 解密模式，凭据只走内存，不落盘、不入日志。
3. **窗口映射未验证**：本机仅返回 1 个额度窗口，5 小时 / 7 天 / 月的 `window_type` / `item_type` 映射需要多账号或多时间点样本；验证前不要硬编码中文标签。
4. **豆包工作企业版未验证**：本机无企业 / 工作版订阅，`doubao_office` 返回空；企业后台与 OpenAPI 的可得性只来自文档，未做真实调用。
5. **ToS 与稳定性**：只读额度接口风险低于写操作，但仍属于非公开接口；上游改版会导致失效。
6. **点数不可换算 Token**：额度点数是综合计价，不能除以单价反推 Token；报告中、UI 中都必须分开标注。

## 六、建议

- **P0**：先接「豆包额度卡」（`membership`），只展示点数 / 百分比 / 重置时间；明确标注「非 Token」。
- **P1**：找一个有豆包工作个人订阅或企业额度的账号，复测 `doubao_office` / `enterprise_window_limit_section`，确认是否需要第二个 product_line。
- **P2**：如用户确实需要真实 Token，单独接火山方舟 `ark_usage`，不与豆包额度混在一起。
- **不做**：本机 Token 账本（不存在）、聊天内容估算 Token、把点数加进 Token 总量。

## 七、本轮未做

- 未改任何代码，未新增采集器。
- 未验证企业后台导出、企业 OpenAPI、豆包工作独立客户端（本机未安装）。
- 未对 `usage/timeline` 的其他 category 做完整枚举。
- 未读取或保存任何 cookie/token 明文，未在报告中保留账号标识。
