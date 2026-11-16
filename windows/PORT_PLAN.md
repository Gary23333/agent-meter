# Windows 版移植与验收计划

目标是以 [Gary23333/agent-meter](https://github.com/Gary23333/agent-meter) v0.11.0（提交 `ac547d0`）为对照，完成具备相近功能完整度与视觉质量的 Windows 版本。系统托盘是常驻入口；账户额度与本机账本分别计量。保留原作者 MIT 版权声明，并在仓库、安装包中说明依赖与来源。

## 与 Mac 版逐项对照

| 功能或界面 | Windows 当前状态 | 后续验收 |
| --- | --- | --- |
| 托盘入口、余量与交互 | 无边框弹层、外部点击及 Esc 收起、固定与更多菜单；数字图标可选来源或自动最低余量，过期数据回退；额度环超过四个时分页切换；细滚动轨道独立裁剪并验证拖动 | 实机验证隐藏图标、菜单、圆角阴影、退出清理、多屏和高 DPI；继续打磨小尺寸表现 |
| 账户额度 | Codex 已在本机实测；Kimi 本地服务、Claude Code 凭据、MiniMax 和 DeepSeek API 余额通过模拟测试；已加入默认关闭的 WorkBuddy 独立网页登录及积分查询，主动输入密钥的智谱和火山方舟 Coding Plan 额度，以及独立网页登录的 MiMo 平台余额和套餐（模拟验证） | 验证托盘开关交互及真实 Windows 账户和 WorkBuddy 登录；Qoder 中国区独立网页登录和只读额度已模拟验证，真实登录尚待验收；TRAE 中国区独立登录与只读额度正以模拟数据验证；继续适配即梦及其他原项目来源 |
| 应用和本机消耗 | 多个本地账本、四个统计周期、Token 构成圆环、缓存命中、模型排行、趋势及近 24 小时应用活动汇总已接入；额度、本机 Token、活动来源状态按应用汇总，并支持筛选和展开。应用页可见时单独刷新本机活动；Qoder 本机积分独立计量 | 验证真实账本、应用概览、定时刷新、趋势与排行界面；完善客户端路径、项目归因、历史导入和重复计数规则 |
| 模型与计费 | 使用上游内置价格和固定回退汇率，展示逐账本的今日美元 API 等价估算；支持本机自定义美元价格 | 验证实际账本和价格编辑界面；移植模型目录同步、更多周期、峰谷与汇率设置 |
| 七套主题与卡片 | 七种配色、连续胶囊导航和服务语义图形已接入；账户页保留双周期仪表，其他页使用紧凑头部。账户时钟可见时按分钟更新。钱包、积分、套餐和 Codex 重置卡到期明细整合进对应卡片；本机汇总和逐日趋势明确未按账户区分 | 对照上游逐套实机检查与完善材质、动效、账户卡片、多账户归因和自适应布局；仍未达到完整视觉一致 |
| 通知与自动领取 | 低额度提醒默认关闭，可在托盘菜单开启并选择 10%、20%、30% 或 50% 阈值；同周期去重和过期快照过滤已做模拟测试；新增独立的 Codex 重置卡到期提醒 | 实机验证 Windows 通知；继续移植积分和订阅提醒；自动领取默认关闭，逐平台验证写操作与授权 |
| 多账号 | MiniMax 最多 5 个账户独立查询；密钥保存在 Windows 凭据管理器，账户列表和查询链路已用模拟数据测试 | 实机验证账户管理窗口和真实账户；扩展其他服务的隔离与切换 |
| 重置预测 | 默认关闭，区分公布值与模型值；新增上游加权中位数、站点范围、明确时间窗口倒计时及最多 40 条历史。超过 48 小时的来源不参加综合预测，时间到点只提示待确认 | 验证真实网站字段变化与界面交互；继续完善原版的承诺摘要、插画和落地验证，不把预测当作个人账户重置 |
| 用量报告与分享 | 已加入本机自然周、自然月的基础报告、Markdown 汇总和随主题切换的 PNG 分享图；深浅两种演示图已检查 | 验证报告与导出界面、真实账本和其他主题；完善内容开关及隐私说明 |
| 收集册和奖章 | 已初步复用上游规则计算本机用量、图片文件和 API 等价估算花费徽章，并提供 5 小时和 7 天额度掉落卡片；额度状态与卡册保存在本机 | 验证真实账本、账户与页面，补充签到、重置卡、创作积分等项目以及动效和分享；提示来源不完整与账本重叠 |
| 桌面宠物 | 已复用上游两套精灵图及五套 3D 形象，接入默认关闭的原生悬浮窗和额度／近期活动状态；弹层可选择形象，并在桌宠显示时同步画面与状态；3D 点击、拖放、刷新及可选视线跟随在隔离构建机验证 | 实机验证透明穿透、拖动、视线、多屏、生命周期、性能和高 DPI；继续移植更多状态与互动 |
| 中文体验与文档 | 中文首页、快速使用、安全和贡献说明正在调整；英文作为辅助 | Windows 新代码的说明与注释以中文为主，保证 README、实际行为及下载版本一致 |

## 当前证据和限制

- [Alpha 39 预览版](https://github.com/FoxBai/agent-meter-windows/releases/tag/windows-v0.1.0-alpha.39) 对应提交 `8d303c4`；Windows 构建、后台唤起、托盘弹层生命周期和真实屏幕绘制检查通过。页面导航、应用筛选及用量周期切换后的画面已用虚构数据核对，发布包独立解压与模拟数据验证通过。真实设备上的新版、高 DPI、多屏及真实新增账户仍待验收。SHA-256：`4af5adc2b0051c18c9080132af54e684d9d6c2a000272d7bd64371c76b923e55`。

- [Alpha 38 预览版](https://github.com/FoxBai/agent-meter-windows/releases/tag/windows-v0.1.0-alpha.38) 对应提交 `cb98224`；Windows 和跨平台检查通过。用量双卡片、周期切换、未知费用与窄屏标签在隔离环境检查，深浅截图已核对，便携包独立解压与模拟数据验证通过。真实账本与实体设备仍待验收。SHA-256：`996f4c9beb5b907483fbd378a84eaea3da11b528d9c4a449722725eb5487e03c`。

- [Alpha 37 预览版](https://github.com/FoxBai/agent-meter-windows/releases/tag/windows-v0.1.0-alpha.37) 对应提交 `82c7c36`；Windows 和跨平台检查通过。模拟账本的 Token 构成、缓存比例、异常值及缺失状态通过检查，深浅主题和窄弹层截图已核对，便携包独立解压验证通过。真实账本与实体设备仍待验收。SHA-256：`7af19f87106592b3881358319e70eaaa6b15469f33865ff3775bd8195f6d0575`。

- [Alpha 36 预览版](https://github.com/FoxBai/agent-meter-windows/releases/tag/windows-v0.1.0-alpha.36) 对应提交 `d461a07`；Windows 和跨平台检查通过。两类桌宠的画面通知、页面同步、隐藏回退及窄弹层截图在隔离环境检查，便携包独立解压与模拟数据验证通过。实体设备的动画性能、透明穿透、多屏与高 DPI 仍待验收。SHA-256：`164e4122bdf2c2d888d972d62ed5cb553e0c0fb2b6d7e88a90f8bb5c8b651aee`。

- [Alpha 35 预览版](https://github.com/FoxBai/agent-meter-windows/releases/tag/windows-v0.1.0-alpha.35) 对应提交 `de1ead0`；Windows 和跨平台检查通过。视线跟随默认关闭、旧设置兼容、模拟左右位置及开关界面在隔离环境检查，便携包独立解压与模拟数据验证通过。实体鼠标、多屏、高 DPI 和性能仍待验收。SHA-256：`f72ceb41f23ff10749ccc67b6589af16cbbde4e8186c25621cfff1f0ed954e03`。

- [Alpha 34 预览版](https://github.com/FoxBai/agent-meter-windows/releases/tag/windows-v0.1.0-alpha.34) 对应提交 `0a034ca`；Windows 和跨平台检查通过。动作队列顺序、拥塞恢复、四种原版动画状态及画面变化经过隔离检查，便携包独立解压与模拟数据验证通过。真实鼠标交互、透明穿透、高 DPI 和性能仍待验收。SHA-256：`c51f7bd48c4f1e706cd270c7565dff3ffbe7e2b58ee8d11b54cdcbe7665f5902`。

- [Alpha 33 预览版](https://github.com/FoxBai/agent-meter-windows/releases/tag/windows-v0.1.0-alpha.33) 对应提交 `25fa1d2`；Windows 和跨平台检查通过。七种主题和窄弹层截图、桌宠选择与开关、横向滚动条和缩放后纵向位置均在隔离构建机检查；便携包独立解压及模拟数据验证通过。实体设备上的桌宠交互、性能、高 DPI 仍待验收。SHA-256：`876162ecf3d35718e47366805f924dce94fa6fb2dbe052c610a1d990d46f4c7c`。

- [Alpha 32 预览版](https://github.com/FoxBai/agent-meter-windows/releases/tag/windows-v0.1.0-alpha.32) 对应提交 `0b0433d`；Windows 和跨平台检查通过。五套原版 3D 形象、透明帧、状态变化、外部请求拦截及原生窗口首帧在隔离构建机检查，便携包独立解压及模拟数据验证通过。真实设备的透明穿透、拖动、高 DPI 和性能仍待验收。SHA-256：`c9bbc1869a9638023365d6b25cfb3d6107266ffc8e654036a7ec530aac8d6add`。

- [Alpha 31 预览版](https://github.com/FoxBai/agent-meter-windows/releases/tag/windows-v0.1.0-alpha.31) 对应提交 `7b1184d`；Windows 和跨平台检查通过。模拟 PNG 文件的时间统计、重定向保护、图片徽章及隐私投影已检查，便携包隔离解压通过；真实图片目录与实体设备仍待验收。SHA-256：`f807f37c5872f2c027cf44f7a9883d2b1b7f6c59cea4bab2f9f072e9b152c5ef`。

- [Alpha 30 预览版](https://github.com/FoxBai/agent-meter-windows/releases/tag/windows-v0.1.0-alpha.30) 对应提交 `6142229`；Windows 和跨平台检查通过。完整与缺失价格的模拟账本、固定汇率、花费徽章界面和独立解压包已检查；真实账本与实体设备仍待验收。SHA-256：`f5fb94375b8e5c6a29f6ab8849feb0a7255957987e16f58101b8101670de7fb7`。

- [Alpha 29 预览版](https://github.com/FoxBai/agent-meter-windows/releases/tag/windows-v0.1.0-alpha.29) 对应提交 `dbf6297`；Windows 和跨平台检查通过。保留测试域名用于验证独立 WebView 的模拟请求头捕获、关闭来源和资料清除，模拟账户接口、缺失数据界面和便携包也已检查；真实 TRAE 登录及凭据续取尚待验收。SHA-256：`e2ec785827bf43fd7b92a4b6165cd44d31bf3c6afd144315a526a8aa975dde74`。

- [Alpha 28 预览版](https://github.com/FoxBai/agent-meter-windows/releases/tag/windows-v0.1.0-alpha.28) 对应提交 `a5b1af3`；Windows 和跨平台检查通过。Qoder 独立登录资料、Cookie 过滤和模拟账户接口通过隔离测试，账户卡片、多账户分页和刷新菜单演示已检查；真实 Qoder 登录、系统通知、多屏及高 DPI 尚待验收。SHA-256：`4002341fbec7135c18383a862e0906e10b988b2cf5d15c2c456f70ab0df6b15c`。

- [Alpha 27 预览版](https://github.com/FoxBai/agent-meter-windows/releases/tag/windows-v0.1.0-alpha.27) 对应提交 `f78bd1d`；Windows 和跨平台检查通过，隔离环境检查了 Qoder 本机积分卡片、缺失记录和窄窗口，便携包通过模拟账本校验；真实 Qoder 本机数据仍待验收。SHA-256：`d6de27ba393dc3a7c752884490399291295fd152c8add894fc6f2e133c4d2e01`。

- [Alpha 26 预览版](https://github.com/FoxBai/agent-meter-windows/releases/tag/windows-v0.1.0-alpha.26) 对应提交 `7ce5bdc`；Windows 和跨平台检查通过。独立提醒开关、到期阶段、过期快照和旧设置兼容经过模拟检查，托盘菜单与深色额度环演示已核对；通知实际显示仍待实体设备验收。SHA-256：`ce22f6dfc45dbc5304acde2802592b9eb34c85a0cc371f3ce9a0d12a3aaab7a8`。

- [Alpha 25 预览版](https://github.com/FoxBai/agent-meter-windows/releases/tag/windows-v0.1.0-alpha.25) 对应提交 `5a0786e`；Windows 和跨平台检查通过。解压包在隔离的模拟账本中验证了 OpenCode v1/v2 去重、活动汇总和隐私字段，真实 OpenCode 安装仍待验收。SHA-256：`74a539a107125090a8d868ff60e5ca750f7496cde0056fdc6a6539ea9d411a9e`。

- [Alpha 24 预览版](https://github.com/FoxBai/agent-meter-windows/releases/tag/windows-v0.1.0-alpha.24) 对应提交 `e9c33e6`；Windows 和跨平台检查通过。提醒阈值、旧设置兼容、过期数据过滤和异步账户结果经过模拟检查，隔离环境菜单演示与便携包校验通过；系统通知显示仍待实体设备验收。SHA-256：`d49ff83bd586bfed0e21efd7b69a847076354bc26c36ac6f1994d6365ed5ce78`。

- Codex 账户额度和本机历史已在开发电脑上读取；Codex 累计 Token 与原始记录独立重算一致。WorkBuddy 和 ZCode 今日及累计账本也与独立重算一致；不代表其他账户或版本均已验证。
- Kimi、OpenCode、MiniMax Code、MiMo Code、DevEco 和 Qoder CN 的新增读取器目前以模拟数据验证为主。Kimi 账户通过模拟本地服务测试；Claude Code 账户使用模拟本地凭据及模拟接口响应测试；两者均尚无真实 Windows 账户验收。OpenCode v2 助手消息和近期活动经过模拟测试；压缩记录和无法识别的数据标记不完整，真实账本仍待验收。
- 真实大账本首次扫描约 91 秒，同一进程内第二次约 1.3 秒；缓存只保存在内存，文件变化会重新读取。测试结果只适用于本机数据规模。
- GitHub Windows 运行器已构建便携包并通过隔离数据和程序启动检查；开发电脑也验证了解压启动。完整托盘交互与另一台独立实体电脑尚未验证。
- 此前公开的 [Alpha 7 预览版](https://github.com/FoxBai/agent-meter-windows/releases/tag/windows-v0.1.0-alpha.7) 并非完整移植，尚未代码签名。该包对应提交 `033d7b9`；Windows 构建和跨平台检查通过，解压包已用隔离账本验证价格、活动汇总隐私、徽章与卡片、账户开关、DeepSeek 默认关闭和预测缓存，卡册展开与桌宠窗口在隔离构建机完成基础检查。主题、通知、完整托盘交互和真实新增账户仍待实机验收。
- [Alpha 8 预览版](https://github.com/FoxBai/agent-meter-windows/releases/tag/windows-v0.1.0-alpha.8) 对应提交 `1e34c58`；独立构建机以虚构 Cookie 验证 WebView2 资料读取和清除，安装包通过隔离数据检查。WorkBuddy 真实登录尚未验证。
- [Alpha 9 预览版](https://github.com/FoxBai/agent-meter-windows/releases/tag/windows-v0.1.0-alpha.9) 对应提交 `dfb9233`；构建与隔离数据检查通过，已检查账户卡片的深色、浅色和窄窗口演示图，真实设备仍需验收。
- [Alpha 10 预览版](https://github.com/FoxBai/agent-meter-windows/releases/tag/windows-v0.1.0-alpha.10) 对应提交 `5be3690`；账户卡片的本机汇总、30 日曲线和滚动演示已检查，安装包通过隔离账本和隐私字段检查。
- [Alpha 11 预览版](https://github.com/FoxBai/agent-meter-windows/releases/tag/windows-v0.1.0-alpha.11) 对应提交 `1067f97`；应用概览的筛选和展开在隔离构建机通过基础检查，深浅色和窄窗口演示已检查，实体设备仍需验收。
- [Alpha 12 预览版](https://github.com/FoxBai/agent-meter-windows/releases/tag/windows-v0.1.0-alpha.12) 对应提交 `68d9010`；活动刷新条件、打包后的隔离数据读取和隐私字段过滤已检查，界面定时交互和资源占用仍需实机验收。
- 主分支提交 `9b8b412` 后，在隔离 Windows 构建机用虚构数据验证了活动刷新触发、间隔、切换页面取消、隐藏时停止及重新打开后恢复；实体设备上的定时器和资源占用仍需验收。
- [Alpha 13 预览版](https://github.com/FoxBai/agent-meter-windows/releases/tag/windows-v0.1.0-alpha.13) 对应提交 `dc8d948`。Windows 构建与跨平台检查通过；隔离 Windows 构建机检查了弹层固定、菜单保护、子窗口保护、失焦收起、Esc 和翻页键，生成 59 张虚构数据预览，主要深浅主题、窄窗口和菜单已检查。ZIP 独立解压验证了本机账本、隐私字段、账户开关、卡册和预测合并／历史／缓存。真实任务栏、多屏、高 DPI、窗口阴影及真实新增账户仍未完成实机验收。

- [Alpha 14 预览版](https://github.com/FoxBai/agent-meter-windows/releases/tag/windows-v0.1.0-alpha.14) 对应提交 `859e948`。Windows 与跨平台检查通过；隔离 Windows 构建机验证了托盘来源反复切换、图标克隆与释放、细轨道拖动、重置卡展开和收起。生成 63 张虚构数据预览，七种账户主题、深浅色到期状态、主要页面和图标尺寸已检查。最终 ZIP 独立解压验证通过，SHA-256 为 `120044d0b297632498ed9b62f81a662965251f4e1c8f603a551b210ede92e26f`。真实新增账户与多屏、高 DPI、隐藏图标区仍需实体设备验收。

- [Alpha 15 预览版](https://github.com/FoxBai/agent-meter-windows/releases/tag/windows-v0.1.0-alpha.15) 对应提交 `ebe7419`。Windows 构建及跨平台检查通过；结构化本机 Token 汇总导出通过虚构数据隐私、未知值和零值检查。隔离 Windows 构建机生成 64 张演示预览，已查看窄面板导出入口；ZIP 独立解压并验证历史、隐私字段、卡册及预测缓存。SHA-256：`6fb3301b108a8d640d6b46c4334c488558fc505a79d58ff69bb1549de2a2e393`。真实保存对话框及实体设备验收仍待完成。

- [Alpha 16 预览版](https://github.com/FoxBai/agent-meter-windows/releases/tag/windows-v0.1.0-alpha.16) 对应提交 `44180cb`；四周期切换、偏好、分周期费用与主题图表通过隔离检查。Windows 和跨平台检查通过；ZIP 独立解压验证通过，SHA-256：`9bfe8176501d200343415534ca2906e5dbc92e14626b80b899f4955998154f6d`。真实账户与多屏、高 DPI 仍需实体设备验收。

- [Alpha 17 预览版](https://github.com/FoxBai/agent-meter-windows/releases/tag/windows-v0.1.0-alpha.17) 对应提交 `e11aff9`。自然日对照、跨月及零值边界通过测试，深浅主题和窄弹层演示已检查，ZIP 独立解压校验通过。Windows 构建和跨平台 Python、桌宠检查通过，该次 macOS Swift 检查因后续提交取消，Alpha 18 跨平台检查通过；真实设备验收仍未完成。SHA-256：`37c157d0d12421b49dbabf9eed3c9baf17dd04bc9f2f9dd8d3931987897703ce`。

- [Alpha 18 预览版](https://github.com/FoxBai/agent-meter-windows/releases/tag/windows-v0.1.0-alpha.18) 对应提交 `2a10554`。Windows 构建、隔离注册表启停和后台启动检查通过，ZIP 独立解压校验通过。跨平台 Python、桌宠及 macOS Swift 检查通过；实体设备上的登录启动、多屏与高 DPI 仍需验收。SHA-256：`e9ba169d8a78f75025397e90546b2210fdae52c8e6455edd5a2f815e45256aea`。

- [Alpha 19 预览版](https://github.com/FoxBai/agent-meter-windows/releases/tag/windows-v0.1.0-alpha.19) 对应提交 `fe0756d`。Windows 和跨平台检查通过；智谱密钥、固定接口、余额类型、托盘、提醒和无密钥状态以模拟数据验证，账户和设置窗口预览已检查；ZIP 独立解压验证通过。真实智谱账户、多屏及高 DPI 尚待实体设备验收。SHA-256：`6b500bf2922ae74cdc6b6e477f90fef99f11ac15e3cb1aef32c7655761f08280`。

- [Alpha 20 预览版](https://github.com/FoxBai/agent-meter-windows/releases/tag/windows-v0.1.0-alpha.20) 对应提交 `ffe827c`。同周期费用汇总、未知值与免费价格通过检查；深浅主题、窄弹层和圆角导出按钮实渲染已检查。Windows 与跨平台检查通过，ZIP 独立解压验证通过。SHA-256：`e80f6b648aa8ff7bb6d4221c9c926f60d36cfe5ee1706956a32c433fd555e9a1`。真实新增账户、多屏与高 DPI 仍需实体设备验收。

- [Alpha 21 预览版](https://github.com/FoxBai/agent-meter-windows/releases/tag/windows-v0.1.0-alpha.21) 对应提交 `1085ebe`。Windows 与跨平台检查通过；火山方舟签名、缺失凭据离线、窗口及额度展示以模拟数据验证，ZIP 独立解压通过。SHA-256：`8ba09f77d9aab6512fb12fbd8cc8469dc71281d225bec13afc13f2ca44b636d7`。真实账户及权限、多屏和高 DPI 尚待实体设备验收。

- [Alpha 22 预览版](https://github.com/FoxBai/agent-meter-windows/releases/tag/windows-v0.1.0-alpha.22) 对应提交 `e8fd83c`。Windows 与跨平台检查通过；胶囊筛选、重置卡和收藏展开在隔离构建机检查，深浅主题圆角实渲染已核对，ZIP 独立解压通过。SHA-256：`3895d9596ddbc7b2e0a974af3d868f65008200bdc67522106769fec74bce74ea`。真实账户、多屏与高 DPI 仍需实体设备验收。

- 此前公开的 [Alpha 23 预览版](https://github.com/FoxBai/agent-meter-windows/releases/tag/windows-v0.1.0-alpha.23) 对应提交 `1bcb8f4`。Windows 和跨平台检查通过；MiMo Cookie 过滤、独立 WebView2 资料、模拟接口与错误状态已检查，账户和登录窗口预览已核对，ZIP 独立解压通过。SHA-256：`9f1da5f30b1899e6f14707bf5de77ff24a1012c026225d073b6bbce2f47268dc`。真实小米登录和账户、多屏及高 DPI 尚待实体设备验收。

## 安全与数据边界

托盘弹层的交互与视觉约定见 [Windows 托盘弹层设计](DESIGN.md)。

读取用量只应访问对应的本机账本和已授权账户接口；凭据、对话、账户快照和真实截图不得进入日志、测试夹具或公开仓库。缺失不等于零，不同服务的积分不混算，本机历史不等于账户总量。涉及联网、登录、导出、自动领取和桌宠分享时，分别说明数据来源、写操作和用户控制方式。

