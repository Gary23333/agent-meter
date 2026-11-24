using System.Text.Json;

using static AgentMeter.Windows.UiScale;

namespace AgentMeter.Windows;

internal sealed partial class MeterWindow
{
    void AddModelRanking(JsonElement history)
    {
        var ranking = ModelRanking.Read(history, usagePeriod);
        if (ranking.Rows.Count == 0)
        {
            if (ranking.Incomplete) AddCard("模型排行", "暂无完整模型数据", "部分来源未提供当前周期的模型明细", null);
            return;
        }
        var card = new RoundedCard(theme) { Name = "model-ranking", Height = S(46 + ranking.Rows.Count * 33),
            Margin = Pad(0, 0, 0, 12), BackColor = Card };
        var bold = new Font(Font.FontFamily, 9F, FontStyle.Bold); card.Disposed += (_, _) => bold.Dispose();
        var title = new Label { Text = "模型排行", Font = bold, AutoSize = true, ForeColor = Primary, Location = P(16, 11) };
        var note = new Label { Text = UsagePeriodLabel + (ranking.Incomplete ? " · 不完整" : " · Top 5"), Font = tabCompact,
            ForeColor = Muted, TextAlign = ContentAlignment.MiddleRight, AutoSize = false, AutoEllipsis = true, Top = S(10), Height = S(20)};
        card.Resize += (_, _) => { note.Left = Math.Max(S(100), card.ClientSize.Width - S(145)); note.Width = Math.Max(S(0), card.ClientSize.Width - note.Left - S(16)); };
        card.Controls.AddRange([title, note]);
        for (int i = 0; i < ranking.Rows.Count; i++)
        {
            var row = ranking.Rows[i]; int y = 39 + i * 33; var identity = ProviderStyle.For(row.Source);
            var model = new Label { Name = "model-rank-name-" + i, Text = row.Model, ForeColor = Primary, AutoSize = false,
                AutoEllipsis = true, Height = S(22), Location = P(16, y) };
            string shortSource = row.Source switch { "Claude Code" => "Claude", "MiniMax Code" => "MiniMax", "Kimi Code" => "Kimi",
                "Gemini CLI" => "Gemini", "DeepSeek Harness" => "DeepSeek", _ => identity.DisplayName };
            var source = new Label { Name = "model-rank-source-" + i, Text = shortSource, ForeColor = identity.Color,
                Font = tabCompact, AutoSize = false, AutoEllipsis = true, Height = S(22), Top = S(y), TextAlign = ContentAlignment.MiddleLeft };
            var cost = new Label { Name = "model-rank-cost-" + i, Text = row.CostDisplay + (row.Cost.HasValue && row.CostPartial ? "*" : ""),
                Font = tabCompact, ForeColor = Muted, AutoSize = false, AutoEllipsis = true, Height = S(22), Top = S(y), TextAlign = ContentAlignment.MiddleRight };
            var tokens = new Label { Name = "model-rank-tokens-" + i, Text = FormatNumber(row.Tokens), Font = bold,
                ForeColor = Primary, AutoSize = false, AutoEllipsis = true, Height = S(22), Top = S(y), TextAlign = ContentAlignment.MiddleRight };
            card.Resize += (_, _) => {
                tokens.Left = Math.Max(S(0), card.ClientSize.Width - S(80)); tokens.Width = Math.Max(S(0), card.ClientSize.Width - tokens.Left - S(16));
                cost.Left = Math.Max(S(0), tokens.Left - S(68)); cost.Width = Math.Max(S(0), tokens.Left - cost.Left - S(4));
                source.Left = Math.Max(S(16), cost.Left - S(58)); source.Width = Math.Max(S(0), cost.Left - source.Left - S(4));
                model.Width = Math.Max(S(0), source.Left - model.Left - S(5));
            };
            popupTips.SetToolTip(model, row.Model == "未识别模型" ? "未匹配内置模型目录的名称已匿名汇总" : row.Model);
            popupTips.SetToolTip(source, identity.DisplayName + " · 本机账本");
            popupTips.SetToolTip(cost, row.Cost.HasValue ? row.CostDisplay + " · API 等价估算，非账单" + (row.CostPartial ? " · 部分未计入" : "") : "该模型暂无可用费用估算");
            popupTips.SetToolTip(tokens, row.Tokens.ToString("N0") + " Token");
            card.Controls.AddRange([model, source, cost, tokens]);
        }
        popupTips.SetToolTip(note, "同一模型在不同本机账本中分别展示；不同账本可能重叠。未识别模型名称已匿名汇总。");
        StyleCard(card); content.Controls.Add(card);
    }
}
