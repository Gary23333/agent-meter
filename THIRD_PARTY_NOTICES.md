# 第三方声明与许可

以下保留第三方组件的英文许可原文；Windows 发布包中的完整许可文件见 `licenses/`。

## Windows bundle

The Windows build includes CPython, the PyInstaller bootloader, python-zstandard, tzdata, and the .NET runtime. Their license texts and .NET third-party notices are copied into the Windows bundle's `licenses/` directory by `windows/build.ps1`. Dependency versions are listed in `windows/requirements.txt`. The MIT license and copyright for the upstream Agent Meter project are in the root `LICENSE` file. The notices below are retained from the upstream repository; not every listed component is bundled in the Windows application.

## CC Switch

The SQL filtering and token normalization in `agent_meter/ccswitch_sql.py` are adapted from CC Switch 4.0.22. The MiniMax parsing in `agent_meter/minimax.py` remains adapted from CC Switch 4.0.5.

CC Switch 4.0.22 source: https://github.com/farion1231/cc-switch/tree/b76426741ef93069e2f374ac01ca7ef5760e1d0e
CC Switch 4.0.5 source (MiniMax parsing): https://github.com/farion1231/cc-switch/tree/2db86e94da13365caae55bb08d09295e31500d21

MIT License

Copyright (c) 2025 Jason Young

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## three.js

The desktop pet (`pets/runtime/`) renders 3D characters with [three.js](https://threejs.org/) r187 (npm `three@0.187.0`), shipped as a curated, tree-shaken single-file build `pets/runtime/vendor/three.pet.min.js`; the export list and the reproducible build recipe are in `pets/runtime/vendor/`. The build includes `RoundedBoxGeometry` from the same package's `examples/jsm`. The app bundle carries the license text at `Contents/Resources/Pet/runtime/vendor/LICENSE.three.txt`.

Windows 便携包中的许可证位置为 `pet/runtime/vendor/LICENSE.three.txt`；3D 桌宠使用上游内置形象和本地渲染资源。

The MIT License

Copyright © 2010-2026 three.js authors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.

## External installed SDKs

Qoder SDK assets remain code from the user's installed Qoder application. Any local materialization is private runtime cache, excluded from this repository and package. They are not redistributed.

## Windows 桌宠精灵图

Windows 版内置的「麻薯」和「比特」精灵图来自上游 [Gary23333/agent-meter](https://github.com/Gary23333/agent-meter) 的 `pets/presets/mochi` 和 `pets/presets/bit`。对应 `pet.json` 将素材标注为 CC0-1.0；清单和原图随源码保留，并作为资源嵌入 Windows 程序。

Windows 网页登录适配使用 Microsoft WebView2 SDK 1.0.4314.35。SDK 许可和第三方声明随 Windows 构建包放在 `licenses/`；WebView2 Runtime 由 Windows 或用户单独提供。

## Bundled runtime

The macOS release bundles CPython and the PyInstaller bootloader. Their license texts are included in `Agent 用量.app/Contents/Resources/Licenses/`. PyInstaller's license includes an exception allowing distribution of applications built with its bootloader. Build dependencies are pinned in `requirements-build.txt`; no third-party installed application SDKs are bundled.
