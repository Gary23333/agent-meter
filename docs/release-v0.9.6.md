# v0.9.6 发布说明

2026-10-30，macOS 14+，Apple Silicon。

- 日志解析缓存限制为估算 16 MiB / 512 文件，按来源隔离，减少反复解析；大体积 SQLite 元数据采用流式读取。
- 报告窗口关闭释放视图，导出临时位图及时释放。
- 海报支持简洁晒用量与完整复盘、六个内容开关、DeepSeek 峰谷和 Codex 生图独立统计。
- 金额统一展示人民币，USD 按固定 1:7.25 汇率换算汇总；这是估算汇率。
- 修复模型价格切换人民币后被恢复为美元的问题；支持修改同步目录模型价格。

源码验证：329 项 Python 完整回归通过；币种修改后 36 项针对性测试通过；4 项 Swift 数据测试通过。七套主题的海报已离线导出。详细口径与性能测量见 [优化记录](performance-sharing-review-2026-10-30.md)。

发布验证：App 使用 Developer ID Application 签名，Apple 公证 Accepted，Gatekeeper 认可；内嵌 Python 3.14 后端隔离运行、合成 collect/verify、认证 HTTP API 与 token 权限冒烟通过。DMG 容器同样使用 Developer ID 签名并公证装订。
