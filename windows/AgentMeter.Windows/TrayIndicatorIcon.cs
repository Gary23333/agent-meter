using System.Drawing.Drawing2D;
using System.Drawing.Text;
using System.Runtime.InteropServices;

namespace AgentMeter.Windows;

/// <summary>托盘用整数近似百分比；精确值和来源放在悬停提示中，图标无需读取新数据。</summary>
internal static class TrayIndicatorIcon
{
    public static Bitmap Render(double remaining, int pixels)
    {
        if (!double.IsFinite(remaining) || remaining < 0 || remaining > 100 || pixels is < 16 or > 128) throw new ArgumentOutOfRangeException();
        var bitmap = new Bitmap(pixels, pixels);
        using var graphics = Graphics.FromImage(bitmap);
        graphics.Clear(Color.Transparent); graphics.SmoothingMode = SmoothingMode.AntiAlias;
        float scale = pixels / 16F;
        Color accent = remaining < 20 ? Color.FromArgb(255, 106, 132) : remaining < 50 ? Color.FromArgb(255, 185, 83) : Color.FromArgb(112, 237, 204);
        using var shape = new GraphicsPath();
        float r = 4 * scale, edge = pixels - scale;
        shape.AddArc(0, 0, r, r, 180, 90); shape.AddArc(edge - r, 0, r, r, 270, 90);
        shape.AddArc(edge - r, edge - r, r, r, 0, 90); shape.AddArc(0, edge - r, r, r, 90, 90); shape.CloseFigure();
        using var back = new SolidBrush(Color.FromArgb(22, 29, 43)); graphics.FillPath(back, shape);
        string text = Math.Round(remaining, MidpointRounding.AwayFromZero).ToString("0", System.Globalization.CultureInfo.InvariantCulture);
        using var font = new Font("Segoe UI", (text.Length == 3 ? 8.2F : 10.5F) * scale, FontStyle.Bold, GraphicsUnit.Pixel);
        graphics.TextRenderingHint = TextRenderingHint.AntiAliasGridFit;
        using var format = new StringFormat(StringFormat.GenericTypographic) { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Center };
        using var ink = new SolidBrush(accent);
        graphics.DrawString(text, font, ink, new RectangleF(0, 0, edge, 12 * scale), format);
        using var track = new Pen(Color.FromArgb(66, 76, 95), 1.5F * scale) { StartCap = LineCap.Round, EndCap = LineCap.Round };
        using var bar = new Pen(accent, 1.5F * scale) { StartCap = LineCap.Round, EndCap = LineCap.Round };
        graphics.DrawLine(track, 3 * scale, 13 * scale, 12 * scale, 13 * scale);
        if (remaining > 0) graphics.DrawLine(bar, 3 * scale, 13 * scale, (3 + (float)remaining / 100 * 9) * scale, 13 * scale);
        return bitmap;
    }
    public static Icon Create(double remaining)
    {
        // 32 像素资源覆盖常见缩放；通知区域可按所在屏幕缩放。
        using var bitmap = Render(remaining, 32);
        IntPtr handle = bitmap.GetHicon();
        try { using var borrowed = Icon.FromHandle(handle); return (Icon)borrowed.Clone(); }
        finally { _ = DestroyIcon(handle); }
    }
    public static Bitmap Preview()
    {
        var canvas = new Bitmap(720, 300);
        using var graphics = Graphics.FromImage(canvas);
        graphics.Clear(Color.FromArgb(245, 247, 251));
        using var font = new Font("Microsoft YaHei UI", 11, GraphicsUnit.Pixel);
        using var ink = new SolidBrush(Color.FromArgb(35, 45, 60));
        graphics.DrawString("托盘余量 · 虚构数据 · 上：原尺寸 16 / 24 / 32 px · 下：放大检查", font, ink, 20, 16);
        double[] values = [0, 2, 19, 49, 73, 100];
        for (int index = 0; index < values.Length; index++)
        {
            int x = 20 + index * 116;
            graphics.DrawString(values[index] + "% 剩余", font, ink, x, 45);
            using var source = Render(values[index], 32);
            graphics.DrawImage(source, new Rectangle(x, 72, 16, 16));
            graphics.DrawImage(source, new Rectangle(x + 23, 68, 24, 24));
            graphics.DrawImage(source, new Rectangle(x + 54, 64, 32, 32));
            using var background = new SolidBrush(Color.FromArgb(16, 22, 32));
            graphics.FillRectangle(background, x - 4, 111, 94, 46);
            graphics.DrawImage(source, new Rectangle(x, 126, 16, 16));
            graphics.DrawImage(source, new Rectangle(x + 23, 122, 24, 24));
            graphics.DrawImage(source, new Rectangle(x + 54, 118, 32, 32));
            using var large = Render(values[index], 80);
            graphics.DrawImageUnscaled(large, x, 182);
        }
        return canvas;
    }
    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    static extern bool DestroyIcon(IntPtr icon);
}
