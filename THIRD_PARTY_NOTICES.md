# Third party notices

## CC Switch

The SQL filtering and token normalization in `agent_meter/ccswitch_sql.py` and the MiniMax parsing in `agent_meter/minimax.py` are adapted from CC Switch 4.0.5.

Source: https://github.com/farion1231/cc-switch/tree/2db86e94da13365caae55bb08d09295e31500d21

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

## External installed SDKs

Qoder SDK assets remain code from the user's installed Qoder application. Any local materialization is private runtime cache, excluded from this repository and package. They are not redistributed.

## Bundled runtime

The macOS release bundles CPython and the PyInstaller bootloader. Their license texts are included in `Agent 用量.app/Contents/Resources/Licenses/`. PyInstaller's license includes an exception allowing distribution of applications built with its bootloader. Build dependencies are pinned in `requirements-build.txt`; no third-party installed application SDKs are bundled.
