using System.Text.Json;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace AgentMeter.Windows;

/// <summary>仅在隔离构建机运行：验证原版 3D 形象、透明像素与姿态变化。</summary>
internal static class Pet3dSmoke
{
    const string Host = "pet.agentmeter.invalid";

    public static void Run(string outputDirectory)
    {
        using var form = new Form { ShowInTaskbar = false, StartPosition = FormStartPosition.Manual,
            Location = new Point(-32000, -32000), ClientSize = new Size(240, 260) };
        using var view = new WebView2 { Dock = DockStyle.Fill, DefaultBackgroundColor = Color.Transparent };
        form.Controls.Add(view);
        form.Shown += async (_, _) =>
        {
            try { await CheckAsync(view, outputDirectory); }
            catch (Exception error)
            {
                Console.Error.WriteLine($"3D 桌宠隔离检查失败：{error.GetType().Name}: {error.Message}");
                Environment.ExitCode = 1;
            }
            finally { form.Close(); }
        };
        Application.Run(form);
    }

    static async Task CheckAsync(WebView2 view, string outputDirectory)
    {
        WebViewSafety.EnsureNoOverrides();
        string profile = Path.Combine(Path.GetTempPath(), "AgentMeterPetSmoke-" + Guid.NewGuid().ToString("N"));
        var options = new CoreWebView2EnvironmentOptions { AllowSingleSignOnUsingOSPrimaryAccount = false, AreBrowserExtensionsEnabled = false };
        var environment = await CoreWebView2Environment.CreateAsync(userDataFolder: profile, options: options);
        if (!WebViewSafety.SameDirectory(profile, environment.UserDataFolder)) throw new InvalidOperationException("资料目录不匹配");
        await view.EnsureCoreWebView2Async(environment);
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
            e.Response = environment.CreateWebResourceResponse(null, 403, "Forbidden", "");
        };
        Directory.CreateDirectory(outputDirectory);
        foreach (string pack in new[] { "gauge", "cat", "bot", "tibo", "blob" })
        {
            var loaded = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            void Navigated(object? sender, CoreWebView2NavigationCompletedEventArgs e) => loaded.TrySetResult(e.IsSuccess);
            core.NavigationCompleted += Navigated;
            core.Navigate($"https://{Host}/runtime/index.html?pack={pack}&hud=off&still=1");
            bool success = await loaded.Task.WaitAsync(TimeSpan.FromSeconds(30));
            core.NavigationCompleted -= Navigated;
            if (!success) throw new InvalidOperationException($"{pack} 页面加载失败");
            for (int i = 0; i < 100; i++)
            {
                string state = await core.ExecuteScriptAsync("JSON.stringify({ready:document.body.dataset.settled, error:document.body.dataset.error, pack:window.__pet?.model?.id, renderer:window.__pet?.renderer?.constructor?.name, messages:window.__pet?.host?.log})");
                string decoded = JsonSerializer.Deserialize<string>(state) ?? "{}";
                using var doc = JsonDocument.Parse(decoded);
                var root = doc.RootElement;
                if (root.TryGetProperty("error", out var error)) throw new InvalidOperationException(error.ToString());
                if (root.TryGetProperty("ready", out var ready) && ready.GetString() == "1")
                {
                    if (root.GetProperty("pack").GetString() != pack || root.GetProperty("renderer").GetString() != "ThreeRenderer")
                        throw new InvalidOperationException($"{pack} 未使用预期的 3D 渲染器");
                    if (root.TryGetProperty("messages", out var messages) && messages.EnumerateArray().Any(x => x.TryGetProperty("problem", out var p) && p.ValueKind != JsonValueKind.Null))
                        throw new InvalidOperationException($"{pack} 已回退到备用形象");
                    break;
                }
                if (i == 99) throw new TimeoutException($"{pack} 渲染超时");
                await Task.Delay(100);
            }
            byte[] first = await FrameAsync(core, 0.2);
            byte[] second = await FrameAsync(core, 1.2);
            if (first.SequenceEqual(second)) throw new InvalidOperationException($"{pack} 姿态没有变化");
            using var stream = new MemoryStream(first);
            using var bitmap = new Bitmap(stream);
            int transparent = 0, painted = 0;
            for (int y = 0; y < bitmap.Height; y += 3)
                for (int x = 0; x < bitmap.Width; x += 3)
                    if (bitmap.GetPixel(x, y).A == 0) transparent++; else if (bitmap.GetPixel(x, y).A > 128) painted++;
            if (transparent < 100 || painted < 100) throw new InvalidOperationException($"{pack} 透明或可见区域异常");
            File.WriteAllBytes(Path.Combine(outputDirectory, pack + ".png"), first);
        }
    }

    static async Task<byte[]> FrameAsync(CoreWebView2 core, double time)
    {
        string script = $"(()=>{{const r=window.__pet.renderer;r.seek({time.ToString(System.Globalization.CultureInfo.InvariantCulture)});r.render();return r.canvas.toDataURL('image/png')}})()";
        string data = JsonSerializer.Deserialize<string>(await core.ExecuteScriptAsync(script)) ?? "";
        const string prefix = "data:image/png;base64,";
        if (!data.StartsWith(prefix, StringComparison.Ordinal)) throw new InvalidOperationException("无法读取透明帧");
        return Convert.FromBase64String(data[prefix.Length..]);
    }
}
