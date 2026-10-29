# AgentMeter 本机 Agent 用量统计目录导览

发布包 0.9.5；主目录还包含 2026-10-30 性能与分享优化源码，尚未重新发布。

## 阅读顺序

README → AGENTS（存在时）→ 对应模块说明 → 构建与测试脚本。历史计划不自动构成实施任务。

## 主要入口

| 路径 | 用途 |
|---|---|
| [agent_meter/](agent_meter/) | Python 用量采集与汇总。 |
| [menubar/](menubar/) | 菜单栏客户端。 |
| [tests/](tests/) | 自动化测试。 |
| [scripts/](scripts/) | 构建、验证与辅助脚本。 |
| [docs/](docs/) | 说明、方案与验收资料。 |
| [release/](release/) | 最新发布产物与发布入口。 |

## 文件分工

- 源码、模块、构建清单保持原路径，防止打包和相对导入失效。
- 文档集中在 docs/ 或项目既有文档目录；验收证据和原素材保留。
- 发布包存放在 release/、dist/ 或现有打包脚本输出位置，只保留当前版本；生成文件不加入 Git。
- 本地环境、凭据、数据库和缓存受 .gitignore 保护；不要上传恢复快照。
- 旧副本在同级恢复目录；本项目保留的历史入口 README 说明恢复路径。

## 当前一级目录

`agent_meter/`, `docs/`, `examples/`, `menubar/`, `release/`, `scripts/`, `tests/`
