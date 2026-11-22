# 只在一次性的交互式 Windows 构建机上移动鼠标、按键并启动虚构数据面板。
param([Parameter(Mandatory)][string]$Executable, [Parameter(Mandatory)][string]$OutputDir,
      [ValidateSet('current','125','150','175','200')][string]$Scale='current')
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
function Get-NavigationTabs($panel) {
    # 页面正文也可能出现「桌宠」等字样，只取与「用量」标签同一行的七个控件。
    $items = $panel.FindAll($desc,$all)
    $usage = $items | Where-Object { $_.Current.Name -eq '用量' } | Select-Object -First 1
    if (-not $usage) { throw '面板缺少用量导航' }
    $row = $usage.Current.BoundingRectangle.Top
    $tabs = @($items | Where-Object { $_.Current.Name -in @('账户','应用','用量','报告','预测','桌宠','收集') -and $_.Current.BoundingRectangle.Top -eq $row } | Sort-Object { $_.Current.BoundingRectangle.Left })
    if (($tabs | ForEach-Object { $_.Current.Name }) -join ',' -ne '账户,应用,用量,报告,预测,桌宠,收集') { throw '未能定位完整导航' }
    return $tabs
}
function Save-Navigation($panel,[string]$name,[string]$selected='用量') {
    # 移出导航，排除鼠标悬停颜色，比较完整七个标签（包括文字）。
    $tabs = @(Get-NavigationTabs $panel)
    $area = [System.Windows.Rect]::Empty
    foreach ($tab in $tabs) { $area.Union($tab.Current.BoundingRectangle) }
    [void][TrayDesktop]::SetCursorPos(1,1)
    Start-Sleep -Milliseconds 200
    $hash = Save-Region $area $name
    $image = [Drawing.Bitmap]::new((Join-Path $OutputDir "$name.png"))
    try {
        foreach ($tab in $tabs) {
            $rect = $tab.Current.BoundingRectangle
            $pixel = $image.GetPixel([int]($rect.Left-$area.Left+$rect.Width*0.2),[int]($rect.Height*0.19))
            $expected = if ($tab.Current.Name -eq $selected) { @(115,76,219) } else { @(26,32,47) }
            $distance = [Math]::Abs($pixel.R-$expected[0])+[Math]::Abs($pixel.G-$expected[1])+[Math]::Abs($pixel.B-$expected[2])
            if ($distance -gt 45) { throw "$name 中「$($tab.Current.Name)」的颜色与预期不符，截图已保留" }
        }
    } finally { $image.Dispose() }
    return $hash
}
function Test-NavigationSequence($panel,[bool]$stableRow) {
    $initial = @(Get-NavigationTabs $panel)
    $row = $initial[0].Current.BoundingRectangle.Top
    $hashes = @{}
    $offsets = [ordered]@{}
    # 分别从容纳额度环的账户页和紧凑页面进入同一页，最后回到用量页。
    $steps = @('账户','应用','用量','报告','预测','桌宠','收集','账户','用量','应用','账户','报告','用量')
    for ($i=0; $i -lt $steps.Count; $i++) {
        $page = $steps[$i]
        $tabs = @(Get-NavigationTabs $panel)
        $target = $tabs | Where-Object { $_.Current.Name -eq $page }
        Click-Control $target
        $hash = Save-Navigation $panel "tab-$i" $page
        $y = (@(Get-NavigationTabs $panel))[0].Current.BoundingRectangle.Top
        $offsets[$page] = $y-$row
        if ($stableRow -and $y -ne $row) { throw "切到$page 后导航偏移了 $($y-$row) 个物理像素" }
        if ($hashes.ContainsKey($page) -and $hashes[$page] -ne $hash) { throw "再次进入$page 时导航像素有差异" }
        $hashes[$page] = $hash
    }
    $report.navigationOffsets = $offsets
    $refresh = $panel.FindFirst($desc,[Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::NameProperty,'刷新用量'))
    if (-not $refresh) { $refresh = $panel.FindFirst($desc,[Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::NameProperty,'刷新')) }
    if (-not $refresh) { throw '找不到顶部刷新按钮' }
    Click-Control $refresh
    $cost = $panel.FindFirst($desc,[Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::NameProperty,'API 等价估算'))
    if (-not $cost -or (Save-Navigation $panel 'usage-refreshed') -ne $hashes['用量']) { throw '刷新后用量页或导航显示发生变化' }
    Record '连续点选七页、往返切页和手动刷新后导航高亮正确'
}
function Test-UsageLayout($panel,$result,[bool]$enforce,[string]$name='usage') {
    $bounds = $panel.Current.BoundingRectangle
    $result.panelPixels = @{ width=$bounds.Width; height=$bounds.Height }
    $image = [Drawing.Bitmap]::new((Join-Path $OutputDir "$name.png"))
    $result.metricBottomPadding = [ordered]@{}
    try {
        foreach ($value in @('1.77M','$2.464')) {
            $matchesByName = $panel.FindAll($desc,[Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::NameProperty,$value))
            $label = $matchesByName | Sort-Object { $_.Current.BoundingRectangle.Top } | Select-Object -First 1
            if (-not $label) { throw "用量首屏缺少演示数值 $value" }
            $r = $label.Current.BoundingRectangle
            $left = [int][Math]::Ceiling($r.Left - $bounds.Left)
            $top = [int][Math]::Ceiling($r.Top - $bounds.Top)
            $right = [int][Math]::Floor($r.Right - $bounds.Left)
            $bottom = [int][Math]::Floor($r.Bottom - $bounds.Top)
            if ($left -lt 0 -or $top -lt 0 -or $right -gt $image.Width -or $bottom -gt $image.Height) { throw "数值 $value 超出可见弹层" }
            # 演示主题使用白色大数字。检查最后一个可见笔画与标签底边之间的实际留白。
            $lastInk = $null
            for ($y=$bottom-1; $y -ge $top -and $null -eq $lastInk; $y--) {
                for ($x=$left; $x -lt $right; $x++) {
                    $pixel = $image.GetPixel($x,$y)
                    if ($pixel.R -gt 190 -and $pixel.G -gt 190 -and $pixel.B -gt 190) { $lastInk=$y; break }
                }
            }
            if ($null -eq $lastInk) { throw "未在截图中找到数值 $value 的笔画" }
            $padding = $bottom - 1 - $lastInk
            $result.metricBottomPadding[$value] = $padding
            if ($enforce -and $padding -lt 2) { throw "数值 $value 的笔画贴住底边，剩余 $padding 像素" }
        }
    } finally { $image.Dispose() }
    if (-not $enforce) { return }
    $work = [Windows.Forms.Screen]::FromPoint([Drawing.Point]::new([int]$bounds.Left,[int]$bounds.Top)).WorkingArea
    if ($bounds.Left -lt $work.Left -or $bounds.Top -lt $work.Top -or $bounds.Right -gt $work.Right -or $bounds.Bottom -gt $work.Bottom) { throw '托盘弹层超出工作区' }
    $dpi = [TrayDesktop]::MonitorDpi([int]($bounds.Left+$bounds.Width/2),[int]($bounds.Top+$bounds.Height/2))
    $expectedWidth = [Math]::Min(440*$dpi/96,$work.Width-24*$dpi/96)
    if ([Math]::Abs($bounds.Width-$expectedWidth) -gt 2) { throw "弹层宽度 $($bounds.Width) 与缩放后的 $expectedWidth 不符" }
    Record '面板适应当前工作区，两项用量大字底部完整'
}
function Set-DesktopScale([string]$percent) {
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
    $choice = $choices | Where-Object { $_.Current.Name -like "$percent%*" } | Select-Object -First 1
    if (-not $choice) { throw ('该显示模式可选的缩放为 ' + (($choices | ForEach-Object { $_.Current.Name }) -join ', ')) }
    Click-Control $choice
    Start-Sleep -Seconds 2
    $settings.GetCurrentPattern([Windows.Automation.WindowPattern]::Pattern).Close()
}
$app = $null
try {
    if ($Scale -ne 'current') {
        # 使用系统设置里的缩放选择器，实际读回 DPI 后才开始测试。
        if ($Scale -in '150','175','200') { [TrayDesktop]::UseLargeDisplay($Scale -eq '200'); Start-Sleep -Seconds 2 }
        Set-DesktopScale $Scale
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
    $version = [Diagnostics.FileVersionInfo]::GetVersionInfo($Executable)
    if ([version]$version.FileVersion -ge [version]'0.1.0.47') {
        Test-NavigationSequence $panel ([version]$version.FileVersion -ge [version]'0.1.0.48')
    } else {
        Click-Control (@(Get-NavigationTabs $panel) | Where-Object { $_.Current.Name -eq '用量' })
    }
    $before = Save-Navigation (Get-Panel) 'usage-before'
    $null = Save-Region (Get-Panel).Current.BoundingRectangle 'usage'
    $report.fileVersion = $version.FileVersion
    $checkSize = [version]$version.FileVersion -ge [version]'0.1.0.47'
    Test-UsageLayout $panel $report $checkSize
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
    if ($checkSize -and $Scale -eq '150') {
        # 同一进程保持运行，改动同一块屏幕的真实缩放，然后从原来的常驻图标再打开。
        Set-DesktopScale '125'
        $null = Wait-Panel $false '打开系统设置后面板收起'
        Click-Tray
        $panel = Wait-Panel $true '改变缩放后从原图标重新打开'
        $bounds = $panel.Current.BoundingRectangle
        $newDpi = [TrayDesktop]::MonitorDpi([int]($bounds.Left+$bounds.Width/2),[int]($bounds.Top+$bounds.Height/2))
        if ($newDpi -ne 120) { throw "运行中调整后实际 DPI 为 $newDpi，预期 120" }
        $report.afterScale = [ordered]@{ dpi=$newDpi; scalePercent=125 }
        $null = Save-Navigation $panel 'navigation-after-scale'
        $null = Save-Region $bounds 'usage-after-scale'
        Test-UsageLayout $panel $report.afterScale $true 'usage-after-scale'
    }
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
