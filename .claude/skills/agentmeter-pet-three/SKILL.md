---
name: agentmeter-pet-three
description: 用前端 + three.js 为 AgentMeter 制作、复刻、修改或评审 3D 桌宠形象（声明式 avatar.json：槽位、脸、道具、逐状态覆盖），并校验、用全状态联系表预览、安装。凡是用户要「做一个新桌宠 / 新形象 / 新预设」「改某只桌宠的外观或动作」「给桌宠加状态、表情、道具」，且要的是程序化 3D 角色而不是生图模型的精灵图时使用。生图路线用 agentmeter-pet-imagegen。
---

# AgentMeter 桌宠 · three.js 形象制作

一个 3D 形象就是两份 JSON：`pet.json`（清单）和 `avatar.json`（几何体 + 材质 + 槽位 + 表情 + 道具）。**动作不用你写**：运行时的配方库已经为全部 24 个动画（待机、干活、告急、耗尽、睡觉、庆祝……）写好了对「槽位」的动作；你只要把角色的部位映射到槽位、画好脸，所有状态就都会动。

所有命令都在仓库根目录执行。完整格式见 [pets/SPEC.md](../../../pets/SPEC.md)（§3 DSL、§5 覆盖）；现成参考是 [pets/tools/build_presets.py](../../../pets/tools/build_presets.py) 里的 5 个角色（每个约 60 行）。

## 先想清楚再动手

1. **一句话概念**：它是什么、性格、最有辨识度的一个特征（例：圆环就是额度的仪表兽）。
2. **选体型**（决定从哪个预设起步）：

| 体型 | 起步 | 特点 |
|---|---|---|
| 圆球 + 脸盘 | `gauge` | 最稳，脸贴在椭球上；有额度环 |
| 果冻/无四肢 | `blob` | 靠挤压拉伸表演；`exhausted` 化成一滩 |
| 方块机器人 | `bot` | 平面屏幕脸；胸口小表盘当额度 |
| 四足/带尾巴 | `cat` | `tail`、`ear` 槽位；吃鱼道具 |
| Q 版人形 | `tibo` | 头发、手脚、`resetter` 重置器 |

3. 读 [references/design-guide.md](references/design-guide.md) 的「设计检查表」——比例、轮廓、配色、脸的位置，决定一半观感。

## 流程

```sh
# 1. 起步：两种方式选一种
python3 pets/tools/petpack.py new my-pet --from cat --name 小宠          # 复制一个预设来改
python3 .claude/skills/agentmeter-pet-three/templates/new_character.py --id my-pet --name 小宠 --body "#ffd6a5"   # 或从模板脚本起步

# 2. 校验（错误必须清零；警告要逐条看）
python3 pets/tools/petpack.py validate pets/presets/my-pet --strict

# 3. 看联系表：全部状态 × 3 个时间点 + 12 个表情 + 七套主题
python3 pets/tools/serve.py &                                  # 禁缓存的静态服务器
open "http://127.0.0.1:8765/runtime/sheet.html?pack=my-pet"    # 或让浏览器工具打开；macOS 无头出 PNG：
sh pets/tools/sheet.sh my-pet .runtime/my-pet.png              # 需先 swift build --package-path menubar

# 4. 交互调试（切状态、额度、反应、气泡、主题）
open "http://127.0.0.1:8765/runtime/dev.html"
```

**迭代循环**：改 `avatar.json`（或你的生成脚本）→ `validate` → 刷新联系表 → 逐格检查 → 再改。联系表是确定性的：同一个包两次渲染完全一致，可以截图对比。

### 两种改法

- **小改**（颜色、位置、一个道具）：直接编辑 `pets/presets/my-pet/avatar.json`。
- **成形的角色**：把起步脚本留在包**外面**（包里禁止放 `.py`），用 `Avatar` 构建器写角色，每次改完重新生成。`Avatar.face()` 会在任意椭球头上自动贴好 12 个表情用到的全部眼睛/眉毛/嘴/腮红（见 `build_presets.py`）。

## 逐格检查（看联系表时）

- 脸是否**贴在头表面**（不能陷进去或漂在外面）；睁眼、`happy ^ ^`、`sleepy`、`dizzy ×`、`love ♥` 是否都清晰可辨。
- 四肢旋转方向对不对：右臂 `rot.z` 为正 = 向外抬；左侧由镜像得到，不要为左侧再写一套。
- `working` 的笔记本、`painting` 的画笔、`alert` 的标牌、`offline` 的电源线是否出现并不穿模。
- `celebrate` 起跳时头顶有没有被裁掉（舞台默认 240×260，必要时调相机或 `stage`）。
- 七套主题行：用了 `$accent1` 的部位在极简（黑白）、霓虹（品红青）里是否仍好看；固定色（肤色、毛色）用 `#rrggbb`。
- 缩到 100 px 高，轮廓还能认出是什么吗。

## 常用调参（都在 `pet.json` 的 `states` 里，不用改配方）

```jsonc
"states": {
  "exhausted": {"pose": {"root": {"pos": [0, -0.1, 0], "scl": [1.4, 0.5, 1.4]}}},   // 化成一滩
  "celebrate": {"scale": {"amp": 1.25, "speed": 1}},                                  // 蹦得更夸张
  "eating":    {"show": ["fish"]},                                                    // 这个状态显示道具
  "working":   {"channels": [{"t": "tail", "p": "rot.y", "k": "sine", "a": 24, "f": 1.6}]}
}
```

动作配方速查与特效清单见 [references/animation-cheatsheet.md](references/animation-cheatsheet.md)。

## 收尾

```sh
python3 pets/tools/petpack.py validate pets/presets/my-pet --strict
python3 pets/tools/petpack.py install pets/presets/my-pet      # 装到 ~/Library/Application Support/AgentMeter/pets（App 设置 → 桌宠 → 形象 里就能选）
python3 pets/tools/petpack.py pack pets/presets/my-pet         # 打成可分享的 my-pet-0.1.0.agentpet
```

提交内置预设时：把生成脚本的函数加进 `pets/tools/build_presets.py`，并跑 `python3 -m unittest tests.test_pet_tools`（它会检查生成结果与已提交 JSON 一致、预设无警告）。

## 不要做

- 不要在包里放脚本、SVG、符号链接、隐藏文件（校验器会拒绝；这是安全边界，不是风格）。
- 不要用负缩放或 0 缩放；不要让节点先于它的父节点出现。
- 不要为每个状态重写动作：先看 `states` 覆盖够不够；真缺动作再在 `pets/runtime/js/recipes.js` 加配方（会影响所有形象，需同步 `constants.js` 与 `petpack.py` 的词汇并跑测试）。
- 不要把「额度未知」画成「额度为 0」——`confused`/`offline` 有自己的动作；形象不用也不应该自行判断状态。
- 问题排查见 [references/troubleshooting.md](references/troubleshooting.md)。
