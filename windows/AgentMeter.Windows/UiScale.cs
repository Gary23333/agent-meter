using System.Drawing;

namespace AgentMeter.Windows;

/// <summary>
/// 统一的 DPI 缩放因子。布局像素一律以 96 DPI 的逻辑值书写，
/// 在赋给控件边界（Location/Size/Bounds/Padding 等）时经 S/P/Sz/Pad/Rect 缩放，
/// 使其与按磅值渲染、随 DPI 自动放大的字体保持一致。内部累加变量保持逻辑值，
/// 只在边界处缩放一次，避免重复缩放。跨屏 DPI 变化时由窗体更新 Factor 并重建。
/// </summary>
internal static class UiScale
{
    public static float Factor = 1f;

    public static void SetFromDpi(int deviceDpi)
    {
        float f = deviceDpi / 96f;
        Factor = f > 0.25f && f < 8f ? f : 1f;
    }

    public static int S(int value) => (int)Math.Round(value * Factor);
    public static int S(double value) => (int)Math.Round(value * Factor);
    public static Point P(int x, int y) => new(S(x), S(y));
    public static Size Sz(int w, int h) => new(S(w), S(h));
    public static Padding Pad(int all) => new(S(all));
    public static Padding Pad(int horizontal, int vertical) => new(S(horizontal), S(vertical), S(horizontal), S(vertical));
    public static Padding Pad(int left, int top, int right, int bottom) => new(S(left), S(top), S(right), S(bottom));
    public static Rectangle Rect(int x, int y, int w, int h) => new(S(x), S(y), S(w), S(h));
}