# 只在一次性的交互式 Windows 构建机上移动鼠标、按键并启动虚构数据面板。
param([Parameter(Mandatory)][string]$Executable, [Parameter(Mandatory)][string]$OutputDir)
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted') { throw '需要 GitHub 托管的隔离桌面' }
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Drawing, System.Windows.Forms
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class TrayDesktop {
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr FindWindow(string cls, string title);
    public static IntPtr ShellWindow(string cls) { return FindWindow(cls,null); }
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr handle);
    [DllImport("user32.dll")] public static extern uint GetDpiForWindow(IntPtr handle);
    [DllImport("user32.dll")] public static extern IntPtr SetThreadDpiAwarenessContext(IntPtr context);
    [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint x, uint y, uint data, UIntPtr extra);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
    [DllImport("user32.dll")] public static extern void keybd_event(byte key,byte scan,uint flags,UIntPtr extra);
}
'@
[void][TrayDesktop]::SetThreadDpiAwarenessContext([IntPtr](-4))
$null = New-Item -ItemType Directory -Path $OutputDir -Force
$report = [ordered]@{ screens = @(); steps = @(); windowDpi = $null }
$desc = [Windows.Automation.TreeScope]::Descendants
$root = [Windows.Automation.AutomationElement]::RootElement
$all = [Windows.Automation.Condition]::TrueCondition
function Record([string]$step) { $report.steps += $step; Write-Host $step }
function Find-ShellControl([string]$kind) {
    foreach ($class in 'Shell_TrayWnd','NotifyIconOverflowWindow','TopLevelWindowForOverflowXamlIsland') {
        $hwnd = [TrayDesktop]::ShellWindow($class)
        if ($hwnd -eq [IntPtr]::Zero -or -not [TrayDesktop]::IsWindowVisible($hwnd)) { continue }
        $base = [Windows.Automation.AutomationElement]::FromHandle($hwnd)
        foreach ($item in $base.FindAll($desc,$all)) {
            try {
                $c = $item.Current
                if ($c.IsOffscreen -or $c.BoundingRectangle.Width -le 0) { continue }
                if ($kind -eq 'icon' -and $c.Name -like 'Agent Meter*') { return $item }
                if ($kind -eq 'overflow' -and ($c.Name -match 'show hidden icons|notification chevron|显示隐藏的图标' -or $c.AutomationId -eq 'SystemTray.ChevronButton')) { return $item }
            } catch [Windows.Automation.ElementNotAvailableException] { continue }
        }
    }
}
function Click-Control($element, [int]$hold=45) {
    $r = $element.Current.BoundingRectangle
    if ($r.IsEmpty -or $r.Width -le 0) { throw '待点击控件没有有效边界' }
    if (-not [TrayDesktop]::SetCursorPos([int]($r.X+$r.Width/2),[int]($r.Y+$r.Height/2))) { throw '无法设置隔离桌面鼠标位置' }
    [TrayDesktop]::mouse_event(2,0,0,0,[UIntPtr]::Zero)
    try { Start-Sleep -Milliseconds $hold } finally { [TrayDesktop]::mouse_event(4,0,0,0,[UIntPtr]::Zero) }
}
function Click-Tray([int]$hold=45) {
    $icon = Find-ShellControl 'icon'
    if (-not $icon) {
        $chevron = Find-ShellControl 'overflow'
        if (-not $chevron) { throw 'Explorer 中未找到演示托盘图标或溢出入口' }
        Click-Control $chevron
        $deadline = [DateTime]::UtcNow.AddSeconds(4)
        do {
            Start-Sleep -Milliseconds 200
            $icon = Find-ShellControl 'icon'
        } while (-not $icon -and [DateTime]::UtcNow -lt $deadline)
    }
    if (-not $icon) { throw '展开隐藏图标后仍未找到演示托盘图标' }
    Click-Control $icon $hold
}
function Get-Panel {
    foreach ($item in $root.FindAll([Windows.Automation.TreeScope]::Children,$processCondition)) {
        if ($item.Current.Name -eq 'Agent Meter' -and [TrayDesktop]::IsWindowVisible([IntPtr]$item.Current.NativeWindowHandle)) { return $item }
    }
}
function Wait-Panel([bool]$visible, [string]$step) {
    $until = [DateTime]::UtcNow.AddSeconds(3)
    do {
        Start-Sleep -Milliseconds 70
        $panel = Get-Panel
        if ([bool]$panel -eq $visible) { Record $step; return $panel }
    } while ([DateTime]::UtcNow -lt $until)
    throw "面板开合状态与预期不同：$step"
}
function Save-Navigation($panel,[string]$name) {
    # 移出导航，排除鼠标悬停颜色，比较完整七个标签（包括文字）。
    $tabs = @($panel.FindAll($desc,$all) | Where-Object { $_.Current.Name -in @('账户','应用','用量','报告','预测','桌宠','收集') })
    if ($tabs.Count -ne 7) { throw "未能唯一定位七个导航标签：$($tabs.Count)" }
    $area = [System.Windows.Rect]::Empty
    foreach ($tab in $tabs) { $area.Union($tab.Current.BoundingRectangle) }
    [void][TrayDesktop]::SetCursorPos(1,1)
    Start-Sleep -Milliseconds 200
    $bitmap = [Drawing.Bitmap]::new([int]$area.Width,[int]$area.Height)
    try {
        $graphics = [Drawing.Graphics]::FromImage($bitmap)
        try { $graphics.CopyFromScreen([int]$area.Left,[int]$area.Top,0,0,$bitmap.Size) } finally { $graphics.Dispose() }
        $path = Join-Path $OutputDir "$name.png"
        $bitmap.Save($path,[Drawing.Imaging.ImageFormat]::Png)
        return (Get-FileHash -LiteralPath $path).Hash
    } finally { $bitmap.Dispose() }
}
$app = $null
try {
    foreach ($screen in [Windows.Forms.Screen]::AllScreens) { $report.screens += [ordered]@{bounds=$screen.Bounds.ToString(); work=$screen.WorkingArea.ToString()} }
    if ([TrayDesktop]::ShellWindow('Shell_TrayWnd') -eq [IntPtr]::Zero) { throw '隔离会话未提供 Explorer 任务栏' }
    $app = Start-Process -FilePath $Executable -ArgumentList '--demo','--background' -PassThru
    $processCondition = [Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::ProcessIdProperty,$app.Id)
    Start-Sleep -Seconds 2
    $null = Wait-Panel $false '后台启动时面板收起'
    Click-Tray
    $panel = Wait-Panel $true '点击 Explorer 图标后弹出'
    $report.windowDpi = [TrayDesktop]::GetDpiForWindow([IntPtr]$panel.Current.NativeWindowHandle)
    $usage = $panel.FindFirst($desc,[Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::NameProperty,'用量'))
    if (-not $usage) { throw '面板缺少用量导航入口' }
    Click-Control $usage
    Start-Sleep -Milliseconds 250
    $before = Save-Navigation (Get-Panel) 'usage-before'
    [TrayDesktop]::keybd_event(27,0,0,[UIntPtr]::Zero); [TrayDesktop]::keybd_event(27,0,2,[UIntPtr]::Zero)
    $null = Wait-Panel $false '按 Esc 后收起'
    Click-Tray
    $panel = Wait-Panel $true '再次点击 Explorer 图标后弹出'
    if ((Save-Navigation $panel 'usage-reopened') -ne $before) { throw '重新打开后导航像素发生变化' }
    Record '重新打开后七个导航标签像素一致'
    Click-Tray 550
    $null = Wait-Panel $false '长按图标并松开后保持收起'
    Start-Sleep -Milliseconds 250
    if (Get-Panel) { throw '同次点击松开后意外重开' }
    Click-Tray
    $panel = Wait-Panel $true '下一次独立点击正常打开'
    $report.result = 'passed'
} catch {
    $report.error = $_.Exception.Message
    foreach ($element in $root.FindAll([Windows.Automation.TreeScope]::Children,$all)) {
        $cls = $element.Current.ClassName
        Write-Host "窗口类型 $cls"
        if ($cls -match 'TrayWnd|Overflow') {
            foreach ($child in $element.FindAll($desc,$all)) {
                Write-Host ($child.Current.ClassName + ' | ' + $child.Current.Name + ' | ' + $child.Current.AutomationId)
            }
        }
    }
    throw
} finally {
    $report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $OutputDir 'result.json') -Encoding UTF8
    if ($app -and -not $app.HasExited) { Stop-Process -Id $app.Id }
}
