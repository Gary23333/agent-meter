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
                if (page == View.Usage)
                {
                    var sourceCard = content.Controls.OfType<RoundedCard>().Single(card => card.Name == "usage-sources");
                    content.ScrollControlIntoView(sourceCard);
                    await Task.Delay(150);
                    using var sourcePicture = new Bitmap(ClientSize.Width, ClientSize.Height, PixelFormat.Format32bppArgb);
                    using (var graphics = Graphics.FromImage(sourcePicture)) graphics.CopyFromScreen(PointToScreen(Point.Empty), Point.Empty, ClientSize);
                    sourcePicture.Save(Path.Combine(output, "usage-sources.png"), ImageFormat.Png);
                    if (!sourceCard.Controls.OfType<Label>().Any(label => label.Name == "usage-source-tokens-0" && label.Text == "7.6M"))
                        throw new InvalidOperationException("应用用量对比缺少当前周期数值");
                    Size = new Size(380, 680); SetTheme(VisualThemes.Find("porcelain"));
                    sourceCard = content.Controls.OfType<RoundedCard>().Single(card => card.Name == "usage-sources");
                    content.ScrollControlIntoView(sourceCard); await Task.Delay(200);
                    var nameLabel = sourceCard.Controls.OfType<Label>().Single(label => label.Name == "usage-source-name-0");
                    var count = sourceCard.Controls.OfType<Label>().Single(label => label.Name == "usage-source-tokens-0");
                    var cost = sourceCard.Controls.OfType<Label>().Single(label => label.Name == "usage-source-cost-0");
                    if (nameLabel.Right > count.Left || count.Right > cost.Left || cost.Right > sourceCard.ClientSize.Width)
                        throw new InvalidOperationException("窄弹层的应用用量对比发生重叠");
                    using var narrowPicture = new Bitmap(ClientSize.Width, ClientSize.Height, PixelFormat.Format32bppArgb);
                    using (var graphics = Graphics.FromImage(narrowPicture)) graphics.CopyFromScreen(PointToScreen(Point.Empty), Point.Empty, ClientSize);
                    narrowPicture.Save(Path.Combine(output, "usage-sources-porcelain-narrow.png"), ImageFormat.Png);
                    Size = new Size(440, 680); SetTheme(VisualThemes.Find("aurora"));
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
            ActiveControl = null;
            await Task.Delay(100);
            if (view != View.Accounts) throw new InvalidOperationException("主题切换后导航无法点击");
            using var picture = new Bitmap(ClientSize.Width, ClientSize.Height, PixelFormat.Format32bppArgb);
            using (var graphics = Graphics.FromImage(picture)) graphics.CopyFromScreen(PointToScreen(Point.Empty), Point.Empty, ClientSize);
            picture.Save(Path.Combine(output, $"theme-{option.Id}.png"), ImageFormat.Png);
            for (int i = 0; i < tabs.Length; i++) CheckTabPixel(picture, tabs[i], i == 0);
        }
        SetTheme(VisualThemes.Find("aurora"));
        var loading = System.Text.Json.Nodes.JsonNode.Parse(DemoData)!.AsObject();
        loading["account"] = new System.Text.Json.Nodes.JsonObject { ["status"] = "loading" };
        foreach (string source in new[] { "Kimi Code", "Claude Code", "MiniMax Code" })
            loading["other_accounts"]![source] = new System.Text.Json.Nodes.JsonObject { ["status"] = "loading" };
        using (var document = System.Text.Json.JsonDocument.Parse(loading.ToJsonString())) Render(document.RootElement);
        content.AutoScrollPosition = Point.Empty;
        await Task.Delay(150);
        if (content.Controls.OfType<RoundedCard>().SelectMany(card => card.Controls.OfType<Label>()).Count(label => label.Text == "正在读取额度") != 4)
            throw new InvalidOperationException("账户加载状态显示错误");
        if (!gauges.Controls.OfType<Label>().Any(label => label.Text == "正在读取账户额度…"))
            throw new InvalidOperationException("额度环加载状态显示错误");
        using var loadingPicture = new Bitmap(ClientSize.Width, ClientSize.Height, PixelFormat.Format32bppArgb);
        using (var graphics = Graphics.FromImage(loadingPicture)) graphics.CopyFromScreen(PointToScreen(Point.Empty), Point.Empty, ClientSize);
        loadingPicture.Save(Path.Combine(output, "accounts-loading.png"), ImageFormat.Png);
        SetView(View.Usage);
        var withBudget = System.Text.Json.Nodes.JsonNode.Parse(DemoData)!.AsObject();
        withBudget["budget"] = System.Text.Json.Nodes.JsonNode.Parse("""{"status":"ok","daily":{"budget_cny":"10","spent_cny":"3.625","partial":false},"weekly":{"budget_cny":"100","spent_cny":"15","partial":true}}""");
        using (var document = System.Text.Json.JsonDocument.Parse(withBudget.ToJsonString())) Render(document.RootElement);
        content.AutoScrollPosition = Point.Empty; await Task.Delay(200);
        var budgetCard = content.Controls.OfType<RoundedCard>().Single(card => card.Name == "budget-progress");
        if (!budgetCard.Controls.OfType<Label>().Any(label => label.Text.Contains("¥3.63 / ¥10")) ||
            !budgetCard.Controls.OfType<Label>().Any(label => label.Text.Contains("¥15 / ¥100 · 部分")))
            throw new InvalidOperationException("预算进度显示错误");
        using var budgetPicture = new Bitmap(ClientSize.Width, ClientSize.Height, PixelFormat.Format32bppArgb);
        using (var graphics = Graphics.FromImage(budgetPicture)) graphics.CopyFromScreen(PointToScreen(Point.Empty), Point.Empty, ClientSize);
        budgetPicture.Save(Path.Combine(output, "budget-progress.png"), ImageFormat.Png);
        string testDirectory = Path.Combine(Path.GetTempPath(), "AgentMeterBudgetSmoke-" + Guid.NewGuid().ToString("N"));
        using (var dialog = new BudgetDialog(testDirectory) { StartPosition = FormStartPosition.Manual, Location = new Point(40, 40), TopMost = true })
        {
            dialog.Show(); ShowWindow(dialog.Handle, 5); dialog.BringToFront(); dialog.Activate(); await Task.Delay(300);
            using var dialogPicture = new Bitmap(dialog.Width, dialog.Height, PixelFormat.Format32bppArgb);
            using (var graphics = Graphics.FromImage(dialogPicture)) graphics.CopyFromScreen(dialog.Location, Point.Empty, dialog.Size);
            dialogPicture.Save(Path.Combine(output, "budget-settings.png"), ImageFormat.Png);
            ((CheckBox)dialog.Controls.Find("budget-enabled", true).Single()).Checked = true;
            ((TextBox)dialog.Controls.Find("budget-daily", true).Single()).Text = "20.5";
            ((Button)dialog.Controls.Find("budget-save", true).Single()).PerformClick();
            var saved = BudgetPreferences.Load(testDirectory);
            if (dialog.DialogResult != DialogResult.OK || !saved.Enabled || saved.Daily != 20.5m || saved.AlertsEnabled)
                throw new InvalidOperationException("预算设置保存错误");
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
