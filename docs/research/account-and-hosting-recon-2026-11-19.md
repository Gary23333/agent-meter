# 云端同步的账号体系与托管方案调研（2026-11-19）

范围：多机用量/额度历史同步的「身份层」选型，以及「家里服务器 + Cloudflare + 域名」能否承载。
本文只做调研与决策建议，不改代码、不部署。

关联现状：M0 骨架在分支 `claude/cloud-sync-m0`（commit `59ec1da`），规划见该分支的
`docs/cloud-sync-plan-2026-11-10.md`；当前工作分支未包含 `sync_server/` 源码，只有历史缓存。

---

## 0. 结论（先看这里）

1. **微信、支付宝、抖音三家都不支持「纯个人开发者」直接做网站/桌面端登录。**
   - 微信开放平台：个人主体无法完成开发者资质认证，未认证不能开通微信登录；网站应用还要
     300 元/年认证费 + 已备案域名。
   - 抖音：个人主体只能创建「小玩法」，网站应用/移动应用仅企业主体（含个体工商户）。
   - 支付宝：个人可实名、可认证个体工商户，但多数产品准入仍要求企业或个体工商户。
   最低门槛是注册个体工商户/企业。这不是「接个 SDK」，而是先有经营主体。
2. **建议把「身份」和「加密」拆开。** 同步继续用 M0 的空间密钥（服务端零知识），账号只在
   需要会员、多设备管理、找回时叠加。这样换任何一家登录都不影响同步协议。
3. **对当前 DMG + Developer ID 分发方式，原生 Sign in with Apple 不可用。** Apple 的支持
   能力表里 Developer ID 列不含 Sign in with Apple，Apple DTS 论坛也明确回复不支持。
   只能走网页版 Sign in with Apple JS，或等上架 Mac App Store。零主体的可行账号是
   邮箱 Magic Link / GitHub OAuth。
4. **家里服务器 + Cloudflare Tunnel + 域名：技术上可行**，适合自用和小范围内测；
   不建议长期作为公开收费服务的生产环境（可用性、跨境延迟、备案）。
5. **建议路线**：P0 无账号同步（家里跑）→ P1 轻账号（邮箱/GitHub）＋兑换码会员 →
   P2 有主体后再上微信扫码 + 国内云/备案。

---

## 1. 调研方法与边界

- 只看官方文档、官方社区答复和公开法规；平台政策以 2026-11 可查到的页面为准。
- 不把「网上有人这么干过」当作合规依据；不评估绕过审核的做法。
- 托管部分只评估技术可行性与风险，不代替备案/法律意见。
- 项目现有边界不变：不读对话正文、只同步聚合行、服务端只存密文。

---

## 2. 账号体系对比

| 方案 | 主体要求 | 费用 | 域名/备案 | Mac 端接入 | 适合谁 | 结论 |
|---|---|---|---|---|---|---|
| 微信开放平台（网站应用扫码登录） | 企业/政府/媒体/其他组织；个人无法完成开发者资质认证 | 认证 300 元/年 | 需已审核网站应用 + 授权回调域名；业务域名需 ICP 备案 | 系统浏览器/内嵌 WebView 打开二维码页，回调到 https 域名，再 deep link 回 App；Mac 微信 4.0+ 支持快速登录 | 有企业/个体户、面向中国大众、已备案 | 体验最好，门槛最高 |
| 支付宝开放平台 | 个人可实名/可认证个体工商户；多数会员信息产品要求企业或个体工商户 | 认证免费 | 网页/移动应用需开通产品、配置加签；隐私类产品有额外审核 | 网页授权扫码，或 App 授权 | 有支付宝商家资质 | 门槛略低，但工具类用户授权意愿弱 |
| 抖音开放平台 | 个人仅「小玩法」；网站应用/移动应用仅企业主体（含个体工商户） | 企业认证免费 + 对公验证 | 需应用审核、上线转正 | OAuth 网页授权 | 内容/社交类产品 | 不适合效率工具 |
| Sign in with Apple（原生） | Apple Developer Program（个人可） | 含在 688 元/年会员费 | 不需要 ICP | macOS 原生 `ASAuthorizationAppleIDProvider` | 上架 Mac App Store 的 App | **Developer ID 不支持**，当前分发方式用不了 |
| Sign in with Apple JS（网页） | Apple Developer Program + Services ID | 含在会员费 | 需验证域名（不要求 ICP） | 浏览器打开 Apple 登录页，回调到 https 域名/deep link | 愿意做网页登录中转 | 可行，但多一次浏览器跳转 |
| 邮箱 Magic Link | 无 | 邮件服务量级 0–100 元/月 | 不需要 ICP（除非自建网页） | App 内输入邮箱 → 收信点链接/输码 | 所有桌面工具 | 零主体、最通用；送达率要测 |
| GitHub OAuth | 无 | 免费 | 不需要 ICP | 浏览器授权 + 回调 deep link | AI/开发工具用户 | 零主体、接入最快；覆盖面窄 |
| 无账号空间密钥（M0 现状） | 无 | 0 | 不需要 | 二维码配对 `space_id + master_key` | 自用/小圈子 | 最省事、最隐私；丢 key 丢数据 |

### 2.1 微信开放平台

- 网站应用微信登录基于 OAuth2.0，前置条件是「已审核通过的网站应用 + 开放平台账号完成
  开发者资质认证」。
- 「网站应用授权回调域名」是微信登录的前置必要配置；每个应用 1 个域名，每月最多改 5 次，
  网站应用审核通过后才可编辑。业务域名要求 HTTPS 且需 ICP 备案，新备案域名 24 小时后
  才能配置。
- 微信 4.0.0 for Mac 及以上支持「网站应用快速登录」：已登录微信客户端时可直接确认，
  无需扫码。对 Mac 桌面 App 是体验加分项。
- 个人主体：开放平台注册页仍列出「个人」，但开发者资质认证只面向企业/政府/媒体/其他组织；
  官方社区答复明确「个人主体无法申请微信登录」「未认证开发者无法申请开通微信登录」。
  实操上可理解为：个人可以注册账号，但开不了微信登录能力。
- 结论：微信是三家中国平台里体验最顺的（扫码 + Mac 快速登录、用户覆盖最大），但也是
  门槛最高的（主体 + 300 元/年 + 备案域名 + 应用审核）。一旦上微信，备案就是硬约束。

### 2.2 支付宝开放平台

- 个人支付宝账号可完成实名认证，也可认证为个体工商户，但官方明确「不具备企业资质，
  建议商家申请企业账号」；「大部分产品准入及小程序接口调用均强制要求商家账号为企业
  账号或个体工商户资质」。
- 网页/移动应用的创建流程是：实名账号 → 创建应用 → 开通产品 → 配置加签（必填）→
  配置 IP 白名单/应用网关（选填）。
- 会员信息类能力：手机号接口对个体工商户开放，头像昵称走组件；隐私申请通常要求企业
  认证资质。
- 结论：比微信便宜（认证免费），但桌面效率工具用户不一定愿意用支付宝授权；且同样需要
  个体工商户起步。

### 2.3 抖音开放平台

- 入驻主体可以是企业、个体工商户、党政机关、事业单位、社会组织等；**个人主体仅支持
  创建「小玩法」，小程序/移动应用/网站应用仅支持企业主体**。
- 企业认证免费，对公验证有四种方式（法人人脸、银行账户实名、平台打款、客户打款）。
- 结论：对 AgentMeter 这种 macOS 效率工具，抖音登录既无用户心智，也无资质便利，直接排除。

### 2.4 Sign in with Apple

- 原生接入：App ID 启用 Sign in with Apple capability，macOS 用
  `ASAuthorizationAppleIDProvider`，服务端校验 `identityToken`（Apple 公钥验 JWT）。
  只拿到稳定的 `sub` 和可选的中继邮箱，不拿手机号。
- **关键限制**：Apple 的「Supported capabilities (macOS)」表里，Developer ID 列不含
  Sign in with Apple；Apple DTS 在开发者论坛明确回复「Sign in with Apple is not
  supported for Developer ID」。也就是说，当前 DMG + Developer ID 公证的分发方式下，
  原生 Apple 登录不可用。
- 可行替代：
  1. **Sign in with Apple JS（网页流程）**：注册 Services ID、验证域名，App 打开浏览器
     完成登录，回调到你的 https 域名或 `agentmeter://` deep link。域名验证不等于 ICP
     备案，境外托管可行。
  2. **上架 Mac App Store**：ADP 分发支持原生能力，但引入审核、沙箱和分成，和现在的
     发布模式不同。
- 结论：Apple 是最适合 Mac 用户的「一家」，但当前分发方式只能走网页版，收益/成本比一般；
  等有 App Store 版本再启用原生能力更合理。

### 2.5 邮箱 Magic Link

- 账号 = 邮箱；输入邮箱 → 发送一次性链接/验证码 → 换取长期会话 token。
- 优点：零主体、零备案、跨平台；不依赖任何一家平台的审核。
- 缺点：国内邮箱（QQ/163）送达率与垃圾箱要实测；需要维护发信域名 SPF/DKIM/DMARC；
  免费额度有限（Resend/Postmark/SES 各有免费档）。
- 适合作为「轻账号」的默认选项，也适合作为微信/Apple 之外的兜底。

### 2.6 GitHub OAuth

- 零主体、免费、接入快；对 AI 编程工具用户（Codex/Claude Code/Kimi/Qoder 用户）覆盖率高。
- 缺点：非开发者用户没有 GitHub；对中国大众市场覆盖不足。
- 适合 P1 内测阶段，或作为开发者向的备选登录方式。

### 2.7 无账号空间密钥（M0 现状）

- `space_id`（32 hex）+ `master_key`（32 字节）+ 二维码配对；`enc_key`/`auth_token` 由
  HKDF/HMAC 派生，服务端只存 `auth_hash` 和密文。
- 优点：服务端零知识、无账号合规负担、离线可验证、成本几乎为零。
- 缺点：丢 key = 丢数据；换设备必须扫码；不能做跨用户/团队；付费只能靠兑换码。
- 这正是 M0 已经实现并测试过的路径，应作为 P0 的默认。

---

## 3. 推荐的身份架构：身份层与加密层解耦

```
Apple/邮箱/GitHub  ──►  身份记录（sub/email、license、设备列表）   ──►  仅用于「你是谁、买了没、有几台设备」
        │
        └─ 不参与解密

space master key  ──►  HKDF/HMAC  ──►  ChaChaPoly 密文  ──►  服务端只存 blob
```

三条原则：

1. **登录不解决解密。** 第三方账号只回答「这是谁」，不持有同步密钥；服务端永远读不到
   明文。这样换登录方式不需要迁移历史数据。
2. **同步密钥不依赖账号。** 用户可以不登录就用同步；登录只是把 space 关联到身份，
   方便换机、找回设备列表、绑定 license。
3. **会员只绑身份。** license 的 `sub`/`email` 与 space 解耦；退订不影响已有数据的
   读取，只影响新增设备/高级能力。

这样做的直接好处：微信/支付宝/抖音/Apple 任何一家的政策变化，都不会让同步协议返工。

---

## 4. 家里服务器 + Cloudflare + 域名

### 4.1 能实现什么

| 目标形态 | 能否用家服务器 | 说明 |
|---|---|---|
| 自己 2–5 台 Mac 同步 | **可以** | 成本≈域名钱；隐私最好；需要保证机器常开 |
| 10–50 人小范围内测 | **可以，但要补运维** | 限速、监控、备份、UPS；家宽上行是瓶颈 |
| 公开下载 + 免费使用 | **勉强** | 可用性没有 SLA；一次停电/断网就是全量用户不可用 |
| 公开收费/会员 | **不建议长期** | 除可用性外，还有备案、主体、发票、退款等合规问题 |

### 4.2 架构

```
Mac App (SyncClient, CryptoKit)
   │  https://sync.example.com  (Cloudflare 边缘 TLS)
   ▼
Cloudflare 边缘（免费版：香港/东京/新加坡等）
   │  Cloudflare Tunnel（cloudflared 主动出站，QUIC 7844）
   ▼
家里服务器 127.0.0.1:8899  sync_server（Python 标准库 + SQLite）
```

关键点：

- 家里**不需要公网 IP、不需要端口映射**；cloudflared 主动向外建连，NAT/动态 IP 都不影响。
- TLS 在 Cloudflare 边缘终止；源站只跑 http，且只绑 `127.0.0.1`。
- 域名 NS 托管到 Cloudflare（在阿里云/腾讯云买的域名改 NS 即可，免费）。
- `sync_server` 启动时加 `--allowed-host sync.example.com`，保留 Host 白名单。

### 4.3 需要准备什么

1. 一个域名（`.com`/`.cn` 均可），NS 改到 Cloudflare。
2. Cloudflare 账号（Free 计划即可）；`cloudflared` 安装在家服务器。
3. `cloudflared tunnel create agentmeter-sync` → `tunnel route dns` 绑定
   `sync.example.com` → 配置文件 ingress 指向 `http://127.0.0.1:8899`。
4. `sync_server` 用 launchd（macOS）或 systemd（Linux）托管，`KeepAlive` 自动重启。
5. 家服务器禁止休眠（macOS 用 `caffeinate` 或能源设置；Linux 关闭 suspend）。
6. 每日 SQLite 备份到另一块盘；可选再加密上传 R2（R2 免费 10 GB）。
7. 外部 uptime 监控打 `/v1/health`；Cloudflare Analytics 看请求量。
8. 上公网前补限速（见 4.6）。

### 4.4 性能预期（国内访问）

- Cloudflare 免费版**没有中国大陆节点**；国内流量通常落到香港/东京/新加坡/美国，
  非高峰 50–150 ms，晚高峰 100–300 ms 或丢包。China Network 是 Enterprise 独立订阅，
  由京东云运营，且每个根域名需 ICP 备案，不适合当前阶段。
- 对「每天几次、每次几百 KB 的 JSON 同步」：延迟无感；首次全量 1–5 MB 可能几秒到
  几十秒。
- 家宽上行常见 30–100 Mbps：8 MB blob 约 1–3 秒（100 Mbps）到 7 秒（10 Mbps）。
- Cloudflare 免费版单请求体上限 100 MB，8 MB blob 无压力。
- Tunnel 实测：默认 QUIC(UDP 7844) 通常可用；部分运营商 TCP 7844 反而不通，不要
  按 precheck 的提示乱改协议；面板显示 2 条连接 / `Degraded` 不一定是故障。
- 注意：Cloudflare 对 WebSocket 上传有 0–1 Mbps 级限速、约 5 MB/40 秒会断；我们的
  同步用普通 HTTPS PUT/GET，不走 WebSocket，不受这条限制。

### 4.5 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 家里停电/断网/机器休眠 | 全员同步中断 | UPS、禁休眠、launchd/systemd 自启、云主机热备 |
| 家宽上行小 | 首次同步慢、超时 | 载荷已限 8 MB；首次分页/压缩；监控耗时 |
| 动态 IP / 无公网 IP | 无法直接回源 | Cloudflare Tunnel 已解决 |
| ISP 对 QUIC/UDP 干扰 | Tunnel 抖动 | 保留 http2/443 回退；自动重连 |
| 单机磁盘故障 | 数据丢失 | 每日备份 + 异地副本；SQLite WAL 定期 checkpoint |
| 服务端被扫描/滥用 | 磁盘塞满、DoS | 限速、空间创建配额、Host/Origin 校验、不放管理面板 |
| 备案/主体 | 公开收费被要求整改 | 自用/内测不对外收费；公开收费前补 ICP/经营许可 |
| 安全 | 密文泄露也怕元数据 | 只存密文；日志不记请求体；token 只存 sha256 |

### 4.6 上公网前必须补的 5 件事

1. **限速**：按 IP + 按 space 双维度令牌桶；建空间也要限速（当前 M0 没有）。
2. **空间创建配额**：匿名者可拿随机 key 建空间塞满磁盘，需要邀请码或每日配额。
3. **请求体/响应体上限**：已有 8 MB blob 上限，再加 HTTP 层上限。
4. **备份与恢复演练**：只备份不演练等于没备份。
5. **监控与告警**：`/v1/health`、磁盘占用、5xx 比例、Tunnel 连接数。

### 4.7 成本量级（2026-11 公开价，实际以账单为准）

| 项目 | 量级 |
|---|---|
| 域名 | 60–100 元/年 |
| Cloudflare Free（Tunnel/DNS/TLS） | 0 |
| 家里服务器电费 | 10–30 元/月 |
| 云主机备选（2C2G，国内轻量） | 60–150 元/月 |
| Cloudflare Workers Paid（若超免费额度） | $5/月 |
| Apple Developer Program | 688 元/年（已有） |
| 微信开放平台认证 | 300 元/年 |
| 个体工商户记账报税 | 1,000–2,000 元/年（如注册） |

### 4.8 何时该换掉家服务器

- 付费用户 > 20，或日活 > 100；
- 需要 99.9% 可用性、发票、退款、客服；
- 需要在国内备案/上微信登录；
- 家宽上行长期打满或晚高峰同步失败率 > 1%。

迁移路径（协议不变）：

1. **同一台云主机**：`sync_server` 原样部署（Docker/系统服务），Cloudflare 继续做前置；
2. **Cloudflare Workers + D1/R2**：把 5 个端点重写成 Worker，元数据进 D1、blob 进 R2。
   Free 计划：Workers 100k 请求/天、10 ms CPU/请求；D1 5 GB、5M 读/天、100k 写/天；
   R2 10 GB、1M Class A/月。注意 `workers.dev`/`pages.dev`/`r2.dev` 域名在国内常被污染，
   必须绑自定义域名；8 MB blob 的 CPU 处理可能超过 10 ms，正式用建议 $5/月 Paid。
3. **国内轻量云 + 备案**：适合要微信登录/国内支付/发票的阶段。

---

## 5. 三阶段落地建议

### P0（现在）：无账号同步，先把闭环跑通

- 把 `claude/cloud-sync-m0` rebase 到当前主线（它基于 v0.10.4，主线已到 v0.11.0）。
- 用 `git worktree` 单独检出，避免污染当前工作分支。
- 家里服务器（Mac mini 或已有 Linux 云主机）+ Cloudflare Tunnel + 域名，跑
  两台 Mac 的真实同步：A 上传 → B 拉取解密 → 合并历史 → 本机账本不受影响。
- 验收：`verify` 不把同步数据算进本机合计；两台机器同日同应用的行按 device 分桶，
  不双算；断网重试幂等。
- 这一阶段不需要任何账号、备案、主体。

### P1（小范围内测）：轻账号 + 兑换码会员

- 账号：邮箱 Magic Link（默认）或 GitHub OAuth（开发者向）；不碰微信生态。
- 会员：沿用 M1 的「兑换码 → 本地 Ed25519 license」；license 绑邮箱/sub，不绑 space。
- 设备管理：设备列表、解绑、替换旧设备（解决卸载重装产生新 device 重复计）。
- 仍然只存密文；账号服务只存 email hash + license 状态。
- 验收：换机后能恢复设备列表和历史；退订不影响已有数据读取。

### P2（公开/收费）：有主体再上微信

- 注册个体工商户/企业 → ICP 备案（网站 + 可能需要的 APP 备案）→ 微信开放平台
  网站应用 + 300 元/年认证 → 微信扫码登录。
- 托管迁到国内轻量云（备案一致）或 Cloudflare Workers（若不想备案，但微信回调域名
  仍需备案，二者通常绑定）。
- 验收：备案号展示、隐私政策、数据删除/导出通道、退款流程。

---

## 6. 待拍板的三件事

1. **账号**：先无账号（推荐）/ 邮箱或 GitHub 轻账号 / 注册个体户走微信 / Apple 网页登录。
2. **托管**：家里 Mac mini + Tunnel / 已有 Linux 云主机 + Tunnel / Cloudflare Workers。
3. **商业化时点**：现在只自用 / 小范围免费内测 / 准备收费（决定是否马上办主体和备案）。

---

## 参考

- 微信开放平台·网站应用授权登录：https://developers.weixin.qq.com/doc/oplatform/developers/dev/auth/web
- 微信开放平台·网站应用平台介绍（授权回调域/业务域）：https://developers.weixin.qq.com/doc/oplatform/developers/product/webapp/
- 微信开放平台·域名管理：https://developers.weixin.qq.com/doc/oplatform/developers/basic_func/domain.html
- 微信开放平台·注册与开发者资质认证：https://developers.weixin.qq.com/doc/oplatform/Third-party_Platforms/2.0/operation/open/create.html
- 微信开放社区·个人主体无法申请微信登录：https://developers.weixin.qq.com/community/develop/doc/00040a139982c0478f157079466800
- 支付宝·个人账号注册及实名认证：https://opendocs.alipay.com/common/02kg61
- 支付宝·个人账号认证个体工商户：https://opendocs.alipay.com/common/02kkul
- 支付宝·创建应用：https://opendocs.alipay.com/open/009yp4
- 抖音开放平台·入驻标准（个人仅小玩法）：https://developer.open-douyin.com/m/docs/resource/zh-CN/developer/join/join-into-developer-platform
- 抖音开放平台·入驻常见问题：https://developer.open-douyin.com/m/docs/resource/zh-CN/developer/join/issues
- Apple·Supported capabilities (macOS)：https://developer.apple.com/help/account/reference/supported-capabilities-macos
- Apple 开发者论坛·Developer ID 不支持 Sign in with Apple：https://developers.apple.com/forums/thread/671319
- Apple·Configuring Sign in with Apple：https://developer.apple.com/documentation/xcode/configuring-sign-in-with-apple/
- 《互联网信息服务管理办法》：https://www.miit.gov.cn/jgsj/zfs/xzfg/art/2020/art_0bf50f171cbf4e5aaca30553d8762d64.html
- 《非经营性互联网信息服务备案管理办法》：https://wap.miit.gov.cn/zcfg/xxtxl/art/2024/art_7c8cc677bfb7433e93e31bbad81142ef.html
- 工信部·移动互联网应用程序备案通知：https://wap.miit.gov.cn/jgsj/xgj/wjfb/art/2023/art_dd783a581c9644a4aee10afa582811db.html
- Cloudflare China Network：https://www.cloudflare-cn.com/application-services/products/china-network/
- Cloudflare·China Authoritative DNS：https://developers.cloudflare.com/china-network/concepts/china-dns/
- Cloudflare Workers·Limits：https://developers.cloudflare.com/workers/platform/limits/
- Cloudflare Workers·Pricing：https://developers.cloudflare.com/workers/platform/pricing/
- Cloudflare Tunnel 调参实录（QUIC/TCP 7844）：https://cloud.tencent.cn/developer/article/2765819
- Cloudflare Tunnel 国内实测（延迟/带宽）：https://songlin.me/2026/04/19/tunnel/
- Cloudflare 国内访问与备案要点：https://chendahuang.com/playbook/cloudflare/chapters/06-china-access
