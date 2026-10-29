# v0.9.5 发布说明

2026-10-29 发布；App 内部版本为 0.9.5。适用于 macOS 14+、Apple Silicon（arm64）。

## Codex 内置生图统计

- 「账户额度」页 Codex 卡片新增「生图 今日」：今日张数、API 等价估算金额与近 30 天张数，并附最近 30 个活跃日的按日柱图。
- 「本机消耗」页新增独立「生图」卡：按今日 / 7 天 / 30 天 / 全部切换展示张数与估算成本，附按日趋势；不计入上方 Token 费用与 Token 总量。
- 数据来自 `~/.codex/generated_images` 的 PNG（只读 PNG 头取尺寸、按 mtime 归日）与 `~/.codex/thread_history*.sqlite` 的 `imageGeneration` 调用记录（只读，必要时以 immutable 方式降级，缓存 10 分钟）。
- 成本按 GPT Image 2.5 high 档输出 token 估算（$30/1M；方形 1024²≈$0.05268、非方形 1536×1024≈$0.04116，按面积缩放）；仅含输出 token，不含参考图输入，不是订阅账单。
- `agent_meter verify` 增加 Codex 生图独立重算：按文件重扫张数/成本，按历史库重查 calls / failed / generating。

## 口径说明

- 内置 `image_gen` 不记录 quality，统一按 high 档估算；可在配置 `codex_image_quality` 切换 low / medium / high / xhigh / max。
- 生图 token 无法从 Codex 账号接口单独拆分；本版展示的是 API 等价成本估算，不写 Token 指标。
- CLI fallback（`image_gen.py` + `OPENAI_API_KEY`）不在 `generated_images` 归档内，不计入。

## 验证

- Python 新增 18 项生图测试；目标回归 68 项、`tests.test_verify` 4 项通过。
- `python3 -m agent_meter verify` 真实对账：Codex 生图 21 项检查全过；总计 2,050 项通过，1 项既有的 `codex_local.ccswitch_cross` 漂移失败（与本次无关）。
- `swift build` 通过。
- Developer ID Application 签名、Apple 公证与装订完成；`codesign --verify --deep --strict`、`stapler validate`（App 与 DMG）、`hdiutil verify`、SHA256 校验通过；App Gatekeeper 评估为 `accepted`（Notarized Developer ID），DMG 内 App 版本 0.9.5。
- 内嵌 Python 3.14 后端打包冒烟测试通过：`collect` 成功生成快照，Codex 生图指标为 `available`（今日 12 张 / 全部 1,188 张），证明 `codex_images` 已进入发布包。
