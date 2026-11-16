using System.Drawing.Imaging;
using System.Runtime.InteropServices;

namespace AgentMeter.Windows;

/// <summary>在隔离构建机检查真实窗口像素，而不是只检查控件的静态绘制结果。</summary>
internal static class NavigationPaintSmoke
{
    public static void Run(string output)
    {
        Directory.CreateDirectory(output);
        using var window = new MeterWindow(demo: true, windowed: true)
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
    internal async Task SyntheticNavigationPaintAsync(string output)
    {
        if (!demo) throw new InvalidOperationException("仅允许演示数据检查绘制");
        // 构建进程本身以隐藏方式启动；测试窗口必须显式显示到隔离桌面。
        ShowWindow(Handle, 5); BringToFront(); Activate();
        await RefreshData();
        // 只在隔离构建机运行，移开鼠标以免悬停色干扰像素判断。
        Cursor.Position = new Point(1, 1);
        var tabs = new[] { accountTab, applicationsTab, usageTab, reportTab, forecastTab, petTab, collectionTab };
        foreach (var (selected, page) in new[] { (0, View.Accounts), (2, View.Usage), (5, View.Pet) })
        {
            SetView(page); navigationStrip.Invalidate(true); Update();
            await Task.Delay(350);
            using var picture = new Bitmap(ClientSize.Width, ClientSize.Height, PixelFormat.Format32bppArgb);
            using (var graphics = Graphics.FromImage(picture)) graphics.CopyFromScreen(PointToScreen(Point.Empty), Point.Empty, ClientSize);
            picture.Save(Path.Combine(output, $"navigation-{selected}.png"), ImageFormat.Png);
            for (int i = 0; i < tabs.Length; i++) CheckTabPixel(picture, tabs[i], i == selected);
            if (page == View.Usage)
            {
                var strip = content.Controls.OfType<NavigationStrip>().Single(item => item.Name == "usage-period-selector");
                var periods = strip.Controls.OfType<NavigationTab>().ToArray();
                for (int i = 0; i < periods.Length; i++) CheckTabPixel(picture, periods[i], i == 0);
            }
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
        if (delta > 45) throw new InvalidOperationException($"导航重绘异常：{tab.Text}，颜色差 {delta}");
    }
}
