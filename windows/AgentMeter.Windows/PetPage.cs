using System.Drawing.Drawing2D;
using System.Text.Json;

namespace AgentMeter.Windows;

internal sealed partial class MeterWindow
{
    PetPreferences pagePetPreferences = PetPreferences.Default;
    public event Action<PetPreferences>? PetChangeRequested;

    public void SetPetPreferences(PetPreferences value)
    {
        pagePetPreferences = value;
        if (view == View.Pet && lastSnapshot is not null)
        {
            using var snapshot = JsonDocument.Parse(lastSnapshot);
            Render(snapshot.RootElement);
        }
    }
    void RequestPetChange(PetPreferences value)
    {
        if (demo) SetPetPreferences(value);
        else PetChangeRequested?.Invoke(value);
    }

    void AddPetPage(JsonElement root)
    {
        var mood = PetState.Select(root, DateTimeOffset.UtcNow.ToUnixTimeSeconds());
        var preview = new PetHero(theme, pagePetPreferences.Pack, mood) { Height = 242, Margin = new Padding(0, 0, 0, 12) };
        content.Controls.Add(preview);

        var switchCard = new RoundedCard(theme) { Height = 92, Margin = new Padding(0, 0, 0, 12), BackColor = Card };
        var heading = new Label { Text = "在桌面上陪着我", AutoSize = true, Location = new Point(17, 15), ForeColor = Primary,
            BackColor = Color.Transparent, Font = new Font(Font.FontFamily, 10F, FontStyle.Bold) };
        var detail = new Label { Text = pagePetPreferences.Enabled ? "已显示 · 可拖动调整位置" : "默认隐藏，随时可以开启", AutoSize = true,
            Location = new Point(18, 48), ForeColor = Muted, BackColor = Color.Transparent, Font = new Font(Font.FontFamily, 8.5F) };
        var toggle = new RoundedActionButton(theme) { Name = "pet-toggle", Text = pagePetPreferences.Enabled ? "隐藏" : "显示",
            Size = new Size(72, 34), Anchor = AnchorStyles.Top | AnchorStyles.Right, AccentText = true };
        switchCard.Resize += (_, _) => toggle.Location = new Point(Math.Max(180, switchCard.Width - 88), 29);
        toggle.Click += (_, _) => RequestPetChange(pagePetPreferences with { Enabled = !pagePetPreferences.Enabled });
        switchCard.Controls.AddRange([heading, detail, toggle]); content.Controls.Add(switchCard);

        AddHeading("选择形象", "内置形象 · 点击切换");
        var grid = new TableLayoutPanel { Name = "pet-choices", ColumnCount = 3, RowCount = 3, Height = 352,
            Margin = new Padding(0, 0, 0, 12), BackColor = Background };
        for (int i = 0; i < 3; i++) { grid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100F / 3)); grid.RowStyles.Add(new RowStyle(SizeType.Percent, 100F / 3)); }
        var packs = new[] { ("mochi", "麻薯"), ("bit", "比特"), ("gauge", "量量"), ("cat", "缓存猫"),
            ("bot", "码码"), ("tibo", "Tibo"), ("blob", "团团") };
        for (int i = 0; i < packs.Length; i++)
        {
            var (pack, name) = packs[i];
            var button = new PetChoiceButton(theme, pack, name, pagePetPreferences.Pack == pack)
                { Name = "pet-choice-" + pack, Dock = DockStyle.Fill, Margin = new Padding(0, 0, 8, 8) };
            button.Click += (_, _) => RequestPetChange(pagePetPreferences with { Pack = pack });
            grid.Controls.Add(button, i % 3, i / 3);
        }
        content.Controls.Add(grid);
        AddCard("桌宠状态", mood.Description, mood.Remaining.HasValue ? $"最低有效额度 {mood.Remaining.Value:0.#}% · 不同服务不能比较绝对额度" : "额度未知时不虚构数字", null,
            "状态依据近期额度和本机记录更新；形象预览为静态图");
    }
}

/// <summary>静态预览取自隔离构建机的原版渲染，不读取账户信息。</summary>
internal static class PetArt
{
    public static Bitmap Load(string pack)
    {
        if (pack is "mochi" or "bit")
        {
            using var sprite = new SpritePet(pack);
            var frame = sprite.Frame("idle", 0, 240);
            int left = frame.Width, top = frame.Height, right = -1, bottom = -1;
            for (int y = 0; y < frame.Height; y++) for (int x = 0; x < frame.Width; x++)
                if (frame.GetPixel(x, y).A > 8)
                { left = Math.Min(left, x); top = Math.Min(top, y); right = Math.Max(right, x); bottom = Math.Max(bottom, y); }
            if (right < left || bottom < top) return new Bitmap(frame);
            int padding = Math.Max(3, Math.Max(right - left, bottom - top) / 9);
            left = Math.Max(0, left - padding); top = Math.Max(0, top - padding);
            right = Math.Min(frame.Width - 1, right + padding); bottom = Math.Min(frame.Height - 1, bottom + padding);
            return frame.Clone(new Rectangle(left, top, right - left + 1, bottom - top + 1), System.Drawing.Imaging.PixelFormat.Format32bppPArgb);
        }
        using var stream = typeof(PetArt).Assembly.GetManifestResourceStream($"AgentMeter.PetPreview.{pack}.png")
            ?? throw new InvalidDataException("桌宠预览资源缺失");
        using var image = Image.FromStream(stream);
        return new Bitmap(image);
    }
    public static GraphicsPath Round(Rectangle bounds, int radius)
    {
        var path = new GraphicsPath();
        int d = Math.Min(radius, Math.Min(bounds.Width, bounds.Height));
        path.AddArc(bounds.Left, bounds.Top, d, d, 180, 90);
        path.AddArc(bounds.Right - d, bounds.Top, d, d, 270, 90);
        path.AddArc(bounds.Right - d, bounds.Bottom - d, d, d, 0, 90);
        path.AddArc(bounds.Left, bounds.Bottom - d, d, d, 90, 90); path.CloseFigure();
        return path;
    }
}

internal sealed class PetHero : Control
{
    readonly VisualTheme theme;
    readonly PetMood mood;
    readonly Bitmap art;
    public PetHero(VisualTheme theme, string pack, PetMood mood)
    {
        this.theme = theme; this.mood = mood; art = PetArt.Load(pack); DoubleBuffered = true;
        AccessibleName = "桌宠预览 · " + mood.Description;
    }
    protected override void OnPaint(PaintEventArgs e)
    {
        if (Width < 80 || Height < 100) return;
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        e.Graphics.Clear(theme.Background);
        using var outside = PetArt.Round(new Rectangle(0, 0, Width - 1, Height - 1), 24);
        using var baseFill = new SolidBrush(theme.Card);
        using var border = new Pen(theme.Border);
        e.Graphics.FillPath(baseFill, outside); e.Graphics.DrawPath(border, outside);
        var stage = new Rectangle(14, 46, Width - 28, Height - 96);
        using var shape = PetArt.Round(stage, 20);
        using var fill = new LinearGradientBrush(stage, theme.CardEnd, theme.Background, 90F);
        e.Graphics.FillPath(fill, shape);
        int h = Math.Min(stage.Height - 6, 155), w = h * art.Width / art.Height;
        e.Graphics.InterpolationMode = InterpolationMode.HighQualityBicubic;
        e.Graphics.DrawImage(art, new Rectangle(stage.Left + (stage.Width - w) / 2, stage.Top + (stage.Height - h) / 2, w, h));
        using var titleFont = new Font(Font.FontFamily, 10F, FontStyle.Bold);
        TextRenderer.DrawText(e.Graphics, mood.Description, titleFont, new Rectangle(17, 12, Width - 34, 26), theme.Primary,
            TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis | TextFormatFlags.SingleLine);
        string info = mood.Remaining.HasValue ? $"最低有效额度 {mood.Remaining.Value:0.#}%" : "额度未知 · 等待数据";
        TextRenderer.DrawText(e.Graphics, info + " · 静态预览", Font, new Rectangle(17, Height - 39, Width - 34, 25), theme.Secondary,
            TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis | TextFormatFlags.SingleLine);
    }
    protected override void Dispose(bool disposing) { if (disposing) art.Dispose(); base.Dispose(disposing); }
}

internal sealed class PetChoiceButton : Button
{
    readonly VisualTheme theme;
    readonly Bitmap art;
    readonly bool selected;
    readonly string kind;
    public PetChoiceButton(VisualTheme theme, string pack, string name, bool selected)
    {
        this.theme = theme; this.selected = selected; art = PetArt.Load(pack); Text = name;
        kind = pack is "mochi" or "bit" ? "精灵图" : "3D";
        AccessibleName = name + " · " + kind + (selected ? " · 已选择" : "");
        AccessibleRole = AccessibleRole.PushButton; FlatStyle = FlatStyle.Flat; FlatAppearance.BorderSize = 0; DoubleBuffered = true;
    }
    protected override void OnPaint(PaintEventArgs e)
    {
        if (Width < 20 || Height < 20) return;
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias; e.Graphics.Clear(Parent?.BackColor ?? theme.Background);
        using var shape = PetArt.Round(new Rectangle(1, 1, Width - 3, Height - 3), 18);
        using var fill = new SolidBrush(theme.Card); using var border = new Pen(selected ? theme.Accent : theme.Border, selected ? 2 : 1);
        e.Graphics.FillPath(fill, shape); e.Graphics.DrawPath(border, shape);
        int h = Math.Min(68, Height - 38), w = h * art.Width / art.Height;
        e.Graphics.InterpolationMode = InterpolationMode.HighQualityBicubic;
        e.Graphics.DrawImage(art, new Rectangle((Width - w) / 2, 4, w, h));
        TextRenderer.DrawText(e.Graphics, Text, Font, new Rectangle(4, h + 3, Width - 8, 21), theme.Primary,
            TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis);
        using var small = new Font(Font.FontFamily, 7F);
        TextRenderer.DrawText(e.Graphics, kind, small, new Rectangle(4, h + 24, Width - 8, 16), theme.Secondary,
            TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.SingleLine);
        if (Focused && ShowFocusCues) ControlPaint.DrawFocusRectangle(e.Graphics, Rectangle.Inflate(ClientRectangle, -6, -6));
    }
    protected override void Dispose(bool disposing) { if (disposing) art.Dispose(); base.Dispose(disposing); }
}
