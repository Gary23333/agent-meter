using System.Drawing.Drawing2D;

namespace AgentMeter.Windows;

/// <summary>显示单个本机账本的逐日用量，不把走势解释为账户额度。</summary>
internal sealed class TokenSparkline : Control
{
    readonly IReadOnlyList<double> values;
    readonly Color accent;
    public TokenSparkline(IReadOnlyList<double> values, Color accent)
    {
        this.values = values; this.accent = accent;
        SetStyle(ControlStyles.SupportsTransparentBackColor, true);
        BackColor = Color.Transparent; DoubleBuffered = true;
        AccessibleRole = AccessibleRole.Graphic;
        AccessibleName = "本机 Token 近 30 个自然日，依次为 " + string.Join("、", values.Select(value => value.ToString("0")));
    }
    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        if (values.Count < 2 || Width < 4 || Height < 4) return;
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        double maximum = Math.Max(1, values.Max());
        float bottom = Height - 3, top = 4;
        var points = values.Select((value, index) => new PointF(
            1 + (Width - 3F) * index / (values.Count - 1),
            bottom - (float)(value / maximum) * (bottom - top))).ToArray();
        using var area = new GraphicsPath();
        area.AddLines(points); area.AddLine(points[^1], new PointF(points[^1].X, bottom));
        area.AddLine(new PointF(points[^1].X, bottom), new PointF(points[0].X, bottom));
        area.CloseFigure();
        using var fill = new LinearGradientBrush(new Rectangle(0, 0, Width, Height),
            Color.FromArgb(70, accent), Color.FromArgb(0, accent), 90F);
        e.Graphics.FillPath(fill, area);
        using var line = new Pen(accent, 2) { LineJoin = LineJoin.Round, StartCap = LineCap.Round, EndCap = LineCap.Round };
        e.Graphics.DrawLines(line, points);
    }
}
