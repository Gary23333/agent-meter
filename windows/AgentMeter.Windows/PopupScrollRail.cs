using System.Drawing.Drawing2D;

namespace AgentMeter.Windows;

/// <summary>原生滚动仍由内容面板负责；细轨道提供拖动入口，避免浅色系统滚动条破坏深色弹层。</summary>
internal sealed class PopupScrollRail(FlowLayoutPanel content) : Control
{
    Color thumbColor = Color.Gray;
    bool dragging;
    int dragOffset;
    public Color ThumbColor { set { thumbColor = value; Invalidate(); } }
    int Maximum => content.VerticalScroll.Visible ? Math.Max(0, content.VerticalScroll.Maximum - content.VerticalScroll.LargeChange + 1) : 0;
    Rectangle Thumb
    {
        get
        {
            if (Maximum == 0 || Height <= 8) return Rectangle.Empty;
            int length = Math.Clamp((int)((double)Height * content.ClientSize.Height / (content.ClientSize.Height + Maximum)), Math.Min(24, Height), Height);
            int top = (int)((double)-content.AutoScrollPosition.Y / Maximum * (Height - length));
            return new Rectangle(1, Math.Clamp(top, 0, Height - length), Math.Max(1, Width - 2), length);
        }
    }
    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        var thumb = Thumb;
        if (thumb.IsEmpty) return;
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        using var path = new GraphicsPath();
        int diameter = thumb.Width;
        path.AddArc(thumb.Left, thumb.Top, diameter, diameter, 180, 180);
        path.AddArc(thumb.Left, thumb.Bottom - diameter, diameter, diameter, 0, 180); path.CloseFigure();
        using var fill = new SolidBrush(thumbColor); e.Graphics.FillPath(fill, path);
    }
    protected override void OnMouseDown(MouseEventArgs e)
    {
        base.OnMouseDown(e);
        if (e.Button != MouseButtons.Left || Thumb.IsEmpty) return;
        dragOffset = Thumb.Contains(e.Location) ? e.Y - Thumb.Top : Thumb.Height / 2;
        dragging = Capture = true; MoveTo(e.Y);
    }
    protected override void OnMouseMove(MouseEventArgs e) { base.OnMouseMove(e); if (dragging) MoveTo(e.Y); }
    protected override void OnMouseUp(MouseEventArgs e) { base.OnMouseUp(e); dragging = Capture = false; }
    protected override void OnMouseWheel(MouseEventArgs e)
    {
        base.OnMouseWheel(e);
        content.AutoScrollPosition = new Point(0, Math.Max(0, -content.AutoScrollPosition.Y - e.Delta)); Invalidate();
    }
    void MoveTo(int y)
    {
        int track = Height - Thumb.Height;
        if (track <= 0) return;
        int offset = (int)(Math.Clamp((double)(y - dragOffset) / track, 0, 1) * Maximum);
        content.AutoScrollPosition = new Point(0, offset); Invalidate();
    }
}
