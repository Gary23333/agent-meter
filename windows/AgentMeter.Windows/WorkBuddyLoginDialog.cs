using System.Runtime.InteropServices;
using System.Text.Json;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace AgentMeter.Windows;

/// <summary>在应用专用资料中由用户自行登录，不访问已有浏览器的资料。</summary>
internal sealed class WorkBuddyLoginDialog : Form
{
    const string LoginUrl = "https://www.workbuddy.cn/profile/plans-usage";
    readonly WorkBuddyBrowser browser;
    readonly Action cancelReads;
    readonly WebView2 view = new() { Dock = DockStyle.Fill };
    readonly Label status = new();
    readonly List<Form> popups = [];
    readonly Button finish = new(), clear = new(), cancel = new();
    bool operationPending;
    public bool Cleared { get; private set; }

    public WorkBuddyLoginDialog(WorkBuddyBrowser browser, Action cancelReads, bool preview = false)
    {
        this.browser = browser; this.cancelReads = cancelReads;
        Text = "连接 WorkBuddy"; Font = new Font("Microsoft YaHei UI", 10F);
        StartPosition = FormStartPosition.CenterParent; ClientSize = new Size(900, 680); MinimumSize = new Size(620, 480);
        var instructions = new Label { Dock = DockStyle.Top, Height = 72, Padding = new Padding(14, 10, 14, 0),
            Text = "请在应用内窗口登录 WorkBuddy，回到用量页面后点击「完成连接」。\n登录资料保存在本应用的独立浏览器目录；取消不会清除，可使用「清除本地登录」。" };
        status.Dock = DockStyle.Top; status.Height = 28; status.Padding = new Padding(14, 2, 0, 0); status.Text = "正在准备独立登录窗口…";
        var footer = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 58, FlowDirection = FlowDirection.RightToLeft, Padding = new Padding(8) };
        cancel.Text = "取消"; cancel.AutoSize = true; cancel.DialogResult = DialogResult.Cancel;
        clear.Text = "清除本地登录"; clear.AutoSize = true;
        finish.Text = "完成连接"; finish.AutoSize = true; finish.Enabled = false;
        clear.Click += async (_, _) => await ClearLoginAsync();
        finish.Click += async (_, _) => await FinishAsync();
        footer.Controls.AddRange([cancel, clear, finish]);
        Controls.Add(preview ? new Panel { Dock = DockStyle.Fill, BackColor = Color.White } : view);
        Controls.Add(footer); Controls.Add(status); Controls.Add(instructions);
        CancelButton = cancel;
        if (preview) status.Text = "演示预览 · 不访问网络";
        else Shown += async (_, _) => await InitializeAsync();
        FormClosing += (_, e) => { if (operationPending && e.CloseReason == CloseReason.UserClosing) e.Cancel = true; };
        FormClosed += (_, _) => { ClosePopups(); if (preview) view.Dispose(); };
    }

    async Task InitializeAsync()
    {
        try
        {
            await browser.InitializeViewAsync(view);
            if (IsDisposed || Disposing) return;
            Configure(view);
            view.CoreWebView2.Navigate(LoginUrl);
            finish.Enabled = true;
            status.Text = "当前网站：workbuddy.cn";
        }
        catch (Exception ex) when (WebViewSafety.IsIsolationFailure(ex))
        { if (!IsDisposed && !Disposing) status.Text = "无法确认登录资料隔离，请检查 WebView2 系统策略。"; }
        catch (Exception ex) when (ex is WebView2RuntimeNotFoundException or COMException or InvalidOperationException or IOException or UnauthorizedAccessException or System.Security.SecurityException or ObjectDisposedException)
        { if (!IsDisposed && !Disposing) status.Text = "无法启动独立登录窗口，请检查 WebView2 Runtime 和本地目录。"; }
    }

    void Configure(WebView2 web)
    {
        web.CoreWebView2.Settings.AreHostObjectsAllowed = false;
        web.CoreWebView2.Settings.IsWebMessageEnabled = false;
        web.CoreWebView2.DownloadStarting += (_, e) => { e.Cancel = true; if (!IsDisposed) status.Text = "登录窗口不支持下载文件。"; };
        web.CoreWebView2.LaunchingExternalUriScheme += (_, e) => { e.Cancel = true; if (!IsDisposed) status.Text = "登录窗口不支持打开外部应用。"; };
        web.CoreWebView2.NavigationStarting += (_, e) =>
        {
            if (!WorkBuddyNavigation.Allowed(e.Uri)) { e.Cancel = true; if (!IsDisposed) status.Text = "已阻止不受支持的登录跳转。"; }
        };
        web.CoreWebView2.SourceChanged += (_, _) =>
        {
            if (!IsDisposed && Uri.TryCreate(web.CoreWebView2.Source, UriKind.Absolute, out var uri) && uri.Scheme == Uri.UriSchemeHttps)
                status.Text = "当前网站：" + uri.IdnHost;
        };
        web.CoreWebView2.NewWindowRequested += async (_, e) =>
        {
            var deferral = e.GetDeferral();
            Form? popup = null;
            try
            {
                string requested = string.IsNullOrEmpty(e.Uri) ? "about:blank" : e.Uri;
                if (!WorkBuddyNavigation.Allowed(requested)) { e.Handled = true; if (!IsDisposed) status.Text = "已阻止不受支持的登录窗口。"; return; }
                popup = new Form { Text = "WorkBuddy 登录", Size = new Size(720, 620), StartPosition = FormStartPosition.CenterParent };
                var child = new WebView2 { Dock = DockStyle.Fill };
                var address = new Label { Dock = DockStyle.Top, Height = 26, Padding = new Padding(8, 3, 0, 0), Text = "当前网站：等待跳转" };
                popup.Controls.Add(child); popup.Controls.Add(address); _ = popup.Handle; _ = child.Handle;
                popups.Add(popup);
                popup.FormClosed += (_, _) => { popups.Remove(popup); popup.Dispose(); };
                await browser.InitializeViewAsync(child);
                if (IsDisposed || Disposing) { popup.Dispose(); e.Handled = true; return; }
                child.CoreWebView2.SourceChanged += (_, _) =>
                {
                    if (!popup.IsDisposed && Uri.TryCreate(child.CoreWebView2.Source, UriKind.Absolute, out var uri) && uri.Scheme == Uri.UriSchemeHttps)
                        address.Text = "当前网站：" + uri.IdnHost;
                };
                Configure(child); popup.Show(this);
                e.NewWindow = child.CoreWebView2; e.Handled = true;
            }
            catch (Exception ex) when (ex is WebView2RuntimeNotFoundException or COMException or InvalidOperationException or IOException or UnauthorizedAccessException or System.Security.SecurityException or ObjectDisposedException)
            { e.Handled = true; if (popup is not null) { popups.Remove(popup); popup.Dispose(); } if (!IsDisposed) status.Text = "登录窗口无法打开，请重试。"; }
            finally { deferral.Complete(); }
        };
    }

    async Task FinishAsync()
    {
        if (view.CoreWebView2 is null || !WorkBuddyNavigation.IsWorkBuddy(view.CoreWebView2.Source))
        { status.Text = "请先返回 WorkBuddy 用量页面，再完成连接。"; return; }
        operationPending = true; finish.Enabled = clear.Enabled = cancel.Enabled = false;
        try
        {
            using var input = JsonDocument.Parse(await browser.SessionInputAsync().WaitAsync(TimeSpan.FromSeconds(30)));
            if (input.RootElement.GetProperty("session").ValueKind == JsonValueKind.Null)
            { status.Text = "未检测到可用登录资料，请登录后重试。"; return; }
            operationPending = false; DialogResult = DialogResult.OK; Close();
        }
        catch (Exception ex) when (ex is WebView2RuntimeNotFoundException or COMException or InvalidOperationException or IOException or UnauthorizedAccessException or System.Security.SecurityException or JsonException or ObjectDisposedException or TimeoutException)
        { if (!IsDisposed) status.Text = "无法读取应用内登录资料，请重试。"; }
        finally { operationPending = false; if (!IsDisposed && !Disposing) finish.Enabled = clear.Enabled = cancel.Enabled = true; }
    }

    async Task ClearLoginAsync()
    {
        cancelReads(); operationPending = true; finish.Enabled = clear.Enabled = cancel.Enabled = false;
        try
        {
            ClosePopups(); view.Dispose();
            await browser.ClearAsync().WaitAsync(TimeSpan.FromSeconds(30));
            Cleared = true; operationPending = false; DialogResult = DialogResult.OK; Close();
        }
        catch (Exception ex) when (ex is WebView2RuntimeNotFoundException or COMException or InvalidOperationException or IOException or UnauthorizedAccessException or System.Security.SecurityException or ObjectDisposedException or TimeoutException)
        { if (!IsDisposed) { status.Text = "清除未完成，请稍后重试或检查状态。"; clear.Enabled = cancel.Enabled = true; } }
        finally { operationPending = false; }
    }

    void ClosePopups()
    {
        foreach (var popup in popups.ToArray()) if (!popup.IsDisposed) popup.Close();
        popups.Clear();
    }
}
