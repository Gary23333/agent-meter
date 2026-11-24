using System.Text.Json;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

using static AgentMeter.Windows.UiScale;

namespace AgentMeter.Windows;

/// <summary>独立 WebView2 资料：只在用户启用或登录时初始化，不读取现有浏览器资料。</summary>
internal sealed class TraeBrowser : IDisposable
{
    const string Endpoint = "https://www.trae.cn/pricing";
    readonly string directory;
    string? profileDirectory;
    Task<CoreWebView2Environment>? environmentTask;
    Task<WebView2>? backgroundTask;
    Form? host;
    bool disposed, clearing, suspended, syntheticNavigation;
    string? token, deviceId, userAgent;
    DateTime capturedAt;
    TaskCompletionSource<bool>? pendingCapture;

    public TraeBrowser(string directory) => this.directory = Path.GetFullPath(directory);

    static string ChildDirectory(string parent, string child)
    {
        Directory.CreateDirectory(parent);
        if ((File.GetAttributes(parent) & FileAttributes.ReparsePoint) != 0) throw new IOException("profile_root_redirected");
        string path = Path.Combine(parent, child);
        Directory.CreateDirectory(path);
        if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0) throw new IOException("profile_directory_redirected");
        return path;
    }

    async Task<CoreWebView2Environment> EnvironmentAsync()
    {
        ObjectDisposedException.ThrowIf(disposed, this);
        if (environmentTask is null)
        {
            WebViewSafety.EnsureNoOverrides();
            string profiles = ChildDirectory(directory, "webprofiles");
            string profile = ChildDirectory(profiles, "trae");
            profileDirectory = profile;
            var options = new CoreWebView2EnvironmentOptions { AllowSingleSignOnUsingOSPrimaryAccount = false, AreBrowserExtensionsEnabled = false };
            environmentTask = CoreWebView2Environment.CreateAsync(userDataFolder: profile, options: options);
        }
        var task = environmentTask;
        try
        {
            var environment = await task;
            if (profileDirectory is null || !WebViewSafety.SameDirectory(profileDirectory, environment.UserDataFolder))
                throw new InvalidOperationException("webview_profile_mismatch");
            return environment;
        }
        catch { if (ReferenceEquals(environmentTask, task)) environmentTask = null; throw; }
    }

    public async Task InitializeViewAsync(WebView2 view)
    {
        var environment = await EnvironmentAsync();
        ObjectDisposedException.ThrowIf(disposed, this);
        await view.EnsureCoreWebView2Async(environment);
        var core = view.CoreWebView2;
        core.AddWebResourceRequestedFilter("https://api.trae.cn/*", CoreWebView2WebResourceContext.All);
        core.WebResourceRequested += (_, e) =>
        {
            if (clearing || disposed) return;
            try
            {
                var headers = e.Request.Headers;
                string? authorization = headers.Contains("Authorization") ? headers.GetHeader("Authorization") : null;
                string? device = headers.Contains("X-Device-Id") ? headers.GetHeader("X-Device-Id") : null;
                Capture(e.Request.Uri, authorization, device, core.Settings.UserAgent ?? "");
            }
            catch (Exception ex) when (ex is System.Runtime.InteropServices.COMException or InvalidOperationException or ObjectDisposedException) { }
        };
    }

    void Capture(string address, string? authorization, string? device, string agent)
    {
        if (clearing || suspended || disposed) return;
        string? captured = TraeHeaderFilter.Token(address, authorization);
        if (captured is null || agent.Length is < 1 or > 1024 || agent.Any(c => c < 32 || c > 126)) return;
        token = captured; deviceId = TraeHeaderFilter.Device(device); userAgent = agent; capturedAt = DateTime.UtcNow;
        pendingCapture?.TrySetResult(true);
    }

    async Task<WebView2> BackgroundAsync()
    {
        ObjectDisposedException.ThrowIf(disposed, this);
        if (backgroundTask is null) backgroundTask = CreateBackgroundAsync();
        var task = backgroundTask;
        try { return await task; }
        catch { if (ReferenceEquals(backgroundTask, task)) backgroundTask = null; throw; }
    }

    async Task<WebView2> CreateBackgroundAsync()
    {
        host = new Form { ShowInTaskbar = false, StartPosition = FormStartPosition.Manual, Location = P(-32000, -32000), Size = Sz(1, 1) };
        var view = new WebView2 { Dock = DockStyle.Fill };
        host.Controls.Add(view);
        _ = host.Handle; _ = view.Handle;
        try
        {
            await InitializeViewAsync(view);
            view.CoreWebView2.Settings.AreHostObjectsAllowed = false;
            view.CoreWebView2.Settings.IsWebMessageEnabled = false;
            view.CoreWebView2.NavigationStarting += (_, e) =>
            {
                if (!TraeNavigation.Allowed(e.Uri) && !(syntheticNavigation && e.Uri == "https://agentmeter.invalid/fixture")) e.Cancel = true;
            };
            view.CoreWebView2.NewWindowRequested += (_, e) => e.Handled = true;
            view.CoreWebView2.DownloadStarting += (_, e) => e.Cancel = true;
            view.CoreWebView2.LaunchingExternalUriScheme += (_, e) => e.Cancel = true;
            return view;
        }
        catch { view.Dispose(); host.Dispose(); host = null; throw; }
    }

    public async Task<string> SessionInputAsync(CancellationToken cancellation = default)
    {
        cancellation.ThrowIfCancellationRequested();
        suspended = false;
        var view = await BackgroundAsync();
        cancellation.ThrowIfCancellationRequested(); AssertProfilePath();
        if (token is null || DateTime.UtcNow < capturedAt || DateTime.UtcNow - capturedAt > TimeSpan.FromMinutes(10))
        {
            token = null; deviceId = null; userAgent = null;
            var pending = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            pendingCapture = pending;
            try
            {
                view.CoreWebView2.Navigate(Endpoint);
                try { await pending.Task.WaitAsync(TimeSpan.FromSeconds(12), cancellation); }
                catch (TimeoutException) { }
            }
            finally { if (ReferenceEquals(pendingCapture, pending)) pendingCapture = null; }
        }
        cancellation.ThrowIfCancellationRequested();
        return token is null || userAgent is null
            ? JsonSerializer.Serialize(new { session = (object?)null })
            : JsonSerializer.Serialize(new { session = new { token, user_agent = userAgent, device_id = deviceId } });
    }

    public void BeginLogin() { ObjectDisposedException.ThrowIf(disposed, this); suspended = false; }

    /// <summary>关闭来源时停止后台页面并丢弃短期凭据，保留用户选择保留的登录资料。</summary>
    public void Suspend()
    {
        suspended = true; token = null; deviceId = null; userAgent = null; pendingCapture?.TrySetCanceled();
        if (backgroundTask is not { IsCompletedSuccessfully: true }) return;
        try
        {
            var core = backgroundTask.Result.CoreWebView2;
            core.Stop(); core.Navigate("about:blank");
        }
        catch (Exception ex) when (ex is System.Runtime.InteropServices.COMException or InvalidOperationException or ObjectDisposedException) { }
    }

    public async Task ClearAsync()
    {
        clearing = true; token = null; deviceId = null; userAgent = null; pendingCapture?.TrySetCanceled();
        try
        {
            WebViewSafety.EnsureNoOverrides();
            var view = await BackgroundAsync();
            AssertProfilePath();
            var core = view.CoreWebView2;
            core.Stop();
            var blank = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            void Finished(object? sender, CoreWebView2NavigationCompletedEventArgs e)
            {
                if (core.Source == "about:blank") blank.TrySetResult(e.IsSuccess);
            }
            core.NavigationCompleted += Finished;
            try
            {
                core.Navigate("about:blank");
                if (!await blank.Task.WaitAsync(TimeSpan.FromSeconds(5))) throw new InvalidOperationException("trae_blank_navigation_failed");
            }
            finally { core.NavigationCompleted -= Finished; }
            await core.Profile.ClearBrowsingDataAsync();
        }
        finally { token = null; deviceId = null; userAgent = null; clearing = false; }
    }

    void AssertProfilePath()
    {
        if (profileDirectory is null) throw new InvalidOperationException("webview_profile_missing");
        foreach (string path in new[] { directory, Path.Combine(directory, "webprofiles"), profileDirectory })
            if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
                throw new InvalidOperationException("webview_profile_redirected");
    }

    internal async Task SyntheticSmokeAsync()
    {
        var view = await BackgroundAsync();
        var manager = view.CoreWebView2.CookieManager;
        var cookie = manager.CreateCookie("agentmeter_synthetic", "example-value", ".trae.cn", "/");
        cookie.IsSecure = true; manager.AddOrUpdateCookie(cookie);
        if (!(await manager.GetCookiesAsync("https://www.trae.cn/")).Any(c => c.Name == "agentmeter_synthetic"))
            throw new InvalidOperationException("synthetic_cookie_read_failed");
        // 保留域名 .invalid 不解析到公网；所有请求均在 WebView 事件中返回模拟内容。
        var core = view.CoreWebView2;
        var environment = await EnvironmentAsync();
        core.AddWebResourceRequestedFilter("https://agentmeter.invalid/*", CoreWebView2WebResourceContext.All);
        string syntheticToken = "synthetic.jwt." + new string('a', 24);
        var captured = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        void Fixture(object? sender, CoreWebView2WebResourceRequestedEventArgs e)
        {
            var headers = e.Request.Headers;
            if (headers.Contains("Authorization"))
                Capture("https://api.trae.cn/fixture", headers.GetHeader("Authorization"), null, core.Settings.UserAgent ?? "");
            string body = e.Request.Uri.EndsWith("/fixture", StringComparison.Ordinal)
                ? "<script>fetch('/capture',{headers:{Authorization:'Cloud-IDE-JWT " + syntheticToken + "'}}).catch(()=>{});</script>"
                : "{}";
            var stream = new MemoryStream(System.Text.Encoding.UTF8.GetBytes(body));
            e.Response = environment.CreateWebResourceResponse(stream, 200, "OK", "Content-Type: " + (body.StartsWith("<script>") ? "text/html" : "application/json"));
        }
        core.WebResourceRequested += Fixture; syntheticNavigation = true; pendingCapture = captured;
        try
        {
            core.Navigate("https://agentmeter.invalid/fixture");
            await captured.Task.WaitAsync(TimeSpan.FromSeconds(10));
            if (token != syntheticToken) throw new InvalidOperationException("synthetic_trae_capture_failed");
        }
        finally { core.WebResourceRequested -= Fixture; syntheticNavigation = false; pendingCapture = null; }
        Suspend();
        Capture("https://api.trae.cn/fixture", "Cloud-IDE-JWT " + syntheticToken, null, core.Settings.UserAgent ?? "");
        if (token is not null) throw new InvalidOperationException("disabled_trae_capture_failed");
        BeginLogin();
        await ClearAsync();
        if (token is not null || (await manager.GetCookiesAsync("https://www.trae.cn/")).Any(c => c.Name == "agentmeter_synthetic"))
            throw new InvalidOperationException("synthetic_cookie_clear_failed");
    }

    public void Dispose()
    {
        if (disposed) return;
        disposed = true; suspended = true; token = null; deviceId = null; userAgent = null; pendingCapture?.TrySetCanceled();
        host?.Dispose(); host = null;
    }
}
