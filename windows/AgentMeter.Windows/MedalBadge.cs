using System.Drawing.Drawing2D;

namespace AgentMeter.Windows;

/// <summary>使用本地矢量绘制徽章，不依赖网络或系统图标字体。</summary>
internal sealed class MedalBadge : Control
{
    readonly VisualTheme theme;
    readonly string tier;
    readonly bool earned;

    public MedalBadge(VisualTheme theme, string tier, bool earned)
    {
        this.theme = theme; this.tier = tier; this.earned = earned;
        SetStyle(ControlStyles.SupportsTransparentBackColor, true);
        BackColor = Color.Transparent;
        AccessibleRole = AccessibleRole.Graphic;
        DoubleBuffered = true;
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        var area = new Rectangle(4, 4, Math.Max(1, Width - 9), Math.Max(1, Height - 9));
        Color metal = theme.Minimal ? Color.FromArgb(208, 208, 208) : tier switch
        {
            "silver" => Color.FromArgb(174, 190, 210),
            "gold" => Color.FromArgb(240, 190, 74),
            "platinum" => Color.FromArgb(150, 208, 225),
            _ => Color.FromArgb(197, 133, 96)
        };
        Color start = earned ? Blend(metal, Color.White, 0.35) : theme.CardEnd;
        Color end = earned ? Blend(metal, Color.Black, 0.25) : theme.Card;
        Color line = earned ? Blend(metal, Color.White, 0.45) : theme.Border;
        Color symbol = earned ? Blend(metal, Color.Black, 0.48) : theme.Secondary;
        using var fill = new LinearGradientBrush(area, start, end, 45F);
        using var rim = new Pen(line, 2F);
        using var engraving = new Pen(earned ? Blend(metal, Color.Black, 0.25) : theme.Border, 1F);
        using var symbolFill = new SolidBrush(symbol);
        e.Graphics.FillEllipse(fill, area);
        e.Graphics.DrawEllipse(rim, area);
        var inside = Rectangle.Inflate(area, -6, -6);
        if (inside.Width > 0 && inside.Height > 0) e.Graphics.DrawEllipse(engraving, inside);
        float cx = area.Left + area.Width / 2F, cy = area.Top + area.Height / 2F;
        float radius = Math.Min(area.Width, area.Height) * 0.26F;
        var points = new PointF[10];
        for (int i = 0; i < points.Length; i++)
        {
            double angle = -Math.PI / 2 + i * Math.PI / 5;
            float r = i % 2 == 0 ? radius : radius * 0.45F;
            points[i] = new PointF(cx + r * (float)Math.Cos(angle), cy + r * (float)Math.Sin(angle));
        }
        e.Graphics.FillPolygon(symbolFill, points);
    }

    static Color Blend(Color a, Color b, double fraction) => Color.FromArgb(
        (int)Math.Round(a.R + (b.R - a.R) * fraction),
        (int)Math.Round(a.G + (b.G - a.G) * fraction),
        (int)Math.Round(a.B + (b.B - a.B) * fraction));
}
