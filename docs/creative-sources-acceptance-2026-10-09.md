# 即梦 CLI、MiniMax Design 与续费字段验收

2026-10-09。本轮实际实现采集器及测试，菜单栏界面尚未开发。后端快照 schema 从 1 升级为 2，HTTP health 与快照版本一致。

## 当前真实结果

以 脱敏验收证据（本机文件 `creative-sources-evidence-2026-10-09.json`，不随源码上传） 中的观测时间为准：

| 产品 | 积分 | 订阅 / 续费 | 尚缺字段 |
|---|---:|---|---|
| 即梦 CLI | 6086 | CLI 返回会员等级 maestro | 续费日期、金额；CLI 未返回这些字段 |
| MiniMax Design | 211021 | Design Pro 年会员；下一续费日期 2027-08-26；北京时间日倒计时 321 天 | 下一笔续费金额；钱包未返回该字段 |

Design 下次会员积分补发日为 2026-10-20，与年会员续费日分开。钱包当前两类余额 210930 + 91 = 211021，各自有效期保留，不把它们换算为货币金额或 token。

余额值来自真实只读查询与独立直接源读取的对账，未发送生成请求。当前没有独立账单页面或实际扣款凭证对账；不能说续费金额已验证。没有根据公开套餐价格补金额。

## 接入实现

- [dreamina.py](../agent_meter/dreamina.py)：只运行官方 CLI `user_credit`。现有登录态可复用，CLI 自己可能写自身日志。仅提取积分、会员等级和哈希账户指纹，不输出用户名及原始 user_id。不自动 login、relogin 或 logout，不读取生成记录。
- [minimax_design.py](../agent_meter/minimax_design.py)：连接已运行应用的 `127.0.0.1:8001` 网关，GET 健康、当前计费 scope、账户上下文、钱包；钱包 GET 带相同 group header，查询前后核对身份。只支持当前个人 Media Plan；团队钱包另行实现。余额使用 Decimal 字符串；只读 source=1 的 OP 钱包，不与旧 HILO 钱包叠加。
- [design_mcp.py](../agent_meter/design_mcp.py)：使用安装版 `/Applications/MiniMax Design.app/Contents/Resources/mcp-tools/dist/main.js` 初始化 stdio MCP，列出工具。实测 server 名 hub、版本 1.0.0、57 个工具，没有财务查询工具；财务数据使用本机网关补齐。MCP 客户端不提供 tools/call，未调用生成或付费工具。MCP 探测失败不影响已经成功的钱包。
- [billing.py](../agent_meter/billing.py)：新增续费日期、日倒计时、续费金额及手填来源。金额和日期手填必须绑定当前成功读取的账户指纹。提供方已有日期优先；未匹配账户不应用手填配置。

实测 Design 安装版 3.0.21；即梦 CLI version 为 `1d0bd17-dirty`，commit `1d0bd17`，build_time `2026-10-03T13:51:54Z`。安装代码仅在临时目录进行契约研究，没有把供应商代码加入本项目发布包。用户要求 MCP 后已真实初始化并核查工具列表，不把源码中的工具描述别名当实际工具名称。

## 续费倒计时与金额约定

`renewal_time` 按提供方返回的月/日/年字符串严格转换为 YYYY-MM-DD，时区为当前验证的中国区 Asia/Shanghai。它只有日期精度；`renewal_countdown.seconds_remaining=null`，按自然日期计算剩余天数，当日为 today，过期为 overdue。命中缓存也重算倒计时，不需要为了倒计时持续请求供应方。stale 的日期可重算，但倒计时继续标 stale。

`subscription.ends_on` 是会员到期，不自动替代自动续费日；明确取消自动续费时，续费日期和倒计时为空。额度补发、积分过期和续费是三个不同事件。续费日期解析异常仅影响该字段，不抹掉成功的积分余额。

`renewal_amount` 接口与金额/币种校验已实现。目前两个自动来源均没有返回金额，状态是 not_provided。可在 `billing_overrides` 中填写下一笔续费金额和币种，显示 origin=user、confirmed_by_provider=false。即梦日期也可同样填写。配置样例的金额和日期仅为演示，未写入当前账户的真实配置。

[配置示例](../examples/creative-billing.config.json) 必须替换 account_key 和真实数据；配置不包含凭据。账户 key 可从本机受认证快照取得；原始账户 ID 不输出。已经向用户请求缺失日期和金额，本次未收到可用于填入的值。

## 测试与实际对账

完整回归 **95 项通过，0 失败**。其中新创作来源文件有 28 项测试，另新增 HTTP health/schema 一致性测试；原测试继续通过。

测试覆盖：

- 官方 CLI 只读命令、超时、登录失效不自动重登、零值与未知、敏感字段过滤。
- 个人账户前后核对、切换期间丢弃结果、团队 scope 拒绝、只读路径限制、MCP 失败隔离。
- OP 钱包不叠加 HILO，超大 Decimal 精度、钱包格式错误不补零，积分桶及有效期。
- 取消续费后保留会员到期、续费/补发日期分离、非法日期不抹掉余额、午夜/今日/已过期日倒计时。
- 手填金额来源、币种/非有限值/负值校验、账户绑定、提供方日期优先、缓存跨午夜更新。
- MCP 初始化与工具目录查询，验证没有 tools/call。

此外，本机 HTTP 端到端 **14 项检查通过，0 失败**：两来源可用、CLI 积分及账户哈希匹配、Design 余额/桶合计/续费日期匹配、九列覆盖矩阵、MCP 实际连接、缓存、没有虚构金额、输出无原始身份和认证信息。服务器使用临时本机端口，测试结束关闭；未留下新的常驻服务。

最初沙箱运行中，本机 HTTP 测试因禁止绑定端口而报权限错误；在允许本机测试端口的环境下完整重跑并通过。不是将错误跳过。Design 与即梦真实采集同样在允许本机网关访问/CLI 自身日志的环境下执行。

复现：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -v
python3 -m agent_meter collect --output .runtime/snapshot.json
```

Design 需自行运行，已有即梦登录态需有效。后端默认不自动打开应用或启动登录。本轮为验收打开了 Design 并复用现有登录。金额自动读取、即梦续费日期自动读取、团队钱包、菜单栏展示和付款页面对账仍未实现，覆盖状态不会把缺口算成完成。

官方入口：[Dreamina CLI](https://dreamina.capcut.com/tools/dreamina-cli)、[MiniMax Design 订阅页](https://design.minimax.cn/media-plan/subscribe)。该 CLI 官方页面和本机帮助只支持确认积分查询入口，不证明续费金额可从 CLI 获得。
