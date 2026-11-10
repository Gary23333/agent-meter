# 动作配方速查

配方在 `pets/runtime/js/recipes.js`；形象不重写，只用 `pet.json` 的 `states.<动画>` 覆盖。

## 每个动画做什么

| 动画 | 动作要点 | 用到的槽位 | 默认道具 / 特效 |
|---|---|---|---|
| `idle` | 呼吸（body 挤压）、缓慢摆动、转头、尾巴/耳朵/天线微动 | root body head arm* tail ear* antenna gauge | — |
| `working` | 双臂交替敲键盘、头略低、尾巴快摆 | arm* head body tail | 笔记本 · 火花 |
| `busy` | 同上但更快更猛，头摇晃 | 同上 + root | 笔记本 · 汗滴/蒸汽 |
| `waiting` | 右臂高举挥动、歪头、蹦跳 | armR head root | 感叹号 |
| `painting` | 右臂挥笔、转头 | armR head | 画笔 · 颜料点 |
| `tired` | 塌肩、低头、慢呼吸、耳朵垂 | root head body arm* ear* | 汗滴 |
| `alarm` | 双臂上举、全身发抖、环闪烁 | root arm* head gauge | 感叹号 · 汗滴 · 闪电 |
| `exhausted` | 整个压扁瘫下、头歪 | root head arm* leg* | 眼冒星 |
| `alert` | 举牌、点脚 | armR legR head | 标牌 · 感叹号 |
| `focus` | 戴耳机点头 | head body | 耳机 · 音符 |
| `excited` | 小幅蹦跳、双臂外展 | root body arm* | 水晶球 · 闪光 |
| `confused` | 歪头、左右看 | head | 问号 |
| `sleeping` | 低头、慢呼吸、整体矮一点 | head body root | Zzz |
| `offline` | 去色、歪头、电源线掉在地上 | head | 问号 · 电源线 |
| `celebrate` | 蹦起（落地挤压/空中拉伸）、转身、双臂挥 | root body arm* head | 彩带 |
| `eating` | 嘴开合（`mouth` 槽位）、点头 | mouth head body | 金币飞进嘴 |
| `startle` / `wave` / `poke` / `pet` / `drag` / `drop` / `refresh` / `photo` | 短反应与交互 | root arm* | 各自的特效 |

## 通道写法

```jsonc
{"t": "tail", "p": "rot.y", "k": "sine", "a": 20, "f": 1.3, "ph": 0, "o": 0, "fixed": false}
```

- `t` 槽位；`p` 属性：`pos.x/y/z`（单位）、`rot.x/y/z`（度）、`scl`（整体）、`scl.x/y/z`、`glow`。
- `k` 波形：`sine`、`abs`（只向上的弹跳）、`saw`（锯齿，`a:180` 配 `rot.y` 就是转一圈）、`pulse`、`noise`（平滑随机）、`squash`（体积守恒挤压拉伸，忽略 `p`）、`once`（一次性缓动）。
- `a` 幅度会随大脑给的 `intensity` 缩放（0.5 为基准，最多约 +45%）；`fixed:true` 不缩放。`f` 频率 Hz。
- 落地挤压的口诀：弹跳用 `abs` 频率 f，挤压用 `squash` 同频率、`ph = -π/2`（落地最扁、空中最长）。

## 常见需求

| 想要 | 怎么做 |
|---|---|
| 某状态不要某部位动 | `"drop": ["antenna"]` |
| 整体更夸张/更慢 | `"scale": {"amp": 1.3, "speed": 0.8}` |
| 换个特效 | `"fx": [{"kind": "hearts", "at": "head", "rate": 1.2}]` |
| 这个状态戴耳机 | `"show": ["headphones"]`（先在 avatar.json 的 `props` 里声明） |
| 固定某个表情 | `"expression": "love", "lock": true` |
| 改眼睛看的方向 | `"look": {"x": 0, "y": -0.6}` |

## 特效 `fx.kind`

`zzz hearts sparkles confetti sweat question exclaim notes coins stars steam bolt paint dust flash`；`at` 取 `head body root prop`（对应 `anchors`）。
