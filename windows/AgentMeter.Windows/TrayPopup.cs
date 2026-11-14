using System.Drawing.Drawing2D;
using System.Runtime.InteropServices;

namespace AgentMeter.Windows;

internal sealed partial class MeterWindow
{
    readonly bool popup;
    bool popupPinned, popupMenuVisible, suppressPopupDismissal;
    readonly PopupAction pinAction = new(PopupActionKind.Pin), menuAction = new(PopupActionKind.Menu);
    readonly ToolTip popupTips = new();
    AgentBrandMark? appMark;
    long autoDismissedAt;
    Point autoDismissedPoint;
    public bool JustDismissedAtCursor => Environment.TickCount64 - autoDismissedAt < 350 &&
        Math.Abs(Cursor.Position.X - autoDismissedPoint.X) <= 4 && Math.Abs(Cursor.Position.Y - autoDismissedPoint.Y) <= 4;
    public event Action<Point>? MenuRequested;
    public bool PopupMenuVisible { set { popupMenuVisible = value; if (!value) QueuePopupDismissal(); } }

    void InitializePopup()
    {
        Padding = new Padding(1);
        DoubleBuffered = true;
        if (popup)
        {
            FormBorderStyle = FormBorderStyle.None; ShowInTaskbar = false;
            MaximizeBox = MinimizeBox = false;
            Deactivate += (_, _) => QueuePopupDismissal();
        }
        appMark = new AgentBrandMark { Location = new Point(18, 18), Size = new Size(36, 36), BackColor = Background };
        header.Controls.Add(appMark);
        pinAction.AccessibleName = "固定弹出面板"; menuAction.AccessibleName = "更多设置";
        pinAction.Click += (_, _) => { popupPinned = !popupPinned; pinAction.Active = popupPinned; pinAction.Invalidate();
            popupTips.SetToolTip(pinAction, popupPinned ? "取消固定 · 点击外部可收起" : "固定面板 · 点击外部不收起"); };
        menuAction.Click += (_, _) => MenuRequested?.Invoke(new Point(menuAction.Left, menuAction.Bottom + 6));
        popupTips.SetToolTip(pinAction, "固定面板 · 点击外部不收起"); popupTips.SetToolTip(menuAction, "账户、外观及更多设置");
        popupTips.SetToolTip(refresh, "刷新用量");
        header.Controls.AddRange([pinAction, menuAction]);
        header.Resize += (_, _) => LayoutPopupActions();
        ApplyPopupTheme(); LayoutPopupActions();
    }
    void LayoutPopupActions()
    {
        menuAction.Bounds = new Rectangle(header.Width - 46, 20, 30, 30);
        pinAction.Bounds = new Rectangle(header.Width - 81, 20, 30, 30);
        refresh.Bounds = new Rectangle(header.Width - 116, 20, 30, 30);
    }
    void ApplyPopupTheme()
    {
        pinAction.Theme = menuAction.Theme = theme;
        navigationStrip.BackColor = Card;
        if (refresh is PopupAction action) action.Theme = theme;
        if (appMark is not null) appMark.BackColor = Background;
        ApplyNativePopupFrame();
        Invalidate();
    }
    void QueuePopupDismissal()
    {
        if (!popup || suppressPopupDismissal || !IsHandleCreated || IsDisposed || Disposing) return;
        BeginInvoke(() => {
            if (ShouldDismissPopup()) { autoDismissedAt = Environment.TickCount64; autoDismissedPoint = Cursor.Position; Hide(); }
        });
    }
    bool ShouldDismissPopup() => popup && !IsDisposed && !Disposing && !suppressPopupDismissal && !popupPinned && !popupMenuVisible &&
        Visible && Enabled && !ContainsFocus && ActiveForm != this && !OwnedForms.Any(form => form.Visible);

    protected override bool ProcessCmdKey(ref Message message, Keys keyData)
    {
        if (popup && keyData == Keys.Escape && !popupMenuVisible) { Hide(); return true; }
        if (!popupMenuVisible && keyData is Keys.PageDown or Keys.PageUp or Keys.Home or Keys.End)
        {
            int position = -content.AutoScrollPosition.Y;
            position = keyData switch { Keys.Home => 0, Keys.End => content.VerticalScroll.Maximum,
                Keys.PageDown => position + content.Height - 40, _ => Math.Max(0, position - content.Height + 40) };
            content.AutoScrollPosition = new Point(0, position); scrollRail?.Invalidate(); return true;
        }
        return base.ProcessCmdKey(ref message, keyData);
    }
    protected override CreateParams CreateParams
    {
        get { var parameters = base.CreateParams; if (popup) parameters.ClassStyle |= 0x20000; return parameters; }
    }
    protected override void OnHandleCreated(EventArgs e) { base.OnHandleCreated(e); ApplyNativePopupFrame(); }
    protected override void OnSizeChanged(EventArgs e) { base.OnSizeChanged(e); ApplyNativePopupFrame(); }
    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        using var border = new Pen(theme.Border);
        e.Graphics.DrawRectangle(border, 0, 0, Width - 1, Height - 1);
    }
    void ApplyNativePopupFrame()
    {
        if (!popup || !IsHandleCreated || Width < 2 || Height < 2) return;
        if (OperatingSystem.IsWindowsVersionAtLeast(10, 0, 22000))
        {
            // Windows 11 由窗口管理器绘制圆角，避免逐像素透明造成字体模糊。
            int corner = 2, dark = theme.Light ? 0 : 1;
            int border = theme.Border.R | theme.Border.G << 8 | theme.Border.B << 16;
            _ = DwmSetWindowAttribute(Handle, 33, ref corner, 4);
            _ = DwmSetWindowAttribute(Handle, 20, ref dark, 4);
            _ = DwmSetWindowAttribute(Handle, 34, ref border, 4);
        }
        else
        {
            using var path = new GraphicsPath();
            int diameter = Math.Max(12, 20 * DeviceDpi / 96), w = Width, h = Height;
            path.AddArc(0, 0, diameter, diameter, 180, 90); path.AddArc(w - diameter, 0, diameter, diameter, 270, 90);
            path.AddArc(w - diameter, h - diameter, diameter, diameter, 0, 90); path.AddArc(0, h - diameter, diameter, diameter, 90, 90); path.CloseFigure();
            var previous = Region; Region = new Region(path); previous?.Dispose();
        }
    }
    [DllImport("dwmapi.dll")]
    static extern int DwmSetWindowAttribute(IntPtr window, int attribute, ref int value, int size);

    internal async Task SyntheticPopupSmokeAsync()
    {
        if (!demo || !popup) throw new InvalidOperationException("需要隔离演示弹层");
        await RefreshData();
        if (FormBorderStyle != FormBorderStyle.None || ShowInTaskbar) throw new InvalidOperationException("弹层不应具有普通窗口外框");
        SetView(View.Accounts);
        if (!gauges.Visible || header.Height != 234) throw new InvalidOperationException("账户页布局错误");
        SetView(View.Forecast);
        if (gauges.Visible || header.Height != 118) throw new InvalidOperationException("紧凑页面布局错误");
        using var other = new Form { StartPosition = FormStartPosition.Manual, Location = new Point(-31000, -31000), ShowInTaskbar = false };
        pinAction.PerformClick(); other.Show(); other.Activate(); await Task.Delay(150);
        if (!Visible || !popupPinned) throw new InvalidOperationException("固定面板被意外收起");
        Activate(); pinAction.PerformClick();
        popupMenuVisible = true; other.Activate(); await Task.Delay(100);
        if (!Visible) throw new InvalidOperationException("菜单打开时面板被收起");
        popupMenuVisible = false;
        Activate(); await Task.Delay(100);
        using (var owned = new Form { StartPosition = FormStartPosition.Manual, Location = new Point(-31000, -31000), ShowInTaskbar = false })
        {
            owned.Show(this); owned.Activate(); await Task.Delay(100);
            if (!Visible) throw new InvalidOperationException("子窗口打开时面板被收起");
            owned.Close();
        }
        Activate(); await Task.Delay(100); other.Activate(); await Task.Delay(150);
        if (Visible) throw new InvalidOperationException("失焦后未收起弹层");
        Show(); Activate();
        Message message = default;
        if (!ProcessCmdKey(ref message, Keys.Escape) || Visible) throw new InvalidOperationException("Esc 未收起弹层");
    }
}

/// <summary>按上游 MIT 项目 BrandMark.swift 的双额度环与星芒重绘，保持品牌识别。</summary>
internal sealed class AgentBrandMark : Control
{
    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        e.Graphics.ScaleTransform(Width / 36F, Height / 36F);
        using var shape = new GraphicsPath();
        const int r = 13;
        shape.AddArc(0, 0, r, r, 180, 90); shape.AddArc(36 - r, 0, r, r, 270, 90);
        shape.AddArc(36 - r, 36 - r, r, r, 0, 90); shape.AddArc(0, 36 - r, r, r, 90, 90); shape.CloseFigure();
        using var fill = new LinearGradientBrush(new Rectangle(0, 0, 36, 36), Color.FromArgb(91, 116, 255), Color.FromArgb(180, 92, 250), 45F);
        e.Graphics.FillPath(fill, shape);
        using var outer = new Pen(Color.White, 2.8F) { StartCap = LineCap.Round, EndCap = LineCap.Round };
        using var inner = new Pen(Color.FromArgb(136, 255, 225), 2.3F) { StartCap = LineCap.Round, EndCap = LineCap.Round };
        e.Graphics.DrawArc(outer, 5.3F, 7.2F, 25.4F, 25.4F, 135, 230);
        e.Graphics.DrawArc(inner, 9.7F, 11.6F, 16.6F, 16.6F, 135, 195);
        using var star = new GraphicsPath();
        star.AddBezier(18, 15, 18.6F, 18.7F, 19.3F, 19.4F, 23, 20);
        star.AddBezier(23, 20, 19.3F, 20.6F, 18.6F, 21.3F, 18, 25);
        star.AddBezier(18, 25, 17.4F, 21.3F, 16.7F, 20.6F, 13, 20);
        star.AddBezier(13, 20, 16.7F, 19.4F, 17.4F, 18.7F, 18, 15);
        e.Graphics.FillPath(Brushes.White, star);
    }
}

internal enum PopupActionKind { Refresh, Pin, Menu }

internal sealed class PopupAction(PopupActionKind kind) : Button
{
    VisualTheme theme = VisualThemes.Find("aurora");
    bool hover;
    public bool Active { get; set; }
    public VisualTheme Theme { set { theme = value; BackColor = value.Background; Invalidate(); } }
    protected override void OnMouseEnter(EventArgs e) { hover = true; base.OnMouseEnter(e); Invalidate(); }
    protected override void OnMouseLeave(EventArgs e) { hover = false; base.OnMouseLeave(e); Invalidate(); }
    protected override void OnPaint(PaintEventArgs e)
    {
        e.Graphics.Clear(theme.Background); e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        if (hover || Active) { using var fill = new SolidBrush(Active ? theme.Selected : theme.Card); e.Graphics.FillEllipse(fill, 1, 1, Width - 2, Height - 2); }
        using var pen = new Pen(Active ? Color.White : theme.Secondary, 1.8F) { StartCap = LineCap.Round, EndCap = LineCap.Round };
        float x = Width / 2F, y = Height / 2F;
        if (kind == PopupActionKind.Refresh)
        {
            e.Graphics.DrawArc(pen, x - 7, y - 7, 14, 14, 15, 290);
            e.Graphics.DrawLines(pen, [new PointF(x + 1, y - 9), new PointF(x + 5, y - 5), new PointF(x + 1, y - 3)]);
        }
        else if (kind == PopupActionKind.Pin)
        {
            e.Graphics.DrawLines(pen, [new PointF(x - 4, y - 7), new PointF(x + 4, y - 7), new PointF(x + 3, y - 1), new PointF(x + 6, y + 3), new PointF(x - 6, y + 3), new PointF(x - 3, y - 1), new PointF(x - 4, y - 7)]);
            e.Graphics.DrawLine(pen, x, y + 3, x, y + 9);
        }
        else
        {
            using var brush = new SolidBrush(theme.Secondary);
            for (int i = -1; i <= 1; i++) e.Graphics.FillEllipse(brush, x - 1.5F + i * 6, y - 1.5F, 3, 3);
        }
        if (Focused && ShowFocusCues) ControlPaint.DrawFocusRectangle(e.Graphics, new Rectangle(3, 3, Width - 6, Height - 6));
    }
}
