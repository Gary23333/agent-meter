using System.Drawing.Drawing2D;
using System.Globalization;
using System.Text.Json;

namespace AgentMeter.Windows;

internal sealed partial class MeterWindow
{
    void AddBudgetProgress(JsonElement budget)
    {
        string state = GetString(budget, "status", "disabled");
        if (state == "loading") { AddCard("预算", "正在计算", "等待最新本机估算", null); return; }
        if (state is "invalid" or "error")
        {
            string errorHint = GetString(budget, "reason", "") == "budget_price_invalid"
                ? "价格文件无法读取，请检查自定义模型价格" : "请备份并检查本地预算设置与历史文件";
            AddCard("预算", "暂时无法计算", errorHint, null); return;
        }
        if (state != "ok") return;
        var rows = new List<(string Label, decimal? Spent, decimal Limit, bool Partial)>();
        foreach (var (key, label) in new[] { ("daily", "今日"), ("weekly", "本周") })
        {
            var section = GetValue(budget, key);
            decimal? limit = BudgetAmount(section, "budget_cny"), spent = BudgetAmount(section, "spent_cny");
            if (limit.HasValue) rows.Add((label, spent, limit.Value, GetValue(section, "partial").ValueKind == JsonValueKind.True));
        }
        if (rows.Count == 0) return;
        var card = new RoundedCard(theme) { Name = "budget-progress", Height = 63 + rows.Count * 42, Margin = new Padding(0, 0, 0, 12), BackColor = Card };
        var bold = new Font(Font.FontFamily, 9F, FontStyle.Bold); card.Disposed += (_, _) => bold.Dispose();
        var title = new Label { Text = "预算进度", Font = bold, AutoSize = true, ForeColor = Primary, Location = new Point(16, 10) };
        var hint = new Label { Text = "本机估算 · 非账单", Font = tabCompact, ForeColor = Muted, AutoSize = false,
            AutoEllipsis = true, TextAlign = ContentAlignment.MiddleRight, Height = 20, Top = 9 };
        card.Controls.AddRange([title, hint]);
        card.Resize += (_, _) => { hint.Left = Math.Max(100, card.ClientSize.Width - 150); hint.Width = Math.Max(0, card.ClientSize.Width - hint.Left - 16); };
        for (int i = 0; i < rows.Count; i++)
        {
            var row = rows[i]; int y = 34 + i * 42;
            var name = new Label { Text = row.Label, ForeColor = Muted, AutoSize = true, Location = new Point(16, y) };
            string spent = row.Spent.HasValue ? BudgetMoney(row.Spent.Value) : "—";
            var value = new Label { Name = "budget-" + (i == 0 ? "first" : "second"),
                Text = spent + " / " + BudgetMoney(row.Limit) + (row.Partial ? " · 部分" : ""),
                AutoSize = false, AutoEllipsis = true, TextAlign = ContentAlignment.MiddleRight, ForeColor = row.Spent > row.Limit ? Color.Orange : Primary,
                Height = 21, Top = y };
            card.Resize += (_, _) => { value.Left = Math.Max(85, card.ClientSize.Width - 210); value.Width = Math.Max(0, card.ClientSize.Width - value.Left - 16); };
            card.Controls.AddRange([name, value]);
            int barY = y + 25;
            card.Paint += (_, e) => {
                float width = Math.Max(0, card.ClientSize.Width - 32); if (width < 1) return;
                e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
                using var track = new SolidBrush(theme.Border);
                using var trackPath = UsageSourcePill(new RectangleF(16, barY, width, 5)); e.Graphics.FillPath(track, trackPath);
                if (!row.Spent.HasValue || row.Limit <= 0 || row.Spent.Value <= 0) return;
                float filled = width * (float)Math.Clamp(row.Spent.Value / row.Limit, 0m, 1m);
                using var fill = new SolidBrush(row.Spent > row.Limit ? Color.Orange : theme.Accent);
                using var fillPath = UsageSourcePill(new RectangleF(16, barY, Math.Max(1, filled), 5)); e.Graphics.FillPath(fill, fillPath);
            };
            popupTips.SetToolTip(value, "北京时间自然日／周 · 本机价格表估算 · 美元按 1:7.25 换算" + (row.Partial ? " · 部分记录未计入" : ""));
        }
        var footnote = new Label { Text = "固定汇率 1:7.25 · 缺失来源不视为零", Font = tabCompact, ForeColor = Muted, AutoSize = false,
            AutoEllipsis = true, Height = 20, Left = 16, Top = card.Height - 25 };
        card.Resize += (_, _) => footnote.Width = Math.Max(0, card.ClientSize.Width - 32);
        card.Controls.Add(footnote); StyleCard(card); content.Controls.Add(card);
    }
    static decimal? BudgetAmount(JsonElement value, string key)
    {
        string raw = GetString(value, key, "");
        return decimal.TryParse(raw, NumberStyles.Float, CultureInfo.InvariantCulture, out var amount) && amount >= 0 && amount <= 1_000_000_000_000_000m ? amount : null;
    }
    static string BudgetMoney(decimal amount) => amount is > 0 and < 0.01m ? "<¥0.01" :
        "¥" + Math.Round(amount, 2, MidpointRounding.AwayFromZero).ToString("0.##", CultureInfo.InvariantCulture);
}
