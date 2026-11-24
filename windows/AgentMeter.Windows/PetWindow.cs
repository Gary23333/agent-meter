using System.ComponentModel;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;
using System.Text.Json;

namespace AgentMeter.Windows;

internal interface IPetWindow : IDisposable
{
    event Action? OpenRequested, RefreshRequested, HideRequested, RenderingFailed;
    event Action<Point>? PositionChanged;
    event Action<Bitmap, PetMood>? FrameUpdated;
    void SetSnapshot(string value);
    void SetFollowCursor(bool value);
    void Show();
}

/// <summary>使用逐像素透明的原生悬浮窗；透明区域由 Windows 正常穿透。</summary>
internal sealed class PetWindow : Form, IPetWindow
{
    const int Side = 240;
    readonly SpritePet sprite;
    readonly System.Windows.Forms.Timer timer = new();
    readonly ContextMenuStrip menu = new();
    string? snapshot;
    string state = "idle";
    PetMood mood = new("idle", "待机");
    int frame;
    DateTime lastStateCheck = DateTime.MinValue;
    Point dragCursor, dragOrigin;
    bool dragging, pressed;
    public event Action? OpenRequested, RefreshRequested, HideRequested;
    public event Action<Point>? PositionChanged;
    public event Action<Bitmap, PetMood>? FrameUpdated;
    public event Action? RenderingFailed;

    public PetWindow(string pack, Point position)
    {
        sprite = new SpritePet(pack);
        FormBorderStyle = FormBorderStyle.None; ShowInTaskbar = false; StartPosition = FormStartPosition.Manual;
        Size = new Size(Side, Side); Location = position; TopMost = true;
        menu.Items.Add("打开 Agent Meter", null, (_, _) => OpenRequested?.Invoke());
        menu.Items.Add("刷新数据", null, (_, _) => RefreshRequested?.Invoke());
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("隐藏桌宠", null, (_, _) => HideRequested?.Invoke());
        ContextMenuStrip = menu;
        timer.Interval = 1000 / sprite.FramesPerSecond(state);
        timer.Tick += (_, _) => TickFrame();
        MouseDown += (_, e) =>
        {
            if (e.Button != MouseButtons.Left) return;
            pressed = true; dragging = false; dragCursor = Cursor.Position; dragOrigin = Location;
        };
        MouseMove += (_, e) =>
        {
            if (!pressed || e.Button != MouseButtons.Left) return;
            var cursor = Cursor.Position; int dx = cursor.X - dragCursor.X, dy = cursor.Y - dragCursor.Y;
            if (Math.Abs(dx) + Math.Abs(dy) > 4) dragging = true;
            if (dragging) { Location = new Point(dragOrigin.X + dx, dragOrigin.Y + dy); DrawFrame(); }
        };
        MouseUp += (_, e) =>
        {
            if (e.Button != MouseButtons.Left || !pressed) return;
            pressed = false;
            if (dragging) PositionChanged?.Invoke(Location); else OpenRequested?.Invoke();
        };
    }
    protected override bool ShowWithoutActivation => true;
    protected override CreateParams CreateParams
    {
        get { var value = base.CreateParams; value.ExStyle |= 0x00080000 | 0x00000080 | 0x08000000; return value; }
    }
    protected override void OnShown(EventArgs e) { base.OnShown(e); DrawFrame(); if (Visible) timer.Start(); }
    public void SetSnapshot(string value) { snapshot = value; lastStateCheck = DateTime.MinValue; }
    public void SetFollowCursor(bool value) { } // 精灵图没有眼睛跟随动画。
    void TickFrame()
    {
        if (!Visible) return;
        if (snapshot is not null && DateTime.UtcNow - lastStateCheck >= TimeSpan.FromSeconds(2))
        {
            lastStateCheck = DateTime.UtcNow;
            try
            {
                using var document = JsonDocument.Parse(snapshot);
                mood = PetState.Select(document.RootElement, DateTimeOffset.UtcNow.ToUnixTimeSeconds());
                if (mood.Animation != state) { state = mood.Animation; frame = 0; timer.Interval = Math.Max(34, 1000 / sprite.FramesPerSecond(state)); }
                AccessibleName = "Agent Meter 桌宠 · " + mood.Description;
            }
            catch (JsonException) { state = "idle"; mood = new("idle", "待机"); }
        }
        frame = (frame + 1) % sprite.FrameCount(state);
        DrawFrame();
    }
    void DrawFrame()
    {
        if (!IsHandleCreated || IsDisposed) return;
        try
        {
            var image = sprite.Frame(state, frame, Side);
            LayeredWindow.Draw(Handle, image, Location); FrameUpdated?.Invoke(image, mood);
        }
        catch (Exception ex) when (ex is Win32Exception or InvalidDataException or ExternalException or ArgumentException)
        { timer.Stop(); Hide(); RenderingFailed?.Invoke(); }
    }
    protected override void Dispose(bool disposing)
    {
        if (disposing) { timer.Stop(); timer.Dispose(); menu.Dispose(); sprite.Dispose(); }
        base.Dispose(disposing);
    }
}

internal static class LayeredWindow
{
    [StructLayout(LayoutKind.Sequential)] struct NativePoint { public int X, Y; public NativePoint(int x, int y) { X = x; Y = y; } }
    [StructLayout(LayoutKind.Sequential)] struct NativeSize { public int Width, Height; public NativeSize(int width, int height) { Width = width; Height = height; } }
    [StructLayout(LayoutKind.Sequential, Pack = 1)] struct Blend { public byte Operation, Flags, Alpha, Format; }
    [StructLayout(LayoutKind.Sequential)] struct BitmapHeader
    {
        public uint Size; public int Width, Height; public ushort Planes, BitCount;
        public uint Compression, SizeImage; public int XPelsPerMeter, YPelsPerMeter; public uint ColorsUsed, ColorsImportant;
    }
    [StructLayout(LayoutKind.Sequential)] struct BitmapInfo { public BitmapHeader Header; public uint Color; }
    [DllImport("user32.dll", SetLastError = true)] static extern IntPtr GetDC(IntPtr window);
    [DllImport("user32.dll")] static extern int ReleaseDC(IntPtr window, IntPtr dc);
    [DllImport("gdi32.dll", SetLastError = true)] static extern IntPtr CreateCompatibleDC(IntPtr dc);
    [DllImport("gdi32.dll", SetLastError = true)] static extern IntPtr CreateDIBSection(IntPtr dc, ref BitmapInfo info, uint usage, out IntPtr bits, IntPtr section, uint offset);
    [DllImport("gdi32.dll")] static extern bool DeleteDC(IntPtr dc);
    [DllImport("gdi32.dll", SetLastError = true)] static extern IntPtr SelectObject(IntPtr dc, IntPtr value);
    [DllImport("gdi32.dll")] static extern bool DeleteObject(IntPtr value);
    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    static extern bool UpdateLayeredWindow(IntPtr window, IntPtr screen, ref NativePoint destination, ref NativeSize size,
        IntPtr source, ref NativePoint origin, int colorKey, ref Blend blend, int flags);

    public static void Draw(IntPtr window, Bitmap bitmap, Point location)
    {
        if (bitmap.PixelFormat != PixelFormat.Format32bppPArgb) throw new ArgumentException("桌宠帧必须是预乘透明图像");
        IntPtr screen = IntPtr.Zero, memory = IntPtr.Zero, image = IntPtr.Zero, previous = IntPtr.Zero;
        try
        {
            screen = GetDC(IntPtr.Zero);
            if (screen == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
            memory = CreateCompatibleDC(screen);
            if (memory == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
            var info = new BitmapInfo { Header = new BitmapHeader { Size = (uint)Marshal.SizeOf<BitmapHeader>(), Width = bitmap.Width,
                Height = -bitmap.Height, Planes = 1, BitCount = 32, Compression = 0 } };
            image = CreateDIBSection(screen, ref info, 0, out var bits, IntPtr.Zero, 0);
            if (image == IntPtr.Zero || bits == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
            var locked = bitmap.LockBits(new Rectangle(0, 0, bitmap.Width, bitmap.Height), ImageLockMode.ReadOnly, PixelFormat.Format32bppPArgb);
            try
            {
                int rowLength = checked(bitmap.Width * 4);
                var row = new byte[rowLength];
                for (int y = 0; y < bitmap.Height; y++)
                {
                    Marshal.Copy(IntPtr.Add(locked.Scan0, y * locked.Stride), row, 0, rowLength);
                    Marshal.Copy(row, 0, IntPtr.Add(bits, y * rowLength), rowLength);
                }
            }
            finally { bitmap.UnlockBits(locked); }
            previous = SelectObject(memory, image);
            if (previous == IntPtr.Zero || previous == new IntPtr(-1)) throw new Win32Exception(Marshal.GetLastWin32Error());
            var destination = new NativePoint(location.X, location.Y); var size = new NativeSize(bitmap.Width, bitmap.Height);
            var origin = new NativePoint(0, 0); var blend = new Blend { Operation = 0, Flags = 0, Alpha = 255, Format = 1 };
            if (!UpdateLayeredWindow(window, screen, ref destination, ref size, memory, ref origin, 0, ref blend, 2))
                throw new Win32Exception(Marshal.GetLastWin32Error());
        }
        finally
        {
            if (previous != IntPtr.Zero && previous != new IntPtr(-1) && memory != IntPtr.Zero) SelectObject(memory, previous);
            if (image != IntPtr.Zero) DeleteObject(image);
            if (memory != IntPtr.Zero) DeleteDC(memory);
            if (screen != IntPtr.Zero) ReleaseDC(IntPtr.Zero, screen);
        }
    }
}
