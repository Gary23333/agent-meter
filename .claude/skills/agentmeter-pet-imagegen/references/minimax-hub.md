# 用本项目的 MiniMax Hub MCP 生图

这是 [MINIMAX_MCP.md](../../../../MINIMAX_MCP.md) 的生图子集；那份文档是权威，工具与能力 ID 以**当次会话实际返回的契约**为准（不要沿用历史枚举或虚构能力 ID）。本 skill 写成时**没有真正调用过生成**（会产生用户的费用），下面的顺序来自该文档与工具说明。

## 前置

- 服务名 `minimax-design`（Streamable HTTP `http://127.0.0.1:18810/mcp`），需要本机 MiniMax Design.app 运行并登录。会话里没有这组工具就让用户新开会话，或用 `scripts/minimax_mcp.py` 客户端（见 MINIMAX_MCP.md）。
- **必须有一个用户明确指定并已在 Design 中打开的项目**。不要自己 `create_project`（会在用户的账户里新建东西），不要用目录修改时间猜项目。

## 调用顺序

1. `list_projects {}` → 让用户选 projectId → `open_project {"projectId":"…"}`。`open:false` 时请用户在应用里打开该项目。
2. `capability_list {"operation":"generate_image"}` 找当前账号可用的图像能力，再 `capability_get {"ids":["<能力ID>"]}` 读 `paramSchema`、是否支持**参考图**、支持的画幅、计费说明。选支持参考图的能力。
3. **把参考图导入项目**：`deliver` 只接受项目工作区内、非符号链接、非空文件（当日上限 50 MiB），不接受 URL 或工作区外路径。把 `work/<id>/reference.png` 复制进工作区后 `deliver`，得到 `resourceId/versionId`；之后用它们作为 `references`（按顺序）。
4. `execute`：`capabilityId`、`prompt`（用 `promptkit` 产出的文本）、**扁平** `params`（画幅等，按 `paramSchema`）、`references`（参考图的资源标识，**不要把文件路径放进 params**）、`count`（先 1–2）、`output`（新资源 `mode:"create"` + composition placements，结构见 MINIMAX_MCP.md 的示例）。
5. `execute` 返回 task 后保存 `task.id`；未结束就 `task_wait {"taskId":"原ID"}` 反复等，**超时/断连不等于失败，绝不重新 execute 来轮询**。
6. 完成后取 outputs 的 `versionId` → `get_output {"versionId":"…"}` 得到本机绝对路径，复制到 `work/<id>/raw/<状态>.png`。

## 费用确认（硬规则）

- task 进入 `waiting_user` 且带费用确认时：把 `task.billing.confirmation` 里的**准确费用**告诉用户，**等用户对这个报价明确说同意**，才能 `confirm_cost {"taskId":"原ID"}`。用户拒绝或没回应：`task_resolve` 选 stop。
- 不能拿「配置迁移」「历史预算」「用户让我把桌宠做完」当作确认；报价过期或变化要重新问。
- 一套 8 个状态 + 参考图至少是 9 次生成，开始前先估算并告诉用户大概次数，让用户决定是否继续、是否缩减到 3–4 个状态。
- 失败重试须用户授权，并按 `task.actions` 使用 `task_resolve`。

## 提示词怎么放

- `prompt` 放 `promptkit` 生成的整段英文（含 Layout / Frames / Background / Avoid）。
- 若能力有单独的「负面提示词」参数，把 `Avoid:` 后面的内容放进去，避免正文里出现被模型当成画面元素的词。
- 画幅用提示词里 `Image aspect ratio` 给的值，选能力支持的最接近画幅；不一致时切片用的 `--cols/--rows` 仍按提示词的网格。

## 即梦（dreamina）

即梦是独立通道（模型、工作区、凭据、积分不互用）；本 skill 不使用它。
