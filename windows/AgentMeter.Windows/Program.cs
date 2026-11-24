using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace AgentMeter.Windows;

internal static class Program
{
    [STAThread]
    static void Main(string[] args)
    {
        ApplicationConfiguration.Initialize();
        if (args.Length == 2 && args[0] == "--navigation-paint-smoke")
        {
            NavigationPaintSmoke.Run(args[1]);
            return;
        }
        if (args.Length == 2 && args[0] == "--pet3d-smoke")
        {
            Pet3dSmoke.Run(args[1]);
            return;
        }
        if (args.Length == 1 && args[0] == "--background-ui-smoke")
        {
            using var context = new MeterContext(demo: true, windowed: false, background: true);
            using var testSignal = new SingleInstanceSignal("Local\\AgentMeterWakeTest-" + Guid.NewGuid().ToString("N"));
            testSignal.Listen(context.ActivateFromOtherInstance);
            using var check = new System.Windows.Forms.Timer { Interval = 300 };
            int stage = 0;
            check.Tick += (_, _) => {
                try
                {
                    if (stage++ == 0) { context.SyntheticBackgroundSmoke(); testSignal.Notify(); return; }
                    check.Stop(); context.SyntheticWakeSmoke();
                }
                catch (Exception error) { Console.Error.WriteLine(error.Message); Environment.ExitCode = 1; }
                if (stage > 1 || Environment.ExitCode != 0) { check.Stop(); context.ExitThread(); }
            };
            check.Start(); Application.Run(context); return;
        }
        if (args.Length == 1 && args[0] == "--tray-indicator-smoke")
        {
            using var context = new MeterContext(demo: true, windowed: false);
            using var check = new System.Windows.Forms.Timer { Interval = 100 };
            check.Tick += (_, _) => {
                check.Stop();
                try { context.SyntheticTrayIndicatorSmoke(); }
                catch (Exception error) { Console.Error.WriteLine(error.Message); Environment.ExitCode = 1; }
                finally { context.ExitThread(); }
            };
            check.Start(); Application.Run(context); return;
        }
        if (args.Length == 1 && args[0] == "--webview-smoke")
        {
            RunWebViewSmoke();
            return;
        }
        if (args.Length == 1 && args[0] == "--activity-ui-smoke")
        {
            RunActivitySmoke();
            return;
        }
        if (args.Length == 1 && args[0] == "--isolated-refresh-smoke")
        {
            if (Environment.GetEnvironmentVariable("AGENT_METER_ISOLATED_SMOKE") != "1") { Environment.ExitCode = 1; return; }
            using var testWindow = new MeterWindow(demo: false, windowed: true) { StartPosition = FormStartPosition.Manual, Location = new Point(-32000, -32000) };
            testWindow.Shown += async (_, _) => {
                try { await testWindow.SyntheticFullRefreshSmokeAsync(); }
                catch (Exception error) { Console.Error.WriteLine(error.Message); Environment.ExitCode = 1; }
                finally { testWindow.Close(); }
            };
            Application.Run(testWindow); return;
        }
        if (args.Length == 1 && args[0] == "--popup-ui-smoke")
        {
            using var popup = new MeterWindow(demo: true, windowed: false) { Location = new Point(-32000, -32000) };
            popup.Shown += async (_, _) => {
                try { await popup.SyntheticPopupSmokeAsync(); }
                catch (Exception error) { Console.Error.WriteLine(error.Message); Environment.ExitCode = 1; }
                finally { popup.Close(); }
            };
            Application.Run(popup); return;
        }
        // 构建机使用纯演示数据生成视觉检查图，不启动采集器或读取用户设置。
        if (args.Length == 2 && args[0] == "--render-demo")
        {
            try
            {
                using var preview = new MeterWindow(demo: true, windowed: false);
                preview.RenderDemoImages(args[1]);
            }
            catch (Exception error) { Console.Error.WriteLine(error.Message); Environment.ExitCode = 1; }
            return;
        }
        bool demo = args.Contains("--demo");
        if (demo) { Application.Run(new MeterContext(true, args.Contains("--window"), args.Contains("--background"))); return; }
        using var signal = new SingleInstanceSignal(SingleInstanceSignal.DefaultName);
        // 先持有信号，再争抢单实例锁，避免后启动的进程在前者创建信号前通知并退出。
        using var mutex = new Mutex(true, "Local\\AgentMeterWindows", out bool first);
        if (!first) { signal.Notify(); return; }
        using var appContext = new MeterContext(false, args.Contains("--window"), args.Contains("--background"));
        signal.Listen(appContext.ActivateFromOtherInstance);
        Application.Run(appContext);
    }

    static void RunWebViewSmoke()
    {
        string directory = Path.Combine(Path.GetTempPath(), "AgentMeterWebSmoke-" + Guid.NewGuid().ToString("N"));
        using var pump = new Form { ShowInTaskbar = false, StartPosition = FormStartPosition.Manual,
            Location = new Point(-32000, -32000), Size = new Size(1, 1) };
        pump.Shown += async (_, _) =>
        {
            try
            {
                using var browser = new WorkBuddyBrowser(directory); await browser.SyntheticSmokeAsync();
                using var mimo = new MiMoBrowser(directory); await mimo.SyntheticSmokeAsync();
                using var qoder = new QoderBrowser(directory); await qoder.SyntheticSmokeAsync();
                using var trae = new TraeBrowser(directory); await trae.SyntheticSmokeAsync();
            }
            catch (Microsoft.Web.WebView2.Core.WebView2RuntimeNotFoundException) { Environment.ExitCode = 10; }
            catch (Exception error) { Console.Error.WriteLine($"隔离 WebView 检查失败：{error.GetType().Name}: {error.Message}"); Environment.ExitCode = 1; }
            finally { pump.Close(); }
        };
        Application.Run(pump);
    }

    static void RunActivitySmoke()
    {
        using var window = new MeterWindow(demo: true, windowed: true) { StartPosition = FormStartPosition.Manual, Location = new Point(-32000, -32000) };
        window.Shown += async (_, _) =>
        {
            try { await window.SyntheticActivitySmokeAsync(); await window.SyntheticRefreshPartsSmokeAsync(); }
            catch (Exception error) { Console.Error.WriteLine(error.Message); Environment.ExitCode = 1; }
            finally { window.Close(); }
        };
        Application.Run(window);
    }
}

internal sealed partial class MeterContext : ApplicationContext
{
    readonly NotifyIcon tray;
    readonly Icon icon;
    readonly MeterWindow window;
    readonly ToolStripMenuItem petVisible = new("显示桌宠");
    readonly ToolStripMenuItem petFollow = new("3D 视线跟随光标");
    readonly ToolStripMenuItem petMochi = new("麻薯"), petBit = new("比特");
    readonly Dictionary<string, ToolStripMenuItem> pet3dItems = new()
    {
        ["gauge"] = new("量量 · 3D"), ["cat"] = new("缓存猫 · 3D"), ["bot"] = new("码码 · 3D"),
        ["tibo"] = new("Tibo · 3D"), ["blob"] = new("团团 · 3D")
    };
    PetPreferences petPreferences;
    IPetWindow? pet;
    bool quitting;
    public MeterContext(bool demo, bool windowed, bool background = false)
    {
        using var iconStream = typeof(Program).Assembly.GetManifestResourceStream("AgentMeter.Icon") ?? throw new InvalidOperationException("icon_missing");
        icon = new Icon(iconStream);
        window = new MeterWindow(demo, windowed) { Icon = icon };
        petPreferences = demo ? PetPreferences.Default : PetPreferences.Load(AccountPreferences.DefaultDirectory);
        window.SetPetPreferences(petPreferences);
        window.PetChangeRequested += ChangePet;
        var menu = new ContextMenuStrip();
        menu.Items.Add("打开 Agent Meter", null, (_, _) => ShowPanel(true));
        menu.Items.Add("刷新数据", null, async (_, _) => await window.RefreshData());
        if (!demo)
        {
            var refreshInterval = new ToolStripMenuItem("刷新间隔（账户与本机）");
            foreach (int minutes in RefreshIntervalPreferences.Choices)
            {
                var item = new ToolStripMenuItem($"{minutes} 分钟") { Checked = minutes == window.RefreshIntervalMinutes };
                item.Click += (_, _) =>
                {
                    if (!window.SetRefreshInterval(minutes)) return;
                    foreach (ToolStripMenuItem choice in refreshInterval.DropDownItems) choice.Checked = ReferenceEquals(choice, item);
                };
                refreshInterval.DropDownItems.Add(item);
            }
            menu.Items.Add(refreshInterval);
            var accounts = new ToolStripMenuItem("账户查询");
            var accountItems = new Dictionary<string, ToolStripMenuItem>();
            foreach (var provider in new[] { "Codex", "Kimi", "Claude", "MiniMax", "DeepSeek", "WorkBuddy", "ZCode", "Volcengine", "MiMo", "Qoder", "Trae" })
            {
                var item = new ToolStripMenuItem(provider == "DeepSeek" ? "DeepSeek API 余额" : provider + " 账户额度") { Checked = window.AccountEnabled(provider) };
                item.Click += (_, _) => { if (window.SetAccountEnabled(provider, !item.Checked)) item.Checked = !item.Checked; };
                accountItems[provider] = item;
                accounts.DropDownItems.Add(item);
            }
            menu.Items.Add(accounts);
            menu.Items.Add("自定义模型价格", null, async (_, _) =>
            {
                ShowPanel(true);
                using var editor = new PriceEditor(AccountPreferences.DefaultDirectory);
                if (editor.ShowDialog(window) == DialogResult.OK) await window.RefreshData();
            });
            menu.Items.Add("预算与异常提醒", null, async (_, _) =>
            {
                ShowPanel(true);
                using var dialogIcon = (Icon)window.Icon.Clone();
                using var editor = new BudgetDialog(AccountPreferences.DefaultDirectory) { Icon = dialogIcon };
                if (editor.ShowDialog(window) == DialogResult.OK) await window.RefreshAfterBudgetChange();
            });
            menu.Items.Add("每日积分领取", null, (_, _) =>
            {
                ShowPanel(true);
                using var dialogIcon = (Icon)window.Icon.Clone();
                using var editor = new RewardsDialog(window) { Icon = dialogIcon };
                editor.ShowDialog(window);
            });
            menu.Items.Add("多机同步", null, (_, _) =>
            {
                ShowPanel(true);
                using var dialogIcon = (Icon)window.Icon.Clone();
                using var editor = new SyncDialog(window) { Icon = dialogIcon };
                editor.ShowDialog(window);
            });
            menu.Items.Add("管理 MiniMax 账户", null, async (_, _) =>
            {
                ShowPanel(true);
                using var editor = new MiniMaxAccountsDialog(AccountPreferences.DefaultDirectory);
                editor.ShowDialog(window);
                if (editor.Changed) await window.RefreshAfterAccountChange();
            });
            menu.Items.Add("设置 DeepSeek API 密钥", null, (_, _) =>
            {
                ShowPanel(true);
                using var editor = new DeepSeekKeyDialog();
                if (editor.ShowDialog(window) != DialogResult.OK) return;
                bool enabled = !editor.Deleted;
                if (window.SetAccountEnabled("DeepSeek", enabled)) accountItems["DeepSeek"].Checked = enabled;
            });
            menu.Items.Add("设置智谱 Coding Plan 密钥", null, (_, _) =>
            {
                ShowPanel(true);
                using var editor = new ZCodeKeyDialog();
                if (editor.ShowDialog(window) != DialogResult.OK) return;
                if (window.SetAccountEnabled("ZCode", !editor.Deleted)) accountItems["ZCode"].Checked = !editor.Deleted;
            });
            menu.Items.Add("设置火山方舟 AccessKey", null, (_, _) =>
            {
                ShowPanel(true);
                using var editor = new VolcengineKeyDialog();
                if (editor.ShowDialog(window) != DialogResult.OK) return;
                if (window.SetAccountEnabled("Volcengine", !editor.Deleted)) accountItems["Volcengine"].Checked = !editor.Deleted;
            });
            menu.Items.Add("登录 WorkBuddy", null, (_, _) =>
            {
                ShowPanel(true);
                using var editor = new WorkBuddyLoginDialog(window.WorkBuddyBrowser, window.CancelAccountRequests);
                if (editor.ShowDialog(window) != DialogResult.OK) return;
                bool enabled = !editor.Cleared;
                if (window.SetAccountEnabled("WorkBuddy", enabled)) accountItems["WorkBuddy"].Checked = enabled;
            });
            menu.Items.Add("登录小米 MiMo 平台", null, (_, _) =>
            {
                ShowPanel(true);
                using var editor = new MiMoLoginDialog(window.MiMoBrowser, window.CancelAccountRequests);
                if (editor.ShowDialog(window) != DialogResult.OK) return;
                if (window.SetAccountEnabled("MiMo", !editor.Cleared)) accountItems["MiMo"].Checked = !editor.Cleared;
            });
            menu.Items.Add("登录 Qoder 中国区", null, (_, _) =>
            {
                ShowPanel(true);
                using var editor = new QoderLoginDialog(window.QoderBrowser, window.CancelAccountRequests);
                if (editor.ShowDialog(window) != DialogResult.OK) return;
                if (window.SetAccountEnabled("Qoder", !editor.Cleared)) accountItems["Qoder"].Checked = !editor.Cleared;
            });
            menu.Items.Add("登录 TRAE 中国区", null, (_, _) =>
            {
                ShowPanel(true);
                window.TraeBrowser.BeginLogin();
                using var editor = new TraeLoginDialog(window.TraeBrowser, window.CancelAccountRequests);
                if (editor.ShowDialog(window) != DialogResult.OK)
                { if (!window.AccountEnabled("Trae")) window.TraeBrowser.Suspend(); return; }
                if (window.SetAccountEnabled("Trae", !editor.Cleared)) accountItems["Trae"].Checked = !editor.Cleared;
            });
            var alerts = new ToolStripMenuItem($"低额度提醒（低于 {window.AlertThreshold}%）") { Checked = window.AlertsEnabled };
            alerts.Click += (_, _) => { if (window.SetAlertsEnabled(!alerts.Checked)) alerts.Checked = !alerts.Checked; };
            menu.Items.Add(alerts);
            var thresholds = new ToolStripMenuItem("提醒阈值");
            foreach (int threshold in AlertPreferences.Thresholds)
            {
                var item = new ToolStripMenuItem($"低于 {threshold}%") { Checked = threshold == window.AlertThreshold };
                item.Click += (_, _) =>
                {
                    if (!window.SetAlertThreshold(threshold)) return;
                    foreach (ToolStripMenuItem choice in thresholds.DropDownItems) choice.Checked = ReferenceEquals(choice, item);
                    alerts.Text = $"低额度提醒（低于 {threshold}%）";
                };
                thresholds.DropDownItems.Add(item);
            }
            menu.Items.Add(thresholds);
            var cardAlerts = new ToolStripMenuItem("重置卡到期提醒（3 天 / 1 天）") { Checked = window.CardAlertsEnabled };
            cardAlerts.Click += (_, _) => { if (window.SetCardAlertsEnabled(!cardAlerts.Checked)) cardAlerts.Checked = !cardAlerts.Checked; };
            menu.Items.Add(cardAlerts);
            var forecast = new ToolStripMenuItem("第三方重置预测（联网）") { Checked = window.ForecastEnabled };
            forecast.Click += (_, _) => { if (window.SetForecastEnabled(!forecast.Checked)) forecast.Checked = !forecast.Checked; };
            menu.Items.Add(forecast);
            ConfigureStartupMenu(menu);
        }
        var appearance = new ToolStripMenuItem("界面风格");
        foreach (var themeOption in VisualThemes.All)
        {
            var item = new ToolStripMenuItem(themeOption.Name) { Checked = window.ThemeId == themeOption.Id };
            item.Click += (_, _) =>
            {
                if (!window.SetTheme(themeOption)) return;
                foreach (ToolStripMenuItem other in appearance.DropDownItems) other.Checked = other == item;
            };
            appearance.DropDownItems.Add(item);
        }
        menu.Items.Add(appearance);
        if (!demo)
        {
            var pets = new ToolStripMenuItem("桌宠");
            petVisible.Checked = petPreferences.Enabled;
            petVisible.Click += (_, _) => ChangePet(petPreferences with { Enabled = !petPreferences.Enabled });
            petMochi.Checked = petPreferences.Pack == "mochi"; petBit.Checked = petPreferences.Pack == "bit";
            petMochi.Click += (_, _) => ChangePet(petPreferences with { Pack = "mochi" });
            petBit.Click += (_, _) => ChangePet(petPreferences with { Pack = "bit" });
            pets.DropDownItems.AddRange([petVisible, new ToolStripSeparator(), petMochi, petBit]);
            pets.DropDownItems.Add(new ToolStripSeparator());
            foreach (var (pack, item) in pet3dItems)
            {
                item.Checked = petPreferences.Pack == pack;
                item.Click += (_, _) => ChangePet(petPreferences with { Pack = pack });
                pets.DropDownItems.Add(item);
            }
            pets.DropDownItems.Add(new ToolStripSeparator());
            petFollow.Checked = petPreferences.FollowCursor;
            petFollow.Enabled = petPreferences.Pack is not ("mochi" or "bit");
            petFollow.Click += (_, _) => ChangePet(petPreferences with { FollowCursor = !petPreferences.FollowCursor });
            pets.DropDownItems.Add(petFollow);
            menu.Items.Add(pets);
        }
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("退出", null, (_, _) => ExitThread());
        tray = new NotifyIcon { Text = "Agent Meter · AI 用量", Icon = icon, ContextMenuStrip = menu, Visible = true };
        InitializeTrayIndicator(menu, demo);
        menu.Opening += (_, _) => { TrayMenuStyle.Apply(menu, VisualThemes.Find(window.ThemeId)); window.PopupMenuVisible = true; };
        menu.Closed += (_, _) => window.PopupMenuVisible = false;
        window.MenuRequested += point => menu.Show(window, point);
        void ShowBalloon(string title, IReadOnlyList<string> messages, ToolTipIcon icon)
        {
            string summary = string.Join("\n", messages.Take(3)) + (messages.Count > 3 ? $"\n另有 {messages.Count - 3} 项，请打开面板查看。" : "");
            if (summary.Length > 240) summary = summary[..239] + "…";
            try { tray.ShowBalloonTip(8000, title, summary, icon); }
            catch (Exception ex) when (ex is InvalidOperationException or ObjectDisposedException or System.ComponentModel.Win32Exception) { }
        }
        window.QuotaLow += messages => ShowBalloon("Agent 额度提醒", messages, ToolTipIcon.Warning);
        window.CardsExpiring += messages => ShowBalloon("Agent 重置卡提醒", messages, ToolTipIcon.Warning);
        window.BudgetTriggered += messages => ShowBalloon("Agent 预算提醒", messages, ToolTipIcon.Warning);
        window.RewardsClaimed += messages => ShowBalloon("Agent 积分领取", messages, ToolTipIcon.Info);
        tray.MouseClick += (_, e) => { if (e.Button == MouseButtons.Left) { if (window.Visible) window.Hide(); else if (!window.JustDismissedAtCursor) ShowPanel(true); } };
        window.FormClosing += (_, e) => { if (!quitting && e.CloseReason == CloseReason.UserClosing) { e.Cancel = true; window.Hide(); } };
        window.FormClosed += (_, _) => { if (!quitting) ExitThread(); };
        window.SnapshotUpdated += snapshot => pet?.SetSnapshot(snapshot);
        if (!background) ShowPanel();
        else _ = window.Handle; // 创建隐藏句柄，使后台刷新仍在 Windows UI 消息线程上完成。
        if (petPreferences.Enabled) StartPet();
        _ = window.RefreshData();
    }
    void ChangePet(PetPreferences next)
    {
        try { next.Save(AccountPreferences.DefaultDirectory); }
        catch (Exception ex) when (ex is InvalidDataException or IOException or UnauthorizedAccessException or System.Security.SecurityException)
        { window.ShowNotice("无法保存桌宠设置"); return; }
        bool restart = next.Enabled && (!petPreferences.Enabled || next.Pack != petPreferences.Pack);
        petPreferences = next; petVisible.Checked = next.Enabled; petMochi.Checked = next.Pack == "mochi"; petBit.Checked = next.Pack == "bit";
        foreach (var (pack, item) in pet3dItems) item.Checked = next.Pack == pack;
        petFollow.Checked = next.FollowCursor; petFollow.Enabled = next.Pack is not ("mochi" or "bit");
        if (!next.Enabled) { pet?.Dispose(); pet = null; }
        else if (restart) StartPet();
        else pet?.SetFollowCursor(next.FollowCursor);
        window.SetPetPreferences(petPreferences);
    }
    void StartPet()
    {
        pet?.Dispose(); pet = null;
        try
        {
            var screen = Screen.PrimaryScreen ?? Screen.FromPoint(Point.Empty);
            Point location;
            if (petPreferences.X.HasValue && petPreferences.Y.HasValue)
            {
                var saved = new Rectangle(petPreferences.X.Value, petPreferences.Y.Value, 240, 240);
                var matching = Screen.AllScreens.FirstOrDefault(item => item.WorkingArea.IntersectsWith(saved));
                if (matching is not null)
                {
                    var area = matching.WorkingArea;
                    location = new Point(Math.Clamp(saved.X, area.Left, Math.Max(area.Left, area.Right - 240)),
                                         Math.Clamp(saved.Y, area.Top, Math.Max(area.Top, area.Bottom - 240)));
                }
                else location = PanelPlacement.Find(screen.Bounds, screen.WorkingArea, new Size(240, 240), Point.Empty, false);
            }
            else location = PanelPlacement.Find(screen.Bounds, screen.WorkingArea, new Size(240, 240), Point.Empty, false);
            IPetWindow instance = petPreferences.Pack is "mochi" or "bit"
                ? new PetWindow(petPreferences.Pack, location)
                : new Pet3dWindow(petPreferences.Pack, location, AccountPreferences.DefaultDirectory, petPreferences.FollowCursor);
            instance.OpenRequested += () => ShowPanel(true);
            instance.FrameUpdated += (frame, mood) => window.UpdatePetPreview(frame, mood);
            instance.RefreshRequested += async () => await window.RefreshData();
            instance.HideRequested += () => ChangePet(petPreferences with { Enabled = false });
            instance.PositionChanged += position =>
            {
                var next = petPreferences with { X = position.X, Y = position.Y };
                try { next.Save(AccountPreferences.DefaultDirectory); petPreferences = next; }
                catch (Exception ex) when (ex is InvalidDataException or IOException or UnauthorizedAccessException or System.Security.SecurityException)
                { window.ShowNotice("无法保存桌宠位置"); }
            };
            instance.RenderingFailed += () =>
            {
                petPreferences = petPreferences with { Enabled = false }; petVisible.Checked = false;
                window.SetPetPreferences(petPreferences);
                try { petPreferences.Save(AccountPreferences.DefaultDirectory); }
                catch (Exception ex) when (ex is InvalidDataException or IOException or UnauthorizedAccessException or System.Security.SecurityException) { }
                window.ShowNotice("桌宠暂时无法显示");
            };
            pet = instance;
            if (window.CurrentSnapshot is not null) instance.SetSnapshot(window.CurrentSnapshot);
            instance.Show();
        }
        catch (Exception ex) when (ex is InvalidDataException or IOException or ArgumentException or System.ComponentModel.Win32Exception or System.Runtime.InteropServices.ExternalException)
        {
            pet?.Dispose(); pet = null; petPreferences = petPreferences with { Enabled = false }; petVisible.Checked = false;
            window.SetPetPreferences(petPreferences);
            try { petPreferences.Save(AccountPreferences.DefaultDirectory); }
            catch (Exception saveError) when (saveError is InvalidDataException or IOException or UnauthorizedAccessException or System.Security.SecurityException) { }
            window.ShowNotice("桌宠暂时无法显示");
        }
    }
    void ShowPanel(bool atCursor = false) { window.PlaceAtTray(atCursor); window.Show(); window.Activate(); }
    internal void ActivateFromOtherInstance()
    {
        if (quitting || window.IsDisposed || !window.IsHandleCreated) return;
        try { window.BeginInvoke(() => { if (!quitting && !window.IsDisposed) ShowPanel(true); }); }
        catch (Exception ex) when (ex is InvalidOperationException or ObjectDisposedException) { }
    }
    protected override void ExitThreadCore()
    {
        quitting = true; indicatorTimer.Dispose(); pet?.Dispose(); pet = null; tray.Visible = false; tray.Dispose();
        indicatorIcon?.Dispose(); indicatorIcon = null;
        if (!window.IsDisposed) { window.Close(); window.Dispose(); } icon.Dispose();
        base.ExitThreadCore();
    }
}

internal sealed partial class MeterWindow : Form
{
    enum View { Accounts, Applications, Usage, Report, Forecast, Pet, Collection }
    enum ApplicationFilter { All, Recent, Other }
    VisualTheme theme;
    Color Background => theme.Background;
    Color Card => theme.Card;
    Color Muted => theme.Secondary;
    Color Accent => theme.Accent;
    Color Primary => theme.Primary;
    readonly FlowLayoutPanel content = new();
    readonly Panel contentViewport = new();
    readonly Panel contentClip = new();
    PopupScrollRail? scrollRail;
    readonly Label status = new();
    readonly PopupAction refresh = new(PopupActionKind.Refresh);
    readonly Panel header = new();
    readonly NavigationStrip navigationStrip = new();
    readonly Label title = new(), subtitle = new();
    readonly NavigationTab accountTab = new(), applicationsTab = new(), usageTab = new(), reportTab = new(), forecastTab = new(), petTab = new(), collectionTab = new();
    readonly Font tabRegular = new("Microsoft YaHei UI", 9F, FontStyle.Bold), tabCompact = new("Microsoft YaHei UI", 8F, FontStyle.Bold);
    readonly FlowLayoutPanel gauges = new();
    readonly GaugePageButton gaugePrevious = new(false), gaugeNext = new(true);
    int gaugePage;
    readonly System.Windows.Forms.Timer timer = new();
    readonly System.Windows.Forms.Timer activityTimer = new();
    readonly CancellationTokenSource shutdown = new();
    readonly HistoryWorker historyWorker = new();
    readonly WorkBuddyBrowser workBuddyBrowser = new(AccountPreferences.DefaultDirectory);
    readonly MiMoBrowser mimoBrowser = new(AccountPreferences.DefaultDirectory);
    readonly QoderBrowser qoderBrowser = new(AccountPreferences.DefaultDirectory);
    readonly TraeBrowser traeBrowser = new(AccountPreferences.DefaultDirectory);
    readonly QuotaAlerts quotaAlerts = new();
    readonly ResetCardAlerts cardAlerts = new();
    readonly bool demo;
    AccountPreferences preferences;
    CancellationTokenSource? accountCancellation;
    CancellationTokenSource? activityCancellation;
    Func<CancellationToken, Task<string>>? syntheticActivityReader;
    bool busy, refreshQueued, positioning, alertsEnabled, forecastEnabled, showAllQuotaCards;
    bool rewardBusy;
    int alertThreshold = 20;
    int refreshIntervalMinutes = 15;
    bool cardAlertsEnabled;
    bool activityBusy;
    DateTimeOffset lastActivityAttempt = DateTimeOffset.MinValue;
    Size preferredSize;
    View view = View.Accounts;
    ApplicationFilter applicationFilter = ApplicationFilter.All;
    string usagePeriod = "today";
    string UsagePeriodLabel => usagePeriod switch { "7d" => "近 7 天", "30d" => "近 30 天", "all" => "累计", _ => "今日" };
    readonly HashSet<string> expandedApplications = new(StringComparer.Ordinal);
    string? lastSnapshot;
    string? displayedAccountSnapshot;
    public string? CurrentSnapshot => lastSnapshot;
    internal WorkBuddyBrowser WorkBuddyBrowser => workBuddyBrowser;
    internal MiMoBrowser MiMoBrowser => mimoBrowser;
    internal QoderBrowser QoderBrowser => qoderBrowser;
    internal TraeBrowser TraeBrowser => traeBrowser;
    public void CancelAccountRequests() => accountCancellation?.Cancel();
    public event Action<string>? SnapshotUpdated;
    public void ShowNotice(string message) { if (!IsDisposed && !Disposing) status.Text = message; }

    public MeterWindow(bool demo, bool windowed)
    {
        this.demo = demo; popup = !windowed; preferences = demo ? AccountPreferences.Enabled : AccountPreferences.Load(AccountPreferences.DefaultDirectory);
        usagePeriod = demo ? "today" : UsagePeriodPreferences.Load(AccountPreferences.DefaultDirectory);
        refreshIntervalMinutes = demo ? 15 : RefreshIntervalPreferences.Load(AccountPreferences.DefaultDirectory);
        var alertSettings = demo ? new AlertSettings(false, 20) : AlertPreferences.LoadSettings(AccountPreferences.DefaultDirectory);
        alertsEnabled = alertSettings.Enabled; alertThreshold = alertSettings.Threshold; cardAlertsEnabled = alertSettings.ResetCardsEnabled;
        forecastEnabled = !demo && ForecastPreferences.Load(AccountPreferences.DefaultDirectory);
        theme = demo ? VisualThemes.Find("aurora") : VisualThemes.Load(AccountPreferences.DefaultDirectory);
        Text = "Agent Meter"; Font = new Font("Microsoft YaHei UI", 10F); BackColor = Background; ForeColor = Primary;
        ClientSize = new Size(440, 680); MinimumSize = new Size(380, 420); StartPosition = FormStartPosition.Manual;
        ShowInTaskbar = windowed; FormBorderStyle = windowed ? FormBorderStyle.Sizable : FormBorderStyle.None;
        preferredSize = Size;
        Resize += (_, _) => { if (!positioning && WindowState == FormWindowState.Normal) preferredSize = Size; };
        header.Dock = DockStyle.Top; header.Height = 234; header.BackColor = Background;
        title.Text = "Agent 用量"; title.Font = new Font(Font.FontFamily, 14F, FontStyle.Bold); title.AutoSize = true; title.Location = new Point(63, 14); title.ForeColor = Primary;
        subtitle.Text = "账户额度与本机消耗"; subtitle.AutoSize = false; subtitle.Size = new Size(220, 20); subtitle.Font = new Font(Font.FontFamily, 8.5F); subtitle.Location = new Point(64, 42); subtitle.ForeColor = Muted;
        refresh.Text = "刷新"; refresh.Size = new Size(66, 32); refresh.Location = new Point(0, 23);
        refresh.FlatStyle = FlatStyle.Flat; refresh.FlatAppearance.BorderColor = theme.Border; refresh.ForeColor = Accent; refresh.BackColor = Card;
        refresh.Click += async (_, _) => await RefreshData(); header.Controls.AddRange([title, subtitle, refresh]);
        header.Resize += (_, _) => { gauges.Width = Math.Max(0, header.ClientSize.Width - 32); LayoutTabs(); };
        foreach (var tab in new[] { accountTab, applicationsTab, usageTab, reportTab, forecastTab, petTab, collectionTab })
        {
            tab.ForeColor = Primary;
            tab.Font = tabRegular; tab.Size = new Size(86, 36);
        }
        gauges.Location = new Point(16, 114); gauges.Size = new Size(406, 116);
        gauges.Anchor = AnchorStyles.Top | AnchorStyles.Left;
        gauges.WrapContents = false; gauges.AutoScroll = false; gauges.BackColor = Background;
        gauges.Resize += (_, _) => LayoutGauges();
        header.Controls.Add(gauges);
        foreach (var button in new[] { gaugePrevious, gaugeNext })
        {
            button.FlatStyle = FlatStyle.Flat; button.FlatAppearance.BorderSize = 0; button.BackColor = Background;
            button.ForeColor = Muted; button.Size = new Size(20, 32);
        }
        gaugePrevious.Text = "‹"; gaugePrevious.AccessibleName = "上一组账户额度";
        gaugeNext.Text = "›"; gaugeNext.AccessibleName = "下一组账户额度";
        gaugePrevious.Click += (_, _) => { gaugePage--; LayoutGauges(); };
        gaugeNext.Click += (_, _) => { gaugePage++; LayoutGauges(); };
        header.Controls.AddRange([gaugePrevious, gaugeNext]);
        gaugePrevious.BringToFront(); gaugeNext.BringToFront();
        accountTab.Text = "账户额度"; applicationsTab.Text = "应用";
        usageTab.Text = "本机消耗"; reportTab.Text = "用量报告"; forecastTab.Text = "重置预测"; petTab.Text = "桌宠"; collectionTab.Text = "收集";
        accountTab.Click += (_, _) => SetView(View.Accounts); applicationsTab.Click += (_, _) => SetView(View.Applications);
        usageTab.Click += (_, _) => SetView(View.Usage);
        reportTab.Click += (_, _) => SetView(View.Report);
        forecastTab.Click += (_, _) => SetView(View.Forecast);
        petTab.Click += (_, _) => SetView(View.Pet);
        collectionTab.Click += (_, _) => SetView(View.Collection);
        navigationStrip.Controls.AddRange([accountTab, applicationsTab, usageTab, reportTab, forecastTab, petTab, collectionTab]);
        header.Controls.Add(navigationStrip); LayoutTabs(); UpdateTabs();
        status.Dock = DockStyle.Bottom; status.Height = 31; status.Font = new Font(Font.FontFamily, 8.5F); status.AutoEllipsis = true;
        status.Padding = new Padding(17, 6, 8, 0); status.ForeColor = Muted; status.BackColor = Background; status.Text = "正在准备…";
        contentViewport.Dock = DockStyle.Fill; contentViewport.BackColor = Background;
        content.Dock = DockStyle.None; content.FlowDirection = FlowDirection.TopDown; content.WrapContents = false; content.AutoScroll = true;
        content.Padding = new Padding(14, 0, 14, 10); content.BackColor = Background; content.SizeChanged += (_, _) => ResizeCards();
        scrollRail = new PopupScrollRail(content) { AccessibleName = "页面滚动", AccessibleRole = AccessibleRole.ScrollBar, TabStop = false,
            BackColor = Background, ThumbColor = theme.Border };
        // 单独裁剪原生滚动区，为细轨道留出不重叠的空间，避免子控件重绘时覆盖轨道。
        contentClip.BackColor = Background; contentClip.Controls.Add(content);
        contentViewport.Controls.Add(contentClip); contentViewport.Controls.Add(scrollRail);
        contentViewport.SizeChanged += (_, _) => {
            int previousScroll = -content.AutoScrollPosition.Y;
            // 旧的滚动范围可能在窗口缩窄后残留，重新布局时保留纵向位置。
            content.SuspendLayout(); content.AutoScroll = false;
            contentClip.Bounds = new Rectangle(0, 0, Math.Max(0, contentViewport.Width - 10), contentViewport.Height);
            content.Bounds = new Rectangle(0, 0, contentClip.Width + Math.Max(32, 32 * DeviceDpi / 96), contentClip.Height);
            scrollRail.Bounds = new Rectangle(contentViewport.Width - 9, 3, 5, Math.Max(0, contentViewport.Height - 6)); ResizeCards();
            content.AutoScroll = true; content.ResumeLayout(true);
            content.AutoScrollPosition = new Point(0, previousScroll);
        };
        content.Scroll += (_, _) => scrollRail.Invalidate(); content.Layout += (_, _) => scrollRail.Invalidate();
        content.MouseWheel += (_, _) => { if (IsHandleCreated) BeginInvoke(() => scrollRail.Invalidate()); };
        Controls.Add(contentViewport); Controls.Add(status); Controls.Add(header);
        InitializePopup();
        timer.Interval = refreshIntervalMinutes * 60 * 1000; timer.Tick += async (_, _) => await RefreshData(); timer.Start();
        activityTimer.Interval = 60 * 1000;
        activityTimer.Tick += async (_, _) => await RefreshActivityIfNeeded();
        if (!demo) activityTimer.Start();
        forecastClock.Interval = 1000; forecastClock.Tick += (_, _) => UpdateForecastClocks();
        if (!demo) forecastClock.Start();
        VisibleChanged += (_, _) => { if (!Visible) activityCancellation?.Cancel(); };
    }
    public void PlaceAtTray(bool atCursor)
    {
        Point cursor = Cursor.Position;
        var screen = atCursor ? Screen.FromPoint(cursor) : Screen.PrimaryScreen ?? Screen.FromPoint(cursor);
        positioning = true;
        try
        {
            var fit = PanelPlacement.Fit(preferredSize, screen.WorkingArea);
            MinimumSize = new Size(Math.Min(420, fit.Width), Math.Min(480, fit.Height));
            Size = fit;
            var autoHideEdge = TaskbarLocation.AutoHideEdge(screen.Bounds);
            Location = PanelPlacement.Find(screen.Bounds, screen.WorkingArea, Size, cursor, atCursor, autoHideEdge);
        }
        finally { positioning = false; }
    }
    internal void RenderDemoImages(string directory)
    {
        if (!demo) throw new InvalidOperationException("demo_required");
        Directory.CreateDirectory(directory);
        suppressPopupDismissal = true;
        Location = new Point(-32000, -32000);
        Show();
        RefreshData().GetAwaiter().GetResult();
        using (var icons = TrayIndicatorIcon.Preview()) icons.Save(Path.Combine(directory, "tray-indicators.png"), System.Drawing.Imaging.ImageFormat.Png);
        void SavePreview(string name)
        {
            Application.DoEvents();
            using var image = new Bitmap(Width, Height);
            DrawToBitmap(image, new Rectangle(Point.Empty, image.Size));
            image.Save(Path.Combine(directory, name + ".png"), System.Drawing.Imaging.ImageFormat.Png);
        }
        foreach (string id in new[] { "aurora", "porcelain" })
        {
            using var previewMenu = new ContextMenuStrip { Font = Font };
            previewMenu.Items.Add("刷新数据");
            var refreshPreview = new ToolStripMenuItem("刷新间隔（账户与本机）");
            foreach (int minutes in RefreshIntervalPreferences.Choices)
                refreshPreview.DropDownItems.Add(new ToolStripMenuItem($"{minutes} 分钟") { Checked = minutes == 15 });
            previewMenu.Items.Add(refreshPreview);
            var branch = new ToolStripMenuItem("界面风格"); branch.DropDownItems.Add(new ToolStripMenuItem("极光") { Checked = true });
            previewMenu.Items.Add(branch); previewMenu.Items.Add(new ToolStripMenuItem("低额度提醒（低于 20%）") { Checked = true });
            var alertThresholds = new ToolStripMenuItem("提醒阈值");
            foreach (int threshold in AlertPreferences.Thresholds)
                alertThresholds.DropDownItems.Add(new ToolStripMenuItem($"低于 {threshold}%") { Checked = threshold == 20 });
            previewMenu.Items.Add(alertThresholds);
            previewMenu.Items.Add(new ToolStripMenuItem("重置卡到期提醒（3 天 / 1 天）"));
            previewMenu.Items.Add(new ToolStripSeparator()); previewMenu.Items.Add("退出");
            TrayMenuStyle.Apply(previewMenu, VisualThemes.Find(id));
            previewMenu.Show(this, new Point(20, 60)); Application.DoEvents();
            using var picture = new Bitmap(previewMenu.Width, previewMenu.Height);
            previewMenu.DrawToBitmap(picture, new Rectangle(Point.Empty, picture.Size));
            picture.Save(Path.Combine(directory, id + "-menu.png"), System.Drawing.Imaging.ImageFormat.Png);
            previewMenu.Close();
        }
        foreach (var option in VisualThemes.All)
        {
            SetTheme(option);
            foreach (var (tab, name) in new[] { (View.Accounts, "accounts"), (View.Applications, "applications"),
                                               (View.Usage, "usage"), (View.Report, "report"), (View.Forecast, "forecast"),
                                               (View.Pet, "pet"), (View.Collection, "collection") })
            {
                SetView(tab);
                SavePreview(option.Id + "-" + name);
            }
        }
        SetTheme(VisualThemes.Find("aurora")); SetView(View.Pet);
        using (var hiddenFrame = PetArt.Load("cat")) UpdatePetPreview(hiddenFrame, new PetMood("idle", "待机"));
        if (content.Controls.OfType<PetHero>().Single().IsLive) throw new InvalidOperationException("隐藏桌宠时不应显示动态预览");
        SetPetPreferences(PetPreferences.Default with { Enabled = true });
        using (var spritePreview = new SpritePet("mochi"))
        {
            UpdatePetPreview(spritePreview.Frame("idle", 0, 240), new PetMood("idle", "待机"));
            UpdatePetPreview(spritePreview.Frame("idle", 1, 240), new PetMood("working", "近期本机记录有更新"));
            var spriteHero = content.Controls.OfType<PetHero>().Single();
            if (!spriteHero.IsLive || spriteHero.AccessibleName != "桌宠预览 · 近期本机记录有更新")
                throw new InvalidOperationException("精灵图画面或状态未同步到页面预览");
        }
        SetPetPreferences(PetPreferences.Default);
        var petGrid = content.Controls.OfType<TableLayoutPanel>().Single(item => item.Name == "pet-choices");
        if (petGrid.Controls.Count != 7) throw new InvalidOperationException("桌宠形象列表不完整");
        if (pagePetPreferences.FollowCursor || content.Controls.OfType<RoundedCard>().SelectMany(card => card.Controls.OfType<Button>())
            .Single(button => button.Name == "pet-follow-toggle").Enabled)
            throw new InvalidOperationException("精灵图不应开启视线跟随");
        petGrid.Controls.OfType<Button>().Single(button => button.Name == "pet-choice-cat").PerformClick();
        if (pagePetPreferences.Pack != "cat") throw new InvalidOperationException("桌宠形象切换失败");
        var followButton = content.Controls.OfType<RoundedCard>().SelectMany(card => card.Controls.OfType<Button>()).Single(button => button.Name == "pet-follow-toggle");
        if (!followButton.Enabled) throw new InvalidOperationException("3D 桌宠的视线跟随不可用");
        followButton.PerformClick();
        if (!pagePetPreferences.FollowCursor) throw new InvalidOperationException("桌宠视线跟随开关失败");
        var followCard = content.Controls.OfType<RoundedCard>().Single(card => card.Controls.OfType<Button>().Any(button => button.Name == "pet-follow-toggle"));
        content.ScrollControlIntoView(followCard); Application.DoEvents(); SavePreview("aurora-pet-follow");
        content.Controls.OfType<RoundedCard>().SelectMany(card => card.Controls.OfType<Button>()).Single(button => button.Name == "pet-toggle").PerformClick();
        if (!pagePetPreferences.Enabled) throw new InvalidOperationException("桌宠显示开关失败");
        Size = new Size(380, 680); content.AutoScrollPosition = Point.Empty; Application.DoEvents();
        using (var syntheticFrame = PetArt.Load("cat")) UpdatePetPreview(syntheticFrame, new PetMood("idle", "待机"));
        if (!content.Controls.OfType<PetHero>().Single().IsLive) throw new InvalidOperationException("显示中的桌宠没有同步到页面预览");
        SavePreview("aurora-pet-live");
        if (content.HorizontalScroll.Visible)
        {
            string children = string.Join(",", content.Controls.Cast<Control>().Select(item => $"{item.GetType().Name}:{item.Width}+{item.Margin.Horizontal}"));
            throw new InvalidOperationException($"桌宠页面出现横向滚动条：content={content.Width} viewport={contentViewport.Width} display={content.DisplayRectangle.Width} controls={children}");
        }
        content.AutoScrollPosition = new Point(0, 80); Application.DoEvents();
        int beforeResize = -content.AutoScrollPosition.Y;
        Size = new Size(400, 680); Application.DoEvents();
        if (beforeResize < 30 || Math.Abs(-content.AutoScrollPosition.Y - beforeResize) > 2)
            throw new InvalidOperationException("窗口缩放后未保留纵向滚动位置");
        Size = new Size(380, 680); content.AutoScrollPosition = Point.Empty; Application.DoEvents();
        if (content.HorizontalScroll.Visible) throw new InvalidOperationException("反复缩放后出现横向滚动条");
        SavePreview("aurora-pet-narrow");
        SetPetPreferences(PetPreferences.Default);
        if (content.Controls.OfType<PetHero>().Single().IsLive) throw new InvalidOperationException("隐藏桌宠后未恢复静态预览");
        Size = new Size(500, 1100);
        SetTheme(VisualThemes.Find("aurora")); SetView(View.Accounts);
        if (!content.Controls.OfType<RoundedCard>().SelectMany(card => card.Controls.OfType<Label>())
            .Any(label => label.Name == "account-local-today"))
            throw new InvalidOperationException("account_local_usage_missing");
        SavePreview("aurora-account-local-detail");
        content.AutoScrollPosition = new Point(0, 230); Application.DoEvents();
        if (content.AutoScrollPosition.Y == 0) throw new InvalidOperationException("account_local_scroll_failed");
        SavePreview("aurora-account-local-scrolled");
        var qoderCard = content.Controls.OfType<RoundedCard>().Single(card => card.Name == "qoder-local-credits");
        if (!qoderCard.Controls.OfType<Label>().Any(label => label.Text.Contains("非账户余额")))
            throw new InvalidOperationException("Qoder 本机积分需要标明不等于账户余额");
        if (!qoderCard.Controls.OfType<Label>().Any(label => label.Text == "今日 12.5"))
            throw new InvalidOperationException("Qoder 本机积分应显示今日记录");
        content.ScrollControlIntoView(qoderCard); Application.DoEvents(); SavePreview("aurora-qoder-local");
        string qoderSnapshot = lastSnapshot!;
        var noQoder = JsonNode.Parse(qoderSnapshot)!.AsObject(); noQoder.Remove("local_credits");
        using (var snapshot = JsonDocument.Parse(noQoder.ToJsonString())) Render(snapshot.RootElement);
        if (content.Controls.OfType<RoundedCard>().Any(card => card.Name == "qoder-local-credits"))
            throw new InvalidOperationException("没有本机 Qoder 记录时不能显示零积分");
        using (var snapshot = JsonDocument.Parse(qoderSnapshot)) Render(snapshot.RootElement);
        var qoderDemo = JsonNode.Parse(qoderSnapshot)!.AsObject();
        qoderDemo["other_accounts"]!["Qoder CN"] = JsonNode.Parse("""{"status":"available","quota":{"value":[{"bucket":"totalQuota","remaining_percent":80}]},"credits":{"value":[{"bucket":"totalQuota","remaining":"80"}]}}""");
        using (var snapshot = JsonDocument.Parse(qoderDemo.ToJsonString())) Render(snapshot.RootElement);
        var qoderAccountCard = content.Controls.OfType<RoundedCard>().First(card =>
            card.Controls.OfType<Label>().Any(label => label.Text == "Qoder CN · 账户额度"));
        if (!qoderAccountCard.Controls.OfType<Label>().Any(label => label.Text.Contains("80 积分")))
            throw new InvalidOperationException("Qoder 账户额度应显示网站余额");
        content.ScrollControlIntoView(qoderAccountCard); Application.DoEvents(); SavePreview("aurora-qoder-account");
        using (var dialog = new QoderLoginDialog(qoderBrowser, () => { }, preview: true) { StartPosition = FormStartPosition.Manual, Location = new Point(-32000, -32000) })
        {
            dialog.Show(this); Application.DoEvents();
            using var picture = new Bitmap(dialog.Width, dialog.Height);
            dialog.DrawToBitmap(picture, new Rectangle(Point.Empty, picture.Size));
            picture.Save(Path.Combine(directory, "qoder-dialog.png"), System.Drawing.Imaging.ImageFormat.Png);
            dialog.Close();
        }
        var traeDemo = JsonNode.Parse(qoderSnapshot)!.AsObject();
        traeDemo["other_accounts"]!["TRAE CN"] = JsonNode.Parse("""{"status":"available","quota":{"value":[{"bucket":"credits","remaining_percent":75}]},"credits":{"value":{"balance":"75","total":"100"}}}""");
        using (var snapshot = JsonDocument.Parse(traeDemo.ToJsonString())) Render(snapshot.RootElement);
        var traeAccountCard = content.Controls.OfType<RoundedCard>().First(card =>
            card.Controls.OfType<Label>().Any(label => label.Text == "TRAE CN · 账户额度"));
        if (!traeAccountCard.Controls.OfType<Label>().Any(label => label.Text.Contains("75 积分")))
            throw new InvalidOperationException("TRAE 账户额度应显示网站余额");
        content.ScrollControlIntoView(traeAccountCard); Application.DoEvents(); SavePreview("aurora-trae-account");
        using (var dialog = new TraeLoginDialog(traeBrowser, () => { }, preview: true) { StartPosition = FormStartPosition.Manual, Location = new Point(-32000, -32000) })
        {
            dialog.Show(this); Application.DoEvents();
            using var picture = new Bitmap(dialog.Width, dialog.Height);
            dialog.DrawToBitmap(picture, new Rectangle(Point.Empty, picture.Size));
            picture.Save(Path.Combine(directory, "trae-dialog.png"), System.Drawing.Imaging.ImageFormat.Png);
            dialog.Close();
        }
        traeDemo["other_accounts"]!["TRAE CN"] = JsonNode.Parse("""{"status":"partial","reason":"trae_usage_incomplete","quota":{"value":null},"credits":{"value":null}}""");
        using (var snapshot = JsonDocument.Parse(traeDemo.ToJsonString())) Render(snapshot.RootElement);
        if (!content.Controls.OfType<RoundedCard>().SelectMany(card => card.Controls.OfType<Label>())
            .Any(label => label.Text == "部分额度未提供使用情况"))
            throw new InvalidOperationException("TRAE 未提供用量时不能显示满额");
        using (var snapshot = JsonDocument.Parse(qoderSnapshot)) Render(snapshot.RootElement);
        content.AutoScrollPosition = Point.Empty;
        Size = new Size(420, 760);
        SetTheme(VisualThemes.Find("aurora"));
        SetView(View.Usage);
        var summaryRow = content.Controls.OfType<TableLayoutPanel>().Single(row => row.Name == "usage-summary");
        if (summaryRow.Controls.OfType<RoundedCard>().Count() != 2) throw new InvalidOperationException("用量总量与估算应分别显示");
        Size = new Size(380, 680); Application.DoEvents();
        if (content.HorizontalScroll.Visible) throw new InvalidOperationException("窄用量页出现横向滚动条");
        var narrowBreakdown = content.Controls.OfType<RoundedCard>().Single(card => card.Name == "usage-breakdown");
        var outputLabel = narrowBreakdown.Controls.OfType<Label>().Single(label => label.Name == "usage-part-name-1");
        if (TextRenderer.MeasureText(outputLabel.Text, outputLabel.Font, Size.Empty, TextFormatFlags.NoPadding).Width > outputLabel.Width)
            throw new InvalidOperationException("窄用量页的输出含推理标签被截断");
        content.AutoScrollPosition = Point.Empty; SavePreview("aurora-usage-compact");
        Size = new Size(420, 760); Application.DoEvents();
        var usageComposition = content.Controls.OfType<RoundedCard>().Single(card => card.Name == "usage-breakdown");
        if (!usageComposition.Controls.OfType<UsageCompositionRing>().Any(ring => ring.AccessibleName == "用量构成，缓存命中 75%") ||
            !usageComposition.Controls.OfType<Label>().Any(label => label.Name == "usage-part-0" && label.Text == "400K") ||
            !usageComposition.Controls.OfType<Label>().Any(label => label.Name == "usage-part-2" && label.Text == "1.2M"))
            throw new InvalidOperationException("用量构成或缓存命中显示错误");
        content.AutoScrollPosition = Point.Empty; SavePreview("aurora-usage-breakdown");
        var usageExport = content.Controls.OfType<Button>().Single(button => button.Name == "usage-export-data");
        content.ScrollControlIntoView(usageExport); Application.DoEvents(); SavePreview("aurora-usage-export-narrow");
        using (var snapshot = JsonDocument.Parse(lastSnapshot!))
            if (!UsageDataExport.Json(snapshot.RootElement, demo: true).Contains("\"demo\": true")) throw new InvalidOperationException("演示汇总导出缺少标识");
        foreach (var (period, expected) in new[] { ("7d", "8.5M"), ("30d", "28.2M"), ("all", "105.8M"), ("today", "1.77M") })
        {
            var selector = content.Controls.OfType<NavigationStrip>().SelectMany(strip => strip.Controls.OfType<NavigationTab>()).Single(button => button.Name == "usage-period-" + period);
            selector.PerformClick(); Application.DoEvents();
            if (usagePeriod != period || !content.Controls.OfType<TableLayoutPanel>().Where(row => row.Name == "usage-summary")
                .SelectMany(row => row.Controls.OfType<RoundedCard>()).SelectMany(card => card.Controls.OfType<Label>()).Any(label => label.Name == "usage-total" && label.Text == expected))
                throw new InvalidOperationException("用量周期切换或汇总错误：" + period);
            if (period == "7d" && !content.Controls.OfType<RoundedCard>().SelectMany(card => card.Controls.OfType<Label>()).Any(label => label.Text.Contains("近 7 天 API 等价估算 $12.3")))
                throw new InvalidOperationException("用量周期费用未切换");
            if (period == "7d" && !content.Controls.OfType<RoundedCard>().SelectMany(card => card.Controls.OfType<Label>()).Any(label => label.Text == "8 个 · 近 7 天"))
                throw new InvalidOperationException("图片文件统计未跟随用量周期");
            var totalCost = content.Controls.OfType<TableLayoutPanel>().Where(row => row.Name == "usage-summary")
                .SelectMany(row => row.Controls.OfType<RoundedCard>()).SelectMany(card => card.Controls.OfType<Label>()).Single(label => label.Name == "usage-cost-total");
            if (period == "7d" && totalCost.Text != "$12.3" || period == "today" && totalCost.Text != "$2.464")
                throw new InvalidOperationException("用量页首屏费用未跟随周期");
            var sourcesCard = content.Controls.OfType<RoundedCard>().Single(card => card.Name == "usage-sources");
            var leadingTokens = sourcesCard.Controls.OfType<Label>().Single(label => label.Name == "usage-source-tokens-0").Text;
            if (period == "7d" && leadingTokens != "7.6M" || period == "today" && leadingTokens != "1.43M")
                throw new InvalidOperationException("应用用量对比未跟随所选周期");
            var rankingCard = content.Controls.OfType<RoundedCard>().Single(card => card.Name == "model-ranking");
            string leadingModelTokens = rankingCard.Controls.OfType<Label>().Single(label => label.Name == "model-rank-tokens-0").Text;
            string expectedModelTokens = period switch { "today" => "1.43M", "7d" => "6.2M", "30d" => "25.8M", _ => "102M" };
            if (leadingModelTokens != expectedModelTokens) throw new InvalidOperationException("模型排行未跟随所选周期");
            if (period == "7d") SavePreview("aurora-usage-period-seven-days");
        }
        string fullUsageSnapshot = lastSnapshot!;
        var missingUsage = JsonNode.Parse(fullUsageSnapshot)!;
        missingUsage["history"] = JsonNode.Parse("""{"Codex":{"status":"available","value":{"periods":{"today":{"totals":{"total_tokens":10}}}}}}""");
        usagePeriod = "7d";
        using (var snapshot = JsonDocument.Parse(missingUsage.ToJsonString())) Render(snapshot.RootElement);
        if (!content.Controls.OfType<RoundedCard>().SelectMany(card => card.Controls.OfType<Label>()).Any(label => label.Text == "暂无数据"))
            throw new InvalidOperationException("缺失的用量周期不能显示为零");
        SavePreview("aurora-usage-period-unknown");
        usagePeriod = "today";
        using (var snapshot = JsonDocument.Parse(fullUsageSnapshot)) Render(snapshot.RootElement);
        var invalidBreakdown = JsonNode.Parse(fullUsageSnapshot)!;
        invalidBreakdown["history"]!["Codex"]!["value"]!["periods"]!["today"]!["totals"]!["fresh_input"] = null;
        using (var snapshot = JsonDocument.Parse(invalidBreakdown.ToJsonString())) Render(snapshot.RootElement);
        if (content.Controls.OfType<RoundedCard>().Any(card => card.Name == "usage-breakdown") ||
            !content.Controls.OfType<RoundedCard>().SelectMany(card => card.Controls.OfType<Label>()).Any(label => label.Text == "拆分数据不完整"))
            throw new InvalidOperationException("未知构成不应显示完整圆环");
        var partialZero = JsonNode.Parse(fullUsageSnapshot)!;
        partialZero["history"] = JsonNode.Parse("""{"A":{"status":"available","value":{"periods":{"today":{"totals":{"total_tokens":0}}}}},"B":{"status":"error"}}""");
        using (var snapshot = JsonDocument.Parse(partialZero.ToJsonString())) Render(snapshot.RootElement);
        if (!content.Controls.OfType<RoundedCard>().SelectMany(card => card.Controls.OfType<Label>()).Any(label => label.Text == "已读取来源为零，部分来源不完整"))
            throw new InvalidOperationException("部分来源缺失时不能断言没有消耗");
        var unknownHit = JsonNode.Parse(fullUsageSnapshot)!;
        unknownHit["history"] = JsonNode.Parse("""{"A":{"status":"available","value":{"periods":{"today":{"totals":{"total_tokens":100,"fresh_input":40,"cache_read":30,"unclassified":30}}}}}}""");
        using (var snapshot = JsonDocument.Parse(unknownHit.ToJsonString())) Render(snapshot.RootElement);
        var unknownHitCard = content.Controls.OfType<RoundedCard>().Single(card => card.Name == "usage-breakdown");
        if (!unknownHitCard.Controls.OfType<UsageCompositionRing>().Any(ring => ring.AccessibleName == "用量构成，缓存命中 未知") ||
            !unknownHitCard.Controls.OfType<Label>().Any(label => label.Text == "存在未拆分 Token，缓存命中未知"))
            throw new InvalidOperationException("未拆分 Token 时不能显示缓存命中率");
        var unknownCost = content.Controls.OfType<TableLayoutPanel>().Where(row => row.Name == "usage-summary")
            .SelectMany(row => row.Controls.OfType<RoundedCard>()).SelectMany(card => card.Controls.OfType<Label>()).ToArray();
        if (!unknownCost.Any(label => label.Name == "usage-cost-total" && label.Text == "—") ||
            !unknownCost.Any(label => label.Text == "非账单 · 暂无金额"))
            throw new InvalidOperationException("缺失费用不能显示为零或真实账单");
        using (var snapshot = JsonDocument.Parse(fullUsageSnapshot)) Render(snapshot.RootElement);
        SetView(View.Report);
        if (!content.Controls.OfType<RoundedCard>().SelectMany(card => card.Controls.OfType<Label>()).Any(label => label.Text == "+25%"))
            throw new InvalidOperationException("报告已结束自然日对照缺失");
        SavePreview("aurora-report-comparison-narrow");
        var reportExport = content.Controls.OfType<Button>().First(button => button.Text == "导出报告分享图");
        content.ScrollControlIntoView(reportExport); Application.DoEvents(); SavePreview("aurora-report-actions-narrow");
        SetView(View.Applications);
        var expandApp = content.Controls.OfType<RoundedCard>().SelectMany(card => card.Controls.OfType<Button>())
            .FirstOrDefault(button => button.Name == "app-expand-Codex") ?? throw new InvalidOperationException("application_card_missing");
        expandApp.PerformClick(); Application.DoEvents();
        if (!content.Controls.OfType<RoundedCard>().SelectMany(card => card.Controls.OfType<Label>())
            .Any(label => label.Name == "app-details-Codex" && label.Text.Contains("本机记录不按登录账户区分")))
            throw new InvalidOperationException("application_expand_failed");
        SavePreview("aurora-applications-expanded-narrow");
        var recentFilter = content.Controls.OfType<Panel>().SelectMany(panel => panel.Controls.OfType<NavigationTab>())
            .FirstOrDefault(button => button.Name == "app-filter-Recent") ?? throw new InvalidOperationException("application_filter_missing");
        recentFilter.PerformClick(); Application.DoEvents();
        if (applicationFilter != ApplicationFilter.Recent || content.Controls.OfType<RoundedCard>().SelectMany(card => card.Controls.OfType<Button>())
            .Any(button => button.Name == "app-expand-Claude Code")) throw new InvalidOperationException("application_filter_failed");
        SavePreview("aurora-applications-recent-narrow");
        applicationFilter = ApplicationFilter.All; expandedApplications.Clear();
        SetView(View.Forecast); SavePreview("aurora-forecast-narrow");
        var historyToggle = content.Controls.OfType<Button>().First(button => button.Name == "forecast-history-toggle");
        if (content.Controls.OfType<RoundedCard>().Count(card => card.Name == "forecast-history-card") != 3)
            throw new InvalidOperationException("forecast_history_initial_count");
        historyToggle.PerformClick(); Application.DoEvents();
        var historyCards = content.Controls.OfType<RoundedCard>().Where(card => card.Name == "forecast-history-card").ToArray();
        if (historyCards.Length != 7) throw new InvalidOperationException("forecast_history_expand_failed");
        content.ScrollControlIntoView(historyCards[0]); Application.DoEvents();
        SavePreview("aurora-forecast-history-narrow");
        content.Controls.OfType<Button>().First(button => button.Name == "forecast-history-toggle").PerformClick();
        if (allForecastHistory || content.Controls.OfType<RoundedCard>().Count(card => card.Name == "forecast-history-card") != 3)
            throw new InvalidOperationException("forecast_history_collapse_failed");
        SetTheme(VisualThemes.Find("porcelain")); SetView(View.Forecast); content.AutoScrollPosition = Point.Empty; SavePreview("porcelain-forecast-narrow");
        SetTheme(VisualThemes.Find("aurora"));
        SetView(View.Accounts); SavePreview("aurora-accounts-narrow");
        SetView(View.Collection); SavePreview("aurora-collection-narrow");
        var costMedal = content.Controls.OfType<RoundedCard>().Single(card => card.Controls.OfType<Label>().Any(label => label.Text == "小试牛刀"));
        if (!costMedal.Controls.OfType<Label>().Any(label => label.Text == "当前 145.5 / 100 元"))
            throw new InvalidOperationException("估算花费徽章金额显示错误");
        content.ScrollControlIntoView(costMedal); Application.DoEvents(); SavePreview("aurora-cost-medal");
        string medalSnapshot = lastSnapshot!;
        var noCost = JsonNode.Parse(medalSnapshot)!.AsObject();
        noCost["local_medals"]!["cost_status"] = "incomplete";
        ((JsonArray)noCost["local_medals"]!["medals"]!).RemoveAt(4);
        using (var snapshot = JsonDocument.Parse(noCost.ToJsonString())) Render(snapshot.RootElement);
        if (!content.Controls.OfType<RoundedCard>().SelectMany(card => card.Controls.OfType<Label>()).Any(label => label.Text == "来源、逐日模型拆分或价格不完整，暂不计算"))
            throw new InvalidOperationException("价格不完整时应隐藏花费徽章并提示原因");
        using (var snapshot = JsonDocument.Parse(medalSnapshot)) Render(snapshot.RootElement);
        var imageMedal = content.Controls.OfType<RoundedCard>().Single(card => card.Controls.OfType<Label>().Any(label => label.Text == "灵感速写"));
        if (!imageMedal.Controls.OfType<Label>().Any(label => label.Text == "当前 12 / 10 个 PNG 文件"))
            throw new InvalidOperationException("图片徽章的文件数量显示错误");
        content.ScrollControlIntoView(imageMedal); Application.DoEvents(); SavePreview("aurora-image-medal");
        bool HasCard(string name) => content.Controls.OfType<RoundedCard>()
            .SelectMany(card => card.Controls.OfType<Label>()).Any(label => label.Text == name);
        var toggle = content.Controls.OfType<Button>().FirstOrDefault(button => button.Text == "查看全部额度卡片")
            ?? throw new InvalidOperationException("card_toggle_missing");
        if (HasCard("八分饱")) throw new InvalidOperationException("locked_card_visible");
        toggle.PerformClick(); Application.DoEvents();
        if (!showAllQuotaCards || !HasCard("八分饱")) throw new InvalidOperationException("card_toggle_failed");
        SavePreview("aurora-collection-all-narrow");
        var collapse = content.Controls.OfType<Button>().FirstOrDefault(button => button.Text == "只看已收集卡片")
            ?? throw new InvalidOperationException("card_collapse_missing");
        collapse.PerformClick(); Application.DoEvents();
        if (showAllQuotaCards || HasCard("八分饱")) throw new InvalidOperationException("card_collapse_failed");
        RenderAccountDetailsPreviews(SavePreview);
        // 多账户分页；避免系统滚动条挤压额度环。
        var many = JsonNode.Parse(lastSnapshot!)!.AsObject();
        var accounts = new JsonArray();
        double[] remaining = [0, 12.5, 99.9, 100, 55];
        for (int index = 1; index <= remaining.Length; index++)
            accounts.Add(new JsonObject { ["label"] = "演示" + index, ["status"] = "available",
                ["quota"] = new JsonObject { ["value"] = new JsonArray(new JsonObject {
                    ["bucket"] = "5h", ["remaining_percent"] = remaining[index - 1] }) } });
        many["other_accounts"]!["MiniMax Code"] = accounts;
        using (var snapshot = JsonDocument.Parse(many.ToJsonString())) Render(snapshot.RootElement);
        SetView(View.Accounts); SavePreview("aurora-many-accounts-narrow");
        if (gauges.AutoScroll || !gaugeNext.Visible || !gaugeNext.Enabled || gaugePage != 0)
            throw new InvalidOperationException("多账户额度分页不可用");
        using (var arrow = new Bitmap(gaugeNext.Width, gaugeNext.Height))
        {
            gaugeNext.DrawToBitmap(arrow, new Rectangle(Point.Empty, arrow.Size));
            if (!Enumerable.Range(0, arrow.Width).Any(x => Enumerable.Range(0, arrow.Height).Any(y => arrow.GetPixel(x, y).ToArgb() != gaugeNext.BackColor.ToArgb())))
                throw new InvalidOperationException("分页箭头没有绘制");
        }
        gaugeNext.PerformClick(); Application.DoEvents();
        if (gaugePage != 1 || !gaugePrevious.Enabled || gauges.Controls.OfType<QuotaGauge>().Count(item => item.Visible) > 4)
            throw new InvalidOperationException("下一组账户额度未正确切换");
        var thirdAccount = gauges.Controls.Find("gauge-MINIMAX CODE · 演示3", false).OfType<QuotaGauge>().Single();
        var thirdCard = content.Controls.Find("account-MINIMAX CODE · 演示3", false).Single();
        if (!thirdAccount.Visible) throw new InvalidOperationException("第二组缺少指定的 MiniMax 账户");
        thirdAccount.PerformClick(); Application.DoEvents();
        var heading = thirdCard.Controls.OfType<Label>().First();
        if (-content.AutoScrollPosition.Y <= 0 || !contentClip.RectangleToScreen(contentClip.ClientRectangle).Contains(heading.RectangleToScreen(heading.ClientRectangle)))
            throw new InvalidOperationException("点击第二组额度环没有定位到对应别名的卡片");
        SavePreview("aurora-many-accounts-next");
        gaugePrevious.PerformClick();
        if (gaugePage != 0) throw new InvalidOperationException("上一组账户额度未正确切换");
        // 仅在隔离演示预览中显示虚构余额，不读取或保存凭据。
        var deepseek = JsonNode.Parse(lastSnapshot!)!.AsObject();
        deepseek["account"] = new JsonObject { ["status"] = "disabled" };
        deepseek["other_accounts"] = JsonNode.Parse("""{"DeepSeek API":{"status":"available","credits":{"value":[{"unit":"CNY","total":"88.00","granted":"8.00","topped_up":"80.00"}]}}}""");
        using (var snapshot = JsonDocument.Parse(deepseek.ToJsonString())) Render(snapshot.RootElement);
        SetView(View.Accounts); SavePreview("aurora-deepseek-narrow");
        using (var dialog = new DeepSeekKeyDialog { StartPosition = FormStartPosition.Manual, Location = new Point(-32000, -32000) })
        {
            dialog.Show(); Application.DoEvents();
            using var picture = new Bitmap(dialog.Width, dialog.Height);
            dialog.DrawToBitmap(picture, new Rectangle(Point.Empty, picture.Size));
            picture.Save(Path.Combine(directory, "deepseek-dialog.png"), System.Drawing.Imaging.ImageFormat.Png);
            dialog.Close();
        }
        var workbuddy = JsonNode.Parse(lastSnapshot!)!.AsObject();
        workbuddy["other_accounts"] = JsonNode.Parse("""{"WorkBuddy":{"status":"available","quota":{"value":[{"bucket":"credits","remaining_percent":25}]},"credits":{"value":{"balance":"25","total":"100","frozen":"0"}}}}""");
        using (var snapshot = JsonDocument.Parse(workbuddy.ToJsonString())) Render(snapshot.RootElement);
        SetView(View.Accounts); SavePreview("aurora-workbuddy-narrow");
        using (var dialog = new WorkBuddyLoginDialog(workBuddyBrowser, () => { }, preview: true) { StartPosition = FormStartPosition.Manual, Location = new Point(-32000, -32000) })
        {
            dialog.Show(); Application.DoEvents();
            using var picture = new Bitmap(dialog.Width, dialog.Height);
            dialog.DrawToBitmap(picture, new Rectangle(Point.Empty, picture.Size));
            picture.Save(Path.Combine(directory, "workbuddy-dialog.png"), System.Drawing.Imaging.ImageFormat.Png);
            dialog.Close();
        }
        var zcode = JsonNode.Parse(lastSnapshot!)!.AsObject();
        zcode["other_accounts"] = JsonNode.Parse("""{"ZCode":{"status":"available","subscription":{"plan":"GLM Coding Pro"},"quota":{"value":[{"bucket":"quota","limit_type":"CREDIT_LIMIT","window_minutes":300,"remaining_percent":72},{"bucket":"quota","limit_type":"CREDIT_LIMIT","window_minutes":10080,"remaining_percent":50},{"bucket":"mcp","limit_type":"TIME_LIMIT","remaining_percent":20}]}}}""");
        using (var snapshot = JsonDocument.Parse(zcode.ToJsonString())) Render(snapshot.RootElement);
        SetView(View.Accounts); SavePreview("aurora-zcode-narrow");
        if (!content.Controls.OfType<RoundedCard>().SelectMany(card => card.Controls.OfType<Label>()).Any(label => label.Text == "MCP 调用额度"))
            throw new InvalidOperationException("智谱额度卡片缺少 MCP 调用窗口");
        using (var dialog = new ZCodeKeyDialog { StartPosition = FormStartPosition.Manual, Location = new Point(-32000, -32000) })
        {
            dialog.Show(); Application.DoEvents();
            using var picture = new Bitmap(dialog.Width, dialog.Height);
            dialog.DrawToBitmap(picture, new Rectangle(Point.Empty, picture.Size));
            picture.Save(Path.Combine(directory, "zcode-dialog.png"), System.Drawing.Imaging.ImageFormat.Png);
            dialog.Close();
        }
        var volcengine = JsonNode.Parse(lastSnapshot!)!.AsObject();
        volcengine["other_accounts"] = JsonNode.Parse("""{"Volcengine":{"status":"available","subscription":{"plan":"Coding Plan Lite"},"quota":{"value":[{"bucket":"session","window_minutes":300,"remaining_percent":82},{"bucket":"weekly","window_minutes":10080,"remaining_percent":60},{"bucket":"monthly","window_minutes":43200,"remaining_percent":45}]}}}""");
        using (var snapshot = JsonDocument.Parse(volcengine.ToJsonString())) Render(snapshot.RootElement);
        SetView(View.Accounts); SavePreview("aurora-volcengine-narrow");
        if (!content.Controls.OfType<RoundedCard>().SelectMany(card => card.Controls.OfType<Label>()).Any(label => label.Text == "月度额度"))
            throw new InvalidOperationException("火山方舟额度卡片缺少月度窗口");
        using (var dialog = new VolcengineKeyDialog { StartPosition = FormStartPosition.Manual, Location = new Point(-32000, -32000) })
        {
            dialog.Show(); Application.DoEvents();
            using var picture = new Bitmap(dialog.Width, dialog.Height);
            dialog.DrawToBitmap(picture, new Rectangle(Point.Empty, picture.Size));
            picture.Save(Path.Combine(directory, "volcengine-dialog.png"), System.Drawing.Imaging.ImageFormat.Png);
            dialog.Close();
        }
        var mimo = JsonNode.Parse(lastSnapshot!)!.AsObject();
        mimo["other_accounts"] = JsonNode.Parse("""{"MiMo":{"status":"available","subscription":{"plan":"Token Plan Lite"},"quota":{"value":[{"bucket":"monthTotal","remaining_percent":75}]},"credits":{"value":[{"unit":"CNY","balance":"12.3","cash":"10","granted":"2.3"}]}}}""");
        using (var snapshot = JsonDocument.Parse(mimo.ToJsonString())) Render(snapshot.RootElement);
        SetView(View.Accounts); SavePreview("aurora-mimo-narrow");
        if (!content.Controls.OfType<RoundedCard>().SelectMany(card => card.Controls.OfType<Label>()).Any(label => label.Text == "Token Plan · 月度额度"))
            throw new InvalidOperationException("MiMo 账户卡片缺少月度额度");
        using (var dialog = new MiMoLoginDialog(mimoBrowser, () => { }, preview: true) { StartPosition = FormStartPosition.Manual, Location = new Point(-32000, -32000) })
        {
            dialog.Show(); Application.DoEvents();
            using var picture = new Bitmap(dialog.Width, dialog.Height);
            dialog.DrawToBitmap(picture, new Rectangle(Point.Empty, picture.Size));
            picture.Save(Path.Combine(directory, "mimo-dialog.png"), System.Drawing.Imaging.ImageFormat.Png);
            dialog.Close();
        }
        if (!SetRefreshInterval(5) || timer.Interval != 5 * 60 * 1000 || SetRefreshInterval(7) ||
            !SetRefreshInterval(15) || timer.Interval != 15 * 60 * 1000)
            throw new InvalidOperationException("刷新间隔未正确应用到计时器");
        Hide();
    }
    protected override void Dispose(bool disposing)
    {
        if (disposing) { shutdown.Cancel(); activityCancellation?.Cancel(); historyWorker.Dispose(); workBuddyBrowser.Dispose(); mimoBrowser.Dispose(); qoderBrowser.Dispose(); traeBrowser.Dispose(); timer.Dispose(); activityTimer.Dispose(); forecastClock.Dispose(); popupTips.Dispose(); }
        base.Dispose(disposing);
        if (disposing) { tabRegular.Dispose(); tabCompact.Dispose(); }
    }
    void UpdateTabs()
    {
        foreach (var (button, tab) in new[] { (accountTab, View.Accounts), (applicationsTab, View.Applications), (usageTab, View.Usage), (reportTab, View.Report), (forecastTab, View.Forecast), (petTab, View.Pet), (collectionTab, View.Collection) })
        {
            button.SetAppearance(theme, view == tab);
            button.TabStop = view == tab;
        }
        gauges.Visible = view == View.Accounts;
        header.Height = view == View.Accounts ? 234 : 118;
        LayoutGauges();
        subtitle.Text = view switch { View.Accounts => "账户额度与本机消耗", View.Applications => "应用覆盖与近期活动",
            View.Usage => "本机账本 · Token 与模型", View.Report => "自然周与自然月 · 用量报告",
            View.Forecast => "Codex 全局重置 · 第三方预测", View.Pet => "桌面伙伴 · 形象与状态", _ => "额度卡片与本机成就" };
        LayoutTabs();
    }
    void LayoutTabs()
    {
        var tabs = new[] { accountTab, applicationsTab, usageTab, reportTab, forecastTab, petTab, collectionTab };
        string[] full = ["账户额度", "应用", "本机消耗", "用量报告", "重置预测", "桌宠", "收集"];
        string[] compact = ["账户", "应用", "用量", "报告", "预测", "桌宠", "收集"];
        // 七页共用同一排点击位置，账户额度环在导航下方单独展开。
        navigationStrip.Bounds = new Rectangle(16, 76, Math.Max(1, header.ClientSize.Width - 32), 35);
        int width = Math.Max(1, (navigationStrip.ClientSize.Width - 6) / tabs.Length);
        for (int index = 0; index < tabs.Length; index++)
        {
            tabs[index].Size = new Size(width, 29);
            tabs[index].Location = new Point(3 + index * width, 3);
            tabs[index].Font = width < 62 ? tabCompact : tabRegular;
            tabs[index].Text = width < 62 ? compact[index] : full[index];
        }
    }
    public string ThemeId => theme.Id;
    public bool SetTheme(VisualTheme value)
    {
        try { if (!demo) VisualThemes.Save(AccountPreferences.DefaultDirectory, value); }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException)
        { status.Text = "无法保存界面风格，请检查设置目录权限"; return false; }
        theme = value;
        BackColor = header.BackColor = content.BackColor = contentViewport.BackColor = contentClip.BackColor = gauges.BackColor = status.BackColor = Background;
        if (scrollRail is not null) { scrollRail.BackColor = Background; scrollRail.ThumbColor = theme.Border; }
        ForeColor = Primary; title.ForeColor = Primary; subtitle.ForeColor = status.ForeColor = Muted;
        refresh.ForeColor = Accent; refresh.BackColor = Card; refresh.FlatAppearance.BorderColor = theme.Border;
        navigationStrip.BackColor = Card; ApplyPopupTheme();
        UpdateTabs();
        if (lastSnapshot is not null) { using var snapshot = JsonDocument.Parse(lastSnapshot); Render(snapshot.RootElement); }
        return true;
    }
    void SetView(View selected)
    {
        if (selected != View.Applications) activityCancellation?.Cancel();
        bool changed = view != selected;
        if (changed) content.AutoScrollPosition = Point.Empty;
        view = selected; UpdateTabs();
        // 正文会重建许多子窗口。先将新标题和整排标签画到屏幕上，避免正文先出现、旧高亮仍停留。
        if (changed && Visible && header.IsHandleCreated) header.Refresh();
        if (lastSnapshot is not null) { using var snapshot = JsonDocument.Parse(lastSnapshot); Render(snapshot.RootElement); }
        if (changed) content.AutoScrollPosition = Point.Empty;
        if (selected == View.Applications) _ = RefreshActivityIfNeeded();
    }

    public bool AccountEnabled(string provider) => provider switch
    {
        "Codex" => preferences.Codex, "Kimi" => preferences.Kimi, "Claude" => preferences.Claude,
        "MiniMax" => preferences.MiniMax, "DeepSeek" => preferences.DeepSeek, "WorkBuddy" => preferences.WorkBuddy,
        "ZCode" => preferences.ZCode, "Volcengine" => preferences.Volcengine, "MiMo" => preferences.MiMo, "Qoder" => preferences.Qoder, "Trae" => preferences.Trae, _ => false
    };
    public Task RefreshAfterAccountChange()
    {
        quotaAlerts.Clear(); cardAlerts.Clear(); accountCancellation?.Cancel();
        return RefreshData();
    }
    public Task RefreshAfterBudgetChange()
    {
        if (lastSnapshot is not null)
        {
            var snapshot = JsonNode.Parse(lastSnapshot)!.AsObject(); BudgetState.Apply(snapshot, AccountPreferences.DefaultDirectory);
            using var document = JsonDocument.Parse(snapshot.ToJsonString()); Render(document.RootElement);
        }
        return RefreshData();
    }
    internal async Task<string> RewardStatusAsync()
    {
        if (demo) return RewardError("demo_rewards_disabled");
        try
        {
            return await RunCollector("--rewards-status", shutdown.Token, "{}");
        }
        catch (Exception ex) when (ex is IOException or InvalidOperationException or System.ComponentModel.Win32Exception or
            OperationCanceledException or ObjectDisposedException)
        { return RewardError("rewards_status_unavailable"); }
    }
    internal async Task<string> ClaimRewardsAsync(bool claimAll)
    {
        if (demo) return RewardError("demo_rewards_disabled");
        if (busy) return RewardError("refresh_in_progress");
        if (rewardBusy) return RewardError("rewards_in_progress");
        rewardBusy = true;
        try
        {
            using var cancellation = CancellationTokenSource.CreateLinkedTokenSource(shutdown.Token);
            cancellation.CancelAfter(TimeSpan.FromSeconds(90));
            string output = await ClaimRewardsCoreAsync(claimAll, cancellation.Token);
            var successes = RewardsReport.Successes(output);
            if (successes.Count > 0 && !IsDisposed && !Disposing) RewardsClaimed?.Invoke(successes);
            return output;
        }
        catch (Exception ex) when (ex is IOException or InvalidOperationException or System.ComponentModel.Win32Exception or
            OperationCanceledException or ObjectDisposedException)
        { return RewardError("rewards_unavailable"); }
        finally { rewardBusy = false; }
    }
    async Task<string> ClaimRewardsCoreAsync(bool claimAll, CancellationToken cancellation)
    {
        var sessions = await RewardSessionsAsync(cancellation);
        if (sessions.Count == 0) return RewardError("rewards_session_unavailable");
        var input = new JsonObject { ["sessions"] = sessions, ["claim_all"] = claimAll };
        return await RunCollector("--rewards-claim", cancellation, input.ToJsonString());
    }
    async Task<JsonObject> RewardSessionsAsync(CancellationToken cancellation)
    {
        var workbuddyTask = preferences.WorkBuddy
            ? ReadRewardSessionAsync(token => workBuddyBrowser.SessionInputAsync(token), cancellation)
            : Task.FromResult<JsonNode?>(null);
        var traeTask = preferences.Trae
            ? ReadRewardSessionAsync(token => traeBrowser.SessionInputAsync(token), cancellation)
            : Task.FromResult<JsonNode?>(null);
        var workbuddy = await workbuddyTask; var trae = await traeTask;
        var sessions = new JsonObject();
        if (workbuddy is not null) { var rows = new JsonArray(); rows.Add(workbuddy); sessions["workbuddy"] = rows; }
        if (trae is not null) { var rows = new JsonArray(); rows.Add(trae); sessions["trae_cn"] = rows; }
        return sessions;
    }
    static async Task<JsonNode?> ReadRewardSessionAsync(Func<CancellationToken, Task<string>> read, CancellationToken cancellation)
    {
        try
        {
            string? raw = await read(cancellation);
            if (string.IsNullOrWhiteSpace(raw)) return null;
            var node = JsonNode.Parse(raw);
            var session = node?["session"];
            return session is JsonObject ? JsonNode.Parse(session.ToJsonString()) : null;
        }
        catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { throw; }
        catch (Exception ex) when (ex is JsonException or InvalidOperationException or IOException or UnauthorizedAccessException or
            System.Security.SecurityException or System.Runtime.InteropServices.COMException or
            Microsoft.Web.WebView2.Core.WebView2RuntimeNotFoundException)
        { return null; }
    }
    static string RewardError(string reason) => JsonSerializer.Serialize(new
    {
        schema_version = 1, timezone = "Asia/Shanghai", accounts = Array.Empty<object>(),
        unsupported = new[] {
            new { provider = "qoder", reason = "qoder_desktop_credentials_macos_only" },
            new { provider = "minimax_code", reason = "minimax_code_not_supported" }
        },
        status = "error", reason
    });
    public bool AlertsEnabled => alertsEnabled;
    public int RefreshIntervalMinutes => refreshIntervalMinutes;
    public bool SetRefreshInterval(int minutes)
    {
        if (!RefreshIntervalPreferences.Valid(minutes)) return false;
        if (minutes == refreshIntervalMinutes) return true;
        try { if (!demo) RefreshIntervalPreferences.Save(AccountPreferences.DefaultDirectory, minutes); }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException)
        { status.Text = "无法保存刷新设置，请检查设置目录权限"; return false; }
        refreshIntervalMinutes = minutes; timer.Stop(); timer.Interval = minutes * 60 * 1000; timer.Start();
        status.Text = $"刷新间隔已设为 {minutes} 分钟";
        return true;
    }
    public int AlertThreshold => alertThreshold;
    public bool CardAlertsEnabled => cardAlertsEnabled;
    /// <summary>跨设备同步只带不随机器变化的设置；开关与项目别名留在本机。</summary>
    internal string SyncSettingsJson() => new JsonObject
    {
        ["theme"] = ThemeId,
        ["low_quota_threshold"] = AlertThreshold,
        ["alerts_enabled"] = AlertsEnabled
    }.ToJsonString();
    public bool ForecastEnabled => forecastEnabled;
    public bool SetForecastEnabled(bool enabled)
    {
        try { ForecastPreferences.Save(AccountPreferences.DefaultDirectory, enabled); }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException)
        { status.Text = "无法保存预测设置，请检查设置目录权限"; return false; }
        forecastEnabled = enabled;
        accountCancellation?.Cancel();
        if (lastSnapshot is not null)
        {
            var snapshot = JsonNode.Parse(lastSnapshot)!.AsObject();
            snapshot["forecast"] = new JsonObject { ["status"] = enabled ? "loading" : "disabled" };
            using var doc = JsonDocument.Parse(snapshot.ToJsonString()); Render(doc.RootElement);
        }
        if (busy) { refreshQueued = true; status.Text = "预测设置已保存，当前刷新结束后生效"; }
        else _ = RefreshData();
        return true;
    }
    public event Action<IReadOnlyList<string>>? QuotaLow;
    public event Action<IReadOnlyList<string>>? CardsExpiring;
    public event Action<IReadOnlyList<string>>? BudgetTriggered;
    public event Action<IReadOnlyList<string>>? RewardsClaimed;
    public bool SetAlertsEnabled(bool enabled)
    {
        try { AlertPreferences.Save(AccountPreferences.DefaultDirectory, new AlertSettings(enabled, alertThreshold, cardAlertsEnabled)); }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException)
        { status.Text = "无法保存提醒设置，请检查设置目录权限"; return false; }
        alertsEnabled = enabled; quotaAlerts.Clear();
        if (enabled && lastSnapshot is not null)
        {
            using var snapshot = JsonDocument.Parse(lastSnapshot);
            NotifyLowQuota(snapshot.RootElement);
        }
        return true;
    }
    public bool SetAlertThreshold(int threshold)
    {
        if (!AlertPreferences.ValidThreshold(threshold)) return false;
        if (threshold == alertThreshold) return true;
        try { AlertPreferences.Save(AccountPreferences.DefaultDirectory, new AlertSettings(alertsEnabled, threshold, cardAlertsEnabled)); }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException)
        { status.Text = "无法保存提醒设置，请检查设置目录权限"; return false; }
        alertThreshold = threshold; quotaAlerts.Clear();
        if (alertsEnabled && lastSnapshot is not null)
        {
            using var snapshot = JsonDocument.Parse(lastSnapshot);
            NotifyLowQuota(snapshot.RootElement);
        }
        return true;
    }
    public bool SetCardAlertsEnabled(bool enabled)
    {
        try { AlertPreferences.Save(AccountPreferences.DefaultDirectory, new AlertSettings(alertsEnabled, alertThreshold, enabled)); }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException)
        { status.Text = "无法保存提醒设置，请检查设置目录权限"; return false; }
        cardAlertsEnabled = enabled; cardAlerts.Clear();
        if (enabled && lastSnapshot is not null)
        {
            using var snapshot = JsonDocument.Parse(lastSnapshot);
            NotifyLowQuota(snapshot.RootElement);
        }
        return true;
    }
    void NotifyLowQuota(JsonElement snapshot)
    {
        if (alertsEnabled)
        {
            var messages = quotaAlerts.Evaluate(snapshot, threshold: alertThreshold);
            if (messages.Count > 0) QuotaLow?.Invoke(messages);
        }
        if (cardAlertsEnabled)
        {
            var messages = cardAlerts.Evaluate(snapshot);
            if (messages.Count > 0) CardsExpiring?.Invoke(messages);
        }
    }
    public bool SetAccountEnabled(string provider, bool enabled)
    {
        var next = provider switch
        {
            "Codex" => preferences with { Codex = enabled }, "Kimi" => preferences with { Kimi = enabled },
            "Claude" => preferences with { Claude = enabled }, "MiniMax" => preferences with { MiniMax = enabled },
            "DeepSeek" => preferences with { DeepSeek = enabled }, "WorkBuddy" => preferences with { WorkBuddy = enabled },
            "ZCode" => preferences with { ZCode = enabled }, "Volcengine" => preferences with { Volcengine = enabled },
            "MiMo" => preferences with { MiMo = enabled }, "Qoder" => preferences with { Qoder = enabled }, "Trae" => preferences with { Trae = enabled }, _ => preferences
        };
        try { next.Save(AccountPreferences.DefaultDirectory); }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException)
        {
            status.Text = "无法保存账户开关，请检查设置目录权限";
            return false;
        }
        preferences = next;
        if (provider == "Trae" && !enabled) traeBrowser.Suspend();
        quotaAlerts.Clear(); cardAlerts.Clear();
        accountCancellation?.Cancel();
        if (lastSnapshot is not null)
        {
            var snapshot = JsonNode.Parse(lastSnapshot)!.AsObject(); ApplyAccountPreferences(snapshot);
            using var doc = JsonDocument.Parse(snapshot.ToJsonString()); Render(doc.RootElement);
        }
        if (busy) { refreshQueued = true; status.Text = "账户设置已保存，当前刷新结束后生效"; }
        else _ = RefreshData();
        return true;
    }

    void ApplyAccountPreferences(JsonObject snapshot)
    {
        static JsonObject Disabled() => new() { ["status"] = "disabled", ["reason"] = "disabled_by_user" };
        if (!preferences.Codex) snapshot["account"] = Disabled();
        var others = snapshot["other_accounts"] as JsonObject;
        if (others is null) { others = new JsonObject(); snapshot["other_accounts"] = others; }
        if (!preferences.Kimi) others["Kimi Code"] = Disabled();
        if (!preferences.Claude) others["Claude Code"] = Disabled();
        if (!preferences.MiniMax) others["MiniMax Code"] = Disabled();
        if (!preferences.DeepSeek) others["DeepSeek API"] = Disabled();
        if (!preferences.WorkBuddy) others["WorkBuddy"] = Disabled();
        if (!preferences.ZCode) others["ZCode"] = Disabled();
        if (!preferences.Volcengine) others["Volcengine"] = Disabled();
        if (!preferences.MiMo) others["MiMo"] = Disabled();
        if (!preferences.Qoder) others["Qoder CN"] = Disabled();
        if (!preferences.Trae) others["TRAE CN"] = Disabled();
        if (!forecastEnabled) snapshot["forecast"] = Disabled();
    }

    public async Task RefreshData()
    {
        if (busy) { refreshQueued = true; return; }
        activityCancellation?.Cancel();
        busy = true; refresh.Enabled = false; status.Text = "正在刷新，本机记录较多时可能需要一些时间…";
        try
        {
            if (demo)
            {
                var sample = JsonNode.Parse(DemoData)!.AsObject();
                var codexPeriods = sample["history"]!["Codex"]!["value"]!["periods"]!;
                codexPeriods["today"]!["groups"] = JsonNode.Parse("""[{"model":"gpt-5.3-codex","total_tokens":1426000}]""");
                codexPeriods["today"]!["model_costs"] = JsonNode.Parse("""{"gpt-5.3-codex":{"amount_usd":"2.464","partial":false}}""");
                codexPeriods["7d"]!["model_costs"] = JsonNode.Parse("""{"gpt-5.3-codex":{"amount_usd":"10.3","partial":false},"gpt-5.1-codex":{"amount_usd":"2","partial":false}}""");
                codexPeriods["30d"]!["groups"] = JsonNode.Parse("""[{"model":"gpt-5.3-codex","total_tokens":25800000}]""");
                codexPeriods["all"]!["groups"] = JsonNode.Parse("""[{"model":"gpt-5.3-codex","total_tokens":102000000}]""");
                var claudePeriods = sample["history"]!["Claude Code"]!["value"]!["periods"]!;
                claudePeriods["today"]!["groups"] = JsonNode.Parse("""[{"model":"claude-sonnet-4","total_tokens":341000}]""");
                claudePeriods["30d"]!["groups"] = JsonNode.Parse("""[{"model":"claude-sonnet-4","total_tokens":2400000}]""");
                claudePeriods["all"]!["groups"] = JsonNode.Parse("""[{"model":"claude-sonnet-4","total_tokens":3800000}]""");
                sample["activity"]!["sources"] = JsonNode.Parse("""{"Codex":"available","Claude Code":"available","Kimi Code":"available"}""");
                var daily = new JsonArray();
                int[] demoDailyThousands = [324, 480, 550, 710, 280, 820, 650, 840, 1030, 610,
                    680, 810, 910, 930, 1230, 850, 660, 1050, 930, 880,
                    1070, 930, 790, 1150, 1240, 1050, 910, 980, 1030, 1426];
                for (int index = 0; index < 30; index++)
                    daily.Add(new JsonObject { ["date"] = new DateOnly(2026, 10, 16).AddDays(index).ToString("yyyy-MM-dd"),
                        ["tokens"] = demoDailyThousands[index] * 1000 });
                sample["history"]!["Codex"]!["value"]!["daily_trend"] = new JsonObject { ["days"] = daily, ["incomplete"] = false };
                sample["history"]!["Codex"]!["estimates"] = JsonNode.Parse("""{"today":{"amount_usd":"2.464","partial":false},"7d":{"amount_usd":"12.3","partial":false},"30d":{"amount_usd":"35.8","partial":true},"all":{"amount_usd":"120.9","partial":true}}""");
                sample["other_accounts"]!["DeepSeek API"] = JsonNode.Parse("""{"status":"available","credits":{"value":[{"unit":"CNY","total":"88.00","granted":"8.00","topped_up":"80.00"}]}}""");
                sample["forecast"] = ForecastDemo();
                sample["calendar_report"]!["periods"]!["week"]!["comparable_days"] = 5;
                sample["calendar_report"]!["periods"]!["week"]!["current_comparable_tokens"] = 5000000;
                sample["calendar_report"]!["periods"]!["week"]!["previous_comparable_tokens"] = 4000000;
                sample["calendar_report"]!["periods"]!["month"]!["comparable_days"] = 13;
                sample["calendar_report"]!["periods"]!["month"]!["current_comparable_tokens"] = 6500000;
                sample["calendar_report"]!["periods"]!["month"]!["previous_comparable_tokens"] = 8000000;
                sample["observed_at"] = ForecastDemoNow.ToUnixTimeSeconds();
                AddDemoAccountDetails(sample);
                sample["local_medals"] = JsonNode.Parse("""{"sources":2,"incomplete":false,"earned":1,"total":3,"active_days":12,"medals":[{"name":"亿级玩家","category":"day_peak","category_name":"单日用量","tier":"bronze","target":100000000,"unit":"tokens","value":120000000,"progress":1,"earned":true,"earned_on":"2026-11-12"},{"name":"五亿狂飙","category":"day_peak","category_name":"单日用量","tier":"silver","target":500000000,"unit":"tokens","value":120000000,"progress":0.24,"earned":false},{"name":"一周不停","category":"streak","category_name":"连续使用","tier":"bronze","target":7,"unit":"days","value":4,"progress":0.57,"earned":false}]}""");
                sample["image_files"] = JsonNode.Parse("""{"status":"available","value":{"periods":{"today":{"files":4},"7d":{"files":8},"30d":{"files":12},"all":{"files":12}}}}""");
                sample["local_medals"]!["image_status"] = "available";
                sample["local_medals"]!["cost_status"] = "available";
                sample["local_medals"]!["earned"] = 3; sample["local_medals"]!["total"] = 5;
                ((JsonArray)sample["local_medals"]!["medals"]!).Add(JsonNode.Parse("""{"name":"灵感速写","category":"img_day","category_name":"单日出图","tier":"bronze","target":10,"unit":"images","value":12,"progress":1,"earned":true,"earned_on":"2026-11-12"}"""));
                ((JsonArray)sample["local_medals"]!["medals"]!).Add(JsonNode.Parse("""{"name":"小试牛刀","category":"cost_day","category_name":"单日估算花费","tier":"bronze","target":100,"unit":"cny","value":145.5,"progress":1,"earned":true,"earned_on":"2026-11-12"}"""));
                sample["quota_cards"] = JsonNode.Parse("""{"status":"available","distinct":1,"cards":[{"id":"q5_50","name":"热身完毕","series":"five_hour","rarity":"common","description":"5 小时窗口用量达到 50% 即掉落","count":2},{"id":"q5_80","name":"八分饱","series":"five_hour","rarity":"rare","description":"5 小时窗口用量达到 80% 即掉落","count":0}]}""");
                using var preview = JsonDocument.Parse(sample.ToJsonString()); Render(preview.RootElement); status.Text = "演示数据 · 不代表真实账户";
            }
            else
            {
                accountCancellation = CancellationTokenSource.CreateLinkedTokenSource(shutdown.Token);
                string? accountInput = null; bool profilesInvalid = false;
                if (preferences.MiniMax)
                {
                    try { accountInput = MiniMaxAccountInput.Build(AccountPreferences.DefaultDirectory, new WindowsMiniMaxVault()); }
                    catch (Exception ex) when (ex is InvalidDataException or IOException or UnauthorizedAccessException or System.Security.SecurityException or JsonException)
                    { profilesInvalid = true; }
                }
                string arguments = "--account-only" + (preferences.Codex ? "" : " --disable-codex-account") +
                    (preferences.Kimi ? "" : " --disable-kimi-account") + (preferences.Claude ? "" : " --disable-claude-account") +
                    (preferences.MiniMax && !profilesInvalid ? " --enable-minimax-account" : "") +
                    (accountInput is null ? "" : " --account-input");
                var accountTask = RunCollector(arguments, accountCancellation.Token, accountInput);
                accountInput = null;
                var historyTask = historyWorker.RefreshAsync(shutdown.Token);
                var forecastTask = forecastEnabled ? RunCollector("--forecast-only", accountCancellation.Token) : null;
                var workbuddyTask = preferences.WorkBuddy ? WorkBuddyAccountAsync(accountCancellation.Token) : null;
                var mimoTask = preferences.MiMo ? MiMoAccountAsync(accountCancellation.Token) : null;
                var qoderTask = preferences.Qoder ? QoderAccountAsync(accountCancellation.Token) : null;
                var traeTask = preferences.Trae ? TraeAccountAsync(accountCancellation.Token) : null;
                Task<string>? deepseekTask = null;
                Task<string>? zcodeTask = null;
                Task<string>? volcengineTask = null;
                if (preferences.Volcengine)
                {
                    VolcengineKeys? keys = null;
                    try { keys = VolcengineKeyStore.Read(); }
                    catch (Exception ex) when (ex is System.ComponentModel.Win32Exception or InvalidDataException or IOException or UnauthorizedAccessException or System.Security.SecurityException) { }
                    string? secretInput = VolcengineKeyStore.Input(keys); keys = null;
                    volcengineTask = RunCollector("--volcengine-only", accountCancellation.Token, secretInput); secretInput = null;
                }
                if (preferences.ZCode)
                {
                    string? key = null;
                    try { key = ZCodeKeyStore.Read(); }
                    catch (Exception ex) when (ex is System.ComponentModel.Win32Exception or InvalidDataException or IOException or UnauthorizedAccessException or System.Security.SecurityException) { }
                    string? secretInput = ZCodeKeyStore.Input(key); key = null;
                    zcodeTask = RunCollector("--zcode-only", accountCancellation.Token, secretInput); secretInput = null;
                }
                if (preferences.DeepSeek)
                {
                    string? key = null;
                    try { key = DeepSeekKeyStore.Read(); }
                    catch (Exception ex) when (ex is System.ComponentModel.Win32Exception or InvalidDataException or IOException or UnauthorizedAccessException or System.Security.SecurityException) { }
                    string? secretInput = DeepSeekKeyStore.Input(key);
                    key = null;
                    deepseekTask = RunCollector("--deepseek-only", accountCancellation.Token, secretInput);
                    secretInput = null;
                }
                var combined = new JsonObject {
                    ["observed_at"] = DateTimeOffset.UtcNow.ToUnixTimeSeconds(),
                    ["account"] = new JsonObject { ["status"] = "loading" },
                    ["other_accounts"] = new JsonObject {
                        ["Kimi Code"] = new JsonObject { ["status"] = "loading" },
                        ["Claude Code"] = new JsonObject { ["status"] = "loading" },
                        ["MiniMax Code"] = new JsonObject { ["status"] = "loading" },
                        ["DeepSeek API"] = new JsonObject { ["status"] = preferences.DeepSeek ? "loading" : "disabled" },
                        ["WorkBuddy"] = new JsonObject { ["status"] = preferences.WorkBuddy ? "loading" : "disabled" },
                        ["ZCode"] = new JsonObject { ["status"] = preferences.ZCode ? "loading" : "disabled" },
                        ["Volcengine"] = new JsonObject { ["status"] = preferences.Volcengine ? "loading" : "disabled" },
                        ["MiMo"] = new JsonObject { ["status"] = preferences.MiMo ? "loading" : "disabled" },
                        ["Qoder CN"] = new JsonObject { ["status"] = preferences.Qoder ? "loading" : "disabled" },
                        ["TRAE CN"] = new JsonObject { ["status"] = preferences.Trae ? "loading" : "disabled" }
                    },
                    ["history"] = new JsonObject { ["历史统计"] = new JsonObject { ["status"] = "loading", ["reason"] = "history_loading" } },
                    ["forecast"] = new JsonObject { ["status"] = forecastEnabled ? "loading" : "disabled" },
                    ["quota_cards"] = new JsonObject { ["status"] = "loading" },
                    ["local_medals"] = new JsonObject { ["status"] = "loading" }
                };
                if (profilesInvalid) combined["other_accounts"]!["MiniMax Code"] = new JsonObject { ["status"] = "error", ["reason"] = "minimax_profiles_invalid" };
                if (lastSyncedQuota is not null) combined["synced_quota"] = lastSyncedQuota.DeepClone();
                ApplyAccountPreferences(combined);
                using (var first = JsonDocument.Parse(combined.ToJsonString())) Render(first.RootElement, accountDetailsPending: true);
                var pending = new List<(string Name, Task<string> Task)> { ("accounts", accountTask), ("history", historyTask) };
                if (deepseekTask is not null) pending.Add(("DeepSeek API", deepseekTask));
                if (zcodeTask is not null) pending.Add(("ZCode", zcodeTask));
                if (volcengineTask is not null) pending.Add(("Volcengine", volcengineTask));
                if (workbuddyTask is not null) pending.Add(("WorkBuddy", workbuddyTask));
                if (mimoTask is not null) pending.Add(("MiMo", mimoTask));
                if (qoderTask is not null) pending.Add(("Qoder CN", qoderTask));
                if (traeTask is not null) pending.Add(("TRAE CN", traeTask));
                if (forecastTask is not null) pending.Add(("forecast", forecastTask));
                var refreshCancellation = accountCancellation.Token;
                await ApplyRefreshPartsAsync(combined, pending, false, profilesInvalid, snapshot =>
                    RunCollector("--cards-update", refreshCancellation, CardInput.Create(snapshot)),
                    snapshot => StartSyncedQuota(snapshot, refreshCancellation));
            }
        }
        catch (Exception ex) when (ex is IOException or InvalidOperationException or JsonException or System.ComponentModel.Win32Exception or OperationCanceledException or ObjectDisposedException)
        {
            if (IsDisposed || Disposing) return;
            content.Controls.Clear(); AddHeading("暂时无法读取数据", "请确认应用文件完整后重试。");
            status.Text = "刷新失败 · " + (ex is OperationCanceledException ? "读取超时" : "无法启动或解析采集程序");
        }
        finally
        {
            accountCancellation?.Dispose(); accountCancellation = null; busy = false;
            if (!IsDisposed && !Disposing)
            {
                refresh.Enabled = true;
                if (refreshQueued) { refreshQueued = false; _ = RefreshData(); }
            }
        }
    }
    async Task RefreshActivityIfNeeded()
    {
        if (!ActivityRefreshPolicy.CanRefresh(demo && syntheticActivityReader is null, Visible, view == View.Applications, busy, activityBusy,
            lastSnapshot is not null, lastActivityAttempt, DateTimeOffset.UtcNow)) return;
        activityBusy = true; lastActivityAttempt = DateTimeOffset.UtcNow;
        using var cancellation = CancellationTokenSource.CreateLinkedTokenSource(shutdown.Token);
        activityCancellation = cancellation; cancellation.CancelAfter(TimeSpan.FromSeconds(45));
        try
        {
            string output = syntheticActivityReader is null
                ? await RunCollector("--activity-only", cancellation.Token) : await syntheticActivityReader(cancellation.Token);
            if (cancellation.IsCancellationRequested || IsDisposed || Disposing || !Visible || view != View.Applications || busy || lastSnapshot is null) return;
            var next = JsonNode.Parse(output) as JsonObject;
            string? state = next?["status"]?.GetValue<string>();
            if (state is not ("available" or "partial")) { status.Text = "活动更新失败，保留上次记录"; return; }
            var snapshot = JsonNode.Parse(lastSnapshot)!.AsObject();
            snapshot["activity"] = next;
            var scroll = content.AutoScrollPosition;
            using var document = JsonDocument.Parse(snapshot.ToJsonString()); Render(document.RootElement);
            content.PerformLayout(); content.AutoScrollPosition = new Point(-scroll.X, -scroll.Y);
            status.Text = $"活动更新于 {DateTime.Now:HH:mm:ss} · 仅本机记录";
        }
        catch (Exception ex) when (ex is IOException or InvalidOperationException or JsonException or System.ComponentModel.Win32Exception or OperationCanceledException or ObjectDisposedException)
        {
            if (!shutdown.IsCancellationRequested && !busy && !IsDisposed && !Disposing && Visible && view == View.Applications)
                status.Text = "活动更新失败，保留上次记录";
        }
        finally
        {
            if (ReferenceEquals(activityCancellation, cancellation)) activityCancellation = null;
            activityBusy = false;
        }
    }
    internal async Task SyntheticActivitySmokeAsync()
    {
        if (!demo) throw new InvalidOperationException("demo_required");
        await RefreshData();
        int calls = 0; CancellationToken secondToken = default;
        var pendingResult = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
        const string data = """{"status":"available","sources":{"Codex":"available"},"apps":[{"name":"Codex","sessions":1,"recent_updates":1,"last_updated":1800000000}]}""";
        syntheticActivityReader = token =>
        {
            calls++;
            if (calls == 2) { secondToken = token; return pendingResult.Task.WaitAsync(token); }
            return Task.FromResult(data);
        };
        try
        {
            lastActivityAttempt = DateTimeOffset.MinValue;
            SetView(View.Applications);
            if (calls != 1 || lastSnapshot is null || !lastSnapshot.Contains("\"recent_updates\":1", StringComparison.Ordinal))
                throw new InvalidOperationException("activity_refresh_not_applied");
            await RefreshActivityIfNeeded();
            if (calls != 1) throw new InvalidOperationException("activity_refresh_too_soon");
            lastActivityAttempt = DateTimeOffset.UtcNow.AddMinutes(-2);
            var pending = RefreshActivityIfNeeded();
            if (calls != 2) throw new InvalidOperationException("activity_refresh_not_started");
            SetView(View.Usage);
            await pending;
            if (!secondToken.IsCancellationRequested || activityBusy) throw new InvalidOperationException("activity_refresh_not_cancelled");
            Hide(); SetView(View.Applications); lastActivityAttempt = DateTimeOffset.UtcNow.AddMinutes(-2);
            await RefreshActivityIfNeeded();
            if (calls != 2) throw new InvalidOperationException("hidden_activity_refresh_started");
            Show(); SetView(View.Applications);
            if (calls != 3) throw new InvalidOperationException("activity_refresh_not_resumed");
        }
        finally { syntheticActivityReader = null; activityCancellation?.Cancel(); }
    }
    async Task<string> WorkBuddyAccountAsync(CancellationToken cancellation)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        timeout.CancelAfter(TimeSpan.FromSeconds(30));
        try
        {
            string? session = await workBuddyBrowser.SessionInputAsync(timeout.Token).WaitAsync(timeout.Token);
            timeout.Token.ThrowIfCancellationRequested();
            var task = RunCollector("--workbuddy-only", timeout.Token, session);
            session = null;
            return await task;
        }
        catch (Microsoft.Web.WebView2.Core.WebView2RuntimeNotFoundException)
        { return """{"status":"unavailable","reason":"workbuddy_runtime_missing"}"""; }
        catch (Exception ex) when (!cancellation.IsCancellationRequested && WebViewSafety.IsIsolationFailure(ex))
        { return """{"status":"unavailable","reason":"workbuddy_profile_unsafe"}"""; }
        catch (Exception ex) when (!cancellation.IsCancellationRequested && ex is System.Runtime.InteropServices.COMException or
            InvalidOperationException or IOException or UnauthorizedAccessException or System.Security.SecurityException or OperationCanceledException)
        { return """{"status":"unavailable","reason":"workbuddy_session_unavailable"}"""; }
    }
    async Task<string> MiMoAccountAsync(CancellationToken cancellation)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        timeout.CancelAfter(TimeSpan.FromSeconds(30));
        try
        {
            string? session = await mimoBrowser.SessionInputAsync(timeout.Token).WaitAsync(timeout.Token);
            timeout.Token.ThrowIfCancellationRequested();
            var task = RunCollector("--mimo-only", timeout.Token, session); session = null;
            return await task;
        }
        catch (Microsoft.Web.WebView2.Core.WebView2RuntimeNotFoundException)
        { return """{"status":"unavailable","reason":"mimo_runtime_missing"}"""; }
        catch (Exception ex) when (!cancellation.IsCancellationRequested && WebViewSafety.IsIsolationFailure(ex))
        { return """{"status":"unavailable","reason":"mimo_profile_unsafe"}"""; }
        catch (Exception ex) when (!cancellation.IsCancellationRequested && ex is System.Runtime.InteropServices.COMException or
            InvalidOperationException or IOException or UnauthorizedAccessException or System.Security.SecurityException or OperationCanceledException)
        { return """{"status":"unavailable","reason":"mimo_session_unavailable"}"""; }
    }
    async Task<string> QoderAccountAsync(CancellationToken cancellation)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        timeout.CancelAfter(TimeSpan.FromSeconds(30));
        try
        {
            string? session = await qoderBrowser.SessionInputAsync(timeout.Token).WaitAsync(timeout.Token);
            timeout.Token.ThrowIfCancellationRequested();
            var task = RunCollector("--qoder-only", timeout.Token, session); session = null;
            return await task;
        }
        catch (Microsoft.Web.WebView2.Core.WebView2RuntimeNotFoundException)
        { return """{"status":"unavailable","reason":"qoder_runtime_missing"}"""; }
        catch (Exception ex) when (!cancellation.IsCancellationRequested && WebViewSafety.IsIsolationFailure(ex))
        { return """{"status":"unavailable","reason":"qoder_profile_unsafe"}"""; }
        catch (Exception ex) when (!cancellation.IsCancellationRequested && ex is System.Runtime.InteropServices.COMException or
            InvalidOperationException or IOException or UnauthorizedAccessException or System.Security.SecurityException or OperationCanceledException)
        { return """{"status":"unavailable","reason":"qoder_session_unavailable"}"""; }
    }
    async Task<string> TraeAccountAsync(CancellationToken cancellation)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        timeout.CancelAfter(TimeSpan.FromSeconds(30));
        try
        {
            string? session = await traeBrowser.SessionInputAsync(timeout.Token).WaitAsync(timeout.Token);
            timeout.Token.ThrowIfCancellationRequested();
            var task = RunCollector("--trae-only", timeout.Token, session); session = null;
            return await task;
        }
        catch (Microsoft.Web.WebView2.Core.WebView2RuntimeNotFoundException)
        { return """{"status":"unavailable","reason":"trae_runtime_missing"}"""; }
        catch (Exception ex) when (!cancellation.IsCancellationRequested && WebViewSafety.IsIsolationFailure(ex))
        { return """{"status":"unavailable","reason":"trae_profile_unsafe"}"""; }
        catch (Exception ex) when (!cancellation.IsCancellationRequested && ex is System.Runtime.InteropServices.COMException or
            InvalidOperationException or IOException or UnauthorizedAccessException or System.Security.SecurityException or OperationCanceledException)
        { return """{"status":"unavailable","reason":"trae_session_unavailable"}"""; }
    }
    static async Task<string> RunCollector(string mode, CancellationToken shutdown, string? accountInput = null)
    {
        var path = Path.Combine(AppContext.BaseDirectory, "backend", "AgentMeterBackend.exe");
        if (!File.Exists(path)) throw new IOException("backend_missing");
        using var process = new Process { StartInfo = new ProcessStartInfo(path, mode) { UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true, StandardOutputEncoding = System.Text.Encoding.UTF8 } };
        if (accountInput is not null) { process.StartInfo.RedirectStandardInput = true; process.StartInfo.StandardInputEncoding = new System.Text.UTF8Encoding(false); }
        if (!process.Start()) throw new InvalidOperationException("backend_start_failed");
        var output = process.StandardOutput.ReadToEndAsync(); var error = process.StandardError.ReadToEndAsync();
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(shutdown);
        timeout.CancelAfter(TimeSpan.FromMinutes(10));
        try
        {
            if (accountInput is not null)
            {
                await process.StandardInput.WriteAsync(accountInput.AsMemory(), timeout.Token);
                await process.StandardInput.FlushAsync(timeout.Token);
                process.StandardInput.Close();
                accountInput = null;
            }
            await process.WaitForExitAsync(timeout.Token);
        }
        catch (Exception ex) when (ex is OperationCanceledException or IOException or ObjectDisposedException)
        {
            try { process.Kill(true); }
            catch (Exception stopError) when (stopError is InvalidOperationException or System.ComponentModel.Win32Exception or NotSupportedException) { }
            throw;
        }
        await error;
        if (process.ExitCode != 0) throw new InvalidOperationException("backend_failed");
        return await output;
    }
    void Render(JsonElement root, bool accountDetailsPending = false)
    {
        lastSnapshot = root.GetRawText();
        SnapshotUpdated?.Invoke(lastSnapshot);
        // 分批采集时，托盘仍接收最新结果。正在阅读明细的人可以继续操作眼前的卡片。
        if (accountDetailsPending && view == View.Accounts && displayedAccountSnapshot is not null &&
            (content.AutoScrollPosition.Y != 0 || gauges.ContainsFocus || content.ContainsFocus))
        {
            status.Text = "正在刷新 · 当前显示上次账户明细";
            return;
        }
        RenderPage(root, lastSnapshot);
    }
    void RenderPage(JsonElement root, string snapshotText)
    {
        displayedAccountSnapshot = view == View.Accounts ? snapshotText : null;
        string? focusedGaugeName = gauges.Controls.OfType<QuotaGauge>().FirstOrDefault(gauge => gauge.Focused)?.Name;
        bool resetToggleFocused = view == View.Accounts && content.Controls.Find("account-reset-toggle", true).FirstOrDefault()?.Focused == true;
        int previousTop = -content.AutoScrollPosition.Y;
        if (view == View.Accounts)
        {
            gauges.SuspendLayout();
            while (gauges.Controls.Count > 0) gauges.Controls[0].Dispose();
        }
        content.SuspendLayout();
        forecastClocks.Clear(); quotaResetLabels.Clear(); accountClockUpdates.Clear();
        while (content.Controls.Count > 0) content.Controls[0].Dispose();
        if (view == View.Accounts)
        {
        // 托盘面板直接进入账户卡片，避免重复标题占据首屏。
        var localHistories = GetValue(root, "history");
        var account = GetValue(root, "account"); var codexDetails = AccountDetails.Read("Codex", account); var quotas = GetValue(GetValue(account, "quota"), "value");
        if (quotas.ValueKind == JsonValueKind.Array && quotas.GetArrayLength() > 0)
        {
            var rows = new List<QuotaRow>();
            foreach (var q in quotas.EnumerateArray())
            {
                string bucket = GetString(q, "bucket", "Codex"), window = GetString(q, "window", "");
                var minutes = GetNumber(q, "window_minutes");
                string period = minutes == 300 ? "5 小时" : minutes == 10080 ? "7 天" : minutes.HasValue ? $"{minutes:0} 分钟" : window;
                double? remaining = GetNumber(q, "remaining_percent");
                string prefix = bucket.Equals("codex", StringComparison.OrdinalIgnoreCase) ? "" : bucket.ToUpperInvariant() + " · ";
                rows.Add(new QuotaRow(prefix + period, remaining, QuotaResetClock.Read(q)));
            }
            AddQuotaGroup("CODEX", rows, GetValue(localHistories, "Codex"), codexDetails, account);
        }
        else if (codexDetails.HasContent) AddQuotaGroup("CODEX", [], GetValue(localHistories, "Codex"), codexDetails);
        else if (GetString(account, "status", "") == "disabled") AddCard("CODEX", "账户查询已关闭", "可在托盘菜单重新开启", null);
        else if (GetString(account, "status", "") == "loading") AddCard("CODEX", "正在读取额度", "正在查询账户", null);
        else AddCard("CODEX", "暂时无法获取额度", Reason(account), null);
        var otherAccounts = GetValue(root, "other_accounts");
        var kimiAccount = GetValue(otherAccounts, "Kimi Code");
        var kimiStatus = GetString(kimiAccount, "status", "");
        if (kimiAccount.ValueKind == JsonValueKind.Object && GetString(kimiAccount, "reason", "") != "kimi_server_token_missing")
        {
            var kimiQuotas = GetValue(GetValue(kimiAccount, "quota"), "value");
            if (kimiQuotas.ValueKind == JsonValueKind.Array && kimiQuotas.GetArrayLength() > 0)
            {
                var rows = new List<QuotaRow>();
                foreach (var q in kimiQuotas.EnumerateArray())
                {
                    string bucket = GetString(q, "bucket", "");
                    var window = GetValue(q, "window");
                    double? duration = GetNumber(window, "duration");
                    string unit = GetString(window, "unit", "");
                    string label = bucket switch { "limit5h" => "5 小时", "limit7d" => "7 天", "monthTotal" => "月度总额", "monthCode" => "月度代码", _ => bucket };
                    if (duration.HasValue) label = $"{duration:0.##} " + (unit switch { "hour" => "小时", "day" => "天", "week" => "周", "month" => "月", "minute" => "分钟", "second" => "秒", _ => unit });
                    double? remaining = GetNumber(q, "remaining_percent");
                    rows.Add(new QuotaRow(label, remaining, QuotaResetClock.Read(q)));
                }
                AddQuotaGroup("KIMI CODE", rows, GetValue(localHistories, "Kimi Code"), AccountDetails.Read("Kimi Code", kimiAccount), kimiAccount);
            }
            else if (AccountDetails.Read("Kimi Code", kimiAccount).HasContent) AddQuotaGroup("KIMI CODE", [], GetValue(localHistories, "Kimi Code"), AccountDetails.Read("Kimi Code", kimiAccount));
            else if (kimiStatus == "disabled") AddCard("KIMI CODE", "账户查询已关闭", "可在托盘菜单重新开启", null);
            else if (kimiStatus == "loading") AddCard("KIMI CODE", "正在读取额度", "正在查询账户", null);
            else if (kimiStatus is "unavailable" or "error") AddCard("KIMI CODE", "暂时无法获取额度", Reason(kimiAccount), null);

        }
        var claudeAccount = GetValue(otherAccounts, "Claude Code");
        var claudeQuotas = GetValue(GetValue(claudeAccount, "quota"), "value");
        if (claudeQuotas.ValueKind == JsonValueKind.Array)
        {
            var rows = new List<QuotaRow>();
            foreach (var q in claudeQuotas.EnumerateArray())
            {
                string bucket = GetString(q, "bucket", "");
                string label = bucket switch { "five_hour" => "5 小时", "seven_day" => "7 天", "seven_day_opus" => "7 天 · Opus", "seven_day_sonnet" => "7 天 · Sonnet", "seven_day_oauth_apps" => "7 天 · OAuth 应用", _ => bucket };
                double? remaining = GetNumber(q, "remaining_percent");
                rows.Add(new QuotaRow(label, remaining, QuotaResetClock.Read(q)));
            }
            if (rows.Count > 0) AddQuotaGroup("CLAUDE CODE", rows, GetValue(localHistories, "Claude Code"), AccountDetails.Read("Claude Code", claudeAccount), claudeAccount);
        }
        else if (GetString(claudeAccount, "status", "") == "disabled") AddCard("CLAUDE CODE", "账户查询已关闭", "可在托盘菜单重新开启", null);
        else if (GetString(claudeAccount, "status", "") == "loading") AddCard("CLAUDE CODE", "正在读取额度", "正在查询账户", null);
        else if (GetString(claudeAccount, "status", "") == "error") AddCard("CLAUDE CODE", "暂时无法获取额度", Reason(claudeAccount), null);
        else if (GetString(claudeAccount, "reason", "") is not ("" or "claude_subscription_login_missing"))
            AddCard("CLAUDE CODE", "暂时无法获取额度", Reason(claudeAccount), null);
        var minimaxAccount = GetValue(otherAccounts, "MiniMax Code");
        if (minimaxAccount.ValueKind == JsonValueKind.Array)
        {
            foreach (var accountRow in minimaxAccount.EnumerateArray())
                AddMiniMaxAccount(accountRow, GetString(accountRow, "label", "账户"));
        }
        else AddMiniMaxAccount(minimaxAccount, "");
        AddDeepSeekBalance(GetValue(otherAccounts, "DeepSeek API"));
        AddWorkBuddyAccount(GetValue(otherAccounts, "WorkBuddy"), GetValue(localHistories, "WorkBuddy"));
        AddZCodeAccount(GetValue(otherAccounts, "ZCode"), GetValue(localHistories, "ZCode"));
        AddVolcengineAccount(GetValue(otherAccounts, "Volcengine"));
        AddMiMoAccount(GetValue(otherAccounts, "MiMo"));
        AddQoderAccount(GetValue(otherAccounts, "Qoder CN"));
        AddTraeAccount(GetValue(otherAccounts, "TRAE CN"));
        AddQoderLocalCredits(GetValue(root, "local_credits"));
        foreach (var synced in SyncedQuota.Read(GetValue(root, "synced_quota")))
            AddQuotaGroup(synced.Heading, synced.Windows.Select(item => new QuotaRow(item.Label, item.Remaining, item.ResetAt)).ToList());
        FinishAccountGauges(root);
        gauges.ResumeLayout();
        if (focusedGaugeName is not null)
            gauges.Controls.OfType<QuotaGauge>().FirstOrDefault(gauge => gauge.Visible && gauge.Name == focusedGaugeName)?.Focus();
        }
        else if (view == View.Applications) AddApplications(root);
        else if (view == View.Usage)
        {
        AddUsagePeriodSelector();
        AddBudgetProgress(GetValue(root, "budget"));
        var history = GetValue(root, "history");
        if (history.ValueKind == JsonValueKind.Object)
        {
            AddUsageSummary(history);
            AddUsageSources(history);
            AddModelRanking(history);
            AddDailyTrend(GetValue(root, "daily_trend"));
            var exportData = new RoundedActionButton(theme) { Name = "usage-export-data", Text = "导出本机汇总 · JSON / CSV", Height = 42,
                Margin = new Padding(0, 0, 0, 12), ForeColor = Primary };
            exportData.FlatAppearance.BorderColor = theme.Border;
            exportData.Click += (_, _) => ExportUsageData(); content.Controls.Add(exportData);
            AddHeading("本机账本", GetString(root, "price_status", "") == "invalid"
                ? "自定义价格无法读取，已隐藏金额" : "按价格快照及自定义价格估算，不代表账单");
            int visible = 0;
            foreach (var item in history.EnumerateObject())
            {
                if (IsAbsent(item.Value)) continue;
                visible++;
                var periods = GetValue(GetValue(item.Value, "value"), "periods");
                var today = GetValue(GetValue(periods, usagePeriod), "totals"); var all = GetValue(GetValue(periods, "all"), "totals");
                var week = GetValue(GetValue(periods, "7d"), "totals"); var month = GetValue(GetValue(periods, "30d"), "totals");
                double? dayTokens = GetNumber(today, "total_tokens"), allTokens = GetNumber(all, "total_tokens");
                double? weekTokens = GetNumber(week, "total_tokens"), monthTokens = GetNumber(month, "total_tokens");
                var note = allTokens.HasValue && weekTokens.HasValue && monthTokens.HasValue
                    ? $"近 7 天 {FormatNumber(weekTokens.Value)}  ·  近 30 天 {FormatNumber(monthTokens.Value)}"
                    : allTokens.HasValue ? "累计 " + FormatNumber(allTokens.Value) + " tokens" : Reason(item.Value);
                string? extra = allTokens.HasValue && weekTokens.HasValue && monthTokens.HasValue ? "累计 " + FormatNumber(allTokens.Value) + " tokens" : null;
                if (GetString(item.Value, "status", "") == "partial")
                {
                    string detail = GetString(item.Value, "reason", "") == "opencode_v2_partial" ? "部分新版记录未计入" : "部分记录未读取";
                    if (extra is null) note += " · " + detail; else extra += " · " + detail;
                }
                var estimate = GetValue(GetValue(item.Value, "estimates"), usagePeriod);
                if (usagePeriod == "today" && estimate.ValueKind != JsonValueKind.Object) estimate = GetValue(item.Value, "estimate");
                string rawAmount = GetString(estimate, "amount_usd", "");
                string? costNote = null;
                if (decimal.TryParse(rawAmount, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var amount) && amount >= 0)
                {
                    string display = amount is > 0 and < 0.0001m ? "<$0.0001" : $"${amount:0.####}";
                    costNote = $"{UsagePeriodLabel} API 等价估算 {display} · 非账单" + (GetValue(estimate, "partial").ValueKind == JsonValueKind.True ? " · 不完整" : "");
                }
                AddCard(item.Name, dayTokens.HasValue ? FormatNumber(dayTokens.Value) + " " + UsagePeriodLabel : "暂无数据", note, null, extra, costNote);
            }
            if (visible == 0) AddCard("本机记录", "暂无数据", "未发现支持的会话记录", null);
        }
        AddCodexImageFiles(GetValue(root, "image_files"));
        var creditsHistory = GetValue(root, "local_credits");
        if (creditsHistory.ValueKind == JsonValueKind.Object)
        {
            bool headingShown = false;
            foreach (var item in creditsHistory.EnumerateObject())
            {
                if (IsAbsent(item.Value) || GetString(item.Value, "reason", "") == "history_no_usage_records") continue;
                if (!headingShown) { AddHeading("本机积分", "独立计量，不等于账户余额"); headingShown = true; }
                var periods = GetValue(GetValue(item.Value, "value"), "periods");
                var today = GetValue(GetValue(periods, usagePeriod), "totals");
                var all = GetValue(GetValue(periods, "all"), "totals");
                var week = GetValue(GetValue(periods, "7d"), "totals");
                var month = GetValue(GetValue(periods, "30d"), "totals");
                string todayCredits = GetString(today, "credits", "");
                string allCredits = GetString(all, "credits", "");
                string billed = GetString(all, "billable_credits", "");
                string weekly = GetString(week, "credits", "—"), monthly = GetString(month, "credits", "—");
                AddCard(item.Name + " · 本机积分消耗", todayCredits == "" ? "暂无数据" : todayCredits + " " + UsagePeriodLabel,
                        allCredits == "" ? Reason(item.Value) : $"近 7 天 {weekly} · 近 30 天 {monthly}", null,
                        allCredits == "" ? null : $"累计 {allCredits} · 计费 {billed}");
            }
        }
        }
        else if (view == View.Report) AddCalendarReport(GetValue(root, "calendar_report"));
        else if (view == View.Forecast) AddForecast(GetValue(root, "forecast"));
        else if (view == View.Pet) AddPetPage(root);
        else AddCollection(GetValue(root, "local_medals"), GetValue(root, "quota_cards"));
        content.ResumeLayout(); ResizeCards();
        if (view == View.Accounts)
        {
            if (resetToggleFocused) content.Controls.Find("account-reset-toggle", true).FirstOrDefault()?.Focus();
            content.AutoScrollPosition = new Point(0, previousTop);
        }
    }
    void AddCollection(JsonElement collection, JsonElement quotaCards)
    {
        AddHeading("收集册", "额度卡片与本机徽章分别计算");
        AddQuotaCards(quotaCards);
        AddHeading("本机徽章", "根据本机逐日账本计算，不同账本可能重叠");
        if (GetString(collection, "status", "") == "loading")
        { AddCard("本机徽章", "正在计算", "本机记录仍在扫描", null); return; }
        var medals = GetValue(collection, "medals");
        if (medals.ValueKind != JsonValueKind.Array || medals.GetArrayLength() == 0)
        {
            string note = GetString(collection, "image_status", "") == "incomplete" ? "部分图片文件未能统计，请稍后刷新" :
                GetValue(collection, "incomplete").ValueKind == JsonValueKind.True
                ? "部分账本未能读取，请稍后刷新" : "需要可读取的本机逐日用量账本";
            AddCard("本机徽章", "暂无可用记录", note, null);
            return;
        }
        var earned = GetNumber(collection, "earned"); var total = GetNumber(collection, "total");
        var sources = GetNumber(collection, "sources");
        AddCard("本机徽章", earned.HasValue && total.HasValue ? $"{earned:0} / {total:0} 已获得" : "正在计算",
                sources.HasValue ? $"基于 {sources:0} 个可读取来源" : "基于可读取来源", null);
        if (GetValue(collection, "incomplete").ValueKind == JsonValueKind.True)
            AddCard("读取范围", "部分记录不完整", "徽章只反映已读取的数据", null);
        if (GetString(collection, "cost_status", "") == "incomplete")
            AddCard("估算花费徽章", "数据不完整", "来源、逐日模型拆分或价格不完整，暂不计算", null);
        if (GetString(collection, "image_status", "") == "incomplete")
            AddCard("图片文件徽章", "数据不完整", "部分文件无法统计，暂不计算", null);
        foreach (var (category, title) in new[] { ("day_peak", "单日巅峰"), ("lifetime", "累计里程"),
            ("streak", "连续出勤"), ("apps", "多端并用"), ("record", "个人纪录"),
            ("cost_day", "单日估算花费"), ("cost_month", "月度估算花费"), ("cost_life", "累计估算价值"),
            ("img_day", "单日图片文件"), ("img_life", "累计图片文件"), ("img_streak", "连续图片文件") })
        {
            var rows = medals.EnumerateArray().Where(row => GetString(row, "category", "") == category).ToArray();
            if (rows.Length == 0) continue;
            AddHeading(title, category.StartsWith("img_", StringComparison.Ordinal) ? "按文件修改时间统计 · 不等于生成调用" :
                category.StartsWith("cost_", StringComparison.Ordinal) ? "按当前基础价格及固定汇率估算 · 非账单" :
                category == "streak" ? "当前连续天数与历史达成分别计算" : "按已读取的本机记录计算");
            foreach (var row in rows)
            {
                string name = GetString(row, "name", "徽章");
                double? value = GetNumber(row, "value"), target = GetNumber(row, "target"), progress = GetNumber(row, "progress");
                if (!value.HasValue || !target.HasValue || !progress.HasValue || !double.IsFinite(value.Value) ||
                    !double.IsFinite(target.Value) || !double.IsFinite(progress.Value) || value < 0 || target <= 0) continue;
                string unit = GetString(row, "unit", "") switch { "tokens" => "tokens", "days" => "天", "apps" => "个应用", "times" => "次", "cny" => "元", "images" => "个 PNG 文件", _ => "" };
                bool hasMedal = GetValue(row, "earned").ValueKind == JsonValueKind.True;
                string date = GetString(row, "earned_on", "");
                string detail = unit == "元" ? $"当前 {value.Value:0.##} / {target.Value:0.##} 元" : $"当前 {FormatNumber(value.Value)} / {FormatNumber(target.Value)} {unit}";
                string? dateNote = hasMedal && date.Length == 10 ? "达成于 " + date : null;
                AddMedalCard(name, GetString(row, "tier", "bronze"), hasMedal, detail, dateNote, Math.Clamp(progress.Value * 100, 0, 100));
            }
        }
        AddCard("尚在移植", "更多卡片与徽章", "签到、重置卡和创作积分等暂未计算", null);
    }

    void AddQuotaCards(JsonElement collection)
    {
        string status = GetString(collection, "status", "loading");
        if (status == "loading") { AddCard("额度卡片", "正在读取", "卡片进度保存在本机", null); return; }
        var cards = GetValue(collection, "cards");
        if (status != "available" || cards.ValueKind != JsonValueKind.Array)
        { AddCard("额度卡片", "暂时无法读取", "请检查设置目录并稍后重试", null); return; }
        var distinct = GetNumber(collection, "distinct");
        AddCard("额度卡片", distinct.HasValue ? $"{distinct:0} / {cards.GetArrayLength()} 种已收集" : "本机卡册",
                "额度窗口达到对应用量时掉落", null);
        var toggle = new RoundedActionButton(theme) { Text = showAllQuotaCards ? "只看已收集卡片" : "查看全部额度卡片", Height = 38,
            Margin = new Padding(0, 0, 0, 12), ForeColor = Primary };
        toggle.FlatAppearance.BorderColor = theme.Border;
        toggle.Click += (_, _) =>
        {
            var scroll = content.AutoScrollPosition;
            showAllQuotaCards = !showAllQuotaCards;
            if (lastSnapshot is not null) { using var snapshot = JsonDocument.Parse(lastSnapshot); Render(snapshot.RootElement); }
            content.PerformLayout();
            content.AutoScrollPosition = new Point(-scroll.X, -scroll.Y);
        };
        content.Controls.Add(toggle);
        foreach (var card in cards.EnumerateArray())
        {
            var count = GetNumber(card, "count");
            if (!count.HasValue || !double.IsFinite(count.Value) || count < 0 || (!showAllQuotaCards && count == 0)) continue;
            string tier = GetString(card, "rarity", "") switch { "rare" => "silver", "epic" => "gold", "legendary" => "platinum", _ => "bronze" };
            AddMedalCard(GetString(card, "name", "额度卡片"), tier, count > 0, $"已收集 {count:0} 张",
                         GetString(card, "description", ""), count > 0 ? 100 : 0);
        }
    }

    void AddApplications(JsonElement root)
    {
        AddHeading("应用概览", "额度、本机用量与活动记录分别统计");
        var activity = GetValue(root, "activity");
        var apps = ApplicationOverview.Build(root);
        var filters = new NavigationStrip { Name = "app-filter-selector", Height = 40, Margin = new Padding(0, 0, 0, 12), BackColor = Card };
        var buttons = new List<NavigationTab>();
        foreach (var (filter, label) in new[] { (ApplicationFilter.All, "全部"), (ApplicationFilter.Recent, "近期有更新"), (ApplicationFilter.Other, "其他") })
        {
            var button = new NavigationTab { Text = label, Name = "app-filter-" + filter, Font = tabRegular };
            button.SetAppearance(theme, applicationFilter == filter);
            button.Click += (_, _) => { applicationFilter = filter; if (lastSnapshot is not null) { using var snapshot = JsonDocument.Parse(lastSnapshot); Render(snapshot.RootElement); } };
            buttons.Add(button); filters.Controls.Add(button);
        }
        filters.Resize += (_, _) =>
        {
            int width = Math.Max(1, (filters.ClientSize.Width - 6) / 3);
            for (int index = 0; index < buttons.Count; index++) buttons[index].Bounds = new Rectangle(3 + index * width, 3, width, 34);
        };
        content.Controls.Add(filters);
        AddHeading("数据覆盖", "近 15 分钟有记录更新 ≠ 应用正在运行");
        if (GetString(activity, "status", "") == "partial")
            AddCard("读取范围", "部分来源不完整", "不同客户端的记录覆盖范围不同", null);
        var visible = apps.Where(app => applicationFilter == ApplicationFilter.All ||
            (applicationFilter == ApplicationFilter.Recent ? app.RecentUpdates > 0 : app.RecentUpdates == 0)).ToArray();
        if (visible.Length == 0)
        {
            string note = applicationFilter != ApplicationFilter.All ? "该筛选下暂无记录" :
                GetString(GetValue(GetValue(root, "history"), "历史统计"), "status", "") == "loading" ? "本机记录正在扫描" : "未发现可展示的数据，或来源暂不支持";
            AddCard("应用概览", "暂无数据", note, null); return;
        }
        foreach (var app in visible) AddApplicationCard(app);
    }
    void AddApplicationCard(ApplicationOverview app)
    {
        bool expanded = expandedApplications.Contains(app.Name);
        var identity = ProviderStyle.For(app.Name);
        var box = new RoundedCard(theme, identity.Color) { Height = expanded ? 196 : 88,
            Margin = new Padding(0, 0, 0, 12), BackColor = Card };
        box.Controls.Add(new ProviderMark(identity) { Location = new Point(16, 14), Size = new Size(34, 34) });
        var toggle = new Button { Name = "app-expand-" + app.Name, Text = app.Name + (expanded ? "  ▾" : "  ▸"),
            AccessibleName = (expanded ? "收起 " : "展开 ") + app.Name, Height = 29, Location = new Point(58, 10),
            FlatStyle = FlatStyle.Flat, BackColor = Color.Transparent, ForeColor = Primary, TextAlign = ContentAlignment.MiddleLeft,
            Font = new Font(Font.FontFamily, 10F, FontStyle.Bold) };
        toggle.FlatAppearance.BorderSize = 0;
        toggle.Click += (_, _) =>
        {
            var scroll = content.AutoScrollPosition;
            if (!expandedApplications.Add(app.Name)) expandedApplications.Remove(app.Name);
            if (lastSnapshot is not null) { using var snapshot = JsonDocument.Parse(lastSnapshot); Render(snapshot.RootElement); }
            content.PerformLayout(); content.AutoScrollPosition = new Point(-scroll.X, -scroll.Y);
        };
        string activityText = app.Activity.StartsWith("有记录", StringComparison.Ordinal) ? $"近 24 小时 {app.Sessions} 条 · 近 15 分钟更新 {app.RecentUpdates} 条" +
            (app.Activity.Contains("部分", StringComparison.Ordinal) ? " · 不完整" : "") : app.Activity;
        var subtitle = new Label { Text = activityText, Location = new Point(60, 45), Height = 22, ForeColor = Muted, AutoEllipsis = true };
        var today = new Label { Text = app.Today.HasValue ? "今日 " + FormatNumber(app.Today.Value) : "今日未提供",
            ForeColor = Accent, AutoSize = true, Font = new Font(Font.FontFamily, 9F, FontStyle.Bold), Location = new Point(0, 16) };
        box.Controls.AddRange([toggle, subtitle, today]);
        if (expanded)
        {
            string total = app.All.HasValue ? " · 累计 " + FormatNumber(app.All.Value) : "";
            string last = app.LastUpdated.HasValue ? " · 最后更新 " + DateTimeOffset.FromUnixTimeSeconds(app.LastUpdated.Value).LocalDateTime.ToString("MM-dd HH:mm") : "";
            box.Controls.Add(new Label { Name = "app-details-" + app.Name, Text = "账户额度：" + app.Quota + "\n本机 Token：" + app.Local + total + "\n活动记录：" + app.Activity + last + "\n本机记录不按登录账户区分", ForeColor = Muted,
                Location = new Point(16, 82), Height = 102, AutoEllipsis = true });
        }
        box.Resize += (_, _) =>
        {
            today.Left = Math.Max(58, box.ClientSize.Width - today.Width - 16);
            toggle.Width = Math.Max(0, today.Left - toggle.Left - 6);
            subtitle.Width = Math.Max(0, box.ClientSize.Width - 76);
            foreach (Control child in box.Controls) if (child.Name == "app-details-" + app.Name) child.Width = Math.Max(0, box.ClientSize.Width - 32);
        };
        StyleCard(box); content.Controls.Add(box);
    }
    void AddMiniMaxAccount(JsonElement account, string accountLabel)
    {
        string prefix = "MINIMAX CODE" + (accountLabel.Length > 0 ? " · " + accountLabel : "");
        var quotas = GetValue(GetValue(account, "quota"), "value");
        if (quotas.ValueKind == JsonValueKind.Array && quotas.GetArrayLength() > 0)
        {
            var rows = new List<QuotaRow>();
            foreach (var quota in quotas.EnumerateArray())
            {
                string label = GetString(quota, "bucket", "") switch { "5h" => "5 小时", "week" => "7 天", var other => other };
                double? remaining = GetNumber(quota, "remaining_percent");
                rows.Add(new QuotaRow(label, remaining, QuotaResetClock.Read(quota)));
            }
            AddQuotaGroup(prefix, rows, gaugeAccount: account);
        }
        else if (GetString(account, "status", "") == "loading")
            AddCard(prefix, "正在读取额度", "正在查询账户", null);
        else if (GetString(account, "status", "") is "unavailable" or "error")
            AddCard(prefix, "暂时无法获取额度", Reason(account), null);
        else if (GetString(account, "status", "") is "available" or "partial")
            AddCard(prefix, "额度未提供", "账户服务未返回可展示的额度窗口", null);
    }
    void AddDeepSeekBalance(JsonElement account)
    {
        string status = GetString(account, "status", "disabled");
        if (status == "disabled") return;
        if (status == "loading") { AddCard("DEEPSEEK API", "正在读取余额", "只查询账户余额，不调用模型", null); return; }
        var details = AccountDetails.Read("DeepSeek API", account);
        if (details.Amounts.Count > 0) { AddQuotaGroup("DEEPSEEK API", [], details: details); return; }
        string note = GetString(account, "reason", "") switch
        {
            "deepseek_credential_not_connected" => "请在托盘菜单设置 API 密钥",
            "deepseek_credential_invalid" => "密钥格式无效，请重新设置",
            _ => "请检查网络、密钥和账户状态后刷新"
        };
        AddCard("DEEPSEEK API", "暂时无法获取余额", note, null);
    }
    void AddWorkBuddyAccount(JsonElement account, JsonElement localHistory)
    {
        string status = GetString(account, "status", "disabled");
        if (status == "disabled") return;
        if (status == "loading") { AddCard("WORKBUDDY", "正在读取账户", "通过应用内独立登录资料查询", null); return; }
        var quota = GetValue(GetValue(account, "quota"), "value");
        if (status is "available" or "partial")
        {
            var details = AccountDetails.Read("WorkBuddy", account);
            var rows = new List<QuotaRow>();
            if (quota.ValueKind == JsonValueKind.Array)
                foreach (var item in quota.EnumerateArray())
                    rows.Add(new QuotaRow("积分额度", GetNumber(item, "remaining_percent"), QuotaResetClock.Read(item)));
            if (rows.Count > 0 || details.HasContent) { AddQuotaGroup("WORKBUDDY", rows, localHistory, details, account); return; }

        }
        string note = GetString(account, "reason", "") switch
        {
            "workbuddy_session_missing" => "请在托盘菜单登录 WorkBuddy",
            "workbuddy_runtime_missing" => "缺少 WebView2 Runtime，请安装后重试",
            "workbuddy_profile_unsafe" => "无法确认登录资料隔离，请检查 WebView2 系统策略",
            "workbuddy_session_unavailable" or "workbuddy_session_invalid" => "无法读取应用内登录资料，请重新登录",
            "not_authenticated" => "登录可能已过期，请重新登录",
            _ => "请检查登录状态和网络后刷新"
        };
        AddCard("WORKBUDDY", "暂时无法获取账户", note, null);
    }
    void AddCalendarReport(JsonElement report)
    {
        AddHeading("用量报告", "北京时间 · 本机账本相加，可能存在重叠");
        var periods = GetValue(report, "periods");
        if (periods.ValueKind != JsonValueKind.Object)
        {
            AddCard("自然周与自然月", "暂无可用报告", "需要可读取的本机逐日用量记录", null);
            return;
        }
        bool incomplete = GetValue(report, "incomplete").ValueKind == JsonValueKind.True;
        foreach (var (key, title, previous) in new[] { ("week", "本周", "上周"), ("month", "本月", "上月") })
        {
            var period = GetValue(periods, key);
            var current = GetNumber(period, "current_tokens"); var before = GetNumber(period, "previous_tokens");
            if (!current.HasValue || !before.HasValue) continue;
            string start = GetString(period, "current_start", ""), end = GetString(period, "current_end", "");
            string note = $"{previous} {FormatNumber(before.Value)} · 本期截至 {end}";
            string extra = $"本期开始 {start}" + (incomplete ? " · 部分来源不完整" : " · 当前周期未结束");
            AddCard(title, FormatNumber(current.Value) + " tokens", note, null, extra);
            var comparison = ReportComparison.Read(period);
            if (comparison is not null)
                AddCard(title + " · 已结束自然日对照", comparison.Change,
                    $"前 {comparison.Days} 天：本期 {FormatNumber(comparison.Current)} · 上期 {FormatNumber(comparison.Previous)}", null,
                    incomplete ? "部分来源不完整 · 当前日未计入" : "当前日未计入 · 按相同天数对齐");
        }
        AddCard("统计说明", "自然周期比较", "当前周期尚未结束；上期为完整周期", null,
                "仅覆盖本机可读取记录，不等于账户总量");
        var export = new RoundedActionButton(theme) { Text = "导出 Markdown 报告", Height = 42, Margin = new Padding(0, 0, 0, 12),
            ForeColor = Primary };
        export.FlatAppearance.BorderColor = theme.Border;
        export.Click += (_, _) => ExportCalendarReport();
        content.Controls.Add(export);
        var imageExport = new RoundedActionButton(theme) { Text = "导出报告分享图", Height = 42, Margin = new Padding(0, 0, 0, 12),
            ForeColor = Primary };
        imageExport.FlatAppearance.BorderColor = theme.Border;
        imageExport.Click += (_, _) => ExportShareImage();
        content.Controls.Add(imageExport);
    }
    void ExportCalendarReport()
    {
        try
        {
            if (lastSnapshot is null) throw new InvalidDataException("没有可导出的报告");
            using var snapshot = JsonDocument.Parse(lastSnapshot);
            string report = CalendarReportExport.Create(snapshot.RootElement, demo);
            using var dialog = new SaveFileDialog { Title = "导出本机用量报告", Filter = "Markdown 文件 (*.md)|*.md|文本文件 (*.txt)|*.txt",
                FileName = "AgentMeter-报告-" + DateTime.Now.ToString("yyyy-MM-dd") + ".md", AddExtension = true, OverwritePrompt = true };
            if (dialog.ShowDialog(this) != DialogResult.OK) return;
            File.WriteAllText(dialog.FileName, report, new System.Text.UTF8Encoding(false));
            status.Text = "报告已导出到所选位置";
        }
        catch (Exception ex) when (ex is InvalidDataException or IOException or UnauthorizedAccessException or JsonException or System.Security.SecurityException)
        {
            MessageBox.Show(this, ex is InvalidDataException ? ex.Message : "无法导出报告，请检查目标位置。",
                "导出未完成", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }
    void ExportUsageData()
    {
        try
        {
            if (lastSnapshot is null) throw new InvalidDataException("没有可导出的本机 Token 汇总");
            using var snapshot = JsonDocument.Parse(lastSnapshot);
            // 在打开保存窗口前先确认有数据，避免写出空文件。
            _ = UsageDataExport.Read(snapshot.RootElement);
            using var dialog = new SaveFileDialog { Title = "导出本机 Token 汇总", Filter = "JSON 文件 (*.json)|*.json|CSV 文件 (*.csv)|*.csv",
                FileName = "AgentMeter-本机汇总-" + DateTime.Now.ToString("yyyy-MM-dd"), AddExtension = true, OverwritePrompt = true };
            if (dialog.ShowDialog(this) != DialogResult.OK) return;
            string extension = Path.GetExtension(dialog.FileName);
            bool csv = extension.Equals(".csv", StringComparison.OrdinalIgnoreCase);
            if (!csv && !extension.Equals(".json", StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("请选择 .json 或 .csv 文件名");
            string data = csv ? UsageDataExport.Csv(snapshot.RootElement, demo) : UsageDataExport.Json(snapshot.RootElement, demo);
            // CSV 加 BOM，便于 Windows 版 Excel 正确识别中文；JSON 使用标准 UTF-8。
            File.WriteAllText(dialog.FileName, data, new System.Text.UTF8Encoding(csv));
            status.Text = "本机汇总已导出到所选位置";
        }
        catch (Exception ex) when (ex is InvalidDataException or IOException or UnauthorizedAccessException or JsonException or System.Security.SecurityException)
        { MessageBox.Show(this, ex is InvalidDataException ? ex.Message : "无法导出汇总，请检查目标位置。", "导出未完成", MessageBoxButtons.OK, MessageBoxIcon.Warning); }
    }
    void ExportShareImage()
    {
        try
        {
            if (lastSnapshot is null) throw new InvalidDataException("没有可导出的报告");
            using var snapshot = JsonDocument.Parse(lastSnapshot);
            using var image = ShareCardRenderer.Render(snapshot.RootElement, theme, demo);
            using var dialog = new SaveFileDialog { Title = "导出报告分享图", Filter = "PNG 图片 (*.png)|*.png",
                FileName = "AgentMeter-分享图-" + DateTime.Now.ToString("yyyy-MM-dd") + ".png", AddExtension = true, OverwritePrompt = true };
            if (dialog.ShowDialog(this) != DialogResult.OK) return;
            image.Save(dialog.FileName, System.Drawing.Imaging.ImageFormat.Png);
            status.Text = "报告分享图已导出到所选位置";
        }
        catch (Exception ex) when (ex is InvalidDataException or IOException or UnauthorizedAccessException or JsonException or System.Security.SecurityException or System.Runtime.InteropServices.ExternalException)
        {
            MessageBox.Show(this, ex is InvalidDataException ? ex.Message : "无法导出图片，请检查目标位置。",
                "导出未完成", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }
    void FinishAccountGauges(JsonElement root)
    {
        if (gauges.Controls.Count == 0)
        {
            var others = GetValue(root, "other_accounts");
            bool loading = GetString(GetValue(root, "account"), "status", "") == "loading" ||
                (others.ValueKind == JsonValueKind.Object && others.EnumerateObject().Any(item => GetString(item.Value, "status", "") == "loading"));
            gauges.Controls.Add(new Label { Text = loading ? "正在读取账户额度…" : "暂无可用周期额度", ForeColor = Muted, AutoSize = true, Margin = new Padding(5, 32, 0, 0) });
        }
        LayoutGauges();
    }
    void LayoutGauges()
    {
        var items = gauges.Controls.OfType<QuotaGauge>().ToArray();
        int pages = Math.Max(1, (items.Length + 3) / 4);
        gaugePage = Math.Clamp(gaugePage, 0, pages - 1);
        gaugePrevious.Visible = gaugeNext.Visible = view == View.Accounts && pages > 1;
        gaugePrevious.Enabled = gaugePage > 0; gaugeNext.Enabled = gaugePage + 1 < pages;
        int pageButtonTop = gauges.Top + 38;
        gaugePrevious.Location = new Point(1, pageButtonTop); gaugeNext.Location = new Point(Math.Max(0, header.ClientSize.Width - 21), pageButtonTop);
        if (items.Length == 0) return;
        int shown = Math.Min(4, items.Length - gaugePage * 4);
        int width = Math.Clamp(gauges.ClientSize.Width / Math.Max(1, shown) - 7, 70, 95);
        for (int index = 0; index < items.Length; index++)
        {
            items[index].Visible = index / 4 == gaugePage;
            items[index].Width = width;
        }
    }
    static string FormatNumber(double n) => n >= 1_000_000_000 ? $"{n / 1_000_000_000:0.##}B" : n >= 1_000_000 ? $"{n / 1_000_000:0.##}M" : n >= 1_000 ? $"{n / 1_000:0.##}K" : $"{n:0}";
    static JsonElement GetValue(JsonElement e, string key) => e.ValueKind == JsonValueKind.Object && e.TryGetProperty(key, out var v) ? v : default;
    static string GetString(JsonElement e, string key, string fallback) { var v = GetValue(e, key); return v.ValueKind == JsonValueKind.String ? v.GetString() ?? fallback : fallback; }
    static double? GetNumber(JsonElement e, string key) { var v = GetValue(e, key); return v.ValueKind == JsonValueKind.Number && v.TryGetDouble(out var n) ? n : null; }
    static bool IsAbsent(JsonElement e) => (GetString(e, "status", "") is "unavailable" or "not_provided") && GetString(e, "reason", "") is
        "codex_sessions_not_found" or "claude_projects_not_found" or "gemini_chats_not_found" or "workbuddy_projects_not_found" or
        "zcode_db_not_found" or "dsh_sessions_not_found" or "kimi_sessions_not_found" or "kimi_legacy_sessions_not_found" or
        "opencode_db_not_found" or "opencode_memory_database" or "mcode_db_not_found" or "mimocode_db_not_found" or "deveco_db_not_found" or "qoder_sessions_not_found";
    static string Reason(JsonElement e) => GetString(e, "reason", "") switch
    {
        "cli_not_available" => "未找到 Codex；请安装并登录后刷新",
        "rpc_timeout" => "账户查询超时，请稍后重试",
        "rpc_disconnected" => "Codex 服务未连接，请检查登录状态",
        "not_authenticated" => "账户登录已失效，请重新连接",
        "kimi_server_not_running" => "未发现运行中的 Kimi 本地服务",
        "kimi_server_token_invalid" => "Kimi 本地服务凭据不可用",
        "claude_token_expired" => "Claude Code 登录已过期，请在 Claude Code 中重新登录",
        "claude_not_logged_in" or "claude_subscription_login_missing" => "未找到 Claude Code 订阅登录",
        "minimax_credential_not_connected" => "请设置 MINIMAX_TOKEN_PLAN_KEY 并重启",
        "minimax_vault_credential_missing" => "凭据缺失或无法读取，请在账户管理中更新密钥",
        "minimax_profiles_invalid" => "账户列表无法读取，请备份并检查本地文件",
        "minimax_no_saved_accounts" => "尚未添加账户，请在托盘菜单管理 MiniMax 账户",
        "invalid_minimax_region" => "MiniMax 区域设置不正确（cn 或 global）",
        "history_loading" => "后台扫描中，请稍候",
        "history_no_usage_records" => "没有可统计的用量记录",
        "codex_sessions_not_found" or "claude_projects_not_found" or "gemini_chats_not_found" or "workbuddy_projects_not_found" or "zcode_db_not_found" or "dsh_sessions_not_found" => "未找到本机会话记录",
        "zstd_unavailable" => "部分压缩会话无法读取",
        "trae_session_missing" => "请在托盘菜单连接 TRAE 中国区",
        "trae_runtime_missing" => "请安装 WebView2 Runtime 后重试",
        "trae_profile_unsafe" => "无法确认登录资料隔离，请检查系统策略",
        "trae_session_unavailable" or "trae_session_invalid" => "应用内登录资料不可用，请重新连接",
        "unsupported_trae_contract" or "invalid_trae_pack" => "TRAE 账户接口数据暂不可用",
        "qoder_session_missing" => "请在托盘菜单连接 Qoder 中国区",
        "qoder_runtime_missing" => "请安装 WebView2 Runtime 后重试",
        "qoder_profile_unsafe" => "无法确认登录资料隔离，请检查系统策略",
        "qoder_session_unavailable" or "qoder_session_invalid" => "应用内登录资料不可用，请重新连接",
        "unsupported_qoder_web_contract" or "invalid_qoder_quota" => "Qoder 账户接口数据暂不可用",
        "unsupported_qoder_usage_schema" => "当前 Qoder 记录格式暂不支持",
        "opencode_v2_partial" => "部分新版记录暂未计入",
        "unsupported_opencode_schema" => "当前 OpenCode 数据格式暂不支持",
        _ => "未连接、未提供数据或读取失败"
    };
    void AddHeading(string title, string subtitle)
    {
        var box = new Panel { Height = 52, Margin = new Padding(0, 3, 0, 1), BackColor = Background };
        box.Controls.Add(new Label { Text = title, Font = new Font(Font.FontFamily, 11F, FontStyle.Bold), AutoSize = true, Location = new Point(3, 5), ForeColor = Primary });
        var note = new Label { Text = subtitle, AutoSize = false, AutoEllipsis = true, Height = 19, Font = new Font(Font.FontFamily, 8.5F), Location = new Point(3, 29), ForeColor = Muted };
        box.Controls.Add(note); box.Resize += (_, _) => note.Width = Math.Max(0, box.Width - 6); content.Controls.Add(box);
    }
    void AddUsageSummary(JsonElement history)
    {
        double total = 0; int sources = 0; bool complete = true; bool partial = false;
        double[] parts = new double[5];
        foreach (var item in history.EnumerateObject())
        {
            string status = GetString(item.Value, "status", "");
            if (status is "error" or "partial" || (status == "unavailable" && !IsAbsent(item.Value))) partial = true;
            if (status is not ("available" or "partial")) continue;
            var totals = GetValue(GetValue(GetValue(GetValue(item.Value, "value"), "periods"), usagePeriod), "totals");
            var amount = GetNumber(totals, "total_tokens");
            if (!amount.HasValue || !double.IsFinite(amount.Value) || amount.Value < 0) { partial = true; continue; }
            if (!double.IsFinite(total + amount.Value)) { partial = true; continue; }
            total += amount.Value; sources++;
            if (!UsageBreakdown.TryRead(totals, amount.Value, out var values)) complete = false;
            else for (int i = 0; i < parts.Length; i++)
            {
                parts[i] += values[i];
                if (!double.IsFinite(parts[i])) complete = false;
            }
        }
        if (sources == 0)
        {
            AddCard(UsagePeriodLabel + " Token 总量", "暂无数据", partial ? "部分来源读取失败或未提供该周期" : "没有可读取的本机用量汇总", null);
            return;
        }
        var summary = new TableLayoutPanel { Name = "usage-summary", ColumnCount = 2, RowCount = 1, Height = 124,
            Margin = new Padding(0, 0, 0, 12), BackColor = Background };
        summary.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50)); summary.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
        summary.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        var totalBox = new RoundedCard(theme) { Dock = DockStyle.Fill, Margin = new Padding(0, 0, 6, 0), BackColor = Card };
        var costBox = new RoundedCard(theme, theme.Accent) { Dock = DockStyle.Fill, Margin = new Padding(6, 0, 0, 0), BackColor = Card };
        var totalTitle = new Label { Text = UsagePeriodLabel + " Token 总量", Height = 22, AutoEllipsis = true, Font = new Font(Font.FontFamily, 9F, FontStyle.Bold), ForeColor = Muted, Location = new Point(15, 11) };
        var totalValue = new Label { Name = "usage-total", Text = FormatNumber(total), Height = 38, AutoEllipsis = true, Font = new Font(Font.FontFamily, 20F, FontStyle.Bold), ForeColor = Primary, Location = new Point(14, 34) };
        var totalNote = new Label { Text = $"{sources} 个账本相加" + (partial ? " · 不完整" : ""), Height = 20, AutoEllipsis = true,
            Font = new Font(Font.FontFamily, 8F), ForeColor = Muted, Location = new Point(15, 91) };
        totalBox.Controls.AddRange([totalTitle, totalValue, totalNote]);
        var cost = UsageCostSummary.Read(history, usagePeriod);
        var costTitle = new Label { Text = "API 等价估算", Top = 11, Left = 15, Height = 21, Font = new Font(Font.FontFamily, 9F, FontStyle.Bold), ForeColor = Muted, AutoEllipsis = true };
        var costValue = new Label { Name = "usage-cost-total", Text = cost.Display, Top = 36, Left = 14, Height = 32, Font = new Font(Font.FontFamily, 17F, FontStyle.Bold), ForeColor = Primary, AutoEllipsis = true };
        var costNote = new Label { Text = cost.Amount is null ? "非账单 · 暂无金额" : cost.Partial ? "非账单 · 部分未计入" : "非账单 · 本机价格表", Top = 91, Left = 15, Height = 20, Font = new Font(Font.FontFamily, 8F), ForeColor = Muted, AutoEllipsis = true };
        costBox.Controls.AddRange([costTitle, costValue, costNote]);
        popupTips.SetToolTip(costValue, cost.Display); popupTips.SetToolTip(totalValue, total.ToString("N0") + " Token");
        popupTips.SetToolTip(totalNote, totalNote.Text); popupTips.SetToolTip(costNote, costNote.Text);
        totalBox.Resize += (_, _) => totalTitle.Width = totalValue.Width = totalNote.Width = Math.Max(0, totalBox.ClientSize.Width - 30);
        costBox.Resize += (_, _) => costTitle.Width = costValue.Width = costNote.Width = Math.Max(0, costBox.ClientSize.Width - 30);
        StyleCard(totalBox); StyleCard(costBox); summary.Controls.Add(totalBox, 0, 0); summary.Controls.Add(costBox, 1, 0); content.Controls.Add(summary);
        if (complete && total > 0) AddUsageBreakdown(parts, partial);
        else if (complete && total == 0 && !partial) AddCard("用量构成", "本周期暂无 Token 消耗", "暂无可计算的构成比例", null);
        else if (complete && total == 0) AddCard("用量构成", "暂无法计算", "已读取来源为零，部分来源不完整", null);
        else AddCard("用量构成", "拆分数据不完整", "部分来源未提供一致的输入、输出或缓存拆分", null);
    }
    void AddUsageBreakdown(double[] parts, bool partial)
    {
        var box = new RoundedCard(theme) { Name = "usage-breakdown", Height = 216, Margin = new Padding(0, 0, 0, 12), BackColor = Card };
        var title = new Label { Text = "用量构成", AutoSize = true, Font = new Font(Font.FontFamily, 10F, FontStyle.Bold),
            ForeColor = Primary, Location = new Point(16, 12) };
        var note = new Label { Text = partial ? "部分来源不完整" : "已读取的本机账本", AutoSize = false, AutoEllipsis = true,
            Height = 20, TextAlign = ContentAlignment.MiddleRight, ForeColor = Muted, Font = new Font(Font.FontFamily, 8F), Top = 13 };
        var ring = new UsageCompositionRing(parts, theme) { Location = new Point(17, 51), Size = new Size(126, 126) };
        box.Controls.AddRange([title, note, ring]);
        string[] labels = ["新输入", "输出含推理", "缓存读取", "缓存写入", "未拆分"];
        var colors = UsagePalette.ColorsFor(theme);
        for (int i = 0; i < labels.Length; i++)
        {
            var dot = new Label { Text = "●", AutoSize = false, Size = new Size(16, 20), Location = new Point(157, 48 + i * 27), ForeColor = colors[i] };
            var name = new Label { Name = "usage-part-name-" + i, Text = labels[i], AutoSize = false, AutoEllipsis = true, Height = 20,
                Font = new Font(Font.FontFamily, 9F), Location = new Point(173, 48 + i * 27), ForeColor = Muted };
            var value = new Label { Name = "usage-part-" + i, Text = FormatNumber(parts[i]), AutoSize = false, AutoEllipsis = true,
                Height = 20, TextAlign = ContentAlignment.MiddleRight, Top = 48 + i * 27, ForeColor = Primary };
            popupTips.SetToolTip(value, labels[i] + " · " + parts[i].ToString("N0") + " Token");
            box.Resize += (_, _) => {
                value.Left = Math.Max(230, box.ClientSize.Width - 82); value.Width = Math.Max(0, box.ClientSize.Width - value.Left - 16);
                name.Width = Math.Max(0, value.Left - name.Left - 4);
            };
            box.Controls.AddRange([dot, name, value]);
        }
        box.Resize += (_, _) => { note.Left = Math.Max(145, box.ClientSize.Width - 160); note.Width = Math.Max(0, box.ClientSize.Width - note.Left - 16); };
        var formula = new Label { Text = parts[4] > 0 ? "存在未拆分 Token，缓存命中未知" : UsageBreakdown.CacheHitRate(parts).HasValue
                ? "缓存命中 = 缓存读取 ÷ 已分类输入" : "没有可计算的输入，缓存命中未知",
            AutoSize = false, AutoEllipsis = true, Height = 18, Location = new Point(17, 188), ForeColor = Muted,
            Font = new Font(Font.FontFamily, 8F) };
        box.Resize += (_, _) => formula.Width = Math.Max(0, box.ClientSize.Width - 34); box.Controls.Add(formula);
        popupTips.SetToolTip(ring, "缓存命中 = 缓存读取 ÷（新输入 + 缓存读取 + 缓存写入）；未拆分数据存在时不计算");
        StyleCard(box); content.Controls.Add(box);
    }
    void AddDailyTrend(JsonElement trend)
    {
        var days = GetValue(trend, "days");
        if (days.ValueKind != JsonValueKind.Array) return;
        var points = new List<(string Date, double Tokens)>();
        foreach (var day in days.EnumerateArray())
        {
            string date = GetString(day, "date", ""); var tokens = GetNumber(day, "tokens");
            if (date.Length != 10 || !tokens.HasValue || tokens.Value < 0) return;
            points.Add((date, tokens.Value));
        }
        if (points.Count != 7) return;
        var box = new RoundedCard(theme) { Height = 218, Margin = new Padding(0, 0, 0, 12), BackColor = Card };
        box.Controls.Add(new Label { Text = "最近 7 个自然日", AutoSize = true, Font = new Font(Font.FontFamily, 10F, FontStyle.Bold), ForeColor = Primary, Location = new Point(15, 10) });
        bool incomplete = GetValue(trend, "incomplete").ValueKind == JsonValueKind.True;
        box.Controls.Add(new Label { Text = incomplete ? "北京时间 · 部分记录不完整" : "北京时间 · 本机账本相加", AutoSize = true, ForeColor = Muted, Location = new Point(16, 38) });
        var chart = new DailyChart(points, theme) { Location = new Point(14, 70), Height = 132 };
        box.Resize += (_, _) => chart.Width = Math.Max(0, box.ClientSize.Width - 28); box.Controls.Add(chart);
        StyleCard(box); content.Controls.Add(box);
    }
    sealed record QuotaRow(string Name, double? Remaining, long? ResetEpoch);

    void AddMedalCard(string name, string tier, bool earned, string detail, string? date, double progress)
    {
        var box = new RoundedCard(theme) { Height = date is null ? 112 : 136, Margin = new Padding(0, 0, 0, 12), BackColor = Card };
        var badge = new MedalBadge(theme, tier, earned) { Location = new Point(16, 20), Size = new Size(58, 58),
            AccessibleName = name + (earned ? "，已获得" : "，待解锁") };
        var title = new Label { Text = name, AutoEllipsis = true, Height = 21, Font = new Font(Font.FontFamily, 10F, FontStyle.Bold),
            ForeColor = Muted, Location = new Point(85, 11) };
        var state = new Label { Text = earned ? "已获得" : "待解锁", AutoSize = true, Font = new Font(Font.FontFamily, 14F, FontStyle.Bold),
            ForeColor = Primary, Location = new Point(84, 31) };
        var note = new Label { Text = detail, AutoEllipsis = true, Height = 21, ForeColor = Muted, Location = new Point(85, 84) };
        var bar = new MeterBar(theme) { Value = progress, Location = new Point(85, 70), Height = 5 };
        box.Controls.AddRange([badge, title, state, note, bar]);
        Label? dateLabel = date is null ? null : new Label { Text = date, AutoEllipsis = true, Height = 21, ForeColor = Muted, Location = new Point(85, 108) };
        if (dateLabel is not null) box.Controls.Add(dateLabel);
        box.Resize += (_, _) =>
        {
            title.Width = note.Width = bar.Width = Math.Max(0, box.ClientSize.Width - 101);
            if (dateLabel is not null) dateLabel.Width = note.Width;
        };
        StyleCard(box); content.Controls.Add(box);
    }

    void AddQuotaGroup(string provider, IReadOnlyList<QuotaRow> rows, JsonElement localHistory = default, AccountDetails? details = null, JsonElement gaugeAccount = default)
    {
        int shown = Math.Min(rows.Count, 40);
        details ??= AccountDetails.Empty;
        if (shown == 0 && !details.HasContent) return;
        int headingHeight = details.Plan is null ? 49 : 63;
        const int rowHeight = 57;
        var identity = ProviderStyle.For(provider);
        var box = new RoundedCard(theme, identity.Color) { Name = "account-" + provider, Height = headingHeight + shown * rowHeight, Margin = new Padding(0, 0, 0, 12), BackColor = Card };
        box.Controls.Add(new ProviderMark(identity) { Location = new Point(16, 13), Size = new Size(34, 34) });
        var heading = new Label { Text = identity.DisplayName, AutoEllipsis = true, Height = 25,
            Font = new Font(Font.FontFamily, 11F, FontStyle.Bold), ForeColor = Primary, Location = new Point(60, 19) };
        box.Controls.Add(heading);
        if (details.Plan is not null)
        {
            heading.Top = 12;
            var plan = new Label { Text = details.Plan + " · 账户套餐", Left = 60, Top = 37, Height = 21,
                Font = new Font(Font.FontFamily, 9), ForeColor = Muted, AutoEllipsis = true };
            box.Controls.Add(plan); box.Resize += (_, _) => plan.Width = Math.Max(0, box.Width - 76);
        }
        box.Resize += (_, _) => heading.Width = Math.Max(0, box.ClientSize.Width - heading.Left - 16);
        for (int index = 0; index < shown; index++)
        {
            var row = rows[index];
            int top = headingHeight + index * rowHeight;
            string label = new string(row.Name.Where(c => !char.IsControl(c)).Take(80).ToArray());
            if (label.Length == 0) label = "额度窗口";
            var name = new Label { Text = label, AutoEllipsis = true, Height = 21, ForeColor = Muted, Location = new Point(16, top) };
            double? remaining = row.Remaining is double number && double.IsFinite(number) && number >= 0 && number <= 100 ? number : null;
            var amount = new Label { Text = remaining.HasValue ? $"{remaining:0.#}% 剩余" : "额度未提供", AutoSize = true,
                Font = new Font(Font.FontFamily, 10F, FontStyle.Bold), ForeColor = remaining.HasValue ? MeterBar.ValueColor(theme, remaining.Value) : Muted, Location = new Point(0, top) };
            var note = new Label { Text = QuotaResetClock.Detail(row.ResetEpoch, ForecastNow), AutoSize = true, Font = new Font(Font.FontFamily, 9F), ForeColor = Muted, Location = new Point(16, top + 30) };
            var bar = new MeterBar(theme) { Value = remaining ?? 0, Visible = remaining.HasValue, Location = new Point(16, top + 21), Height = 5 };
            quotaResetLabels.Add((note, row.ResetEpoch));
            box.Controls.AddRange([name, amount, note, bar]);
            box.Resize += (_, _) =>
            {
                amount.Left = Math.Max(16, box.ClientSize.Width - amount.Width - 16);
                name.Width = Math.Max(0, amount.Left - name.Left - 8);
                bar.Width = Math.Max(0, box.ClientSize.Width - 32);
            };
        }
        var usage = AccountLocalUsage.Read(localHistory);
        if (usage is not null) box.Height += AddLocalUsageSummary(box, box.Height, usage, identity.Color);
        box.Height += AddAccountDetails(box, box.Height, details);
        StyleCard(box); content.Controls.Add(box);
        if (QuotaWindows.Select(gaugeAccount) is { } windows)
        {
            // 圆环直接关联本次渲染的卡片，同名账户也不会按文字误跳到第一张。
            var gauge = new QuotaGauge(identity.DisplayName, windows, theme, demo ? ForecastDemoNow : null)
                { Name = "gauge-" + provider };
            gauge.Click += (_, _) => {
                int top = box.Top - content.AutoScrollPosition.Y;
                content.AutoScrollPosition = new Point(0, Math.Max(0, top - content.Padding.Top));
                scrollRail?.Invalidate();
            };
            popupTips.SetToolTip(gauge, gauge.AccessibleName + "\n查看账户明细");
            gauges.Controls.Add(gauge);
        }
        if (rows.Count > shown) AddCard(provider, "部分额度未显示", $"仅展示前 {shown} 个窗口", null);
    }

    void AddCard(string name, string value, string detail, double? progress, string? extra = null, string? cost = null)
    {
        var box = new RoundedCard(theme) { Height = progress.HasValue ? 112 : cost is not null ? (extra is null ? 120 : 146) : extra is null ? 95 : 120, Margin = new Padding(0, 0, 0, 12), BackColor = Card };
        box.Controls.Add(new Label { Text = name, AutoSize = true, Font = new Font(Font.FontFamily, 10F, FontStyle.Bold), ForeColor = Muted, Location = new Point(15, 11) });
        box.Controls.Add(new Label { Text = value, AutoSize = true, Font = new Font(Font.FontFamily, 14F, FontStyle.Bold), ForeColor = Primary, Location = new Point(14, 31) });
        box.Controls.Add(new Label { Text = detail, AutoSize = true, ForeColor = Muted, Location = new Point(16, progress.HasValue ? 84 : 67) });
        if (extra is not null) box.Controls.Add(new Label { Text = extra, AutoSize = true, ForeColor = Muted, Location = new Point(16, 91) });
        if (cost is not null) box.Controls.Add(new Label { Text = cost, AutoSize = true, ForeColor = Accent, Location = new Point(16, extra is null ? 91 : 115) });
        if (progress.HasValue)
        {
            var bar = new MeterBar(theme) { Value = Math.Clamp(progress.Value, 0, 100), Location = new Point(16, 70), Height = 5 };
            box.Resize += (_, _) => bar.Width = Math.Max(0, box.ClientSize.Width - 32);
            box.Controls.Add(bar);
        }
        StyleCard(box); content.Controls.Add(box);
    }
    static void StyleCard(RoundedCard box)
    {
        foreach (Control child in box.Controls)
            if (child is Label) child.BackColor = Color.Transparent;
    }
    void ResizeCards() { foreach (Control c in content.Controls) c.Width = Math.Max(280, contentViewport.ClientSize.Width - 28); }
    const string DemoData = """
    {"account":{"status":"available","quota":{"value":[{"bucket":"codex","window":"primary","window_minutes":300,"remaining_percent":73,"resets_at":{"epoch_seconds":1794654000}},{"bucket":"codex","window":"secondary","window_minutes":10080,"remaining_percent":46,"resets_at":{"epoch_seconds":1794913200}}]}},"other_accounts":{"Kimi Code":{"status":"available","quota":{"value":[{"bucket":"limit5h","remaining_percent":64,"resets_at":{"epoch_seconds":1794654000}}]},"credits":{"value":{"amount":"12.34","unit":"CNY"}}},"Claude Code":{"status":"available","quota":{"value":[{"bucket":"five_hour","window_minutes":300,"remaining_percent":82,"resets_at":{"epoch_seconds":1794654000}},{"bucket":"seven_day","window_minutes":10080,"remaining_percent":53,"resets_at":{"epoch_seconds":1794913200}}]}},"MiniMax Code":{"status":"available","quota":{"value":[{"bucket":"5h","remaining_percent":55,"resets_at":{"epoch_seconds":1794654000}}]}}},"history":{"Codex":{"status":"available","value":{"periods":{"today":{"totals":{"total_tokens":1426000,"fresh_input":300000,"output":126000,"reasoning":0,"cache_read":1000000,"cache_write":0}},"7d":{"totals":{"total_tokens":7600000},"groups":[{"model":"gpt-5.3-codex","total_tokens":6200000},{"model":"gpt-5.1-codex","total_tokens":1400000}]},"30d":{"totals":{"total_tokens":25800000}},"all":{"totals":{"total_tokens":102000000}}}},"estimate":{"amount_usd":"2.464","partial":false}},"Claude Code":{"status":"available","value":{"periods":{"today":{"totals":{"total_tokens":341000,"fresh_input":100000,"output":41000,"reasoning":0,"cache_read":200000,"cache_write":0}},"7d":{"totals":{"total_tokens":900000},"groups":[{"model":"claude-sonnet-4","total_tokens":900000}]},"30d":{"totals":{"total_tokens":2400000}},"all":{"totals":{"total_tokens":3800000}}}}},"Gemini CLI":{"status":"unavailable","reason":"gemini_chats_not_found"}},"local_credits":{"Qoder CN":{"status":"available","value":{"periods":{"today":{"totals":{"credits":"12.5"}},"7d":{"totals":{"credits":"75"}},"30d":{"totals":{"credits":"248"}},"all":{"totals":{"credits":"560","billable_credits":"420"}}}}}},"daily_trend":{"days":[{"date":"2026-11-08","tokens":340000},{"date":"2026-11-09","tokens":780000},{"date":"2026-11-10","tokens":1120000},{"date":"2026-11-11","tokens":550000},{"date":"2026-11-12","tokens":970000},{"date":"2026-11-13","tokens":1300000},{"date":"2026-11-14","tokens":1767000}],"sources":2,"incomplete":false},"calendar_report":{"periods":{"week":{"previous_start":"2026-11-02","current_start":"2026-11-09","current_end":"2026-11-14","previous_tokens":4200000,"current_tokens":6367000},"month":{"previous_start":"2026-10-01","current_start":"2026-11-01","current_end":"2026-11-14","previous_tokens":14200000,"current_tokens":8200000}},"sources":2,"incomplete":false,"timezone":"Asia/Shanghai"},"activity":{"status":"available","window_hours":24,"idle_minutes":15,"apps":[{"name":"Codex","sessions":5,"recent_updates":2,"last_updated":1794650400},{"name":"Claude Code","sessions":2,"recent_updates":0,"last_updated":1794643200}]}}
    """;
}
internal sealed class RoundedCard : Panel
{
    readonly VisualTheme theme;
    readonly Color? providerColor;
    bool clipCorners;
    public bool ClipCorners { get => clipCorners; set { clipCorners = value; ApplyClip(); } }
    public RoundedCard(VisualTheme theme, Color? providerColor = null) { this.theme = theme; this.providerColor = providerColor; DoubleBuffered = true; }
    static Color Mix(Color original, Color tint, double weight) => Color.FromArgb(
        (int)Math.Round(original.R * (1 - weight) + tint.R * weight),
        (int)Math.Round(original.G * (1 - weight) + tint.G * weight),
        (int)Math.Round(original.B * (1 - weight) + tint.B * weight));
    protected override void OnResize(EventArgs e)
    {
        base.OnResize(e);
        ApplyClip();
        Invalidate();
    }
    void ApplyClip()
    {
        if (!clipCorners || Width < 28 || Height < 28) return;
        using var shape = new System.Drawing.Drawing2D.GraphicsPath();
        int r = 28, w = Width, h = Height;
        shape.AddArc(0, 0, r, r, 180, 90); shape.AddArc(w - r, 0, r, r, 270, 90);
        shape.AddArc(w - r, h - r, r, r, 0, 90); shape.AddArc(0, h - r, r, r, 90, 90); shape.CloseFigure();
        var previous = Region; Region = new Region(shape); previous?.Dispose();
    }
    protected override void OnPaintBackground(PaintEventArgs e)
    {
        if (ClientRectangle.Width <= 0 || ClientRectangle.Height <= 0) return;
        Color start = providerColor.HasValue ? Mix(theme.Card, providerColor.Value, theme.Light ? .07 : .11) : theme.Card;
        Color end = providerColor.HasValue ? Mix(theme.CardEnd, providerColor.Value, theme.Light ? .025 : .035) : theme.CardEnd;
        if (clipCorners && Parent is RoundedCard parent)
        {
            // 子卡片的边角延续父卡片的渐变，而不是填充一块纯色矩形。
            var state = e.Graphics.Save();
            e.Graphics.TranslateTransform(-Left, -Top);
            InvokePaintBackground(parent, e);
            e.Graphics.Restore(state);
        }
        else e.Graphics.Clear(Parent?.BackColor ?? theme.Background);
        if (Width < 28 || Height < 28) return;
        e.Graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
        using var shape = new System.Drawing.Drawing2D.GraphicsPath();
        int r = 28, w = Width - 1, h = Height - 1;
        shape.AddArc(0, 0, r, r, 180, 90); shape.AddArc(w - r, 0, r, r, 270, 90);
        shape.AddArc(w - r, h - r, r, r, 0, 90); shape.AddArc(0, h - r, r, r, 90, 90); shape.CloseFigure();
        using var fill = new System.Drawing.Drawing2D.LinearGradientBrush(ClientRectangle, start, end, 90F);
        e.Graphics.FillPath(fill, shape);
    }
    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        if (theme.Minimal || Width < 22 || Height < 22) return;
        e.Graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
        using var border = new Pen(providerColor.HasValue ? Mix(theme.Border, providerColor.Value, theme.Light ? .25 : .38) : theme.Border);
        using var path = new System.Drawing.Drawing2D.GraphicsPath();
        int r = 28, w = Width - 1, h = Height - 1;
        path.AddArc(0, 0, r, r, 180, 90); path.AddArc(w - r, 0, r, r, 270, 90);
        path.AddArc(w - r, h - r, r, r, 0, 90); path.AddArc(0, h - r, r, r, 90, 90); path.CloseFigure();
        e.Graphics.DrawPath(border, path);
    }
}
internal sealed class MeterBar : Control
{
    readonly VisualTheme theme;
    public MeterBar(VisualTheme theme)
    {
        this.theme = theme;
        SetStyle(ControlStyles.SupportsTransparentBackColor, true);
        BackColor = Color.Transparent; DoubleBuffered = true;
    }
    public double Value { get; set; }
    public static Color ValueColor(VisualTheme theme, double value) => value < 20
        ? (theme.Light ? Color.FromArgb(174, 42, 63) : Color.FromArgb(255, 111, 128))
        : value < 50 ? (theme.Light ? Color.FromArgb(153, 88, 0) : Color.FromArgb(255, 177, 70)) : theme.Accent;
    protected override void OnPaint(PaintEventArgs e)
    {
        if (Width <= 0 || Height <= 0) return;
        e.Graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
        using var track = new SolidBrush(theme.Border);
        using var path = Pill(new RectangleF(0, 0, Width, Height));
        e.Graphics.FillPath(track, path);
        float length = (float)(Width * Math.Clamp(Value, 0, 100) / 100);
        if (length <= 0) return;
        Color end = ValueColor(theme, Value);
        Color start = theme.Minimal ? end : Value < 50 ? (theme.Light ? Color.FromArgb(181, 55, 67) : Color.FromArgb(255, 113, 109))
                                 : (theme.Light ? Color.FromArgb(32, 110, 150) : Color.FromArgb(53, 192, 231));
        var rectangle = new RectangleF(0, 0, Math.Max(1, length), Height);
        using var fill = new System.Drawing.Drawing2D.LinearGradientBrush(rectangle, start, end, 0F);
        using var progress = Pill(rectangle);
        e.Graphics.FillPath(fill, progress);
    }
    static System.Drawing.Drawing2D.GraphicsPath Pill(RectangleF rectangle)
    {
        float diameter = Math.Min(rectangle.Height, rectangle.Width);
        var path = new System.Drawing.Drawing2D.GraphicsPath();
        path.AddArc(rectangle.X, rectangle.Y, diameter, rectangle.Height, 90, 180);
        path.AddArc(rectangle.Right - diameter, rectangle.Y, diameter, rectangle.Height, 270, 180);
        path.CloseFigure(); return path;
    }
}
/// <summary>手绘窄箭头，避免系统按钮的文字边距将分页入口挤出面板。</summary>
internal sealed class GaugePageButton(bool forward) : Button
{
    protected override void OnPaint(PaintEventArgs e)
    {
        e.Graphics.Clear(BackColor);
        e.Graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
        Color color = Enabled ? ForeColor : Color.FromArgb(80, ForeColor);
        using var pen = new Pen(color, 2F) { StartCap = System.Drawing.Drawing2D.LineCap.Round, EndCap = System.Drawing.Drawing2D.LineCap.Round,
            LineJoin = System.Drawing.Drawing2D.LineJoin.Round };
        float middle = Height / 2F, center = Width / 2F;
        float direction = forward ? 1 : -1;
        e.Graphics.DrawLines(pen, [new PointF(center - direction * 3, middle - 5), new PointF(center + direction * 2, middle),
            new PointF(center - direction * 3, middle + 5)]);
        if (Focused && ShowFocusCues) ControlPaint.DrawFocusRectangle(e.Graphics, new Rectangle(2, 4, Width - 4, Height - 8));
    }
}

internal sealed class QuotaGauge : Button
{
    readonly string provider;
    readonly QuotaWindowPair windows;
    readonly VisualTheme theme;
    readonly DateTimeOffset? referenceNow;
    public QuotaGauge(string provider, QuotaWindowPair windows, VisualTheme theme, DateTimeOffset? referenceNow = null)
    {
        this.provider = provider; this.windows = windows; this.theme = theme; this.referenceNow = referenceNow;
        Size = new Size(95, 116); Margin = new Padding(0, 0, 7, 0);
        FlatStyle = FlatStyle.Flat; FlatAppearance.BorderSize = 0;
        UseVisualStyleBackColor = false; BackColor = theme.Background; Cursor = Cursors.Hand;
        AccessibleDescription = "查看此账户的额度明细";
        AccessibleName = $"{provider} {windows.Primary.Label}，剩余 {windows.Primary.Remaining:0.#}%" +
            (windows.Secondary is null ? "" : $"；{windows.Secondary.Label}，剩余 {windows.Secondary.Remaining:0.#}%");
        DoubleBuffered = true;
    }
    protected override void OnPaint(PaintEventArgs e)
    {
        e.Graphics.Clear(BackColor);
        e.Graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
        void Ring(Rectangle rect, double remaining, Color normal)
        {
            using var track = new Pen(theme.Border, 5);
            Color color = remaining < 20 ? (theme.Light ? Color.FromArgb(181, 51, 71) : Color.FromArgb(255, 98, 135)) :
                remaining < 50 ? (theme.Light ? Color.FromArgb(160, 96, 0) : Color.FromArgb(255, 169, 58)) : normal;
            using var fill = new Pen(color, 5);
            fill.StartCap = fill.EndCap = System.Drawing.Drawing2D.LineCap.Round;
            e.Graphics.DrawArc(track, rect, -90, 359);
            if (remaining > 0)
            {
                float sweep = (float)(3.59 * remaining);
                if (theme.Id is "aurora" or "neon" or "prism")
                {
                    using var halo = new Pen(Color.FromArgb(22, color), 11) { StartCap = System.Drawing.Drawing2D.LineCap.Round, EndCap = System.Drawing.Drawing2D.LineCap.Round };
                    using var glow = new Pen(Color.FromArgb(45, color), 8) { StartCap = System.Drawing.Drawing2D.LineCap.Round, EndCap = System.Drawing.Drawing2D.LineCap.Round };
                    e.Graphics.DrawArc(halo, rect, -90, sweep); e.Graphics.DrawArc(glow, rect, -90, sweep);
                }
                e.Graphics.DrawArc(fill, rect, -90, sweep);
            }
        }
        int left = Math.Max(0, (Width - 60) / 2);
        var outer = new Rectangle(left, 4, 60, 60); Ring(outer, windows.Primary.Remaining, theme.Accent);
        if (windows.Secondary is not null)
            Ring(new Rectangle(left + 8, 12, 44, 44), windows.Secondary.Remaining,
                theme.Light ? Color.FromArgb(103, 75, 159) : Color.FromArgb(178, 145, 255));
        string valueText = $"{windows.Primary.Remaining:0.#}%";
        using var valueFont = new Font(Font.FontFamily, valueText.Length > 4 ? 8F : 9F, FontStyle.Bold);
        using var small = new Font(Font.FontFamily, 7.5F);
        using var accountNameFont = new Font(Font.FontFamily, 8F);
        const TextFormatFlags centered = TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter |
            TextFormatFlags.SingleLine | TextFormatFlags.NoPrefix | TextFormatFlags.NoPadding;
        var secondary = windows.Secondary;
        TextRenderer.DrawText(e.Graphics, valueText, valueFont, new Rectangle(left + 8, secondary is null ? 18 : 15, 44, secondary is null ? 32 : 23), theme.Primary, centered);
        if (secondary is not null)
            TextRenderer.DrawText(e.Graphics, windows.Primary.Label, small, new Rectangle(left + 8, 36, 44, 15), theme.Secondary, centered);
        const string aliasPrefix = "MiniMax Code · ";
        string displayName = provider.StartsWith(aliasPrefix, StringComparison.Ordinal) ? provider[aliasPrefix.Length..] :
            provider switch { "MiniMax Code" => "MiniMax", "Kimi Code" => "Kimi", "Claude Code" => "Claude",
                "Qoder CN · 账户额度" => "Qoder CN", "TRAE CN · 账户额度" => "TRAE CN", _ => provider };
        TextRenderer.DrawText(e.Graphics, displayName, displayName.Length > 9 ? accountNameFont : Font,
            new Rectangle(0, 66, Width, 19), theme.Primary, centered | TextFormatFlags.EndEllipsis);
        string period = secondary is null ? windows.Primary.Label : $"{secondary.Label} · {secondary.Remaining:0.#}%";
        TextRenderer.DrawText(e.Graphics, period, small, new Rectangle(0, 84, Width, 16), theme.Secondary, centered | TextFormatFlags.EndEllipsis);
        TextRenderer.DrawText(e.Graphics, QuotaResetClock.Short(windows.Primary.ResetAt, referenceNow ?? DateTimeOffset.UtcNow),
            small, new Rectangle(0, 100, Width, 16), theme.Secondary, centered | TextFormatFlags.EndEllipsis);
        if (Focused && ShowFocusCues)
            ControlPaint.DrawFocusRectangle(e.Graphics, Rectangle.Inflate(ClientRectangle, -2, -2), theme.Primary, BackColor);
    }
}
internal sealed class DailyChart : Control
{
    readonly IReadOnlyList<(string Date, double Tokens)> points;
    readonly VisualTheme theme;
    public DailyChart(IReadOnlyList<(string Date, double Tokens)> points, VisualTheme theme)
    {
        this.points = points; this.theme = theme; DoubleBuffered = true; AccessibleRole = AccessibleRole.Graphic;
        SetStyle(ControlStyles.SupportsTransparentBackColor, true); BackColor = Color.Transparent;
        AccessibleName = "最近七个自然日 Token：" + string.Join("，", points.Select(p => $"{p.Date} {p.Tokens:0}"));
    }
    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        e.Graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
        double maximum = Math.Max(1, points.Max(p => p.Tokens));
        int slot = Math.Max(1, Width / points.Count), baseline = Height - 28, top = 22;
        using var guide = new Pen(theme.Border);
        using var fill = new SolidBrush(theme.Accent);
        using var small = new Font(Font.FontFamily, 8F);
        string peak = maximum >= 1_000_000 ? $"{maximum / 1_000_000:0.##}M" : maximum >= 1_000 ? $"{maximum / 1_000:0.##}K" : $"{(points.Max(p => p.Tokens)):0}";
        TextRenderer.DrawText(e.Graphics, "单日最高 " + peak, small, new Point(0, 0), theme.Secondary);
        e.Graphics.DrawLine(guide, 0, baseline, Width, baseline);
        for (int i = 0; i < points.Count; i++)
        {
            var point = points[i]; int barHeight = (int)Math.Round((baseline - top) * point.Tokens / maximum);
            int barWidth = Math.Max(4, Math.Min(24, slot / 2)), x = i * slot + (slot - barWidth) / 2;
            if (barHeight > 0) e.Graphics.FillRectangle(fill, x, baseline - barHeight, barWidth, barHeight);
            var labelArea = new Rectangle(i * slot, baseline + 5, slot, 20);
            TextRenderer.DrawText(e.Graphics, point.Date[5..].Replace('-', '/'), small, labelArea,
                theme.Secondary, TextFormatFlags.HorizontalCenter | TextFormatFlags.EndEllipsis | TextFormatFlags.NoPadding);
        }
    }
}
/// <summary>本地只读工作进程在刷新之间保留已解析的用量缓存。</summary>
internal sealed class HistoryWorker : IDisposable
{
    Process? process;
    public async Task<string> RefreshAsync(CancellationToken shutdown)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(shutdown);
        timeout.CancelAfter(TimeSpan.FromMinutes(10));
        try
        {
            if (process is null || process.HasExited)
            {
                Stop();
                var path = Path.Combine(AppContext.BaseDirectory, "backend", "AgentMeterBackend.exe");
                if (!File.Exists(path)) throw new IOException("backend_missing");
                process = new Process { StartInfo = new ProcessStartInfo(path)
                {
                    UseShellExecute = false, CreateNoWindow = true, RedirectStandardInput = true,
                    RedirectStandardOutput = true, RedirectStandardError = true,
                    StandardInputEncoding = new System.Text.UTF8Encoding(false), StandardOutputEncoding = System.Text.Encoding.UTF8
                } };
                process.StartInfo.ArgumentList.Add("--history-worker");
                process.StartInfo.ArgumentList.Add("--prices-dir");
                process.StartInfo.ArgumentList.Add(AccountPreferences.DefaultDirectory);
                if (!process.Start()) throw new InvalidOperationException("backend_start_failed");
                _ = process.StandardError.ReadToEndAsync();
            }
            await process.StandardInput.WriteLineAsync("{\"command\":\"refresh\"}".AsMemory(), timeout.Token);
            await process.StandardInput.FlushAsync(timeout.Token);
            string? response = await process.StandardOutput.ReadLineAsync(timeout.Token);
            if (response is null) throw new IOException("worker_disconnected");
            using var doc = JsonDocument.Parse(response);
            if (doc.RootElement.TryGetProperty("error", out _)) throw new IOException("worker_failed");
            return response;
        }
        catch
        {
            Stop();
            throw;
        }
    }
    void Stop()
    {
        if (process is null) return;
        try { if (!process.HasExited) process.Kill(true); } catch (InvalidOperationException) { }
        process.Dispose(); process = null;
    }
    public void Dispose() => Stop();
}
