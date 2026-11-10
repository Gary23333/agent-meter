# 桌宠形象包规范 · `agentmeter-pet/1`

一个形象包是**一个文件夹，只含数据**：`pet.json`（清单）+ `avatar.json`（three 渲染）或 `sprites/*.png`（精灵图渲染）+ 可选文档。包里没有脚本，安装一个包不会运行任何代码。校验器 [`pets/tools/petpack.py`](tools/petpack.py) 是本规范的可执行版本；运行时是 [`pets/runtime/`](runtime/)。

## 1. 包结构与清单 `pet.json`

```text
my-pet/
  pet.json            必需
  avatar.json         renderer = three
  sprites/idle.png …  renderer = sprite
  README.md           可选
```

| 字段 | 必需 | 说明 |
|---|---|---|
| `format` | ✓ | 固定 `"agentmeter-pet/1"` |
| `id` | ✓ | `[a-z0-9][a-z0-9-]{1,30}`，**必须等于文件夹名** |
| `name` / `name_en` | ✓ / — | 显示名（1–24 字） / 英文名 |
| `version` | ✓ | `1.0.0` 形式 |
| `author`、`license` | ✓ | 作者与许可（如 `CC0-1.0`、`MIT`） |
| `description` | — | ≤ 300 字 |
| `renderer` | ✓ | `"three"` 或 `"sprite"` |
| `stage` | — | `{width 120–480, height 120–520, ground 0–1}`，宠物画布的逻辑大小（默认 240×260）与脚线位置 |
| `three` | three 包 | `{avatar: "avatar.json", camera: {fov, position, target}, lights: soft\|studio\|neon}` |
| `sprite` | sprite 包 | 见 §6 |
| `states` | — | 每个动画的覆盖（§5），键必须是 §2 中的动画名 |
| `voice` | — | `{状态名: [台词…]}`，每状态 1–8 句、每句 ≤ 60 字；用于闲聊气泡 |

## 2. 动画词汇与回退

形象实现的是**动画名**；大脑给出的状态、反应和交互都映射到这些名字。

| 类别 | 名字 |
|---|---|
| 基础状态（循环） | `offline exhausted alarm waiting busy working painting tired alert focus excited confused sleeping idle` |
| 短反应（有时限） | `celebrate eating startle wave`（`painting` 兼作反应） |
| 交互（宿主本地产生） | `poke pet drag drop refresh photo` |

**最小必需集**（sprite 包必须自带，three 包由配方库保证）：`idle working tired alarm sleeping celebrate offline waiting`。其余按回退链降到第一个存在的名字，最终落到 `idle`：

```text
busy→working  painting→working  exhausted→tired  alarm→tired  alert→waiting  focus→working  excited→celebrate
confused→idle  eating→working  startle→alarm  wave→celebrate  poke→wave  pet→celebrate  drag→startle
drop→idle  refresh→working  photo→celebrate  tired|waiting|working|celebrate|sleeping|offline→idle
```

状态的触发条件与优先级见 [规划文档 §5](../docs/pet-system-plan-2026-11-09.md)，实现是 [`agent_meter/pet.py`](../agent_meter/pet.py)。

## 3. three 渲染：`avatar.json`（Avatar DSL）

```jsonc
{
  "format": "agentmeter-avatar/1",
  "palette": {"shell": "#f3efff", "accent": "$accent1"},     // 命名颜色；值可以是 #rrggbb、$主题令牌或别的名字
  "materials": {"shell": {"kind": "toon", "color": "shell"}},
  "outline": {"enabled": true, "thickness": 0.014, "color": "$ink"},
  "nodes": [ {"id": "root", "type": "group"}, {"id": "body", "parent": "root", "type": "sphere", "radius": 0.5, "material": "shell"} ],
  "slots": {"root": "root", "body": "body", "head": "head"},
  "face": {…}, "meter": {…}, "props": {…}, "anchors": {…}
}
```

**约定**：+Y 向上，角色面朝 +Z（朝向观众），地面 y = 0，角色约 1.5 高；`armL/legL/earL` 是**观众视角的左侧**（屏幕左边）。旋转单位是度，绕该节点自己的原点（放在关节上）。节点必须**先定义父、后定义子**。

### 主题令牌

`$accent1 $accent2 $ink $ok $low $crit $paper $unknown`：随用户选的七套界面风格变化，用在需要跟主题走的颜色上（环、星、灯）。固定的肤色/毛色用 `#rrggbb`。

### 材质 `materials.<name>`

| 键 | 说明 |
|---|---|
| `kind` | `toon`（默认，赛璐璐，`steps` 2–5）、`standard`（`roughness`、`metalness`）、`basic`（不受光）、`lambert` |
| `color`、`emissive`、`emissiveIntensity`、`opacity` | 颜色同上；`opacity < 1` 自动透明 |
| `side` | `front` / `back` / `double` |
| `texture` | `softdot`（柔边圆，用于脚下阴影） |
| `decal` | `true`：多边形偏移，脸上的贴片不与球面打架 |
| `glow` | `true`：发光强度随 `gauge` 槽位的 `glow` 动作缩放（圆环、星星、天线灯） |
| `blend` | `add`：叠加混合 |

### 节点 `nodes[]`

通用：`id`（`[A-Za-z][A-Za-z0-9_]{0,40}`）、`parent`、`type`、`position[x,y,z]`（±10）、`rotation[x,y,z]`（度）、`scale`（数或三元，非零）、`material`、`visible`（false 则默认隐藏）、`outline`（`false` 关闭、数字=自定义厚度）。最多 400 个节点。

| `type` | 参数（默认值） |
|---|---|
| `group` | 无几何，做关节/分组 |
| `sphere` | `radius`(.5) `segments[w28,h20]` |
| `capsule` | `radius`(.12) `length`(.3) `segments[cap6,radial12]` |
| `box` | `size[x,y,z]`(.5) `round`（圆角半径） |
| `cylinder` / `cone` | `radiusTop`/`radiusBottom`/`radius` `height` `segments[radial20]` |
| `torus` | `radius`(.5) `tube`(.05) `arc`(360°) `segments[radial10,tubular40]` |
| `disc` / `ring` | `radius`(.1) / `inner`(.08) `outer`(.1) `start`(0°) `arc`(360°)；脸上的眼睛、嘴、腮红 |
| `plane` / `screen` | `size[w,h]` |
| `lathe` | `points[[r,y]…]`（2–64 点）`segments`(24) |
| `tube` | `path[[x,y,z]…]`（2–64 点）`radius`(.03) `segments[radial8,tubular24]` `closed` |
| `extrude` | `shape`：`star`/`heart`/`drop`/`bolt`，或 `{kind:"star",points,inner}`，或 `{points:[[x,y]…]}`；`size`(.2) `depth`(.12) `bevel`(.02) |
| `arc` | 额度环：`radius`(.8) `tube`(.05) `start`(225°) `sweep`(270°，顺时针) `segments[radial8,tubular96]` |

各 `segments` 取 3–128；尺寸类参数 0–5。

### 槽位 `slots`

槽位是**语义部位**，动作配方只对槽位发号施令；没映射的槽位上的动作被忽略。

`root body head armL armR legL legR tail earL earR antenna mouth gauge prop shadow`

建议至少映射 `root`、`body`、`head`。`body` 的挤压拉伸会带着它的子节点一起缩放——想让头不变形，就把头放在 `root` 下而不是 `body` 下。`gauge` 通常指向额度环或发光物（`glow` 动作作用于它）；`shadow` 随跳跃缩放。

### 脸 `face`

```jsonc
"face": {
  "blink": ["eyeL", "eyeR"],                         // 眨眼时纵向压扁的节点
  "look": [{"node": "eyeL", "range": [0.03, 0.022]}], // 跟随光标/视线时平移的节点与幅度
  "managed": ["eyeL", "mouthSmile", …],              // 由表情控制显隐的节点
  "expressions": {"neutral": {"show": ["eyeL", "eyeR", "mouthSmile"]}, "happy": {"show": […]}}
}
```

表情词汇：`neutral happy excited determined worried sad sleepy surprised confused dizzy yawn love`。**必须有 `neutral`**；缺失的按回退（如 `excited→happy→neutral`）。[`avatarkit.Avatar.face()`](tools/avatarkit.py) 能在任意椭球头上一次生成 12 个表情用到的全部节点。

### 额度环 `meter`

```jsonc
"meter": {"node": "ring", "colors": {"ok": "$accent1", "low": "$low", "critical": "$crit", "empty": "$crit", "unknown": "$unknown"}}
```

`node` 必须是 `arc` 类型；运行时按「相关额度」百分比缩短弧长、按档位换色，未知额度显示为空轨道。

### 道具 `props`

内置：`laptop brush sign plug headphones crystal fish resetter`。形象用 `{"laptop": {"parent": "root", "position": […], "rotation": […], "scale": 0.8}}` 声明挂载位置，动画用 `show: ["laptop"]` 决定何时显示。没声明的道具不出现。

### 锚点 `anchors`

`head body prop root` → `{node, offset[x,y,z]}`：特效粒子与气泡尾巴的参照位置（`head` 通常在头顶上方）。

## 4. 动作配方

`pets/runtime/js/recipes.js` 为每个动画写好了对槽位的动作（待机的呼吸、干活时敲键盘、告急时发抖、耗尽时瘫成一滩……）。形象不需要重写它们，只需提供槽位。配方列表：基础状态与反应/交互各一份，另有内部的待机小动作（`antic_hop/stretch/yawn/look/wiggle/spin`）。

## 5. 每个动画的覆盖 `states.<动画名>`

```jsonc
"states": {
  "exhausted": {"pose": {"root": {"pos": [0, -0.1, 0], "scl": [1.4, 0.5, 1.4]}}},   // 按槽位合并姿态
  "celebrate": {"scale": {"amp": 1.25, "speed": 1}},                                  // 整体放大幅度/加速
  "eating":    {"show": ["fish"]},                                                    // 显示道具
  "working":   {"channels": [{"t": "tail", "p": "rot.y", "k": "sine", "a": 20, "f": 1.3}], "drop": ["antenna"]}
}
```

| 键 | 含义 |
|---|---|
| `pose` | `{槽位: {pos[x,y,z], rot[x,y,z]度, scl[x,y,z], glow}}`，叠加在节点静止姿态上（`scl`、`glow` 为乘数） |
| `channels` | 追加的连续动作：`{t:槽位, p:属性, k:波形, a:幅度, f:频率Hz, ph:相位, o:偏移, fixed:true}`；`p` 取 `pos.x/y/z rot.x/y/z scl scl.x/y/z glow`；`k` 取 `sine abs saw pulse noise squash once`（`squash` 体积守恒） |
| `drop` | 要移除的槽位（其配方通道被丢弃） |
| `expression` | 该动画的表情；`lock: true` 表示不让心情改写 |
| `show` | 该动画显示的道具 |
| `fx` | `[{kind, at: head\|body\|root\|prop, rate}]`；`kind`：`zzz hearts sparkles confetti sweat question exclaim notes coins stars steam bolt paint dust flash` |
| `fps`、`dur`、`look`、`desaturate` | 帧率上限、反应时长（秒）、视线 `{x,y}`、去色（0–1，离线用） |
| `scale` | `{amp, speed}`：整体缩放配方里所有通道 |

## 6. sprite 渲染

```jsonc
"sprite": {
  "frame": {"width": 256, "height": 256},     // 每帧大小（8–1024）
  "pivot": {"x": 0.5, "y": 1.0},              // 落地点：帧内相对位置
  "pixelated": false,                          // 像素画设为 true：整数倍放大、最近邻
  "motion": true,                              // 在帧动画上叠加 root 级动作（跳、晃、挤压）
  "anchors": {"head": {"x": 0.5, "y": 0.22}, "body": {…}, "prop": {…}},   // 特效参照点（帧内 0–1）
  "states": {
    "idle": {"image": "sprites/idle.png", "frames": 4, "fps": 4, "loop": true},
    "celebrate": {"image": "sprites/celebrate.png", "frames": 6, "fps": 8, "loop": false}
  }
}
```

条带布局：帧从左到右、再换行，`cols` 默认等于 `frames`（单行条带）；`start` 为起始帧序号，`row` 为起始行（可把多个状态放在一张图里）。每状态 1–64 帧、`fps` 1–30。图须为 PNG（透明背景），最大边 4096。最小必需集必须自带，其余走回退链。

## 7. 大脑帧 `PetFrame`（GET /v1/pet）

字段、仲裁与诚实性规则见 [规划文档 §4–§5](../docs/pet-system-plan-2026-11-09.md)。页面只读取：`state mood intensity reaction energy meters activity focus reminders generated_at`。

## 8. 宿主 ↔ 页面消息

宿主 → 页面（`AgentPet.receive(msg)`）：`frame`、`say`、`prefs`、`theme`、`pointer`（`move/leave/click/dblclick/right`）、`cursor`、`drag`（`start/end`）、`local`（`refresh/photo`）、`visibility`。

页面 → 宿主：`ready`、`rects`（可交互矩形，用于点击穿透）、`bubble-shown`（宿主据此持久化「已提示」）、`bubble-click`/`action`（`{kind:"open_panel", tab}`）、`hud-click`、`refresh-request`、`pet-click`、`error`。宿主对未知消息一律忽略；页面没有网络、没有 token（CSP 禁止外连）。

## 9. 限制与安全

- 允许的文件：`.json .png .webp .jpg .jpeg .md .txt` 与无扩展名的 `LICENSE`/`README`。**禁止**脚本、HTML、SVG、CSS、wasm、符号链接、隐藏文件、`..` 路径。
- 整包 ≤ 12 MB，单文件 ≤ 4 MB，图片最大边 ≤ 4096。
- `.agentpet`（zip）安装时拒绝绝对路径、`..`、符号链接，且必须只含一个包文件夹。
- 校验：`python3 pets/tools/petpack.py validate <包路径或id>`（`--strict` 把警告当错误）。
