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
cp "$here/Resources/AppIcon.icns" "$app/Contents/Resources/"
cp "$root/THIRD_PARTY_NOTICES.md" "$app/Contents/Resources/"
cp "$root/LICENSE" "$app/Contents/Resources/LICENSE.txt"
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
  <key>CFBundleIconFile</key><string>AppIcon</string>
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

# A stable identity keeps Keychain "Always Allow" across rebuilds; ad-hoc
# signing changes every build and re-prompts. SIGN_MODE picks the identity:
# dev (default) = Apple Development, dist = Developer ID Application
# (+ hardened runtime + timestamp + optional notarization), adhoc = ad-hoc.
# SIGN_IDENTITY still overrides for backward compatibility.
pick_sign_identity() {
    security find-identity -v -p codesigning | awk -v pat="$1" '$0 ~ pat { print $2; exit }'
}
SIGN_MODE="${SIGN_MODE:-dev}"
if [ -n "${SIGN_IDENTITY:-}" ]; then
    sign_id="$SIGN_IDENTITY"
else
    case "$SIGN_MODE" in
        dev)
            sign_id="${SIGN_DEV_IDENTITY:-$(pick_sign_identity 'Apple Development')}"
            if [ -z "$sign_id" ]; then
                echo "warning: no Apple Development certificate found, falling back to ad-hoc signing" >&2
                sign_id="-"
            fi
            ;;
        dist)
            sign_id="${SIGN_DIST_IDENTITY:-$(pick_sign_identity 'Developer ID Application')}"
            [ -n "$sign_id" ] || { echo "error: SIGN_MODE=dist requires a Developer ID Application certificate" >&2; exit 1; }
            ;;
        adhoc) sign_id="-" ;;
        *) echo "error: invalid SIGN_MODE: $SIGN_MODE (dev | dist | adhoc)" >&2; exit 1 ;;
    esac
fi
# dist pre-sign: `--deep` does NOT cover loose Mach-O under Contents/Resources
# (the embedded PyInstaller backend), but notarization requires every binary to
# carry Developer ID + hardened runtime + secure timestamp. Sign them one by one.
if [ "$SIGN_MODE" = "dist" ]; then
    echo "==> 预签 Resources 内嵌 Mach-O（后端文件多，需几分钟）..."
    find "$app/Contents/Resources" -type f 2>/dev/null | while IFS= read -r bin; do
        file "$bin" 2>/dev/null | grep -q "Mach-O" || continue
        bin_ok=0
        for attempt in 1 2 3; do
            codesign --force --options runtime --timestamp --sign "$sign_id" "$bin" >/dev/null 2>&1 && { bin_ok=1; break; }
            sleep 3
        done
        [ "$bin_ok" -eq 1 ] || echo "warning: timestamp signing failed (notarization will reject): $bin" >&2
    done
    # 嵌套 framework 由内向外补签（先深层后浅层）
    find "$app/Contents/Resources" -type d -name "*.framework" 2>/dev/null \
        | awk '{print length($0), $0}' | sort -rn | while read -r _len fw; do
        codesign --force --options runtime --timestamp --sign "$sign_id" "$fw" >/dev/null 2>&1 \
            || echo "warning: framework signing failed: $fw" >&2
    done
fi
if [ "$SIGN_MODE" = "dist" ]; then
    codesign --force --deep --options runtime --timestamp --sign "$sign_id" "$app" >/dev/null
else
    codesign --force --deep --options runtime --sign "$sign_id" "$app" >/dev/null
fi

# Optional notarization in dist mode when credentials are provided.
if [ "$SIGN_MODE" = "dist" ]; then
    if [ -n "${APPLE_ID:-}" ] && [ -n "${APPLE_APP_SPECIFIC_PASSWORD:-}" ] && [ -n "${APPLE_TEAM_ID:-}" ]; then
        zip_path="$(dirname "$app")/$(basename "$app" .app).zip"
        ditto -c -k --keepParent "$app" "$zip_path"
        xcrun notarytool submit "$zip_path" \
            --apple-id "$APPLE_ID" \
            --password "$APPLE_APP_SPECIFIC_PASSWORD" \
            --team-id "$APPLE_TEAM_ID" \
            --wait
        xcrun stapler staple "$app"
        rm -f "$zip_path"
    else
        echo "note: notarization skipped (set APPLE_ID / APPLE_APP_SPECIFIC_PASSWORD / APPLE_TEAM_ID to enable)" >&2
    fi
fi
echo "$app"
