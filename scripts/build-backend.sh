#!/bin/sh
set -eu
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
python="${PYTHON:-python3}"
mkdir -p .runtime/build/pyinstaller
PYINSTALLER_CONFIG_DIR="$root/.runtime/build/pyinstaller/cache" PYTHONDONTWRITEBYTECODE=1 "$python" -m PyInstaller \
  --noconfirm --clean --onedir --name agent-meter-backend \
  --paths "$root" --add-data "$root/agent_meter/helpers:agent_meter/helpers" \
  --hidden-import agent_meter.verify --hidden-import agent_meter.codexbar \
  --distpath "$root/.runtime/build/backend" \
  --workpath "$root/.runtime/build/pyinstaller/work" \
  --specpath "$root/.runtime/build/pyinstaller" \
  "$root/scripts/backend-entry.py"
