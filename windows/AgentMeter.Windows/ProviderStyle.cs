using System.Drawing.Drawing2D;

using static AgentMeter.Windows.UiScale;

namespace AgentMeter.Windows;

/// <summary>沿用原版的服务色与通用语义图形，保留账户别名。</summary>
internal sealed record ProviderStyle(string DisplayName, string Initial, Color Color)
{
    public static ProviderStyle For(string provider)
    {
        var choices = new (string Prefix, string Display, string Initial, Color Color)[]
        {
            ("CODEX", "Codex", "C", Color.FromArgb(18, 164, 129)),
            ("CLAUDE CODE", "Claude Code", "✦", Color.FromArgb(202, 105, 73)),
            ("KIMI CODE", "Kimi Code", "K", Color.FromArgb(70, 121, 229)),
            ("MINIMAX CODE", "MiniMax Code", "M", Color.FromArgb(212, 72, 132)),
            ("WORKBUDDY", "WorkBuddy", "W", Color.FromArgb(71, 145, 215)),
            ("ZCODE", "ZCode", "Z", Color.FromArgb(72, 111, 229)),
            ("火山方舟", "火山方舟", "火", Color.FromArgb(235, 106, 55)),
            ("GEMINI CLI", "Gemini CLI", "G", Color.FromArgb(73, 128, 215)),
            ("DEEPSEEK HARNESS", "DeepSeek Harness", "D", Color.FromArgb(76, 122, 225)),
            ("DEEPSEEK API", "DeepSeek API", "D", Color.FromArgb(76, 122, 225)),
            ("QODER CN", "Qoder CN", "Q", Color.FromArgb(106, 112, 218)),
            ("TRAE CN", "TRAE CN", "T", Color.FromArgb(43, 184, 140)),
            ("OPENCODE", "OpenCode", "O", Color.FromArgb(126, 100, 215)),
            ("MIMO CODE", "MiMo Code", "M", Color.FromArgb(223, 133, 48)),
            ("MIMO 平台", "MiMo 平台", "M", Color.FromArgb(223, 133, 48)),
            ("DEVECO", "DevECo", "D", Color.FromArgb(100, 138, 180)),
        };
        foreach (var choice in choices)
            if (provider.StartsWith(choice.Prefix, StringComparison.OrdinalIgnoreCase))
                return new ProviderStyle(choice.Display + provider[choice.Prefix.Length..], choice.Initial, choice.Color);
        return new ProviderStyle(provider, "•", Color.FromArgb(104, 126, 176));
    }
}

/// <summary>账户分组标记，同时保留可访问的文字名称。</summary>
internal sealed class ProviderMark : Control
{
    readonly ProviderStyle provider;
    public ProviderMark(ProviderStyle provider)
    {
        this.provider = provider;
        SetStyle(ControlStyles.SupportsTransparentBackColor, true);
        BackColor = Color.Transparent; DoubleBuffered = true;
        AccessibleRole = AccessibleRole.Graphic; AccessibleName = provider.DisplayName;
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        if (Width < 2 || Height < 2) return;
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        var bounds = new Rectangle(0, 0, Width - 1, Height - 1);
        int r = Math.Min(12, Math.Min(bounds.Width, bounds.Height));
        using var shape = new GraphicsPath();
        shape.AddArc(bounds.Left, bounds.Top, r, r, 180, 90);
        shape.AddArc(bounds.Right - r, bounds.Top, r, r, 270, 90);
        shape.AddArc(bounds.Right - r, bounds.Bottom - r, r, r, 0, 90);
        shape.AddArc(bounds.Left, bounds.Bottom - r, r, r, 90, 90);
        shape.CloseFigure();
        using var fill = new LinearGradientBrush(bounds, provider.Color,
            Color.FromArgb((int)(provider.Color.R * .7), (int)(provider.Color.G * .7), (int)(provider.Color.B * .7)), 90F);
        e.Graphics.FillPath(fill, shape);
        var saved = e.Graphics.Save();
        e.Graphics.ScaleTransform(Width / 36F, Height / 36F);
        using var pen = new Pen(Color.White, 2.5F) { StartCap = LineCap.Round, EndCap = LineCap.Round, LineJoin = LineJoin.Round };
        bool drawn = true;
        if (provider.DisplayName.StartsWith("Codex", StringComparison.OrdinalIgnoreCase))
        {
            e.Graphics.DrawLines(pen, [new PointF(11, 12), new PointF(6, 18), new PointF(11, 24)]);
            e.Graphics.DrawLines(pen, [new PointF(25, 12), new PointF(30, 18), new PointF(25, 24)]);
            e.Graphics.DrawLine(pen, 21, 10, 15, 26);
        }
        else if (provider.DisplayName.StartsWith("Claude", StringComparison.OrdinalIgnoreCase))
        {
            for (int i = 0; i < 8; i++) { double a = i * Math.PI / 4; e.Graphics.DrawLine(pen, 18 + (float)Math.Cos(a) * 5, 18 + (float)Math.Sin(a) * 5, 18 + (float)Math.Cos(a) * 11, 18 + (float)Math.Sin(a) * 11); }
        }
        else if (provider.DisplayName.StartsWith("Kimi", StringComparison.OrdinalIgnoreCase))
        {
            e.Graphics.DrawArc(pen, 9, 8, 18, 20, 55, 255);
            e.Graphics.DrawArc(pen, 16, 6, 13, 16, 70, 175);
            e.Graphics.DrawLine(pen, 26, 8, 26, 14); e.Graphics.DrawLine(pen, 23, 11, 29, 11);
        }
        else if (provider.DisplayName.StartsWith("TRAE", StringComparison.OrdinalIgnoreCase))
        {
            e.Graphics.DrawPolygon(pen, [new PointF(18, 8), new PointF(28, 26), new PointF(8, 26)]);
            e.Graphics.DrawLine(pen, 13, 22, 23, 22);
        }
        else if (provider.DisplayName.StartsWith("Qoder", StringComparison.OrdinalIgnoreCase))
        {
            PointF[] outline = [new(18, 7), new(28, 12), new(28, 24), new(18, 29), new(8, 24), new(8, 12), new(18, 7)];
            e.Graphics.DrawLines(pen, outline);
            e.Graphics.DrawLines(pen, [new PointF(8, 12), new PointF(18, 18), new PointF(28, 12)]);
            e.Graphics.DrawLine(pen, 18, 18, 18, 29);
        }
        else drawn = false;
        e.Graphics.Restore(saved);
        if (drawn) return;
        using var font = new Font(Font.FontFamily, 13F, FontStyle.Bold);
        TextRenderer.DrawText(e.Graphics, provider.Initial, font, bounds, Color.White,
            TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.NoPadding);
    }
}
