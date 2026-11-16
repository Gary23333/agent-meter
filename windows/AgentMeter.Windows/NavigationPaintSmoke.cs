using System.Drawing.Imaging;
using System.Runtime.InteropServices;

namespace AgentMeter.Windows;

/// <summary>在隔离构建机检查真实窗口像素，而不是只检查控件的静态绘制结果。</summary>
internal static class NavigationPaintSmoke
{
    public static void Run(string output)
    {
        Directory.CreateDirectory(output);
        using var window = new MeterWindow(demo: true, windowed: false)
        { StartPosition = FormStartPosition.Manual, Location = new Point(20, 20), TopMost = true };
        window.Shown += async (_, _) =>
        {
            try { await window.SyntheticNavigationPaintAsync(output); }
            catch (Exception error) { Console.Error.WriteLine(error.Message); Environment.ExitCode = 1; }
            finally { window.Close(); }
        };
        Application.Run(window);
    }
}

internal sealed partial class MeterWindow
{
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr handle, int command);
    [DllImport("user32.dll")] static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extraInfo);
    [DllImport("user32.dll")] static extern void keybd_event(byte key, byte scan, uint flags, UIntPtr extraInfo);
    static void ClickOnIsolatedDesktop(Control target)
    {
        Cursor.Position = target.PointToScreen(new Point(target.Width / 2, target.Height / 2));
        mouse_event(0x0002, 0, 0, 0, UIntPtr.Zero);
        mouse_event(0x0004, 0, 0, 0, UIntPtr.Zero);
    }
    internal async Task SyntheticNavigationPaintAsync(string output)
    {
        if (!demo) throw new InvalidOperationException("仅允许演示数据检查绘制");
        // 构建进程本身以隐藏方式启动；测试窗口必须显式显示到隔离桌面。
        ShowWindow(Handle, 5); BringToFront(); Activate();
        await RefreshData();
        content.AutoScrollPosition = new Point(0, 160);
        await Task.Delay(100);
        int scrollBefore = -content.AutoScrollPosition.Y;
        using (var snapshot = System.Text.Json.JsonDocument.Parse(lastSnapshot!)) Render(snapshot.RootElement);
        await Task.Delay(100);
        int scrollAfter = -content.AutoScrollPosition.Y;
        if (scrollBefore < 80 || Math.Abs(scrollAfter - scrollBefore) > 2)
            throw new InvalidOperationException($"scroll_refresh before={scrollBefore} after={scrollAfter}");
        // 只在隔离构建机运行，移开鼠标以免悬停色干扰像素判断。
        Cursor.Position = new Point(1, 1);
        var tabs = new[] { accountTab, applicationsTab, usageTab, reportTab, forecastTab, petTab, collectionTab };
        foreach (var (selected, page) in new[] { (0, View.Accounts), (1, View.Applications), (2, View.Usage), (5, View.Pet) })
        {
            ClickOnIsolatedDesktop(tabs[selected]);
            await Task.Delay(350);
            Cursor.Position = new Point(1, 1);
            if (view != page) throw new InvalidOperationException("导航鼠标点击没有切换页面");
            navigationStrip.Invalidate(true); Update();
            await Task.Delay(100);
            using var picture = new Bitmap(ClientSize.Width, ClientSize.Height, PixelFormat.Format32bppArgb);
            using (var graphics = Graphics.FromImage(picture)) graphics.CopyFromScreen(PointToScreen(Point.Empty), Point.Empty, ClientSize);
            picture.Save(Path.Combine(output, $"navigation-{selected}.png"), ImageFormat.Png);
            for (int i = 0; i < tabs.Length; i++)
            {
                if (tabs[i].IsSelected != (i == selected)) throw new InvalidOperationException("导航选中状态错误");
                CheckTabPixel(picture, tabs[i], i == selected);
            }
            if (page is View.Usage or View.Applications)
            {
                string name = page == View.Usage ? "usage-period-selector" : "app-filter-selector";
                var strip = content.Controls.OfType<NavigationStrip>().Single(item => item.Name == name);
                var choices = strip.Controls.OfType<NavigationTab>().ToArray();
                for (int i = 0; i < choices.Length; i++) CheckTabPixel(picture, choices[i], i == 0);
                ClickOnIsolatedDesktop(choices[1]);
                await Task.Delay(350);
                Cursor.Position = new Point(1, 1);
                await Task.Delay(100);
                strip = content.Controls.OfType<NavigationStrip>().Single(item => item.Name == name);
                choices = strip.Controls.OfType<NavigationTab>().ToArray();
                using var afterClick = new Bitmap(ClientSize.Width, ClientSize.Height, PixelFormat.Format32bppArgb);
                using (var graphics = Graphics.FromImage(afterClick)) graphics.CopyFromScreen(PointToScreen(Point.Empty), Point.Empty, ClientSize);
                afterClick.Save(Path.Combine(output, $"{name}-changed.png"), ImageFormat.Png);
                for (int i = 0; i < choices.Length; i++)
                {
                    if (choices[i].IsSelected != (i == 1)) throw new InvalidOperationException("筛选选中状态错误");
                    CheckTabPixel(afterClick, choices[i], i == 1);
                }
            }
        }
        // 真实键盘事件检查自绘控件的可操作性，再逐个核对七种主题的高亮。
        if (!reportTab.Focus()) throw new InvalidOperationException("无法聚焦导航按钮");
        keybd_event(0x20, 0, 0, UIntPtr.Zero);
        keybd_event(0x20, 0, 0x0002, UIntPtr.Zero);
        await Task.Delay(350);
        if (view != View.Report) throw new InvalidOperationException("键盘空格没有切换页面");
        foreach (var option in VisualThemes.All)
        {
            if (!SetTheme(option)) throw new InvalidOperationException("无法切换主题");
            ClickOnIsolatedDesktop(accountTab);
            await Task.Delay(350);
            Cursor.Position = new Point(1, 1);
            await Task.Delay(100);
            if (view != View.Accounts) throw new InvalidOperationException("主题切换后导航无法点击");
            using var picture = new Bitmap(ClientSize.Width, ClientSize.Height, PixelFormat.Format32bppArgb);
            using (var graphics = Graphics.FromImage(picture)) graphics.CopyFromScreen(PointToScreen(Point.Empty), Point.Empty, ClientSize);
            picture.Save(Path.Combine(output, $"theme-{option.Id}.png"), ImageFormat.Png);
            for (int i = 0; i < tabs.Length; i++) CheckTabPixel(picture, tabs[i], i == 0);
        }
    }

    void CheckTabPixel(Bitmap picture, NavigationTab tab, bool selected)
    {
        Point screen = tab.PointToScreen(new Point(10, 7));
        Point point = PointToClient(screen);
        if (point.X < 0 || point.Y < 0 || point.X >= picture.Width || point.Y >= picture.Height)
            throw new InvalidOperationException("导航测试位置超出窗口");
        Color actual = picture.GetPixel(point.X, point.Y), expected = selected ? theme.Selected : theme.Card;
        int delta = Math.Abs(actual.R - expected.R) + Math.Abs(actual.G - expected.G) + Math.Abs(actual.B - expected.B);
        if (delta > 45) throw new InvalidOperationException($"导航重绘异常：{tab.Text}，选中={tab.IsSelected}，实际={actual.R},{actual.G},{actual.B}，预期={expected.R},{expected.G},{expected.B}，差={delta}");
    }
}
