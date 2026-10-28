# Qoder 第三方模型本地 Token 记录复核

检查日期：2026-10-26。用户指定 DeepSeek、MiniMax，时间为前天、昨天、今天，即 Asia/Shanghai 时区的 2026-10-24 至 2026-10-26。当前安装的 Qoder CN 为 0.4.11。本轮只读检查本机文件，未调用模型、修改连接、读取密钥或部署采集代理。

**找到了实际第三方调用记录，但这批记录没有保存真实 Token 用量。** 不能将缺失值显示为 0，也不能从请求数、文本长度或模型上下文容量反推出准确消耗。

## 实际找到的记录

扫描 `~/.qoder-cn/projects/**/*.jsonl` 共 187 个文件，无 JSON 解析失败。筛选 assistant 消息中的自定义模型 ID，并将消息时间转换为北京时间；包括主会话和子代理文件。模型名称由同机运行日志中的自定义模型配置映射确认。

| 日期 | DeepSeek-Flash | MiniMax-M3.1-Flash | 真实 Token 用量 |
| --- | ---: | ---: | --- |
| 10 月 24 日 | 59 | 424 | 未保存 |
| 10 月 25 日 | 未找到匹配记录 | 未找到匹配记录 | 无法确认 |
| 10 月 26 日 | 348 | 372 | 未保存 |
| 本次找到的合计 | 407 | 796 | 无法计算 |

表内数字是**本地保存了响应的去重请求数**：按 `requestTokenAnchor.requestId` 全局去重，共 1,203 个；独立按 `message.id` 去重也为 1,203 个。它们来自 2,524 条 assistant 记录，流式片段不能重复计数。此口径不等于所有计费请求数，不能覆盖无响应的失败请求、其他设备或已删除的历史。

模型映射：`47780e6a-dbcd-48bd-93a9-188e59301f3f` 为 DeepSeek-Flash；`06880a52-5ddd-4eab-824e-be2b3d7a89e6` 为 MiniMax-M3.1-Flash。10 月 25 日找到的响应为 `dfmodel` 标签，没有匹配这两个自定义模型 ID；不能据此断言当天从未使用第三方，也不能把 `dfmodel` 擅自归为 DeepSeek。

## 为什么无法给出 Token 数字

1. **第三方响应缺少整个 `message.usage` 字段。** 2,524 条相关片段全部缺失；不是字段存在且数值为 0。先前只筛选含 `usage` 的记录，漏掉了这些调用，因此“没找到实际第三方样本”的判断需要更正。
2. **`requestTokenAnchor` 不是 Token 数值。** 它保存 request/response 哈希和 requestId，只能辅助识别请求，不能提供输入、输出或缓存消耗。
3. **桌面数据库未补齐计数。** `~/Library/Application Support/com.qodercn.app.stable/main.sqlite` 的相关 `chat_session_context_usage` 快照为 `totalTokens=0`、`apiUsage=null`，`tokenCountsAvailable` 为 false 或缺失；消息 `turnMetrics` 只含时长和轮数。这些 0 不构成零消耗证据。`qoder_daemon_session_store_entries` 无记录。
4. **待落盘缓存为空。** 同目录 `chat-session-turn-payload-buffer.sqlite` 中 `pending_turn_projections`、`active_turn_projection_items` 均为 0 行。数据库以只读方式检查，无 WAL 文件，检查前后文件大小与修改时间一致。
5. **运行日志中的正数是模型容量。** 这三天日志里 3,544 条命中 `input_tokens` 的正数行都属于 `QoderInferRequest details` 的 `model_config`，实际字段是 `max_input_tokens`，值为 180,000 / 200,000 / 1,000,000，不能当作已消耗输入 Token。

## 已安装统计插件与后续采集

本机存在 `qoder-credits-inspector` 2.7.4。其 `scripts/lib/proxylog.mjs` 支持读取额外的 usage 代理日志，以供应商响应 ID 关联输入、输出、总量、缓存 Token。这只是插件代码能力，不证明本机曾启用代理。

本次检查：默认目录 `~/.qoder-credits-proxy/` 不存在；当前检查进程没有 `QODER_CREDITS_PROXY_LOG` 环境变量；这批调用涉及的两个项目也没有默认 `.qoder-credits/` 报告目录。没有找到可用于回填的代理账本。用户指定的其他日志位置仍可能存在，不将有限范围检查表述成全盘绝对不存在。

仅有会话文本时，插件的字符估算法也不能恢复真实输入、输出、缓存和思考 Token。若要持续采集，需要在后续调用链中保存服务商返回的真实 `usage`；具体方案需另行实现和验证，不能补造这三天的精确历史。供应商后台若保留历史，可以另核对账户用量，但需区分来自 Qoder 与其他客户端的请求。

## 对 AgentMeter 的影响

现有 [`agent_meter/qoder_tokens.py`](../../agent_meter/qoder_tokens.py) 读取 `usage.credits` 和 `usage.request_id`，输出积分指标，不输出 Token。这批没有 `usage` 的 BYOK 响应会被跳过。即使放宽解析条件，也没有真实 Token 数值可读。

2026-10-15 的“Token 采不到”结论是当时本机样本的观察，不能推广为 Qoder 所有版本、所有第三方模型都不会返回 Token。本轮确认的是：**当前这台机器上 10 月 24–26 日的上述第三方响应记录，未保留可供 AgentMeter 直接读取的真实用量。** 本轮没有更改业务代码。

## 脱敏证据

本机忽略目录 `.runtime/qoder-byok-audit-2026-10-26/`：

- `local-message-summary.json`：按日期和模型汇总的片段数、usage 字段存在次数、去重计数与时间边界。
- `confirmed-counts.json`：模型名称映射后的三天汇总，以及跨日期全局去重结果。

这些文件不含提示词、回复正文、密钥或完整原始请求。
