# README 演示截图

此目录的截图由 AgentMeter v0.2 自带离线预览生成，采用虚构账户、积分、额度和 Token 历史。没有读取真实账户、私有日志或登录凭据；来源名称与模型名仅用于展示界面。

- `accounts-light.png` / `accounts-dark.png`：账户额度、重置卡、Token 趋势与积分钱包。
- `usage-light.png` / `usage-dark.png`：本机 Token 构成、估算费用、应用和模型排行。
- `apps-light.png`：应用覆盖矩阵。
- `ticker-light.png`：菜单栏行情条。
- `themes-light.png` / `themes-dark.png`：四套界面风格对比（极简、原生、极光、霓虹，账户额度页）。

重建截图：

```sh
python3 scripts/make-demo-snapshot.py
'release/Agent 用量.app/Contents/MacOS/AgentMeterBar' --preview .runtime/readme-demo/snapshot.json .runtime/readme-demo/rendered
```

按上面的文件名从 `.runtime/readme-demo/rendered/` 复制图片至本目录；预览会额外输出 `minimal-` `native-` `neon-` 前缀的各主题截图，`themes-light.png` / `themes-dark.png` 由 `scripts/make-theme-sheet.py` 拼接。需要已有 release App；构建入口为 `sh scripts/build-dmg.sh`。真实账户截图仍位于被忽略的 `docs/screenshots/`，不发布。
