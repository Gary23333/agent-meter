using System.ComponentModel;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;
using System.Text.Json;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace AgentMeter.Windows;

/// <summary>原版离线 3D 形象通过透明帧绘制到原生悬浮窗；仅在用户选择时启动。</summary>
internal sealed class Pet3dWindow : Form, IPetWindow
{
    const int Side = 240;
    readonly string pack, directory;
    readonly System.Windows.Forms.Timer timer = new() { Interval = 150 };
    readonly ContextMenuStrip menu = new();
    readonly PetInteractionQueue interactions = new();
    Pet3dRenderer? renderer;
    Bitmap? lastFrame;
    string? snapshot;
    PetMood mood = new("idle", "待机");
    DateTime lastStateCheck = DateTime.MinValue, lastFrameTime = DateTime.UtcNow;
    Point dragCursor, dragOrigin;
    bool busy, dragging, pressed, failed;
    internal TaskCompletionSource<bool> FirstFrame { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
    public event Action? OpenRequested, RefreshRequested, HideRequested, RenderingFailed;
    public event Action<Point>? PositionChanged;

    public Pet3dWindow(string pack, Point position, string directory)
    {
        if (!PetPreferences.ValidPack(pack) || pack is "mochi" or "bit") throw new ArgumentException("未知 3D 桌宠");
        this.pack = pack; this.directory = directory;
        FormBorderStyle = FormBorderStyle.None; ShowInTaskbar = false; StartPosition = FormStartPosition.Manual;
        Size = new Size(Side, Side); Location = position; TopMost = true;
        menu.Items.Add("打开 Agent Meter", null, (_, _) => OpenRequested?.Invoke());
        menu.Items.Add("刷新数据", null, (_, _) => { interactions.Add("refresh"); RefreshRequested?.Invoke(); });
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("隐藏桌宠", null, (_, _) => HideRequested?.Invoke());
        ContextMenuStrip = menu;
        MouseDown += (_, e) =>
        {
            if (e.Button != MouseButtons.Left) return;
            pressed = true; dragging = false; dragCursor = Cursor.Position; dragOrigin = Location;
        };
        MouseMove += (_, e) =>
        {
            if (!pressed || e.Button != MouseButtons.Left) return;
            var cursor = Cursor.Position; int dx = cursor.X - dragCursor.X, dy = cursor.Y - dragCursor.Y;
            if (!dragging && Math.Abs(dx) + Math.Abs(dy) > 4) { dragging = true; interactions.Add("drag-start"); }
            if (dragging) { Location = new Point(dragOrigin.X + dx, dragOrigin.Y + dy); DrawFrame(); }
        };
        MouseUp += (_, e) =>
        {
            if (e.Button != MouseButtons.Left || !pressed) return;
            pressed = false;
            if (dragging) { interactions.Add("drag-end"); PositionChanged?.Invoke(Location); }
            else { interactions.Add("poke"); OpenRequested?.Invoke(); }
        };
        timer.Tick += async (_, _) => await TickAsync();
    }

    protected override bool ShowWithoutActivation => true;
    protected override CreateParams CreateParams
    {
        get { var value = base.CreateParams; value.ExStyle |= 0x00080000 | 0x00000080 | 0x08000000; return value; }
    }
    protected override async void OnShown(EventArgs e)
    {
        base.OnShown(e);
        try
        {
            renderer = new Pet3dRenderer(directory, pack);
            await renderer.StartAsync();
            if (IsDisposed || Disposing) return;
            lastFrameTime = DateTime.UtcNow;
            await TickAsync();
            if (!failed && !IsDisposed) timer.Start();
        }
        catch (Exception ex) when (ex is WebView2RuntimeNotFoundException or COMException or InvalidOperationException or IOException or UnauthorizedAccessException or System.Security.SecurityException or ObjectDisposedException or TimeoutException or ArgumentException or JsonException or FormatException)
        { Fail(); }
    }
    public void SetSnapshot(string value) { snapshot = value; lastStateCheck = DateTime.MinValue; }
    async Task TickAsync()
    {
        if (busy || failed || renderer is null || IsDisposed || !Visible) return;
        busy = true;
        try
        {
            if (snapshot is not null && DateTime.UtcNow - lastStateCheck >= TimeSpan.FromSeconds(2))
            {
                lastStateCheck = DateTime.UtcNow;
                try { using var document = JsonDocument.Parse(snapshot); mood = PetState.Select(document.RootElement, DateTimeOffset.UtcNow.ToUnixTimeSeconds()); }
                catch (JsonException) { mood = new("idle", "待机"); }
                AccessibleName = "Agent Meter 桌宠 · " + mood.Description;
            }
            var now = DateTime.UtcNow;
            double elapsed = Math.Clamp((now - lastFrameTime).TotalSeconds, 0.01, 0.25);
            lastFrameTime = now;
            string? interaction = interactions.Take();
            using var rendered = await renderer.FrameAsync(mood, elapsed, interaction);
            if (IsDisposed || Disposing) return;
            var next = new Bitmap(Side, Side, PixelFormat.Format32bppPArgb);
            using (var graphics = Graphics.FromImage(next))
            {
                graphics.Clear(Color.Transparent);
                graphics.InterpolationMode = System.Drawing.Drawing2D.InterpolationMode.HighQualityBicubic;
                graphics.DrawImage(rendered, new Rectangle(9, 0, 222, Side));
            }
            var previous = lastFrame; lastFrame = next; previous?.Dispose(); DrawFrame();
        }
        catch (Exception ex) when (ex is COMException or InvalidOperationException or IOException or ObjectDisposedException or TimeoutException or ArgumentException or ExternalException or JsonException or FormatException)
        { Fail(); }
        finally { busy = false; }
    }
    void DrawFrame()
    {
        if (lastFrame is null || !IsHandleCreated || IsDisposed) return;
        try { LayeredWindow.Draw(Handle, lastFrame, Location); FirstFrame.TrySetResult(true); }
        catch (Exception ex) when (ex is Win32Exception or ExternalException or ArgumentException) { Fail(); }
    }
    void Fail()
    {
        if (failed || IsDisposed || Disposing) return;
        failed = true; timer.Stop(); Hide(); renderer?.Dispose(); renderer = null; FirstFrame.TrySetResult(false); RenderingFailed?.Invoke();
    }
    protected override void Dispose(bool disposing)
    {
        if (disposing) { timer.Stop(); timer.Dispose(); renderer?.Dispose(); lastFrame?.Dispose(); menu.Dispose(); }
        base.Dispose(disposing);
    }
}
