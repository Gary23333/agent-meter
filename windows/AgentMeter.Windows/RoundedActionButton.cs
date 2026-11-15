using System.Drawing.Drawing2D;

namespace AgentMeter.Windows;

/// <summary>保留原生按钮的键盘与辅助功能，同时与托盘卡片使用一致的圆角和颜色。</summary>
internal sealed class RoundedActionButton : Button
{
    readonly VisualTheme theme;
    bool hovered, pressed;
    public RoundedActionButton(VisualTheme theme)
    {
        this.theme = theme; DoubleBuffered = true;
        SetStyle(ControlStyles.SupportsTransparentBackColor, true);
        BackColor = Color.Transparent; FlatStyle = FlatStyle.Flat; FlatAppearance.BorderSize = 0;
        AccessibleRole = AccessibleRole.PushButton;
    }
    protected override void OnMouseEnter(EventArgs e) { hovered = true; Invalidate(); base.OnMouseEnter(e); }
    protected override void OnMouseLeave(EventArgs e) { hovered = pressed = false; Invalidate(); base.OnMouseLeave(e); }
    protected override void OnMouseDown(MouseEventArgs e) { if (e.Button == MouseButtons.Left) pressed = true; Invalidate(); base.OnMouseDown(e); }
    protected override void OnMouseUp(MouseEventArgs e) { pressed = false; Invalidate(); base.OnMouseUp(e); }
    protected override void OnPaint(PaintEventArgs e)
    {
        if (Width < 20 || Height < 20) return;
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        int radius = Math.Min(14, Height - 1), right = Width - 1, bottom = Height - 1;
        using var shape = new GraphicsPath();
        shape.AddArc(0, 0, radius, radius, 180, 90); shape.AddArc(right - radius, 0, radius, radius, 270, 90);
        shape.AddArc(right - radius, bottom - radius, radius, radius, 0, 90); shape.AddArc(0, bottom - radius, radius, radius, 90, 90); shape.CloseFigure();
        using var fill = new SolidBrush(pressed || hovered ? theme.Border : theme.Card);
        using var border = new Pen(theme.Border);
        e.Graphics.FillPath(fill, shape); e.Graphics.DrawPath(border, shape);
        TextRenderer.DrawText(e.Graphics, Text, Font, ClientRectangle, Enabled ? theme.Primary : theme.Secondary,
            TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis);
        if (Focused && ShowFocusCues) ControlPaint.DrawFocusRectangle(e.Graphics, Rectangle.Inflate(ClientRectangle, -6, -6));
    }
}
