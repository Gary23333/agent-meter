using System.Text.Json;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace AgentMeter.Windows;

/// <summary>独立 WebView2 资料：只在用户启用或登录时初始化，不读取现有浏览器资料。</summary>
internal sealed class WorkBuddyBrowser : IDisposable
{
    const string Endpoint = "https://www.workbuddy.cn/billing/meter/get-user-resource-summary";
    readonly string directory;
    string? profileDirectory;
    Task<CoreWebView2Environment>? environmentTask;
    Task<WebView2>? backgroundTask;
    Form? host;
    bool disposed;

    public WorkBuddyBrowser(string directory) => this.directory = Path.GetFullPath(directory);

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
            string profile = ChildDirectory(profiles, "workbuddy");
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
        host = new Form { ShowInTaskbar = false, StartPosition = FormStartPosition.Manual, Location = new Point(-32000, -32000), Size = new Size(1, 1) };
        var view = new WebView2 { Dock = DockStyle.Fill };
        host.Controls.Add(view);
        _ = host.Handle; _ = view.Handle;
        try { await InitializeViewAsync(view); return view; }
        catch { view.Dispose(); host.Dispose(); host = null; throw; }
    }

    public async Task<string> SessionInputAsync(CancellationToken cancellation = default)
    {
        cancellation.ThrowIfCancellationRequested();
        var view = await BackgroundAsync();
        cancellation.ThrowIfCancellationRequested();
        AssertProfilePath();
        var core = view.CoreWebView2;
        var cookies = await core.CookieManager.GetCookiesAsync(Endpoint);
        cancellation.ThrowIfCancellationRequested();
        var safe = cookies.Where(cookie => cookie.IsSession || cookie.Expires.ToUniversalTime() > DateTime.UtcNow)
            .Select(cookie => new WebCookieFilter.Cookie(cookie.Name ?? "", cookie.Value ?? "", cookie.Domain ?? "", cookie.Path ?? ""));
        string? header = WebCookieFilter.WorkBuddyHeader(safe);
        string userAgent = core.Settings.UserAgent ?? "";
        if (header is null || userAgent.Length is < 1 or > 1024 || userAgent.Any(c => c < 32 || c > 126))
            return JsonSerializer.Serialize(new { session = (object?)null });
        return JsonSerializer.Serialize(new { session = new { cookie = header, user_agent = userAgent } });
    }

    public async Task ClearAsync()
    {
        WebViewSafety.EnsureNoOverrides();
        var view = await BackgroundAsync();
        AssertProfilePath();
        await view.CoreWebView2.Profile.ClearBrowsingDataAsync();
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
        var cookie = manager.CreateCookie("agentmeter_synthetic", "example-value", ".workbuddy.cn", "/");
        cookie.IsSecure = true;
        manager.AddOrUpdateCookie(cookie);
        using (var input = JsonDocument.Parse(await SessionInputAsync()))
        {
            var session = input.RootElement.GetProperty("session");
            if (session.ValueKind != JsonValueKind.Object || session.GetProperty("cookie").GetString() != "agentmeter_synthetic=example-value")
                throw new InvalidOperationException("synthetic_cookie_read_failed");
        }
        await ClearAsync();
        using var cleared = JsonDocument.Parse(await SessionInputAsync());
        if (cleared.RootElement.GetProperty("session").ValueKind != JsonValueKind.Null)
            throw new InvalidOperationException("synthetic_cookie_clear_failed");
    }

    public void Dispose()
    {
        if (disposed) return;
        disposed = true;
        host?.Dispose(); host = null;
    }
}
