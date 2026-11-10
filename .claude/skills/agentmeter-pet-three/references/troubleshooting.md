# 排错

| 现象 | 多半是 | 处理 |
|---|---|---|
| 联系表空白 / 一直不出图 | 服务器没起，或浏览器缓存了旧模块 | 用 `python3 pets/tools/serve.py`（带 no-store）；看页面里的错误文字（出错时页面正文会显示栈） |
| 页面写着 `spec.points…` 之类的 JS 错误 | DSL 参数形状不对 | 先跑 `petpack.py validate`；`extrude.shape` 的 `{kind:"star",points:4}` 里 `points` 是角数，多边形才是 `[[x,y]…]` |
| 脸不见了 | 贴片陷进球里 / 朝向反了 | 用 `Avatar.face(head=(中心, 半径))`；椭球半径要和 `shell` 的真实半径（`radius × scale`）一致 |
| 表情切换没反应 | 节点没在 `face.managed` 里，或 `expressions.*.show` 漏了 id | 用 `Avatar.face` 生成；手写时 `managed` 必须包含所有被切换的节点 |
| 眼睛不眨 | `face.blink` 没指到「睁眼」组 | 指向 `eyeL/eyeR` 这两个组，不是单个圆片 |
| 手臂转错方向 | 把左臂也写成了右臂的角度 | 只给 `armR` 写，左侧自动镜像；右臂 `rot.z` 正 = 向外抬 |
| 躯干一挤压，头也变形 | 头是 `body` 的子节点 | 头放到 `root` 下（脸盘随球体鼓起的球形角色则保持在 `body` 下） |
| 道具不出现 | `avatar.json` 没声明，或状态没 `show` | `props` 里声明挂载；内置默认只有 laptop/brush/sign/plug/headphones/crystal 配了 `show` |
| 额度环不缩 | `meter.node` 不是 `arc` 类型 | 用 `arc` 节点；联系表里额度固定为 78%/4% 等示例值 |
| 换主题颜色不变 | 用了 `#rrggbb` 写死 | 想跟主题走就用 `$accent1/$accent2/$ink`；肤色毛色保持固定 |
| 联系表里某状态带橙色 `→ xxx` | 该动画没自带实现，走了回退 | three 包不会出现；sprite 包会，属正常（见 SPEC §2） |
| `validate` 说「id 必须等于文件夹名」 | 用 `new --dest` 或手动改名后 `pet.json` 的 id 没改 | 改 `pet.json.id` 或文件夹名 |
| 装进 App 后没出现在菜单 | 没装到用户目录，或 App 没重新读取 | `petpack.py install …`；在设置菜单里重新打开「桌宠」子菜单 |
| WebGL 不可用 | 在虚拟机/远程桌面 | 运行时会自动退回 2D 兜底脸；联系表则会报错——换到有 GPU 的环境预览 |
