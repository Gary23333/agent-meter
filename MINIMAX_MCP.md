# MiniMax Hub 正式 MCP（2026-10-21）

服务名 `minimax-design`，Streamable HTTP：`http://127.0.0.1:18810/mcp`。需要本机 MiniMax Design.app 运行并登录。Codex 全局已注册；若当前会话工具列表未刷新，可新开会话或使用随附 HTTP 客户端。无需启动 app 内部 stdio 包、扫描进程环境或缓存工作区身份。

## 正式调用流程

1. 每个 MCP 会话先 `list_projects {}`，从返回结果选择明确的 projectId。再 `open_project {"projectId":"实际ID"}`。目标项目必须在 Design 中打开；`open:false` 时请用户在应用中打开。不要用目录修改时间或历史 node_id 推断项目归属。
2. `capability_list {"operation":"generate_video"}` 查当前账号能力（也可 generate_image / generate_music / generate_speech / edit_media），用返回的 ID 调 `capability_get {"ids":["实际capabilityId"]}`。读 paramSchema、references、模式覆盖和计费说明；不沿用历史枚举或虚构能力 ID。说明中偶见 design_ 前缀，以 tools/list 的真实工具名为准。
3. 素材先用当前工具 schema 的 `deliver` 导入，再用返回的 resourceId/versionId 引用；已有资源直接查询引用。文件导入只接受项目工作区内非符号链接的非空文件（当日上限 50 MiB），不接受 URL 或工作区外路径。只向选定项目复制必要素材，不再向多个近期目录广播复制。
4. `execute` 接收 capabilityId、prompt、**扁平 params**、按顺序的 references、count 和 output。params 不放媒体路径；references 使用 Resource/Version/Composition 标识。新资源的 output 同时声明 resources 与 composition placements。模型模式和参考顺序以 capability_get 为准。
5. `execute` 返回 task 后保存 task.id；未结束时 `task_wait {"taskId":"原ID"}`，查看用 `task_query {"mode":"get","taskId":"原ID"}`。等待超时/断连不等于失败，绝不重新 execute 来轮询。失败重试须用户授权，并按 task.actions 使用 task_resolve。
6. `waiting_user` 且有费用确认时，展示 `task.billing.confirmation` 的准确费用，取得用户对该报价的明确同意后才 `confirm_cost {"taskId":"原ID"}`。拒绝时按 schema 用 task_resolve stop。不能以配置迁移、历史预算或泛化的“直接生成”代替该具体报价确认；过期或变化的报价重新查询确认。
7. 完成后取 outputs 的 versionId，调用 `get_output {"versionId":"实际ID"}`，获取绝对本地路径/本机 URL。按返回的资源名交付，再用 ffprobe 核验媒体。不要通过同名文件全盘 find 或旧 `/api/workspace` 猜输出。

旧 `generate_image`、`generate_video`、`generate_audio_*`、`list_capabilities` 等不是当前 MCP 工具；generate_video 等可能作为 capability 的 operation 出现，不能当作工具调用。旧 vendor/vendor_params/image_paths 等 JSON 不能直接重放。

## HTTP 客户端

全局入口：`/Users/guanzizheng/.agents/skills/minimax-hub/scripts/minimax_mcp.py`。项目也可有 `scripts/minimax_mcp.py` 或更新后的 `hub_call.py`；这些副本都使用正式 HTTP 协议。

```sh
python3 scripts/minimax_mcp.py --list
python3 scripts/minimax_mcp.py --schema execute
python3 scripts/minimax_mcp.py list_projects '{}'
python3 scripts/minimax_mcp.py --project '<list_projects 返回的ID>' capability_list '{"operation":"generate_video"}'
python3 scripts/minimax_mcp.py --project '<项目ID>' capability_get '{"ids":["<发现的能力ID>"]}'
python3 scripts/minimax_mcp.py --project '<项目ID>' execute --args request.json --out request-result.json
python3 scripts/minimax_mcp.py --project '<项目ID>' task_wait '{"taskId":"<原任务ID>"}'
```

客户端每次调用都在同一新会话内 list_projects → open_project → 目标工具；`--out` 不得覆盖已有记录，保留未知结果供恢复。确认费用必须先获得用户同意，再额外传 `--approve-cost`；客户端不会自动确认或自动重试。旧 `--discover-app-env`、`call ... --execute`、build_env/run_session 导入接口不再适用。历史批次脚本保留作溯源，不能直接运行；续作请将具体请求按实时 capability schema 迁移到本入口，不能机械替换字段或重放已有任务。

`execute` 的输出结构示例（仅展示结构；能力、params 与引用须实查）：

```json
{"capabilityId":"<从capability_list发现>","prompt":"一项明确的作品描述","params":{},"references":[],"count":1,"output":{"resources":[{"mode":"create","name":"作品名称"}],"composition":{"type":{"label":"视频"},"name":"本次作品","placements":[{"role":"主视频"}]}}}
```

## 验证与边界

2026-10-21 实测 serverInfo 为 minimax-design 1.0.0；发现 19 个工具，list_projects 成功返回 2 个项目，均 open:false。没有打开/改动用户项目，也没有提交生成或费用确认。项目内模型能力、导入与生成未在本轮端到端验证。

即梦/dreamina-canvas 是独立通道，模型、工作区、凭据和积分不互用。Topaz 的既有官方 API 与逐次报价确认规则不变。旧历史模型表、成功样片、提示词经验保留为历史证据，执行时以正式 MCP 实时契约为准。
