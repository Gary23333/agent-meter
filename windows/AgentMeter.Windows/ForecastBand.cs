using System.Drawing.Drawing2D;

namespace AgentMeter.Windows;

/// <summary>圆点表示加权中位数，色带表示站点最小值到最大值，不是统计置信区间。</summary>
internal sealed class ForecastBand(VisualTheme theme, ForecastRange range) : Control
{
    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        if (Width < 20 || Height < 10) return;
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        float y = Height / 2F;
        float X(double value) => 5 + (Width - 10) * (float)value / 100;
        using var track = new Pen(theme.Border, 5) { StartCap = LineCap.Round, EndCap = LineCap.Round };
        using var spread = new Pen(Color.FromArgb(130, theme.Accent), 5) { StartCap = LineCap.Round, EndCap = LineCap.Round };
        using var dot = new SolidBrush(theme.Accent);
        e.Graphics.DrawLine(track, 5, y, Width - 5, y);
        e.Graphics.DrawLine(spread, X(range.Minimum), y, X(range.Maximum), y);
        e.Graphics.FillEllipse(dot, X(range.Median) - 5, y - 5, 10, 10);
    }
}
