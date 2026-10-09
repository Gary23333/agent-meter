#!/bin/sh
# Builds "Agent 用量.app" (menu bar only) into ../release/.
# The distributable embeds its backend and never stores a source checkout path.
set -eu

here="$(cd "$(dirname "$0")/.." && pwd)"
root="$(cd "$here/.." && pwd)"

version="$(cat "$root/VERSION")"
app="$here/../release/Agent 用量.app"

sh "$root/scripts/build-backend.sh"
swift build -c release --package-path "$here" -Xswiftc -debug-prefix-map -Xswiftc "$root=."
bin="$(swift build -c release --package-path "$here" --show-bin-path)/AgentMeterBar"

rm -rf "$app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
cp "$bin" "$app/Contents/MacOS/AgentMeterBar"
strip -S "$app/Contents/MacOS/AgentMeterBar"
cp -R "$root/.runtime/build/backend/agent-meter-backend" "$app/Contents/Resources/backend"
cp "$root/THIRD_PARTY_NOTICES.md" "$app/Contents/Resources/"
# Include the licenses for the redistributed Python runtime and bootloader.
"${PYTHON:-python3}" "$root/scripts/copy-runtime-licenses.py" "$app/Contents/Resources/Licenses"

cat > "$app/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key><string>AgentMeterBar</string>
  <key>CFBundleIdentifier</key><string>local.agent-meter.menubar</string>
  <key>CFBundleName</key><string>Agent 用量</string>
  <key>CFBundleDisplayName</key><string>Agent 用量</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$version</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSUIElement</key><true/>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppTransportSecurity</key>
  <dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict>
</plist>
PLIST

# A stable identity (SIGN_IDENTITY) keeps Keychain "Always Allow" across
# rebuilds; ad-hoc signing (default) changes every build and re-prompts.
codesign --force --deep --sign "${SIGN_IDENTITY:--}" "$app" >/dev/null
echo "$app"
