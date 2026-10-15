# v0.5.0 发布说明

2026-10-15 发布；App 内部版本为 0.5.0。适用于 macOS 14+、Apple Silicon（arm64）。

## 新增来源：阶跃星辰 (StepFun) 开放平台

账户额度页新增一个来源，两条只读路线（与 ZCode、火山方舟同构）：

- **控制台网页登录**（推荐）：「连接网页账户」里登录 `platform.stepfun.com`，停在「订阅 / 用量」页再点「完成连接」。App 只保留页面自己的 `Oasis-Token`（控制台会话里其余 Cookie 会让查询接口拒绝请求，因此后端在转发前把整罐 Cookie 收窄成这一个字段），读取：
  - **账户余额**：可用余额、总充值、总赠送（控制台以「分」下发，按元显示）；
  - **STEP plan 用量**：老 Coding Plan 的 **5 小时 / 每周**滚动窗口，或当前 Token Plan 的**月度积分池**（订阅积分与加油积分是各自独立的比例，不合并相加，优先用 `credit_buckets` 的绝对余额）；两者的重置时间；
  - **套餐名与到期日**（自动续费状态一并显示）。
- **开放平台 API Key**：在连接窗口粘贴。走官方文档接口 `GET https://api.stepfun.com/v1/accounts`，**只能读余额**，读不到 STEP plan 用量——卡片会明确说明，不把缺失当成零。

最多 5 个账号。契约来源：公开 API 文档 `platform.stepfun.com/docs/zh/api-reference/accounts/get`，以及控制台 Connect 风格 RPC（`QueryAccountBalance` / `GetStepPlanStatus` / `QueryStepPlanRateLimit`）的字段与行为记录——两个独立参考实现（stepfun-cli 的逆向记录、CodexBar 的 StepFun 采集器）在该契约上一致。

按「未知不等于零」处理：套餐没有配置某个窗口时，服务端把比例和重置时间都返回 `0`，这被解读为**没有该窗口**而不是「已用完」，因此不会渲染出 0% 的假进度条；只有出现真实重置时间的窗口才会成为一行额度。套餐刊例价（`plan_definition.price`）不作为「下一笔扣款金额」上报。

## 本机消耗口径完善

- **WorkBuddy** 补上按模型分组，**Kimi** 补齐输入 / 输出 / 缓存拆项，两者首次进入「按应用 / 模型 Top」并获得价格表估算；账户额度页的 token 行同步受益。
- **价格表匹配先归一化**（取最后一个 `/` 之后的模型 id、转小写、`.` 统一为 `-`），解决各来源模型名拼写不一致导致的漏配；新增混元 hy4/hy3、阶跃 step-5 等 8 个刊例；仅 CNY 刊例的国产模型在 USD 表中按 1/7.25 折算并标注「折算」。

## 新增：Qoder CN 本机积分账本

Qoder CN CLI 的会话日志每条请求带真实 `credits`，但 token 字段本机恒为 0（实测 8,896 条无一条非零）——因此只采集积分、不臆造 token。按 `request_id` 全局去重后折叠进 Qoder 账户卡片的「积分消耗 今日 / 近 30 天 / 全部」行，**不写 tokens 指标**，不可能被本机消耗页当成 token 汇总。

## 新增：MiniMax Design 本机 Token

读取 Design.app 内嵌 opencode 运行时的账本，按 session ID 剔除与独立 OpenCode 库重复的拷贝会话（避免双算），附着到 Design 账户卡的 token 行，附模型 / agent 双分项。

## 修复

- Swift「估算费用」卡此前恒为「—」：CC Switch 的估价没有进入合并视图。现在按币种合成总数（CNY 表分列、不跨币种相加），按应用与模型行各带金额。
- 账户额度页 token 行改读与本机消耗页**同一个**合并函数，不再因为直读来源按设计剔除了 CC Switch 已导入的日期而显示 0。

## 验证

- Python 后端回归：233 项全部通过（新增 21 项覆盖阶跃星辰的会话收窄、金额单位、两种计费模型、错误码与凭据范围）。
- 真实对账 `python3 -m agent_meter verify`：634 项检查全部通过、0 失败。
- Swift release 编译通过；DMG 校验与内嵌后端合成数据冒烟测试通过。

## 已知限制

- **阶跃星辰尚未用真实账户端到端验收**：本机没有阶跃星辰账号，两条路线都只经过固定样例、契约对照与独立参考实现比对。首次真实连接若失败，卡片会给出固定错误码与原因，不会静默。
- 控制台路线依赖平台自身的未公开 RPC，服务端字段一旦变更即会以 `stepfun_step_plan_usage_unrecognized` 等错误码显式暴露，不会猜值。
- ad-hoc 签名，未做 Apple 公证；升级后钥匙串会再次询问，请选择「始终允许」。仅发布 arm64。

## 重建

```sh
python3 -m pip install -r requirements-build.txt
sh scripts/build-dmg.sh
```
