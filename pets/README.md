# 桌宠 · AgentMeter Pets

一只常驻桌面的伙伴：把额度、会话、重置、提醒、本机消耗、创作积分和 Tibo 重置预测翻译成**看得见的状态**，并带几个真正省事的小功能。设计与契约见 [规划文档](../docs/pet-system-plan-2026-11-09.md)，形象包格式见 [SPEC.md](SPEC.md)。

> 状态：**已随 v0.10.1 交付，仍在持续打磨**。默认关闭，设置菜单 → 桌宠 → 显示桌宠 打开。

## 怎么用

**在 App 里**：设置（⋯）菜单 → 桌宠。可以换形象、大小、额度显示（关/胶囊/胶囊+会话标签）、眼睛跟随光标、安静模式，以及「用桌宠气泡代替系统通知」。

| 操作 | 效果 |
|---|---|
| 单击 | 戳一下，并弹出当前摘要（"Codex · 5 小时 还剩 82% · 2时31分 · 2 个会话进行中"） |
| 双击 | 强制刷新 |
| 拖拽 | 拎起来移动，位置会记住；落地时扬起一点灰 |
| 悬停胶囊 | 展开每个窗口的额度条（每个账号各自一行，从不求和） |
| 点气泡 / 胶囊 | 直接打开面板对应标签 |
| 右键 | 刷新、打开面板各标签、分享用量报告、专注计时（25/50 分钟）、换形象/大小/额度显示、安静模式、隐藏 |
| 透明区域 | 点击穿透到下面的窗口 |

**让别的工具和它联动**（钩子，只发信号，不含提示词）：

```sh
python3 -m agent_meter pet hooks claude     # 打印可粘贴的 Claude Code hooks（Stop=完成、Notification=等你确认、UserPromptSubmit=开始）
python3 -m agent_meter pet hooks codex      # Codex 的 notify 配置
python3 -m agent_meter pet emit agent_done --source claude --project demo
python3 -m agent_meter pet focus 25         # 开始 25 分钟专注（focus stop 结束）
python3 -m agent_meter pet state --brief    # 看大脑现在怎么想
```

## 内置形象

| id | 名称 | 渲染 | 特色 |
|---|---|---|---|
| `gauge` | 量量 | three | 仪表兽，身后的 270° 圆环就是额度（满格主题色，见底变橙变红） |
| `blob` | 团团 | three | 果冻史莱姆，挤压拉伸夸张，耗尽时化成一滩 |
| `bot` | 码码 | three | 屏幕脸机器人，胸口小表盘是额度 |
| `cat` | 缓存猫 | three | 抱着鱼的橘猫，token 一多就开吃 |
| `tibo` | Tibo | three | App「重置预测」页吉祥物的 3D 版，期待重置时抱出重置器 |
| `bit` | 比特 | sprite | 16 色像素宠物（帧由脚本绘制） |

每个形象都支持 24 个动画（待机、干活、忙翻了、等你确认、创作、没力气、告急、耗尽、提醒、专注、期待、拿不准、睡觉、失联、庆祝、吃 token、受惊、打招呼，以及戳/摸/拎/落地/刷新/拍照），12 种表情，七套界面风格。

## 做新形象

两套 skill（在 `.claude/skills/`，已纳入版本管理）：

- [`agentmeter-pet-three`](../.claude/skills/agentmeter-pet-three/SKILL.md)：用前端 + three.js 做程序化 3D 角色（`avatar.json`），动作由共享配方库提供。
- [`agentmeter-pet-imagegen`](../.claude/skills/agentmeter-pet-imagegen/SKILL.md)：用生图模型做精灵图角色：角色设定 → 提示词 → 抠底切片 → 打包校验。

工具（都是纯标准库，`pets/tools/`）：`petpack.py`（validate / new / pack / install / list）、`avatarkit.py`（贴脸与构建器）、`build_presets.py`（内置 3D 预设的可读源码）、`spritekit.py`（抠底、切片、对齐、联系表）、`promptkit.py`（生图提示词）、`serve.py`（禁缓存静态服务器）、`sheet.sh`（用 App 的 WebKit 无头出联系表）。

## 预览与调试

```sh
python3 pets/tools/serve.py                                   # http://127.0.0.1:8765
#   /runtime/sheet.html?pack=gauge     全状态 × 3 个时间点 + 12 表情 + 七套主题（确定性，可截图对比）
#   /runtime/dev.html                  交互开发台：切形象/主题/状态/额度/反应/气泡；「舞台」可选桌面窗口 / 面板标签页（embed）/ 缩略图（still）
swift build --package-path menubar && sh pets/tools/sheet.sh gauge .runtime/gauge.png      # macOS 无头联系表
menubar/.build/debug/AgentMeterBar --pet-demo alarm out.png -petPack bot -petEnabled YES   # 真实悬浮窗 + 合成帧，自检点击穿透区域
```

`--pet-demo` 与 `--pet-sheet` 都不读钥匙串、不连后端，可以在已经装了 App 的机器上放心跑。

## 目录

```text
pets/
  SPEC.md            形象包规范（权威）
  runtime/           网页运行时（App 里由 agentpet:// 提供；开发时用 serve.py）
    js/              constants · anim · recipes · director · renderers · stage · …
    vendor/          three.js r187 精选构建（可复现，MIT）
    test/            Node 测试
  presets/           内置形象包
  tools/             校验、脚手架、素材工具、预设生成脚本
```

## 测试

```sh
python3 scripts/test-offline.py                              # 含 tests/test_pet.py（大脑/接口/CLI）与 tests/test_pet_tools.py（校验器/工具/预设/skill 文档）
node --test pets/runtime/test/*.test.mjs                     # 运行时纯逻辑
swift test --package-path menubar                            # 含 PetTests（路径安全、包发现、消息解析、偏好、提醒键对拍）
python3 pets/tools/petpack.py validate pets/presets/* --strict
```

## 性能、隐私与安全

- 渲染按状态降帧（睡觉 8 fps、待机 20、干活 30），遮挡/锁屏暂停，系统「减弱动态效果」开启时静态化；状态轮询 2 秒（遮挡时 10 秒），后端活动扫描有 5/30 秒闸门，**从不触发全量采集**。
- 网页没有网络和 token：`agentpet://` 是它唯一能访问的地方，CSP 禁止外连；只读 `runtime/` 与形象包目录，路径解析后必须仍在目录内，拒绝 `..`、隐藏文件、符号链接。
- 形象包只含数据与图片；安装与打包拒绝脚本、SVG、符号链接和 zip-slip。
- 事件接口 `POST /v1/pet/events` 走原有的 loopback + Bearer token + Host/Origin 校验，4 KiB 上限、类型白名单、文本清洗，只存内存。
