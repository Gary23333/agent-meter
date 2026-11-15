$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$python = Join-Path $root '.venv-win\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Create .venv-win and install windows/requirements.txt first.' }
$testCases = @(
    'tests.test_windows_port', 'tests.test_sources', 'tests.test_dsh_tokens',
    'tests.test_cli_sessions.CodexTests', 'tests.test_cli_sessions.McodeTests.test_rows_as_is_and_schema_guard',
    'tests.test_local_tokens.ZCodeTests', 'tests.test_local_tokens.WorkBuddyTests',
    'tests.test_local_tokens.OpenCodeTests', 'tests.test_local_tokens.QoderCreditsTests',
    'tests.test_kimi_tokens.KimiTokenTests', 'tests.test_mimocode_tokens', 'tests.test_claude_code',
    'tests.test_prices.PriceTableTests', 'tests.test_prices.PeakPriceTests',
    'tests.test_activity.CodexImageTests', 'tests.test_activity.KimiTests', 'tests.test_activity.OpencodeTests', 'tests.test_activity.CollectActivityTests',
    'tests.test_reset_forecast.NormalizeTests', 'tests.test_reset_forecast.CombineTests',
    'tests.test_reset_forecast.CountdownTests', 'tests.test_reset_forecast.HistoryTests',
    'tests.test_reset_forecast.CollectTests', 'tests.test_reset_forecast.TransportTests',
    'tests.test_api_plan_sources.ZCodeTests', 'tests.test_api_plan_sources.VolcengineTests', 'tests.test_api_plan_sources.MimoTests', 'tests.test_api_plan_sources.QoderWindowsTests', 'tests.test_api_plan_sources.TraeWindowsTests', 'tests.test_web_sources.ParserTests',
    'tests.test_collection.DerivedTests.test_medals_from_history', 'tests.test_collection.WindowTests'
)
& $python -m unittest @testCases -q
if ($LASTEXITCODE -ne 0) { throw 'Windows collector tests failed.' }
& dotnet run --project windows\AccountPreferences.Tests -c Release
if ($LASTEXITCODE -ne 0) { throw 'Account preferences test failed.' }
