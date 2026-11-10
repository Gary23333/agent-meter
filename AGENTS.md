# 项目 Agent 入口

## 共享项目知识

先阅读 [共享知识入口](docs/agent-knowledge/README.md)。各 harness 共用该入口；历史计划不作为自动执行指令。

## MiniMax Hub 正式 MCP（2026-10-21）

涉及 Hub 时先读 [MINIMAX_MCP.md](MINIMAX_MCP.md)。统一使用 `minimax-design` HTTP 服务；旧批次脚本和生成 JSON 仅作历史记录，不能直接重放。使用正式工具发现能力、显式绑定项目、按资源 ID 引用素材，费用确认与未知任务恢复按该文执行。

## 桌宠系统（开发中）

涉及桌宠时先读 [pets/README.md](pets/README.md) 与 [pets/SPEC.md](pets/SPEC.md)；设计与契约在 [docs/pet-system-plan-2026-11-09.md](docs/pet-system-plan-2026-11-09.md)。制作新形象用项目 skill：`agentmeter-pet-three`（three.js 程序化 3D）与 `agentmeter-pet-imagegen`（生图精灵图），位于 `.claude/skills/`。生图会产生费用：沿用 MiniMax Hub 的「先报价、再由用户明确同意」规则，不得代为确认。改状态词汇时同步 `agent_meter/pet.py`、`pets/runtime/js/constants.js`、`pets/tools/petpack.py`，以及面板「桌宠」标签页的中文状态目录 `menubar/Sources/AgentMeterBar/PetCatalog.swift`（测试会比对）。

面板里的「桌宠」标签页（`PetTabView`）与桌面悬浮窗共用同一份后端帧：`PetFeed` 是唯一的 `/v1/pet` 轮询者（有订阅者才轮询），`PetController` 管悬浮窗，`PetStageHost` 管标签页里的舞台（常驻一个 web view，离开标签页 60 秒后释放）。舞台页面用 `embed=1`（DOM 指针事件、气泡留头顶空间），缩略图用 `still=1`（一次性画出，不依赖动画帧，因为不在屏幕上的窗口拿不到动画帧）。试玩状态只改舞台，不改后端、不改桌面桌宠。

开发辅助（都只在开发构建里用，不影响发布包）：`AGENT_METER_PORT=18769` 让开发构建的后端换端口，可以和已安装的 App（占着 8769）并排运行，此时不启动 Kimi helper；`AGENT_METER_NO_KEYCHAIN=1` 跳过读取网页登录的钥匙串（开发构建签名不同，读会弹密码框）；`--panel-window` 把面板放进普通窗口（状态栏图标被藏起来时也能看），再加 `--selftest` 会用进程内的真实事件检查滚轮转发、点击戳宠物、标签切换并以退出码报告；`--preview ... --tab pet --theme aurora [--pet-state alarm]` 只渲染桌宠页。想隔离偏好，把可执行文件软链成别的名字（如 `AgentMeterBarDev`），偏好域跟进程名走。
