#!/bin/sh
set -eu
root="$(cd "$(dirname "$0")/.." && pwd)"
version="$(cat "$root/VERSION")"
arch="$(uname -m)"
sh "$root/menubar/scripts/build-app.sh"
stage="$root/.runtime/build/dmg"
rm -rf "$stage"
mkdir -p "$stage"
cp -R "$root/release/Agent 用量.app" "$stage/"
ln -s /Applications "$stage/Applications"
cp "$root/docs/INSTALL.md" "$stage/安装说明.txt"
dmg="$root/release/AgentMeter-$version-macos-$arch.dmg"
hdiutil create -ov -volname "Agent 用量 v0.1" -srcfolder "$stage" -format UDZO "$dmg"
cd "$root/release"
shasum -a 256 "$(basename "$dmg")" > SHA256SUMS
echo "$dmg"
