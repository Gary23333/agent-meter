param([switch]$FrameworkDependent)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$python = Join-Path $root '.venv-win\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Create .venv-win and install windows/requirements.txt first.' }
& $python -m PyInstaller --noconfirm --clean --onedir --name AgentMeterBackend --paths . --collect-all tzdata --collect-all zstandard windows\backend.py --distpath windows\dist --workpath windows\build\pyinstaller --specpath windows\build
if ($LASTEXITCODE -ne 0) { throw 'Backend build failed.' }
$publishArgs = @('publish', 'windows\AgentMeter.Windows', '-c', 'Release', '-r', 'win-x64', '-o', 'windows\dist\AgentMeter')
if ($FrameworkDependent) { $publishArgs += @('--self-contained', 'false') } else { $publishArgs += @('--self-contained', 'true') }
& dotnet @publishArgs
if ($LASTEXITCODE -ne 0) { throw 'Windows application build failed.' }
New-Item -ItemType Directory -Path 'windows\dist\AgentMeter\backend' -Force | Out-Null
Copy-Item -Path 'windows\dist\AgentMeterBackend\*' -Destination 'windows\dist\AgentMeter\backend' -Recurse -Force
Copy-Item -LiteralPath LICENSE,THIRD_PARTY_NOTICES.md -Destination 'windows\dist\AgentMeter' -Force
Copy-Item -LiteralPath 'windows\QUICK_START.md' -Destination 'windows\dist\AgentMeter' -Force
# 桌宠运行时只打包内置形象和离线渲染所需文件，不包含构建工具或第三方资料。
$petRoot = 'windows\dist\AgentMeter\pet'
New-Item -ItemType Directory -Path "$petRoot\runtime\vendor", "$petRoot\presets" -Force | Out-Null
Copy-Item -LiteralPath 'pets\runtime\index.html', 'pets\runtime\css', 'pets\runtime\js' -Destination "$petRoot\runtime" -Recurse -Force
Copy-Item -LiteralPath 'pets\runtime\vendor\three.pet.min.js', 'pets\runtime\vendor\LICENSE.three.txt' -Destination "$petRoot\runtime\vendor" -Force
foreach ($pack in @('gauge', 'cat', 'bot', 'tibo', 'blob')) {
    Copy-Item -LiteralPath "pets\presets\$pack" -Destination "$petRoot\presets" -Recurse -Force
}
$licenses = 'windows\dist\AgentMeter\licenses'
New-Item -ItemType Directory -Path $licenses -Force | Out-Null
$basePython = (& $python -c 'import sys; print(sys.base_prefix)').Trim()
$site = Join-Path $root '.venv-win\Lib\site-packages'
$dotnetDir = Split-Path -Parent (Get-Command dotnet).Source
Copy-Item -LiteralPath (Join-Path $basePython 'LICENSE.txt') -Destination (Join-Path $licenses 'Python-LICENSE.txt') -Force
Copy-Item -LiteralPath (Join-Path $site 'pyinstaller-6.22.3.dist-info\licenses\COPYING.txt') -Destination (Join-Path $licenses 'PyInstaller-COPYING.txt') -Force
Copy-Item -LiteralPath (Join-Path $site 'zstandard-0.25.0.dist-info\licenses\LICENSE') -Destination (Join-Path $licenses 'python-zstandard-LICENSE.txt') -Force
Copy-Item -LiteralPath (Join-Path $site 'tzdata-2026.6.dist-info\licenses\LICENSE') -Destination (Join-Path $licenses 'tzdata-LICENSE.txt') -Force
Copy-Item -LiteralPath (Join-Path $site 'tzdata-2026.6.dist-info\licenses\licenses\LICENSE_APACHE') -Destination (Join-Path $licenses 'tzdata-APACHE.txt') -Force
Copy-Item -LiteralPath (Join-Path $dotnetDir 'LICENSE.txt') -Destination (Join-Path $licenses 'dotnet-LICENSE.txt') -Force
Copy-Item -LiteralPath (Join-Path $dotnetDir 'ThirdPartyNotices.txt') -Destination (Join-Path $licenses 'dotnet-ThirdPartyNotices.txt') -Force
$assets = Get-Content -Raw -Encoding UTF8 'windows\AgentMeter.Windows\obj\project.assets.json' | ConvertFrom-Json
$webviewPackage = $null
foreach ($packageRoot in $assets.packageFolders.PSObject.Properties.Name) {
    $candidate = Join-Path $packageRoot 'microsoft.web.webview2\1.0.4314.35'
    if (Test-Path -LiteralPath (Join-Path $candidate 'LICENSE.txt')) { $webviewPackage = $candidate; break }
}
if (-not $webviewPackage) { throw 'WebView2 SDK license not found.' }
Copy-Item -LiteralPath (Join-Path $webviewPackage 'LICENSE.txt') -Destination (Join-Path $licenses 'WebView2-SDK-LICENSE.txt') -Force
Copy-Item -LiteralPath (Join-Path $webviewPackage 'NOTICE.txt') -Destination (Join-Path $licenses 'WebView2-SDK-NOTICE.txt') -Force
Write-Host 'Built windows\dist\AgentMeter\AgentMeter.Windows.exe'
