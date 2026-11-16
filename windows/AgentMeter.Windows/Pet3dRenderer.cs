using System.Text.Json;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace AgentMeter.Windows;

/// <summary>只加载随程序附带的形象；不使用用户浏览器资料，也不允许访问网络。</summary>
internal sealed class Pet3dRenderer : IDisposable
{
    const string Host = "pet.agentmeter.invalid";
    readonly string directory, pack;
    Form? host;
    WebView2? view;
    bool disposed;
    int blockedRequests;

    public Pet3dRenderer(string directory, string pack)
    {
        this.directory = Path.GetFullPath(directory); this.pack = pack;
        if (pack is not ("gauge" or "cat" or "bot" or "tibo" or "blob")) throw new ArgumentException("未知 3D 桌宠");
    }
    static string ChildDirectory(string parent, string child)
    {
        Directory.CreateDirectory(parent);
        if ((File.GetAttributes(parent) & FileAttributes.ReparsePoint) != 0) throw new IOException("profile_root_redirected");
        string path = Path.Combine(parent, child);
        Directory.CreateDirectory(path);
        if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0) throw new IOException("profile_directory_redirected");
        return path;
    }
    public async Task StartAsync()
    {
        ObjectDisposedException.ThrowIf(disposed, this);
        WebViewSafety.EnsureNoOverrides();
        string profiles = ChildDirectory(directory, "webprofiles");
        string profile = ChildDirectory(profiles, "pet");
        var options = new CoreWebView2EnvironmentOptions { AllowSingleSignOnUsingOSPrimaryAccount = false, AreBrowserExtensionsEnabled = false };
        var environment = await CoreWebView2Environment.CreateAsync(userDataFolder: profile, options: options);
        ObjectDisposedException.ThrowIf(disposed, this);
        if (!WebViewSafety.SameDirectory(profile, environment.UserDataFolder)) throw new InvalidOperationException("webview_profile_mismatch");
        host = new PetRenderHost { ShowInTaskbar = false, StartPosition = FormStartPosition.Manual,
            Location = new Point(-32000, -32000), ClientSize = new Size(240, 260) };
        view = new WebView2 { Dock = DockStyle.Fill, DefaultBackgroundColor = Color.Transparent };
        host.Controls.Add(view); host.Show();
        await view.EnsureCoreWebView2Async(environment);
        ObjectDisposedException.ThrowIf(disposed, this);
        var core = view.CoreWebView2;
        core.Settings.AreHostObjectsAllowed = false;
        core.Settings.IsWebMessageEnabled = false;
        core.Settings.AreDevToolsEnabled = false;
        core.SetVirtualHostNameToFolderMapping(Host, Path.Combine(AppContext.BaseDirectory, "pet"), CoreWebView2HostResourceAccessKind.DenyCors);
        core.NavigationStarting += (_, e) =>
        {
            if (!Uri.TryCreate(e.Uri, UriKind.Absolute, out var uri) || uri.Scheme != Uri.UriSchemeHttps || uri.Host != Host) e.Cancel = true;
        };
        core.NewWindowRequested += (_, e) => e.Handled = true;
        core.DownloadStarting += (_, e) => e.Cancel = true;
        core.LaunchingExternalUriScheme += (_, e) => e.Cancel = true;
        core.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All);
        core.WebResourceRequested += (_, e) =>
        {
            blockedRequests++;
            e.Response = environment.CreateWebResourceResponse(null, 403, "Forbidden", "");
        };
        var loaded = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        void Navigated(object? sender, CoreWebView2NavigationCompletedEventArgs e) => loaded.TrySetResult(e.IsSuccess);
        core.NavigationCompleted += Navigated;
        try
        {
            core.Navigate($"https://{Host}/runtime/index.html?pack={pack}&hud=off&still=1");
            if (!await loaded.Task.WaitAsync(TimeSpan.FromSeconds(30))) throw new InvalidOperationException("桌宠页面加载失败");
        }
        finally { core.NavigationCompleted -= Navigated; }
        for (int i = 0; i < 100; i++)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            string response = await core.ExecuteScriptAsync("JSON.stringify({ready:document.body.dataset.settled,error:document.body.dataset.error,pack:window.__pet?.model?.id,renderer:window.__pet?.renderer?.constructor?.name,logs:window.__pet?.host?.log})");
            using var doc = JsonDocument.Parse(JsonSerializer.Deserialize<string>(response) ?? "{}");
            var root = doc.RootElement;
            if (root.TryGetProperty("error", out var error)) throw new InvalidOperationException(error.ToString());
            if (root.TryGetProperty("ready", out var ready) && ready.GetString() == "1")
            {
                if (root.GetProperty("pack").GetString() != pack || root.GetProperty("renderer").GetString() != "ThreeRenderer" ||
                    root.GetProperty("logs").EnumerateArray().Any(x => x.TryGetProperty("problem", out var p) && p.ValueKind != JsonValueKind.Null))
                    throw new InvalidOperationException("桌宠形象加载失败");
                await core.ExecuteScriptAsync("window.__pet.renderer.frozen=false; window.__pet.stage.director.setPrefs({calm:true,chatter:false,followCursor:false});");
                return;
            }
            await Task.Delay(100);
        }
        throw new TimeoutException("桌宠渲染超时");
    }

    public async Task<Bitmap> FrameAsync(PetMood mood, double elapsed)
    {
        ObjectDisposedException.ThrowIf(disposed, this);
        var core = view?.CoreWebView2 ?? throw new InvalidOperationException("桌宠尚未启动");
        var remaining = mood.Remaining;
        var frame = new { schema_version = 1, generated_at = DateTimeOffset.UtcNow.ToUnixTimeSeconds(), state = mood.Animation,
            mood = "neutral", intensity = 0.6,
            energy = new { known = remaining.HasValue, remaining = remaining ?? 0, tone = remaining is < 20 ? "crit" : remaining is < 50 ? "low" : remaining.HasValue ? "ok" : "unknown", drives_state = remaining.HasValue, scope = "auto", label = "", resets_at = (long?)null, stale = false },
            meters = Array.Empty<object>(), activity = new { known = false, running = 0, apps = Array.Empty<object>() }, focus = new { active = false }, reminders = Array.Empty<object>() };
        string script = "(()=>{const s=window.__pet.stage;s.receive({type:'frame',frame:" + JsonSerializer.Serialize(frame) + "});s.step(" +
            Math.Clamp(elapsed, 0.01, 0.25).ToString(System.Globalization.CultureInfo.InvariantCulture) + ",s.now);return s.renderer.canvas.toDataURL('image/png')})()";
        string data = JsonSerializer.Deserialize<string>(await core.ExecuteScriptAsync(script).WaitAsync(TimeSpan.FromSeconds(5))) ?? "";
        const string prefix = "data:image/png;base64,";
        if (!data.StartsWith(prefix, StringComparison.Ordinal)) throw new InvalidOperationException("桌宠帧不可用");
        using var stream = new MemoryStream(Convert.FromBase64String(data[prefix.Length..]));
        using var image = new Bitmap(stream);
        return new Bitmap(image);
    }
    internal async Task<bool> SyntheticNetworkBlockAsync()
    {
        var core = view?.CoreWebView2 ?? throw new InvalidOperationException("桌宠尚未启动");
        int before = blockedRequests;
        await core.ExecuteScriptAsync("void fetch('https://agentmeter-test.invalid/probe',{mode:'no-cors'}).catch(()=>null)").WaitAsync(TimeSpan.FromSeconds(5));
        for (int i = 0; i < 50 && blockedRequests == before; i++) await Task.Delay(100);
        return blockedRequests > before;
    }
    public void Dispose()
    {
        if (disposed) return;
        disposed = true; view?.Dispose(); host?.Dispose(); view = null; host = null;
    }
    sealed class PetRenderHost : Form { protected override bool ShowWithoutActivation => true; }
}
