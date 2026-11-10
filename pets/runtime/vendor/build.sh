#!/bin/sh
# Rebuilds three.pet.min.js from entry.js. Needs Node/npm and network access; the runtime itself never does.
# The result is byte-for-byte reproducible for the pinned versions (compare with the SHA-256 in README.md).
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cd "$work"
printf '{"name":"pets-vendor","private":true,"type":"module"}\n' > package.json
npm install --no-audit --no-fund --save-exact three@0.187.0 esbuild@0.25.10 >/dev/null
cp "$here/entry.js" entry.js
./node_modules/.bin/esbuild entry.js --bundle --minify --format=esm --target=es2020 --legal-comments=none \
  --banner:js='/* three.js r187 (MIT, (c) three.js authors) - curated tree-shaken build for AgentMeter Pets. See ../README.md */' \
  --outfile="$here/three.pet.min.js"
shasum -a 256 "$here/three.pet.min.js"
