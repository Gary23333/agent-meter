# 前端视觉重定义：真 3D 仪表（2026-11-23）

## 原则

1. **深度承载信息。** 3D 只用在数据物体上：额度环、品牌徽标、进程拓扑。容器和正文保持安静的 2D。
2. **一套渲染器，七种材质。** 七套主题不再各画一遍 3D，只在 `PanelTheme.look3D` 里提供材质和灯光（陶瓷、磨砂玻璃、钛金属、霓虹等）。
3. **文字永远是 SwiftUI。** 数字叠在 3D 物体上，保持清晰、可访问。
4. **空闲零成本。** 按需渲染；只有动画期间才播放；窗口不可见时停止。
5. **可降级。** 无 Metal 或关闭「真 3D 效果」时回到原有 2D。

## 代码位置

| 文件 | 内容 |
|---|---|
| `Scene3D.swift` | 材质预设、程序化影棚、网格、灯光、`SceneHost`、离屏快照 |
| `Gauge3D.swift` | 顶部额度仪表：一块表盘，多个窗口为同心管 |
| `BrandMark3D.swift` | 3D 徽标，按主题渲染一次后缓存 |
| `Process3D.swift` | 进程星图：核心 = harness，距离 = 派生层级，大小 = 内存，亮度 = CPU |
| `Processes.swift` / `ProcessesView.swift` | 进程页数据与界面，只在该页可见时每 3 秒轮询 |

`SCNView.isPlaying = true` 即使画面不动也会逐帧重绘（实测约 7% 单核），所以按需场景必须通过 `PassiveSceneView.wake(for:)` 短暂唤醒。

## 验证方式

```sh
menubar/.build/debug/AgentMeterBar --preview .runtime/readme-demo/snapshot.json <输出目录> --tab processes --theme aurora
menubar/.build/debug/AgentMeterBar --panel-window --live-snapshot .runtime/readme-demo/snapshot.json --live3d-check
```

前者走离屏快照，后者检查真实窗口里的 SceneKit 视图和空闲 CPU。

## 进度

- 已完成：顶部仪表、徽标、进程页，七套主题的 3D 材质，信息行重叠修复。
- 未完成：奖章与卡牌的真 3D、Tibo 重置器 3D、分享卡 3D、统一字号阶梯、各设置窗口、Windows 端。
