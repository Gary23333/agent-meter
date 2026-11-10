# 质检与排错

## 质检（打包前后各看一次）

| 检查 | 怎么看 | 不合格怎么办 |
|---|---|---|
| 角色大小一致 | 联系表同一状态的 3 个采样 | `build` 已统一缩放；仍差很多说明原图里角色大小不一，重画该状态 |
| 站在同一基线 | 同上，脚底是否水平 | 同上；确保原图每格里角色完整、不被切 |
| 描边/色调一致 | 各状态并排比较 | 重画偏离的状态；全套必须同模型同风格 |
| 无背景残留 | 在深色背景下看（联系表 `bg=checker`） | 调大 `key --tolerance`，或换键色重画 |
| 无白边/绿边 | 放大看边缘 | `--feather` 调大、`--tolerance` 调小，或不去溢色（默认开）；根本解决是换与角色无关的键色 |
| 循环顺滑 | 看 `idle/working/waiting` 首尾帧 | 把动作设计成首尾相接；或把 `pet.json` 的该状态改 `fps` 更低 |
| 能区分八个核心状态 | 缩到 100 px | 加大动作/表情差异，别只靠小道具 |

## 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| `error: found 3 frames, expected 4` | 条带里帧之间没有足够空隙，或有帧粘连 | 用网格切（`--cols/--rows`），不要用 `--frames` 自动探测；或重出图要求更大的格间距 |
| `error: frame is empty after keying` | 键色选错/容差太大，整帧被抠空 | 先 `spritekit.py info 图` 看角落颜色；用 `--color` 指定；降低 `--tolerance` |
| `error: corners are already transparent` | 图本来就带透明背景 | 跳过 `key` |
| `error: interlaced PNG is not supported` | PNG 是隔行的 | 用 Pillow/预览另存为非隔行 PNG |
| 非 PNG 输入（JPEG/WebP）读不了 | 没装 Pillow 且不在 macOS | `python3 -m pip install pillow`，或用 `sips -s format png in.jpg --out out.png` 转换 |
| 角色被切到一半 | 模型没遵守格子边界 | 重画该状态；提示词里强调 margin；或手动把该帧用 `crop` 重切 |
| 动画抖动 | 各帧里角色位置/大小有漂移 | 这是 `align` 要解决的：确认用的是 `build`（它按全局统一缩放+同基线+居中）；仍抖就换成 `pet.json` 里更低的 `fps` |
| 校验报 `is too small for N frames` | 条带宽高与 `frames`/`cols` 对不上 | 不要手改 `pet.json` 的 `frames`；改图后重跑 `build` |
| 像素画变糊 | 没开 `pixelated` | `pet.json` 的 `sprite.pixelated: true`（`build --pixelated`） |
| 想要比 6 帧更流畅 | 帧数多会让一致性崩 | 靠运行时的 `motion` 叠加层；`fps` 保持 6–10 |

## 调整成品而不重新生成

直接改 `pets/presets/<id>/pet.json`：

- `sprite.states.<状态>.fps`：节奏；`loop:false`：只播一遍停在末帧。
- `sprite.anchors`：特效（Z、汗滴、彩带）出现的位置，`{x,y}` 是帧内 0–1 的相对坐标。
- `sprite.motion:false`：关掉叠加的程序化动作（角色本身帧动画已经很满时）。
- `voice`：台词。改完用 `petpack.py validate` 再看联系表。
