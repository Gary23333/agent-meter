using System.Drawing.Drawing2D;

namespace AgentMeter.Windows;

/// <summary>独立绘制页面入口，并提供键盘与辅助功能操作。</summary>
internal sealed class NavigationTab : Control
{
    VisualTheme theme = VisualThemes.Find("aurora");
    bool selected, hovering;
    internal bool IsSelected => selected;
    public NavigationTab()
    {
        // 不依赖系统按钮的原生绘制，避免容器重绘时重复合成相邻选项。
        SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.Selectable, true);
        DoubleBuffered = true;
        TabStop = true; AccessibleRole = AccessibleRole.PageTab;
    }
    public void SetAppearance(VisualTheme value, bool isSelected)
    {
        theme = value; selected = isSelected; BackColor = theme.Card;
        AccessibleDescription = isSelected ? "当前页面" : "切换页面";
        Invalidate();
    }
    protected override void OnMouseEnter(EventArgs e) { hovering = true; base.OnMouseEnter(e); Invalidate(); }
    protected override void OnMouseLeave(EventArgs e) { hovering = false; base.OnMouseLeave(e); Invalidate(); }
    protected override void OnMouseDown(MouseEventArgs e) { if (e.Button == MouseButtons.Left) Focus(); base.OnMouseDown(e); }
    protected override void OnGotFocus(EventArgs e) { base.OnGotFocus(e); Invalidate(); }
    protected override void OnLostFocus(EventArgs e) { base.OnLostFocus(e); Invalidate(); }
    protected override bool IsInputKey(Keys keyData) => (keyData & Keys.KeyCode) is Keys.Enter or Keys.Space || base.IsInputKey(keyData);
    protected override void OnKeyDown(KeyEventArgs e)
    {
        base.OnKeyDown(e);
        if (e.KeyCode is Keys.Enter or Keys.Space) { e.Handled = true; e.SuppressKeyPress = true; }
    }
    protected override void OnKeyUp(KeyEventArgs e)
    {
        base.OnKeyUp(e);
        if (e.KeyCode is Keys.Enter or Keys.Space) { e.Handled = true; PerformClick(); }
    }
    public void PerformClick() { if (Enabled && Visible) OnClick(EventArgs.Empty); }
    protected override AccessibleObject CreateAccessibilityInstance() => new TabAccessibleObject(this);
    sealed class TabAccessibleObject(NavigationTab owner) : ControlAccessibleObject(owner)
    {
        public override string? DefaultAction => "切换";
        public override AccessibleStates State => base.State | (owner.selected ? AccessibleStates.Selected : AccessibleStates.None);
        public override void DoDefaultAction() => owner.PerformClick();
    }
    protected override void OnPaintBackground(PaintEventArgs e)
    {
        using var background = new SolidBrush(theme.Card);
        e.Graphics.FillRectangle(background, ClientRectangle);
    }
    protected override void OnPaint(PaintEventArgs e)
    {
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        var bounds = new Rectangle(0, 0, Width - 1, Height - 1);
        const int corner = 16;
        using var path = new GraphicsPath();
        path.AddArc(bounds.Left, bounds.Top, corner, corner, 180, 90);
        path.AddArc(bounds.Right - corner, bounds.Top, corner, corner, 270, 90);
        path.AddArc(bounds.Right - corner, bounds.Bottom - corner, corner, corner, 0, 90);
        path.AddArc(bounds.Left, bounds.Bottom - corner, corner, corner, 90, 90); path.CloseFigure();
        using var fill = new SolidBrush(selected ? theme.Selected : hovering ? theme.Border : theme.Card);
        if (selected || hovering) e.Graphics.FillPath(fill, path);
        TextRenderer.DrawText(e.Graphics, Text, Font, bounds, selected ? Color.White : theme.Primary,
            TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis |
            TextFormatFlags.PreserveGraphicsClipping | TextFormatFlags.PreserveGraphicsTranslateTransform);
        if (Focused && ShowFocusCues) ControlPaint.DrawFocusRectangle(e.Graphics, Rectangle.Inflate(bounds, -5, -5));
    }
}

internal sealed class NavigationStrip : Panel
{
    protected override void OnPaintBackground(PaintEventArgs e)
    {
        using var background = new SolidBrush(Parent?.BackColor ?? BackColor);
        e.Graphics.FillRectangle(background, ClientRectangle);
        if (Width < Height || Height < 2) return;
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        using var path = new GraphicsPath();
        path.AddArc(0, 0, Height - 1, Height - 1, 90, 180);
        path.AddArc(Width - Height, 0, Height - 1, Height - 1, 270, 180); path.CloseFigure();
        using var fill = new SolidBrush(BackColor); e.Graphics.FillPath(fill, path);
    }
    protected override void OnSizeChanged(EventArgs e)
    {
        base.OnSizeChanged(e);
        if (Width < Height || Height < 2) return;
        using var path = new GraphicsPath();
        path.AddArc(0, 0, Height, Height, 90, 180);
        path.AddArc(Width - Height, 0, Height, Height, 270, 180); path.CloseFigure();
        var previous = Region; Region = new Region(path); previous?.Dispose();
    }
}
