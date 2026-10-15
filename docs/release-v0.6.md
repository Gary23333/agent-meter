# v0.6.0 发布说明

2026-10-16 发布；App 内部版本为 0.6.0，后端 schema 升到 4。适用于 macOS 14+、Apple Silicon（arm64）。

## 新增独立功能：全员（Tibo）重置预测

Codex 负责人不定期在 X 上宣布的**全员额度重置**（社区称 Tibo 重置）与各账户自身的 5 小时 / 每周窗口是两类不同事件。本版把它做成**独立功能**，在面板新增「重置预测」标签页（账户额度 → **重置预测** → 本机消耗 → 应用覆盖）。

### 三源交叉，只采信公布值

并行读取三家第三方追踪站的公开只读页面，归一化到同一行结构后合成：

- `ensemble.horizons.<24h|48h>` 给出**区间**（min / max）、**加权中位**与 `spread`；
- 权重完全取自各站上报的质量字段——自报信心、校准状态、Brier / 回测样本、数据新鲜度——系数常量在模块顶部，逐行随 `weight_components` 下发，便于核对；
- 合成**只用各站自己公布的答复**（`basis=published_answer`）；某站没公布时才回退到站内模型值并标 `cadence_model_fallback`。站内未公布的内部字段不作为跨源输入——这是实测得出的口径：某站当天中午从 `cadence-v1` 切到 `evidence-v2` 时，未公布字段全部归零，若当时参与合成会直接把结论带偏；
- 超过 48 小时未更新的来源**整体剔除**（`forecast_source_stale`），不按 0 计。

### 已公告重置的倒计时

`known_reset_countdown.targets[]` 每项带 `kind`（`promised_reset` / `typical_window`）、`precision`（`window` / `label_only`）、`open_at` / `close_at`、`state` 与来源。**只有拿到可机读的时间或时段才给秒数**；公告只说「会重置」而没给时间时保留 null，面板显示「未给时间」，与天级续费倒计时不伪造秒数同一原则。

### 通知与边界

- 通知**只按已公告事件触发**（进入时段 / 时段已过而额度未刷新 / 记录到落地），**概率永不弹通知**；
- `reset_forecast` 是独立来源，scope `external_forecast`，**永不写 `reset_time`**，不进账户卡片、菜单栏滚动、本机消耗；
- 预测类两个指标（`reset_forecast`、`known_reset_countdown`）**不计入应用覆盖矩阵**（`COVERAGE_METRICS` 排除），否则每个应用都会凭空多出两项「缺失」；
- 设置菜单可单独开关「全员重置预测（联网读第三方追踪站）」，关闭后后端不再抓取。

### 抓取行为

- 三家都拒绝 Python 默认 User-Agent（403），请求固定带应用 UA；**纯公开只读 GET**，不带 Cookie、不发送任何本机数据；
- 默认 45 分钟抓一次（`reset_forecast_refresh_minutes`），有来源失败时缩短到 5 分钟重试；最近成功值缓存于 `.runtime/reset-forecast.json`（0600）；
- 三家全挂且无缓存时来源为 `error`（`reset_forecast_sources_unavailable`），有缓存则按 `stale` 返回旧值并保留原观测时间；
- 解析失败只让**该源降级**（`forecast_object_not_found` / `unsupported_forecast_contract`），不影响其余两源。

### 历史记录

`history_events[]` 按各站共享的 X 状态 ID 去重合并，`sources` 列出印证家数。`announced_at`（公告）、`effective_at`（观测落地）、`official_window`（官方窗口）是三个不同事实，**不相加也不互相覆盖**；推文正文不进快照，只留各站的摘要文本。

## 后端 schema 4

- `METRICS` 新增 `reset_forecast`、`known_reset_countdown` 两类指标，仅由预测来源提供；
- 新增 `COVERAGE_METRICS`（13 类指标中排除上述两类），覆盖矩阵与「十一类关键指标」的口径不变；
- 新增错误码 `disabled_in_config`（来源被配置关闭时显式声明，不再走通用未知错误）。

## 验证

- Python 后端回归：**266 项全部通过**（新增 33 项预测测试）。
- 真实对账 `python3 -m agent_meter verify`：**691 项检查全部通过、0 失败**，其中 33 项为预测来源的独立重算——区间、加权中位、分歧标签、去重、倒计时状态机、以及「数值只来自公布答复」。
- Swift release 编译通过；DMG 校验与内嵌后端合成数据冒烟测试通过。

## 已知限制

- 预测完全依赖三家第三方追踪站：它们改版、停更或长期不更新时，本来源会显式降级或整体剔除，不会猜值；
- 预测概率是**社区观测**，不是官方承诺，面板以区间与「分歧」标签呈现不确定性，不当作确定性时间；
- ad-hoc 签名，未做 Apple 公证；升级后钥匙串会再次询问，请选择「始终允许」。仅发布 arm64。

## 重建

```sh
python3 -m pip install -r requirements-build.txt
sh scripts/build-dmg.sh
```
