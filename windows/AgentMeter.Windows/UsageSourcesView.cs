using System.Drawing.Drawing2D;
using System.Text.Json;

using static AgentMeter.Windows.UiScale;

namespace AgentMeter.Windows;

internal sealed partial class MeterWindow
{
    /// <summary>按本机账本对比当前周期的 Token 与可计算费用。</summary>
    void AddUsageSources(JsonElement history)
    {
        var rows = UsageSource.Read(history, usagePeriod);
        if (rows.Count == 0) return;
        double maximum = rows[0].Tokens;
        bool partial = rows.Any(row => row.Partial) || history.EnumerateObject().Any(entry => {
            string state = GetString(entry.Value, "status", "");
            if (state == "error" || state == "unavailable" && !IsAbsent(entry.Value)) return true;
            if (state is not ("available" or "partial")) return false;
            var total = GetValue(GetValue(GetValue(GetValue(entry.Value, "value"), "periods"), usagePeriod), "totals");
            double? value = GetNumber(total, "total_tokens");
            return state == "partial" || !value.HasValue || !double.IsFinite(value.Value) || value.Value < 0;
        });
        var card = new RoundedCard(theme) { Name = "usage-sources", Height = S(35 + rows.Count * 50),
            Margin = Pad(0, 0, 0, 12), BackColor = Card };
        var bold = new Font(Font.FontFamily, 9F, FontStyle.Bold);
        card.Disposed += (_, _) => bold.Dispose();
        var title = new Label { Text = "按应用", Font = bold, AutoSize = true, ForeColor = Primary, Location = P(16, 12) };
        var note = new Label { Text = partial ? "部分来源不完整" : "本机账本 · 可能重叠", ForeColor = Muted,
            Font = tabCompact, AutoSize = false, AutoEllipsis = true, TextAlign = ContentAlignment.MiddleRight, Height = S(20), Top = S(11)};
        card.Controls.AddRange([title, note]);
        card.Resize += (_, _) => { note.Left = Math.Max(S(110), card.ClientSize.Width - S(155)); note.Width = Math.Max(S(0), card.ClientSize.Width - note.Left - S(16)); };
        for (int i = 0; i < rows.Count; i++)
        {
            var row = rows[i]; var identity = ProviderStyle.For(row.Name); int y = 39 + i * 50;
            var dot = new Label { Text = "●", ForeColor = identity.Color, AutoSize = false, Size = Sz(16, 20), Location = P(16, y) };
            var name = new Label { Name = "usage-source-name-" + i, Text = identity.DisplayName, ForeColor = Primary,
                AutoSize = false, AutoEllipsis = true, Height = S(22), Location = P(34, y) };
            var tokens = new Label { Name = "usage-source-tokens-" + i, Text = FormatNumber(row.Tokens), Font = bold,
                ForeColor = Primary, AutoSize = false, AutoEllipsis = true, TextAlign = ContentAlignment.MiddleRight, Height = S(22), Top = S(y)};
            var cost = new Label { Name = "usage-source-cost-" + i, Text = row.CostDisplay + (row.Partial && row.Cost.HasValue ? "*" : ""),
                ForeColor = Muted, Font = tabCompact, AutoSize = false, AutoEllipsis = true, TextAlign = ContentAlignment.MiddleRight, Height = S(22), Top = S(y)};
            int barY = y + 27;
            card.Paint += (_, e) => {
                float width = Math.Max(0, card.ClientSize.Width - 32);
                if (width < 1) return;
                e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
                using var track = new SolidBrush(theme.Border);
                using var fill = new SolidBrush(identity.Color);
                using var trackPath = UsageSourcePill(new RectangleF(16, barY, width, 5));
                e.Graphics.FillPath(track, trackPath);
                float filled = (float)(width * Math.Clamp(row.Tokens / maximum, 0, 1));
                if (filled <= 0) return;
                using var fillPath = UsageSourcePill(new RectangleF(16, barY, Math.Max(1, filled), 5));
                e.Graphics.FillPath(fill, fillPath);
            };
            card.Resize += (_, _) => {
                cost.Left = Math.Max(S(0), card.ClientSize.Width - S(92)); cost.Width = Math.Max(S(0), card.ClientSize.Width - cost.Left - S(16));
                tokens.Left = Math.Max(S(34), cost.Left - S(75)); tokens.Width = Math.Max(S(0), cost.Left - tokens.Left - S(5));
                name.Width = Math.Max(S(0), tokens.Left - name.Left - S(6));
            };
            popupTips.SetToolTip(name, identity.DisplayName + " · 本机账本，不按账户区分");
            popupTips.SetToolTip(tokens, row.Tokens.ToString("N0") + " Token");
            popupTips.SetToolTip(cost, row.Cost.HasValue ? row.CostDisplay + " · API 等价估算，非账单" + (row.Partial ? " · 部分数据未计入" : "") : "该来源暂无可用费用估算");
            card.Controls.AddRange([dot, name, tokens, cost]);
        }
        popupTips.SetToolTip(note, "按本机账本分别统计，不按账户区分；不同账本可能重复记录。* 表示部分数据未计入。");
        StyleCard(card); content.Controls.Add(card);
    }
    static GraphicsPath UsageSourcePill(RectangleF rect)
    {
        float diameter = Math.Min(rect.Width, rect.Height);
        var path = new GraphicsPath();
        path.AddArc(rect.X, rect.Y, diameter, rect.Height, 90, 180);
        path.AddArc(rect.Right - diameter, rect.Y, diameter, rect.Height, 270, 180);
        path.CloseFigure(); return path;
    }
}
