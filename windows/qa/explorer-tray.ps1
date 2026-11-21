# 只在一次性的交互式 Windows 构建机上移动鼠标、按键并启动虚构数据面板。
param([Parameter(Mandatory)][string]$Executable, [Parameter(Mandatory)][string]$OutputDir,
      [ValidateSet('current','125','150','200')][string]$Scale='current')
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
    [DllImport("user32.dll")] static extern IntPtr GetWindowDpiAwarenessContext(IntPtr handle);
    [DllImport("user32.dll")] static extern int GetAwarenessFromDpiAwarenessContext(IntPtr context);
    public static int Awareness(IntPtr handle) { return GetAwarenessFromDpiAwarenessContext(GetWindowDpiAwarenessContext(handle)); }
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern IntPtr CreateWindowEx(int ex, string cls, string title, uint style, int x, int y, int w, int h, IntPtr parent, IntPtr menu, IntPtr instance, IntPtr param);
    [DllImport("user32.dll")] static extern bool DestroyWindow(IntPtr h);
    public static uint MonitorDpi(int x, int y) {
        IntPtr old = SetThreadDpiAwarenessContext(new IntPtr(-4));
        if (old == IntPtr.Zero) throw new InvalidOperationException("隔离桌面不支持逐屏 DPI 探测");
        try {
            IntPtr probe = CreateWindowEx(0,"STATIC","",0x80000000,x,y,2,2,IntPtr.Zero,IntPtr.Zero,IntPtr.Zero,IntPtr.Zero);
            if (probe == IntPtr.Zero) throw new InvalidOperationException("无法读取隔离屏幕 DPI");
            try { return GetDpiForWindow(probe); } finally { DestroyWindow(probe); }
        } finally { SetThreadDpiAwarenessContext(old); }
    }
    [DllImport("user32.dll")] public static extern IntPtr SetThreadDpiAwarenessContext(IntPtr context);
    [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint x, uint y, uint data, UIntPtr extra);
    // DEVMODEW 的显示器布局。仅在隔离机上选择驱动程序自己枚举出的模式。
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
    struct DisplayMode {
        [MarshalAs(UnmanagedType.ByValTStr,SizeConst=32)] public string DeviceName;
        public ushort SpecVersion, DriverVersion, Size, DriverExtra;
        public uint Fields;
        public int X,Y;
        public uint Orientation,FixedOutput;
        public short Color,Duplex,YResolution,TrueType,Collate;
        [MarshalAs(UnmanagedType.ByValTStr,SizeConst=32)] public string FormName;
        public ushort LogPixels;
        public uint Bpp,Width,Height,Flags,Frequency,IcmMethod,IcmIntent,MediaType,Dither,Reserved1,Reserved2,PanWidth,PanHeight;
    }
    [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern bool EnumDisplaySettings(string device,int number,ref DisplayMode mode);
    [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int ChangeDisplaySettings(ref DisplayMode mode,uint flags);
    public static void UseLargeDisplay(bool largest) {
        var mode = new DisplayMode { Size = (ushort)Marshal.SizeOf(typeof(DisplayMode)) };
        DisplayMode best = new DisplayMode();
        for (int i=0; EnumDisplaySettings(null,i,ref mode); i++) {
            if (mode.Width < 1920 || mode.Height < 1080 || mode.Bpp != 32 || mode.Orientation != 0) continue;
            if (!largest && (mode.Width != 1920 || mode.Height != 1080)) continue;
            if (mode.Width * mode.Height > best.Width * best.Height) best = mode;
        }
        if (best.Width == 0) throw new InvalidOperationException("显示驱动未提供所需的分辨率");
        best.Fields = 0x180000; // DM_PELSWIDTH | DM_PELSHEIGHT
        int result = ChangeDisplaySettings(ref best,0);
        if (result != 0) throw new InvalidOperationException("显示模式切换失败：" + result);
        Console.WriteLine("隔离桌面分辨率：" + best.Width + " × " + best.Height);
    }
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
function Find-ShellControl([string]$kind,[string[]]$classes=@('Shell_TrayWnd','NotifyIconOverflowWindow','TopLevelWindowForOverflowXamlIsland')) {
    foreach ($class in $classes) {
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
function Pin-TestIcon {
    if (Find-ShellControl 'icon' @('Shell_TrayWnd')) { return }
    # 使用 Explorer 自己的「在任务栏显示」设置，只更改此临时用户中新启动的演示程序。
    $items = @(Get-ChildItem 'HKCU:\Control Panel\NotifyIconSettings' | Get-ItemProperty | Where-Object { $_.ExecutablePath -like '*\AgentMeter.Windows.exe' })
    if ($items.Count -ne 1) { throw '无法唯一定位演示程序的托盘偏好' }
    New-ItemProperty -LiteralPath $items[0].PSPath -Name IsPromoted -Value 1 -PropertyType DWord -Force | Out-Null
    $until = [DateTime]::UtcNow.AddSeconds(5)
    do {
        Start-Sleep -Milliseconds 180
        if (Find-ShellControl 'icon' @('Shell_TrayWnd')) { Record '演示图标已在主任务栏中显示'; return }
    } while ([DateTime]::UtcNow -lt $until)
    throw 'Explorer 尚未在主任务栏显示演示图标'
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
function Save-Region([System.Windows.Rect]$area,[string]$name) {
    $bitmap = [Drawing.Bitmap]::new([int]$area.Width,[int]$area.Height)
    try {
        $graphics = [Drawing.Graphics]::FromImage($bitmap)
        try { $graphics.CopyFromScreen([int]$area.Left,[int]$area.Top,0,0,$bitmap.Size) } finally { $graphics.Dispose() }
        $path = Join-Path $OutputDir "$name.png"
        $bitmap.Save($path,[Drawing.Imaging.ImageFormat]::Png)
        return (Get-FileHash -LiteralPath $path).Hash
    } finally { $bitmap.Dispose() }
}
function Save-Navigation($panel,[string]$name) {
    # 移出导航，排除鼠标悬停颜色，比较完整七个标签（包括文字）。
    $cost = $panel.FindFirst($desc,[Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::NameProperty,'API 等价估算'))
    if (-not $cost) { throw '重新打开的面板未显示用量页' }
    $tabs = @($panel.FindAll($desc,$all) | Where-Object { $_.Current.Name -in @('账户','应用','用量','报告','预测','桌宠','收集') })
    if ($tabs.Count -ne 7) { throw "未能唯一定位七个导航标签：$($tabs.Count)" }
    $area = [System.Windows.Rect]::Empty
    foreach ($tab in $tabs) { $area.Union($tab.Current.BoundingRectangle) }
    [void][TrayDesktop]::SetCursorPos(1,1)
    Start-Sleep -Milliseconds 200
    return Save-Region $area $name
}
$app = $null
try {
    if ($Scale -ne 'current') {
        # 使用系统设置里的缩放选择器，实际读回 DPI 后才开始测试。
        if ($Scale -in '150','200') { [TrayDesktop]::UseLargeDisplay($Scale -eq '200'); Start-Sleep -Seconds 2 }
        Start-Process 'ms-settings:display'
        $end = [DateTime]::UtcNow.AddSeconds(15)
        do {
            Start-Sleep -Milliseconds 400
            $settings = $root.FindFirst([Windows.Automation.TreeScope]::Children,[Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::NameProperty,'Settings'))
            if (-not $settings) { continue }
            $combos = @($settings.FindAll($desc,[Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::ControlTypeProperty,[Windows.Automation.ControlType]::ComboBox)))
            $chooser = $combos | Where-Object { $_.Current.Name -match 'scale|size of text' -or $_.Current.AutomationId -match 'scal|DPI' } | Select-Object -First 1
        } while (-not $chooser -and [DateTime]::UtcNow -lt $end)
        if (-not $chooser) { throw ('找不到系统缩放选择器，可见下拉框为 ' + (($combos | ForEach-Object { $_.Current.Name + '/' + $_.Current.AutomationId }) -join ', ')) }
        Click-Control $chooser
        Start-Sleep -Milliseconds 250
        $choices = @($settings.FindAll($desc,$all) | Where-Object { $_.Current.ControlType -eq [Windows.Automation.ControlType]::ListItem })
        $choice = $choices | Where-Object { $_.Current.Name -like "$Scale%*" } | Select-Object -First 1
        if (-not $choice) { throw ('该显示模式可选的缩放为 ' + (($choices | ForEach-Object { $_.Current.Name }) -join ', ')) }
        Click-Control $choice
        Start-Sleep -Seconds 2
        $settings.GetCurrentPattern([Windows.Automation.WindowPattern]::Pattern).Close()
    }
    foreach ($screen in [Windows.Forms.Screen]::AllScreens) {
        $dpi = [TrayDesktop]::MonitorDpi($screen.Bounds.Left + [int]($screen.Bounds.Width/2),$screen.Bounds.Top + [int]($screen.Bounds.Height/2))
        $report.screens += [ordered]@{bounds=$screen.Bounds.ToString(); work=$screen.WorkingArea.ToString(); dpi=$dpi; scalePercent=100*$dpi/96}
    }
    if ($Scale -ne 'current' -and $report.screens.scalePercent -notcontains [int]$Scale) { throw '系统未实际应用指定的屏幕缩放' }
    if ([TrayDesktop]::ShellWindow('Shell_TrayWnd') -eq [IntPtr]::Zero) { throw '隔离会话未提供 Explorer 任务栏' }
    $app = Start-Process -FilePath $Executable -ArgumentList '--demo','--background' -PassThru
    $processCondition = [Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::ProcessIdProperty,$app.Id)
    Start-Sleep -Seconds 2
    $null = Wait-Panel $false '后台启动时面板收起'
    Click-Tray
    $panel = Wait-Panel $true '点击 Explorer 图标后弹出'
    $report.windowDpi = [TrayDesktop]::GetDpiForWindow([IntPtr]$panel.Current.NativeWindowHandle)
    $report.windowAwareness = [TrayDesktop]::Awareness([IntPtr]$panel.Current.NativeWindowHandle)
    [void][TrayDesktop]::SetCursorPos(1,1)
    Start-Sleep -Milliseconds 350
    $null = Save-Region $panel.Current.BoundingRectangle 'accounts'
    $usage = $panel.FindFirst($desc,[Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::NameProperty,'用量'))
    if (-not $usage) { throw '面板缺少用量导航入口' }
    Click-Control $usage
    Start-Sleep -Milliseconds 250
    $before = Save-Navigation (Get-Panel) 'usage-before'
    $null = Save-Region (Get-Panel).Current.BoundingRectangle 'usage'
    [TrayDesktop]::keybd_event(27,0,0,[UIntPtr]::Zero); [TrayDesktop]::keybd_event(27,0,2,[UIntPtr]::Zero)
    $null = Wait-Panel $false '按 Esc 后收起'
    Click-Tray
    $panel = Wait-Panel $true '再次点击 Explorer 图标后弹出'
    if ((Save-Navigation $panel 'usage-reopened') -ne $before) { throw '重新打开后导航像素发生变化' }
    Record '重新打开后七个导航标签像素一致'
    [TrayDesktop]::keybd_event(27,0,0,[UIntPtr]::Zero); [TrayDesktop]::keybd_event(27,0,2,[UIntPtr]::Zero)
    $null = Wait-Panel $false '从隐藏图标打开的用量页可再次收起'
    Pin-TestIcon
    Click-Control (Find-ShellControl 'icon' @('Shell_TrayWnd'))
    $panel = Wait-Panel $true '从常驻图标打开面板'
    Click-Control (Find-ShellControl 'icon' @('Shell_TrayWnd')) 550
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
