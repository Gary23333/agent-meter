# v0.3 · Agent 用量

2026-10-09 发布；App 内部版本为 0.3.0。适用于 macOS 14+、Apple Silicon（arm64）。

## 新增来源

- **ZCode / 智谱 GLM Coding Plan**（实验性）：「连接网页账户」里登录智谱开放平台并打开 Coding Plan 用量页，App 捕获页面自己的查询凭据（只回放给同一允许的 bigmodel.cn 主机）；也可粘贴 Coding Plan API Key。显示 5 小时 / 每周额度（已用 / 总量）、周重置时间与 MCP 月度次数，最多 5 个账号。重置卡只在 ZCode 桌面端，暂不读取。
- **小米 MiMo API**：内嵌窗口登录 MiMo 开放平台控制台，读取账户余额（现金 / 赠送）与 Token Plan（套餐名、本月用量、周期结束时间）。只转发控制台自身的 Cookie；MiMo 推理 API Key 无权查询余额。
- **火山方舟 Coding Plan**：填写火山引擎 AccessKey，签名调用只读的 `GetCodingPlanUsage`（不发模型请求、不消耗额度），显示 5 小时 / 每周 / 每月窗口与重置时间。签名与参考实现逐字节一致。

## 其他

- README 新增菜单栏行情条滚动动画（`scripts/make-ticker-gif.py`）。
- API 密钥区支持多字段密钥（AccessKey ID + Secret 一起保存）；网页登录的凭据捕获按来源配置。
- Token 类额度以「万 / 亿」显示已用 / 总量。

## 验证

- Python 后端回归：155 项全部通过（新增 18 项覆盖三个来源的解析、错误、凭据范围与签名）。
- Swift release 编译通过；DMG 校验与 App 深度签名检查通过；内嵌后端合成数据冒烟测试通过。
- 真实账户：ZCode（网页登录，GLM Coding Lite 5 小时 / 每周窗口）与 MiMo（余额与 Token Plan Pro 用量、周期结束时间）已在本机读取成功。
- 火山方舟 Coding Plan 只经过固定样例与签名对照，**尚未用真实账户验证**。

## 已知限制

与之前版本相同：ad-hoc 签名，未做 Apple 公证；每次升级后钥匙串会再次询问，请选择「始终允许」。仅发布 arm64。MiMo 控制台无时区的周期结束时间按北京时间解读。

## 重建

```sh
python3 -m pip install -r requirements-build.txt
sh scripts/build-dmg.sh
python3 scripts/smoke-release.py 'release/Agent 用量.app/Contents/Resources/backend/agent-meter-backend' .runtime/synthetic-snapshot.json
```
