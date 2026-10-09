# 发布产物

运行 `sh scripts/build-dmg.sh`，本目录生成 App、DMG 和 `SHA256SUMS`。

二进制通过 GitHub Releases 发布（当前 `v0.2`），避免重复放入 Git 历史。发布资产包括最新 DMG 和 SHA256SUMS；本目录的本地构建产物被 Git 忽略。
