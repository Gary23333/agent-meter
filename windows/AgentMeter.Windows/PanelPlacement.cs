using System.Drawing;
using System.Runtime.InteropServices;
using System.Text;

namespace AgentMeter.Windows;

internal enum TaskbarEdge : uint { Left = 0, Top = 1, Right = 2, Bottom = 3 }

/// <summary>查询指定屏幕的自动隐藏任务栏；忽略第三方工具栏，查询失败时交给工作区定位。</summary>
internal static class TaskbarLocation
{
    [StructLayout(LayoutKind.Sequential)]
    struct NativeRect { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)]
    struct AppBarData
    {
        public uint Size;
        public IntPtr Window;
        public uint Callback, Edge;
        public NativeRect Bounds;
        public IntPtr Parameter;
    }
    [DllImport("shell32.dll")] static extern IntPtr SHAppBarMessage(uint message, ref AppBarData data);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetClassName(IntPtr window, StringBuilder name, int capacity);

    internal static TaskbarEdge? AutoHideEdge(Rectangle monitor) => ResolveAutoHide(monitor, (edge, bounds) =>
    {
        var data = new AppBarData { Size = (uint)Marshal.SizeOf<AppBarData>(), Edge = (uint)edge,
            Bounds = new NativeRect { Left = bounds.Left, Top = bounds.Top, Right = bounds.Right, Bottom = bounds.Bottom } };
        return SHAppBarMessage(0x0B, ref data); // ABM_GETAUTOHIDEBAREX
    }, window =>
    {
        var name = new StringBuilder(256);
        return GetClassName(window, name, name.Capacity) > 0 ? name.ToString() : "";
    });

    internal static TaskbarEdge? ResolveAutoHide(Rectangle monitor, Func<TaskbarEdge, Rectangle, IntPtr> query, Func<IntPtr, string> className)
    {
        foreach (var edge in new[] { TaskbarEdge.Left, TaskbarEdge.Top, TaskbarEdge.Right, TaskbarEdge.Bottom })
        {
            IntPtr window = query(edge, monitor);
            if (window != IntPtr.Zero && className(window) is "Shell_TrayWnd" or "Shell_SecondaryTrayWnd") return edge;
        }
        return null;
    }
}

/// <summary>按触发位置和任务栏方向定位面板，并限制在屏幕工作区域内。</summary>
internal static class PanelPlacement
{
    public static Size Fit(Size preferred, Rectangle work)
    {
        int width = Math.Max(1, work.Width - 24), height = Math.Max(1, work.Height - 24);
        return new Size(Math.Clamp(preferred.Width, 1, width), Math.Clamp(preferred.Height, 1, height));
    }

    public static Point Find(Rectangle screen, Rectangle work, Size window, Point cursor, bool anchorToCursor, TaskbarEdge? autoHideEdge = null)
    {
        const int gap = 12;
        int minX = work.Left, maxX = Math.Max(minX, work.Right - window.Width);
        int minY = work.Top, maxY = Math.Max(minY, work.Bottom - window.Height);
        int left = Math.Max(0, work.Left - screen.Left), right = Math.Max(0, screen.Right - work.Right);
        int top = Math.Max(0, work.Top - screen.Top), bottom = Math.Max(0, screen.Bottom - work.Bottom);
        int largest = Math.Max(Math.Max(left, right), Math.Max(top, bottom));
        int padMinX = Math.Min(maxX, minX + gap), padMaxX = Math.Max(padMinX, maxX - gap);
        int padMinY = Math.Min(maxY, minY + gap), padMaxY = Math.Max(padMinY, maxY - gap);
        int alongX = anchorToCursor ? Math.Clamp(cursor.X - window.Width / 2, padMinX, padMaxX) : padMaxX;
        int alongY = anchorToCursor ? Math.Clamp(cursor.Y - window.Height / 2, padMinY, padMaxY) : padMaxY;
        if (autoHideEdge.HasValue) return autoHideEdge.Value switch {
            TaskbarEdge.Left => new Point(Math.Min(maxX, minX + gap), alongY),
            TaskbarEdge.Right => new Point(Math.Max(minX, maxX - gap), alongY),
            TaskbarEdge.Top => new Point(alongX, Math.Min(maxY, minY + gap)),
            _ => new Point(alongX, Math.Max(minY, maxY - gap)) };
        if (largest > 0 && left == largest) return new Point(Math.Min(maxX, minX + gap), alongY);
        if (largest > 0 && right == largest) return new Point(Math.Max(minX, maxX - gap), alongY);
        if (largest > 0 && top == largest) return new Point(alongX, Math.Min(maxY, minY + gap));
        return new Point(alongX, Math.Max(minY, maxY - gap));
    }
}
