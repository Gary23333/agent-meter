# 参与贡献

欢迎改进 Windows 版。涉及较大功能或界面调整时，建议先提交问题讨论数据口径与平台限制。

## 开发环境

使用 Windows x64、Python 3.10 和 .NET 8 SDK，在项目根目录运行：

```powershell
py -3.10 -m venv .venv-win
.\.venv-win\Scripts\python.exe -m pip install -r windows\requirements.txt
powershell -NoProfile -ExecutionPolicy Bypass -File windows\test.ps1
dotnet build windows\AgentMeter.Windows -c Release
powershell -NoProfile -ExecutionPolicy Bypass -File windows\build.ps1
```

构建结果位于 `windows/dist/AgentMeter/`。`--demo` 使用虚构数据，`--window` 将真实数据面板显示为普通任务栏窗口。请在提交说明中写清已验证和未验证的平台、账户与功能。

测试应使用模拟数据和临时目录。请保持账户额度与本机历史的统计边界，不把缺失或不支持的值当作零；不要提交凭据、对话、真实账户快照或私人运行数据。提交前运行 `git diff --check`。

原 macOS 项目等上游部分的贡献说明保留在 [docs/UPSTREAM-CONTRIBUTING.md](docs/UPSTREAM-CONTRIBUTING.md)；涉及上游的改动可与 [Gary23333/agent-meter](https://github.com/Gary23333/agent-meter) 协调。本仓库是独立移植版。
