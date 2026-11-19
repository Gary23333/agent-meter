$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$app = 'windows\dist\AgentMeter'
foreach ($required in @('AgentMeter.Windows.exe', 'backend\AgentMeterBackend.exe', 'LICENSE', 'licenses\Python-LICENSE.txt', 'QUICK_START.md',
    'pet\runtime\index.html', 'pet\runtime\js\main.js', 'pet\runtime\vendor\three.pet.min.js', 'pet\runtime\vendor\LICENSE.three.txt',
    'pet\presets\gauge\pet.json', 'pet\presets\gauge\avatar.json', 'pet\presets\cat\pet.json', 'pet\presets\cat\avatar.json',
    'pet\presets\bot\pet.json', 'pet\presets\bot\avatar.json', 'pet\presets\tibo\pet.json', 'pet\presets\tibo\avatar.json',
    'pet\presets\blob\pet.json', 'pet\presets\blob\avatar.json')) {
    if (-not (Test-Path -LiteralPath (Join-Path $app $required) -PathType Leaf)) { throw "Missing build output: $required" }
}
New-Item -ItemType Directory -Path 'windows\release' -Force | Out-Null
$archive = 'windows\release\AgentMeter-Windows-x64.zip'
Compress-Archive -Path $app -DestinationPath $archive -CompressionLevel Optimal -Force
$digest = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath 'windows\release\SHA256SUMS.txt' -Encoding ascii -Value "$digest  AgentMeter-Windows-x64.zip"
Write-Host "Packaged $archive"
