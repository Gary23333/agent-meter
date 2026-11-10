# vendor · three.js

`three.pet.min.js` 是 [three.js](https://threejs.org/) r187（npm `three@0.187.0`，MIT 许可，见 `LICENSE.three.txt`）的**精选 tree-shaken 单文件构建**：官方包自 r17x 起不再提供 min 版（`three.core.js` 加 `three.module.js` 约 2.1 MB 未压缩），而桌宠只用到一小部分类。

| 项 | 值 |
|---|---|
| 文件 | `three.pet.min.js`（ES Module，573 KB，gzip 约 148 KB） |
| 导出清单 | `entry.js`（形象只能用这里列出的类；需要新类时加一行并重建） |
| 构建 | `sh build.sh`（`three@0.187.0` + `esbuild@0.25.10`，需要联网；运行时不联网） |
| SHA-256 | `61f8c87f716fb943d73bf5ed468d2aadc8cbe0907b3f84d0a225cac1abb6d870` |

`RoundedBoxGeometry` 来自 `three/examples/jsm/geometries/RoundedBoxGeometry.js`，同属 MIT。第三方声明见仓库根的 `THIRD_PARTY_NOTICES.md`。
