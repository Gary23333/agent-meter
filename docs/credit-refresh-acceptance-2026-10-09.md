# 下一次积分更新时间验收

2026-10-09。后端已新增 `credit_refresh_time` 与 `credit_refresh_countdown`，快照与 HTTP health 的 schema 升为 3。覆盖矩阵现在包含十一类指标，历史 schema 1/2 验收文件保留原版本。

## 真实读取

北京时间 2026-10-09 10:35:37，只读采集结果如下，见脱敏证据（本机文件 `credit-refresh-evidence-2026-10-09.json`，不随源码上传）：

| 产品 | 下一次积分更新 | 剩余自然日 | 来源 |
|---|---|---:|---|
| MiniMax Design | 2026-10-20 | 11 | 当前个人钱包 `next_credit_refresh_time` |
| 即梦 CLI | 未提供 | 未知 | `user_credit` 没有返回积分更新时间 |

Design 的续费日期仍为 2027-08-26，独立保留。当前更新时间只有日期精度，不虚构补发时分秒，倒计时的 `seconds_remaining=null`。

即梦有不同来源的积分，CLI 余额与会员等级不能证明某一个固定的每日/月度更新时间，因此没有从套餐名称推算。缺失时可通过账户绑定的 `billing_overrides.dreamina.credit_refresh_date` 填写 YYYY-MM-DD，标记为用户来源；账户不匹配时不使用。当前未填入任何未经用户提供的真实日期。

## 行为与边界

- 积分补发、积分过期、会员到期与自动续费分别建模。
- Design 原 `reset_time` 中的 membership_credit_refill 保留兼容，但它与新字段是同一事件，不能重复显示为两次更新。
- 提供方的有效日期优先，手填日期不覆盖它。
- 缓存读取时重新计算两个事件的倒计时，保留原观测时间；stale 日期的倒计时仍标 stale。
- 日期过后显示 overdue，不自行滚动到下个月。只有供应方新响应或新的用户填写才更新目标日期。
- 无日期保持未知；非法日期只影响积分更新字段，不抹去已读取余额和续费信息。

## 测试

完整回归 **103 项通过，0 失败**，其中新增 8 项测试覆盖：独立事件、无更新字段时不借用过期/续费日期、非法日期隔离、即梦未知值、手填账户绑定及来源优先、手填日期校验、缓存更新且不猜后续周期、失败刷新时 stale 倒计时。

另外真实调用了官方即梦 CLI 和已运行的 MiniMax Design 本机网关，核查解析后的新字段；未提交生成、兑换、购买或续费操作。这次实测是提供方接口读取，不是积分实际到账后的验证。

实现：[billing.py](../agent_meter/billing.py)、[minimax_design.py](../agent_meter/minimax_design.py)、[dreamina.py](../agent_meter/dreamina.py)。配置示例见[creative-billing.config.json](../examples/creative-billing.config.json)，里面的日期和金额均为演示值。
