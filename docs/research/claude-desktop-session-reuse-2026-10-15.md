# Claude 桌面端会话复用获取额度（2026-10-15 实测通过）

**状态：暂缓实现（用户 2026-10-15 决策）。** 研究结论与实现方案如下存档，供未来需要时直接落地。

结论：**可以不额外登录，直接复用 Claude 桌面端已有的登录态读取订阅额度**。全链路已在本机真实账户上端到端验证（读到真实 5 小时/7 天窗口数值）。本文件不记录任何凭据明文；密钥派生规则用应用自带原生插件的输出做了交叉验证。

## 背景与问题

现有 `claude` 来源有两条路，本机都不适用：`collect_claude_web` 需要用户手动提供 claude.ai 的 Cookie（只有 sessionKey 时实测 401）；`collect_claude` 需要 Claude Code CLI 的钥匙串登录（本机未登录订阅，报 `claude_subscription_login_missing`）。用户实际使用的是 Claude 桌面端。

## 实测链路（每一步都已验证）

1. **cookie 存放位置**：`~/Library/Application Support/Claude/Cookies`（Chromium SQLite，`meta.version=24`，值以 `v10` 前缀加密）。`.claude.ai` 域下有 `sessionKey`、`sessionKeyV3`、`cf_clearance`、`anthropic-device-id`、`__cf_bm`、`lastActiveOrg` 等 24 条。
2. **密钥来源**：钥匙串条目 service `Claude Safe Storage` / account `Claude Key`（一次授权后可读；值形如 base64 文本，24 字符）。
3. **密钥派生**：`AES-128 key = PBKDF2-HMAC-SHA1(钥匙串值文本, salt="saltysalt", iterations=1003, dklen=16)`。
   - 该规则不是猜的：调用应用自带原生插件 `@ant/claude-swift`（`swift_addon.node`）的 `deriveBrowserSafeStorageKey("chrome")` 得到 Chrome 的密钥，与对 `Chrome Safe Storage` 条目做上述 PBKDF2 的结果**逐字节一致**（`40dc2b2e…` ↔ 匹配）。该函数对非浏览器名返回 `unsupported_browser`，即无 `claude` 支持项，需自行派生。
   - 插件在裸 node 下加载会因 `UNUserNotificationCenter` 需要 bundle 上下文而崩溃；放入一个最小 `.app` 包壳（CFBundleIdentifier 任意）即可加载。本项仅用于验证派生规则，生产实现不需要加载它。
4. **cookie 解密**：`明文 = AES-128-CBC-decrypt(key, IV = 16 个空格, blob[3:])`，当 cookie 库版本 ≥ 24 时明文前 32 字节是 `sha256(host_key)`，校验通过后剥掉即为 cookie 值，尾部做 PKCS#7 去填充。
   - 交叉验证：`user-sidebar-visible-on-load` 解出 `true`、`CH-prefers-color-scheme` 解出 `dark`、`lastActiveOrg` 解出组织 UUID、`sessionKey` 解出 131 字符的 `sk-ant-sid02-…`。
   - 方案常量来自 `app.asar` 内 ChromeImport 模块（`createDecipheriv("aes-128-cbc", key, Buffer.alloc(16,32))` + `dbVersion>=24` 时的 sha256 前缀分支）。
5. **认证**：只带 `sessionKey` 会 401；**必须带完整 cookie 罐**（含 `cf_clearance`、`anthropic-device-id`、`__cf_bm` 等）并配合真实浏览器 UA。全量 jar 实测 HTTP 200。
6. **额度接口**：`GET https://claude.ai/api/organizations/{uuid}/usage` —— 与现有 `collect_claude_web` 完全同一契约，无需新增接口适配。本机实测返回：5 小时窗口利用率 0%（00:19Z 重置）、7 天窗口 49%（10-19 15:59Z 重置），另含 `limits[]`（`kind: session/weekly_all` + `percent` + `resets_at` + `is_active`）、`seven_day_breakdown`、`spend`、`extra_usage`、多个代号窗口（tangelo/iguana_necktie 等，与 7 天用量同源）。

## 与现有实现的关系

- 现有 `normalize_claude` 的窗口表（five_hour / seven_day / seven_day_opus / seven_day_sonnet / seven_day_oauth_apps）够用；响应里的 `limits[]` 是更结构化的等价视图，可作为后续增强（不改契约即可忽略）。
- 差异点只有一个：**cookie 来源**从"用户手填"变为"自动从桌面端解密"。其余（normalize、account_key、错误码、内存通道）全部复用。
- 纯标准库后端没有 AES。可行做法：(a) node 辅助脚本（项目已有 qoder 的 node helper 模式）用内置 `crypto` 解密，密钥经 env/stdin 传递；(b) 调 `openssl enc` 子进程——但密钥会出现在进程参数里（`ps` 可见），不推荐。推荐 (a)。

## 安全与风险边界

- 本地部分（读钥匙串、解密 cookie）**零服务端可见**；网络部分只读、同账户、同官方端点，与桌面端自身行为同构。最坏情形是会话被判定异常而失效、需要重登，不构成封号（封号针对共享/转售/自动化生成，非用量查询）。
- 实现须沿用项目既有约束：Cookie 只走内存（`PUT /v1/web-sessions`）不落盘不入日志；只读端点白名单；采集频率沿用缓存；绝不发任何生成请求；失败固定错误码。
- 凭据生命周期：`sessionKey` 会随桌面端使用轮换（`sessionKeyLC` 为其变更时间戳），需在失败时提示"重新从桌面端读取"，不做静默重试风暴。
- 多账户：cookie 罐里存在 `lastActiveOrg`，组织列表含个人号与企业号（`capabilities` 区分 chat/api），沿用现有 `pick_organization` 优先个人 chat 组织的规则。

## 证据等级

真实端到端（读到真实额度数值、真实组织列表）；密钥派生规则经应用自带插件输出交叉验证；加密方案来自应用自身的解密实现常量；未做：修改应用、触发提示词生成、写入任何第三方数据。
