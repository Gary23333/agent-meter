using System.Drawing.Drawing2D;

namespace AgentMeter.Windows;

/// <summary>保留标准按钮的键盘与辅助功能行为，用圆角和悬停状态统一六个页面入口。</summary>
internal sealed class NavigationTab : Button
{
    VisualTheme theme = VisualThemes.Find("aurora");
    bool selected, hovering;
    public NavigationTab()
    {
        DoubleBuffered = true;
        FlatStyle = FlatStyle.Flat; FlatAppearance.BorderSize = 0;
    }
    public void SetAppearance(VisualTheme value, bool isSelected)
    {
        theme = value; selected = isSelected; BackColor = value.Background;
        AccessibleDescription = isSelected ? "当前页面" : "切换页面";
        Invalidate();
    }
    protected override void OnMouseEnter(EventArgs e) { hovering = true; base.OnMouseEnter(e); Invalidate(); }
    protected override void OnMouseLeave(EventArgs e) { hovering = false; base.OnMouseLeave(e); Invalidate(); }
    protected override void OnPaint(PaintEventArgs e)
    {
        e.Graphics.Clear(theme.Background);
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        var bounds = new Rectangle(0, 0, Width - 1, Height - 1);
        const int corner = 16;
        using var path = new GraphicsPath();
        path.AddArc(bounds.Left, bounds.Top, corner, corner, 180, 90);
        path.AddArc(bounds.Right - corner, bounds.Top, corner, corner, 270, 90);
        path.AddArc(bounds.Right - corner, bounds.Bottom - corner, corner, corner, 0, 90);
        path.AddArc(bounds.Left, bounds.Bottom - corner, corner, corner, 90, 90); path.CloseFigure();
        using var fill = new SolidBrush(selected ? theme.Selected : hovering ? theme.Border : theme.Card);
        e.Graphics.FillPath(fill, path);
        TextRenderer.DrawText(e.Graphics, Text, Font, bounds, selected ? Color.White : theme.Primary,
            TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis);
        if (Focused && ShowFocusCues) ControlPaint.DrawFocusRectangle(e.Graphics, Rectangle.Inflate(bounds, -5, -5));
    }
}
