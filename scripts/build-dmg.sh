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
hdiutil create -ov -volname "Agent 用量 v${version%.*}" -srcfolder "$stage" -format UDZO "$dmg"

# dist 模式下若提供公证凭据，对 DMG 公证装订（可选；app 内签名由
# menubar/scripts/build-app.sh 完成，DMG 公证覆盖整个分发包）
if [ "${SIGN_MODE:-dev}" = "dist" ]; then
  if [ -n "${APPLE_ID:-}" ] && [ -n "${APPLE_APP_SPECIFIC_PASSWORD:-}" ] && [ -n "${APPLE_TEAM_ID:-}" ]; then
    xcrun notarytool submit "$dmg" \
      --apple-id "$APPLE_ID" --password "$APPLE_APP_SPECIFIC_PASSWORD" --team-id "$APPLE_TEAM_ID" --wait
    xcrun stapler staple "$dmg"
  else
    echo "提示：未提供公证凭据（APPLE_ID/APPLE_APP_SPECIFIC_PASSWORD/APPLE_TEAM_ID），跳过公证" >&2
  fi
fi

cd "$root/release"
shasum -a 256 "$(basename "$dmg")" > SHA256SUMS
echo "$dmg"
