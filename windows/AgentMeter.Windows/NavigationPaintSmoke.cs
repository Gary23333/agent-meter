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
        foreach (var (selected, page) in new[] { (0, View.Accounts), (1, View.Applications), (2, View.Usage),
            (3, View.Report), (4, View.Forecast), (5, View.Pet), (6, View.Collection), (0, View.Accounts) })
        {
            ClickOnIsolatedDesktop(tabs[selected]);
            await Task.Delay(350);
            Cursor.Position = new Point(1, 1);
            if (view != page) throw new InvalidOperationException("导航鼠标点击没有切换页面");
            await Task.Delay(100);
            using var picture = new Bitmap(ClientSize.Width, ClientSize.Height, PixelFormat.Format32bppArgb);
            using (var graphics = Graphics.FromImage(picture)) graphics.CopyFromScreen(PointToScreen(Point.Empty), Point.Empty, ClientSize);
            picture.Save(Path.Combine(output, $"navigation-{selected}.png"), ImageFormat.Png);
            CheckNaturalNavigationFrame(picture, output, $"{page}");
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
                    var rankingCard = content.Controls.OfType<RoundedCard>().Single(card => card.Name == "model-ranking");
                    content.ScrollControlIntoView(rankingCard); await Task.Delay(200);
                    if (!rankingCard.Controls.OfType<Label>().Any(label => label.Name == "model-rank-tokens-0" && label.Text == "6.2M") ||
                        !rankingCard.Controls.OfType<Label>().Any(label => label.Name == "model-rank-cost-0" && label.Text == "$10.3"))
                        throw new InvalidOperationException("模型排行周期或费用显示错误");
                    using var modelPicture = new Bitmap(ClientSize.Width, ClientSize.Height, PixelFormat.Format32bppArgb);
                    using (var graphics = Graphics.FromImage(modelPicture)) graphics.CopyFromScreen(PointToScreen(Point.Empty), Point.Empty, ClientSize);
                    modelPicture.Save(Path.Combine(output, "model-ranking.png"), ImageFormat.Png);
                    Size = new Size(380, 680); SetTheme(VisualThemes.Find("porcelain"));
                    rankingCard = content.Controls.OfType<RoundedCard>().Single(card => card.Name == "model-ranking");
                    content.ScrollControlIntoView(rankingCard); await Task.Delay(200);
                    var model = rankingCard.Controls.OfType<Label>().Single(label => label.Name == "model-rank-name-0");
                    var origin = rankingCard.Controls.OfType<Label>().Single(label => label.Name == "model-rank-source-0");
                    var modelCost = rankingCard.Controls.OfType<Label>().Single(label => label.Name == "model-rank-cost-0");
                    var modelTokens = rankingCard.Controls.OfType<Label>().Single(label => label.Name == "model-rank-tokens-0");
                    if (model.Right > origin.Left || origin.Right > modelCost.Left || modelCost.Right > modelTokens.Left || modelTokens.Right > rankingCard.ClientSize.Width)
                        throw new InvalidOperationException("窄弹层模型排行发生重叠");
                    if (TextRenderer.MeasureText(model.Text, model.Font, Size.Empty, TextFormatFlags.NoPadding).Width > model.Width ||
                        !rankingCard.Controls.OfType<Label>().Any(label => label.Name == "model-rank-source-2" && label.Text == "Claude"))
                        throw new InvalidOperationException("窄弹层模型名称或来源名称显示不完整");
                    using var narrowModelPicture = new Bitmap(ClientSize.Width, ClientSize.Height, PixelFormat.Format32bppArgb);
                    using (var graphics = Graphics.FromImage(narrowModelPicture)) graphics.CopyFromScreen(PointToScreen(Point.Empty), Point.Empty, ClientSize);
                    narrowModelPicture.Save(Path.Combine(output, "model-ranking-porcelain-narrow.png"), ImageFormat.Png);
                    Size = new Size(440, 680); SetTheme(VisualThemes.Find("aurora"));
                }
            }
        }
        await CheckAccountFirstScreenAsync(output);
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
        withBudget["budget"] = System.Text.Json.Nodes.JsonNode.Parse("""{"status":"ok","daily":{"budget_cny":"20","spent_cny":"17.864","partial":true},"weekly":{"budget_cny":"100","spent_cny":"42","partial":true}}""");
        using (var document = System.Text.Json.JsonDocument.Parse(withBudget.ToJsonString())) Render(document.RootElement);
        content.AutoScrollPosition = Point.Empty; await Task.Delay(200);
        var budgetCard = content.Controls.OfType<RoundedCard>().Single(card => card.Name == "budget-progress");
        if (!budgetCard.Controls.OfType<Label>().Any(label => label.Text.Contains("¥17.86 / ¥20 · 部分")) ||
            !budgetCard.Controls.OfType<Label>().Any(label => label.Text.Contains("¥42 / ¥100 · 部分")))
            throw new InvalidOperationException("预算进度显示错误");
        using var budgetPicture = new Bitmap(ClientSize.Width, ClientSize.Height, PixelFormat.Format32bppArgb);
        using (var graphics = Graphics.FromImage(budgetPicture)) graphics.CopyFromScreen(PointToScreen(Point.Empty), Point.Empty, ClientSize);
        budgetPicture.Save(Path.Combine(output, "budget-progress.png"), ImageFormat.Png);
        Size = new Size(380, 680); SetTheme(VisualThemes.Find("porcelain")); content.AutoScrollPosition = Point.Empty; await Task.Delay(200);
        budgetCard = content.Controls.OfType<RoundedCard>().Single(card => card.Name == "budget-progress");
        foreach (var value in budgetCard.Controls.OfType<Label>().Where(label => label.Name is "budget-first" or "budget-second"))
            if (value.Left < 85 || value.Right > budgetCard.ClientSize.Width) throw new InvalidOperationException("窄弹层预算数值布局错误");
        using var lightBudgetPicture = new Bitmap(ClientSize.Width, ClientSize.Height, PixelFormat.Format32bppArgb);
        using (var graphics = Graphics.FromImage(lightBudgetPicture)) graphics.CopyFromScreen(PointToScreen(Point.Empty), Point.Empty, ClientSize);
        lightBudgetPicture.Save(Path.Combine(output, "budget-progress-porcelain-narrow.png"), ImageFormat.Png);
        // 本周期没有消耗时显示零；价格文件损坏时不能继续显示金额或预算。
        var zeroUsage = System.Text.Json.Nodes.JsonNode.Parse(DemoData)!.AsObject();
        zeroUsage["history"] = System.Text.Json.Nodes.JsonNode.Parse("""{"Codex":{"status":"available","value":{"periods":{"today":{"totals":{"total_tokens":0,"fresh_input":0,"output":0,"reasoning":0,"cache_read":0,"cache_write":0,"unclassified":0}}}},"estimates":{"today":{"amount_usd":"0","partial":false}}}}""");
        usagePeriod = "today";
        using (var document = System.Text.Json.JsonDocument.Parse(zeroUsage.ToJsonString())) Render(document.RootElement);
        content.AutoScrollPosition = Point.Empty; await Task.Delay(150);
        if (((Label)content.Controls.Find("usage-cost-total", true).Single()).Text != "$0")
            throw new InvalidOperationException("已读取的零用量没有显示零费用");
        using var zeroPicture = new Bitmap(ClientSize.Width, ClientSize.Height, PixelFormat.Format32bppArgb);
        using (var graphics = Graphics.FromImage(zeroPicture)) graphics.CopyFromScreen(PointToScreen(Point.Empty), Point.Empty, ClientSize);
        zeroPicture.Save(Path.Combine(output, "usage-zero-porcelain-narrow.png"), ImageFormat.Png);
        zeroUsage["history"]!["Codex"]!.AsObject().Remove("estimates");
        zeroUsage["price_status"] = "invalid";
        zeroUsage["budget"] = System.Text.Json.Nodes.JsonNode.Parse("""{"status":"error","reason":"budget_price_invalid"}""");
        using (var document = System.Text.Json.JsonDocument.Parse(zeroUsage.ToJsonString())) Render(document.RootElement);
        if (((Label)content.Controls.Find("usage-cost-total", true).Single()).Text != "—" ||
            !content.Controls.OfType<RoundedCard>().SelectMany(card => card.Controls.OfType<Label>()).Any(label => label.Text.Contains("价格文件无法读取")))
            throw new InvalidOperationException("价格文件损坏时费用或预算提示错误");
        string testDirectory = Path.Combine(Path.GetTempPath(), "AgentMeterBudgetSmoke-" + Guid.NewGuid().ToString("N"));
        using (var dialog = new BudgetDialog(testDirectory) { StartPosition = FormStartPosition.Manual, Location = new Point(40, 40), TopMost = true })
        {
            dialog.Show(); ShowWindow(dialog.Handle, 5); dialog.BringToFront(); dialog.Activate(); await Task.Delay(300);
            using var dialogPicture = new Bitmap(dialog.Width, dialog.Height, PixelFormat.Format32bppArgb);
            using (var graphics = Graphics.FromImage(dialogPicture)) graphics.CopyFromScreen(dialog.Location, Point.Empty, dialog.Size);
            dialogPicture.Save(Path.Combine(output, "budget-settings.png"), ImageFormat.Png);
            ((CheckBox)dialog.Controls.Find("budget-enabled", true).Single()).Checked = true;
            var dailyInput = (TextBox)dialog.Controls.Find("budget-daily", true).Single();
            var saveButton = (Button)dialog.Controls.Find("budget-save", true).Single();
            dailyInput.Text = "0.001"; saveButton.PerformClick();
            if (!dialog.Visible || !((Label)dialog.Controls.Find("budget-message", true).Single()).Text.Contains("2 位小数") || Directory.Exists(testDirectory))
                throw new InvalidOperationException("预算无效输入未被拒绝");
            dailyInput.Text = "20.5"; saveButton.PerformClick();
            var saved = BudgetPreferences.Load(testDirectory);
            if (dialog.DialogResult != DialogResult.OK || !saved.Enabled || saved.Daily != 20.5m || saved.AlertsEnabled)
                throw new InvalidOperationException("预算设置保存错误");
        }
        string testConfig = Path.Combine(testDirectory, "budget-windows.json");
        File.WriteAllText(testConfig, "invalid");
        using (var broken = new BudgetDialog(testDirectory))
        {
            if (((Button)broken.Controls.Find("budget-save", true).Single()).Enabled ||
                !((Label)broken.Controls.Find("budget-message", true).Single()).Text.Contains("无法读取") || File.ReadAllText(testConfig) != "invalid")
                throw new InvalidOperationException("损坏预算设置应保留原文件并阻止覆盖");
        }
    }

    async Task CheckAccountFirstScreenAsync(string output)
    {
        // 此入口仅运行已固定的演示数据；为 macOS 对照保留相同的显示字段。
        var demoFrame = System.Text.Json.Nodes.JsonNode.Parse(lastSnapshot!)!;
        var comparison = new System.Text.Json.Nodes.JsonObject { ["clock"] = ForecastDemoNow.ToUnixTimeSeconds() };
        foreach (var (id, name) in new[] { ("codex", "Codex"), ("kimi", "Kimi Code"), ("claude", "Claude Code"), ("minimax", "MiniMax Code") })
        {
            var account = id == "codex" ? demoFrame["account"] : demoFrame["other_accounts"]?[name];
            comparison[id] = new System.Text.Json.Nodes.JsonObject {
                ["quota"] = account?["quota"]?["value"]?.DeepClone(), ["plan"] = account?["subscription"]?["plan"]?.DeepClone(),
                ["credits"] = account?["credits"]?["value"]?.DeepClone(), ["cards"] = account?["reset_cards"]?["value"]?.DeepClone(),
                ["history"] = demoFrame["history"]?[name]?["value"]?.DeepClone() };
        }
        File.WriteAllText(Path.Combine(output, "account-demo.json"), comparison.ToJsonString());
        foreach (var (style, width) in new[] { ("aurora", 440), ("aurora", 420), ("porcelain", 380) })
        {
            SetTheme(VisualThemes.Find(style)); Size = new Size(width, 680);
            content.AutoScrollPosition = Point.Empty;
            await Task.Delay(100);
            var card = content.Controls.Find("account-CODEX", false).Single();
            var today = (Label)card.Controls.Find("account-local-today", false).Single();
            var trend = card.Controls.Find("account-local-trend", false).Single();
            var viewport = contentClip.RectangleToScreen(contentClip.ClientRectangle);
            if (ClientSize.Width != width || today.Text != "1.43M" ||
                !viewport.Contains(today.RectangleToScreen(today.ClientRectangle)) ||
                !viewport.Contains(trend.RectangleToScreen(trend.ClientRectangle)))
                throw new InvalidOperationException($"账户首屏未完整显示今日用量与趋势：宽 {ClientSize.Width}，DPI {DeviceDpi}");
            using var picture = new Bitmap(ClientSize.Width, ClientSize.Height, PixelFormat.Format32bppArgb);
            using (var graphics = Graphics.FromImage(picture)) graphics.CopyFromScreen(PointToScreen(Point.Empty), Point.Empty, ClientSize);
            picture.Save(Path.Combine(output, $"accounts-{style}-{width}.png"), ImageFormat.Png);
        }
        // 检查按空格展开和收起之后焦点仍在同一操作入口。
        var toggle = content.Controls.Find("account-reset-toggle", true).Single();
        if (!toggle.Focus()) throw new InvalidOperationException("重置卡明细不能获取键盘焦点");
        foreach (bool expanded in new[] { true, false })
        {
            keybd_event(0x20, 0, 0, UIntPtr.Zero); keybd_event(0x20, 0, 0x0002, UIntPtr.Zero);
            await Task.Delay(150);
            if (content.Controls.Find("account-reset-tile", true).Length != (expanded ? 3 : 0) ||
                !content.Controls.Find("account-reset-toggle", true).Single().Focused)
                throw new InvalidOperationException("重置卡键盘展开或焦点恢复失败");
            int before = -content.AutoScrollPosition.Y;
            using var refreshed = System.Text.Json.JsonDocument.Parse(lastSnapshot!);
            Render(refreshed.RootElement);
            await Task.Delay(100);
            if (!content.Controls.Find("account-reset-toggle", true).Single().Focused ||
                content.Controls.Find("account-reset-tile", true).Length != (expanded ? 3 : 0) || Math.Abs(-content.AutoScrollPosition.Y - before) > 2)
                throw new InvalidOperationException("刷新后重置卡明细、焦点或阅读位置发生变化");
        }
        Size = new Size(440, 680); SetTheme(VisualThemes.Find("aurora"));
        Hide(); Show(); Activate();
        using (var snapshot = System.Text.Json.JsonDocument.Parse(lastSnapshot!)) Render(snapshot.RootElement);
        await Task.Delay(150);
        using var reopened = new Bitmap(ClientSize.Width, ClientSize.Height, PixelFormat.Format32bppArgb);
        using (var graphics = Graphics.FromImage(reopened)) graphics.CopyFromScreen(PointToScreen(Point.Empty), Point.Empty, ClientSize);
        CheckNaturalNavigationFrame(reopened, output, "reopened-refresh");
    }

    // 先保留用户正常点击后看到的整条导航，再与同位置同步重绘的结果逐像素对照。
    // 单点取色可以确认高亮位置，但无法发现文字笔画或胶囊边缘上的残影。
    void CheckNaturalNavigationFrame(Bitmap picture, string output, string page)
    {
        Point origin = navigationStrip.PointToScreen(Point.Empty);
        var area = new Rectangle(PointToClient(origin), navigationStrip.ClientSize);
        using var natural = picture.Clone(area, PixelFormat.Format32bppArgb);
        navigationStrip.Refresh();
        using var reference = new Bitmap(area.Width, area.Height, PixelFormat.Format32bppArgb);
        using (var graphics = Graphics.FromImage(reference))
            graphics.CopyFromScreen(origin, Point.Empty, reference.Size);
        int changed = 0;
        for (int y = 0; y < area.Height; y++)
            for (int x = 0; x < area.Width; x++)
                if (natural.GetPixel(x, y).ToArgb() != reference.GetPixel(x, y).ToArgb()) changed++;
        if (changed == 0) return;
        natural.Save(Path.Combine(output, $"navigation-{page}-natural.png"), ImageFormat.Png);
        reference.Save(Path.Combine(output, $"navigation-{page}-reference.png"), ImageFormat.Png);
        throw new InvalidOperationException($"{page} 自然切页与重绘后的导航有 {changed} 个像素不同");
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
