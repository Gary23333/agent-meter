# 参与贡献

使用 Python 3.9+；压缩日志测试在 Python 3.9–3.13 上需要 `zstd` CLI（macOS: `brew install zstd`，Ubuntu: `sudo apt-get install zstd`）。Python 3.14 可使用标准库 `compression.zstd`。原生界面需要 macOS 14+ 和 Xcode/Swift 5.10+。

```sh
python3 scripts/test-offline.py
python3 -m pip install build
python3 -m build
python3 scripts/check-package-version.py
cd menubar
swift test
swift build -c release
```

桌宠相关改动另需（Node 18+，仅用内置测试运行器）：

```sh
node --test pets/runtime/test/*.test.mjs
python3 pets/tools/petpack.py validate pets/presets/* --strict
```

形象包只含数据与图片（禁止脚本、SVG、符号链接）；新增内置预设请改 `pets/tools/build_presets.py` 后重新生成，测试会检查生成结果与已提交 JSON 一致。

离线测试入口使用临时 HOME、移除继承的账户环境变量、禁用默认账户 CLI 和外部网络。HTTP 测试仅连接回环地址。新增采集器测试必须使用合成数据、临时目录和 mock，不依赖开发者真实账户。不要把 `agent_meter verify` 真实环境对账加入 CI。

提交前检查 `git diff --check`，在 PR 说明修改行为、验证命令与未完成的验证。修改数据合并时保留「未知不等于零」、独立账本和账户隔离边界。不要提交 `.runtime/`、认证文件、真实会话或账户快照。

发布版本只修改根目录 `VERSION`，并同步发布说明；Python 元数据和 macOS 打包均读取它。`dist/` 校验要求干净构建目录。应用签名、公证与发布包验收属于额外发布步骤，不由 PR CI 自动执行。
