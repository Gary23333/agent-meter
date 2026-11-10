#!/bin/sh
# Contact sheet of an installed pack (built-in or in ~/Library/Application Support/AgentMeter/pets) as a PNG, rendered
# with the app's own WebKit - no browser or server needed (macOS).
#   sh pets/tools/sheet.sh gauge [out.png] ["frames=1&size=170&themes=0"]
set -eu
root="$(cd "$(dirname "$0")/../.." && pwd)"
bin="${AGENT_METER_BIN:-$root/menubar/.build/debug/AgentMeterBar}"
[ -x "$bin" ] || { echo "build the app first: swift build --package-path menubar" >&2; exit 1; }
out="${2:-$root/.runtime/pet-sheets/$1.png}"
mkdir -p "$(dirname "$out")"
"$bin" --pet-sheet "$1" "$out" "${3:-}"
