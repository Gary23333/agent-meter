using System.Drawing.Drawing2D;

namespace AgentMeter.Windows;

/// <summary>按已验证的互斥 Token 分类绘制圆环；缓存比例的分母仅包含已分类输入。</summary>
internal sealed class UsageCompositionRing : Control
{
    readonly double[] parts;
    readonly VisualTheme theme;
    readonly double? hitRate;
    public UsageCompositionRing(double[] parts, VisualTheme theme)
    {
        this.parts = (double[])parts.Clone(); this.theme = theme; hitRate = UsageBreakdown.CacheHitRate(parts);
        SetStyle(ControlStyles.SupportsTransparentBackColor, true);
        BackColor = Color.Transparent; DoubleBuffered = true;
        AccessibleName = "用量构成，缓存命中 " + (hitRate.HasValue ? $"{hitRate.Value * 100:0.#}%" : "未知");
    }
    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        if (Width < 40 || Height < 40) return;
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        int size = Math.Min(Width, Height), inset = Math.Max(10, size / 9);
        var bounds = new Rectangle((Width - size) / 2 + inset, (Height - size) / 2 + inset, size - 2 * inset, size - 2 * inset);
        using var track = new Pen(theme.Border, Math.Max(8, size / 9F));
        e.Graphics.DrawEllipse(track, bounds);
        double total = parts.Sum(), start = -90;
        var colors = UsagePalette.ColorsFor(theme);
        if (total > 0 && double.IsFinite(total))
            for (int i = 0; i < parts.Length; i++)
            {
                double sweep = parts[i] / total * 360;
                if (sweep <= 0) continue;
                double gap = Math.Min(2, sweep / 3);
                using var pen = new Pen(colors[i], track.Width);
                e.Graphics.DrawArc(pen, bounds, (float)(start + gap / 2), (float)(sweep - gap));
                start += sweep;
            }
        using var number = new Font(Font.FontFamily, 13F, FontStyle.Bold);
        string rate = hitRate.HasValue ? $"{hitRate.Value * 100:0.#}%" : "—";
        TextRenderer.DrawText(e.Graphics, rate, number, new Rectangle(0, Height / 2 - 24, Width, 27), theme.Primary,
            TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.SingleLine);
        TextRenderer.DrawText(e.Graphics, "缓存命中", Font, new Rectangle(0, Height / 2 + 3, Width, 21), theme.Secondary,
            TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.SingleLine);
    }
}

internal static class UsagePalette
{
    static readonly Color[] Dark = [Color.FromArgb(95, 164, 255), Color.FromArgb(166, 112, 255), Color.FromArgb(69, 208, 185), Color.FromArgb(255, 176, 73), Color.FromArgb(151, 154, 168)];
    static readonly Color[] Light = [Color.FromArgb(35, 94, 180), Color.FromArgb(105, 55, 160), Color.FromArgb(15, 111, 97), Color.FromArgb(149, 84, 0), Color.FromArgb(89, 95, 112)];
    public static Color[] ColorsFor(VisualTheme theme) => theme.Light ? Light : Dark;
}
