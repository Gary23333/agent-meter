using System.Text.Json;
using System.Text.Json.Nodes;

namespace AgentMeter.Windows;

internal sealed partial class MeterWindow
{
    bool expandedResetCredits;
    readonly List<Action<DateTimeOffset>> accountClockUpdates = [];

    static void AddDemoAccountDetails(JsonNode sample)
    {
        var cards = new JsonArray();
        foreach (int days in new[] { 1, 3, 10 }) cards.Add(new JsonObject { ["status"] = "available",
            ["expires_at"] = new JsonObject { ["epoch_seconds"] = ForecastDemoNow.AddDays(days).ToUnixTimeSeconds() } });
        sample["account"]!["reset_cards"] = new JsonObject { ["value"] = new JsonObject {
            ["available_count"] = 3, ["details_state"] = "returned", ["cards"] = cards } };
        sample["account"]!["credits"] = JsonNode.Parse("""{"value":[{"balance":"125","unit":"provider_credits","bucket":"codex"}]}""");
        sample["other_accounts"]!["Claude Code"]!["subscription"] = new JsonObject { ["plan"] = "Max" };
    }

    int AddAccountDetails(RoundedCard box, int top, AccountDetails details)
    {
        int start = top;
        if (details.Amounts.Count > 0)
        {
            var divider = new Panel { Left = 16, Top = top, Height = 1, BackColor = theme.Border };
            box.Controls.Add(divider); box.Resize += (_, _) => divider.Width = Math.Max(0, box.Width - 32);
            top += 8;
        }
        foreach (var amount in details.Amounts)
        {
            var caption = new Label { Text = amount.Label, Left = 16, Top = top + 4, Height = 24, ForeColor = Muted,
                Font = new Font(Font.FontFamily, 9), AutoEllipsis = true };
            var value = new Label { Text = amount.Value, Top = top, Height = 28, ForeColor = Primary, TextAlign = ContentAlignment.TopRight,
                Font = new Font(Font.FontFamily, 11, FontStyle.Bold), AutoEllipsis = true };
            box.Controls.AddRange([caption, value]); popupTips.SetToolTip(value, amount.Value);
            box.Resize += (_, _) => { caption.Width = (box.Width - 32) * 2 / 5; value.Left = caption.Right + 6; value.Width = Math.Max(0, box.Width - value.Left - 16); };
            top += 30;
            if (amount.Note is not null)
            {
                var note = new Label { Text = amount.Note, Left = 16, Top = top, Height = 20, AutoEllipsis = true,
                    Font = new Font(Font.FontFamily, 8), ForeColor = Muted };
                box.Controls.Add(note); box.Resize += (_, _) => note.Width = Math.Max(0, box.Width - 32); top += 21;
            }
        }
        if (details.ResetCredits is { } resets)
        {
            top += 8;
            var title = new Label { Text = "重置卡", Left = 16, Top = top, Height = 24, ForeColor = Muted,
                Font = new Font(Font.FontFamily, 10, FontStyle.Bold), AutoSize = true };
            var total = new Label { Text = $"{resets.Count} 张 · 服务报告", Top = top, Height = 25, ForeColor = Primary,
                Font = new Font(Font.FontFamily, 10, FontStyle.Bold), AutoSize = true };
            box.Controls.AddRange([title, total]);
            box.Resize += (_, _) => total.Left = Math.Max(title.Right + 8, box.Width - total.Width - 16);
            top += 29;
            var hint = new Label { Text = resets.Incomplete ? "明细不完整 · 不据此推算可用总数" : "到期明细 · 按时间排序",
                Left = 16, Top = top, Height = 20, ForeColor = Muted, Font = new Font(Font.FontFamily, 8), AutoEllipsis = true };
            box.Controls.Add(hint); box.Resize += (_, _) => hint.Width = Math.Max(0, box.Width - 32); top += 25;
            int shown = Math.Min(resets.Cards.Count, expandedResetCredits ? 100 : 3);
            for (int index = 0; index < shown; index++)
            {
                var credit = resets.Cards[index];
                int row = index / 3, column = index % 3;
                var tile = new RoundedCard(theme) { Name = "account-reset-tile", Top = top + row * 82, Height = 74, BackColor = Card, ClipCorners = true };
                var state = new Label { Text = credit.Status switch { "redeeming" => "兑换中", "redeemed" => "已兑换", "unknown" => "状态未明", _ => "账户标为可用" },
                    Left = 8, Top = 7, Height = 18, ForeColor = Muted, Font = new Font(Font.FontFamily, 8), AutoEllipsis = true };
                var date = new Label { Text = credit.Expires?.LocalDateTime.ToString("MM 月 dd 日") ?? "日期未知", Left = 8, Top = 26, Height = 23,
                    ForeColor = Primary, Font = new Font(Font.FontFamily, 10, FontStyle.Bold), AutoEllipsis = true };
                var remaining = new Label { Left = 8, Top = 51, Height = 18, Font = new Font(Font.FontFamily, 8), AutoEllipsis = true };
                void Update(DateTimeOffset now)
                {
                    if (remaining.IsDisposed) return;
                    remaining.Text = credit.State(now);
                    remaining.ForeColor = credit.Status == "available" && credit.Expired(now) ? MeterBar.ValueColor(theme, 0) :
                        credit.Status == "available" && credit.Expires - now < TimeSpan.FromDays(3) ? MeterBar.ValueColor(theme, 25) : Muted;
                }
                Update(ForecastNow); accountClockUpdates.Add(Update);
                tile.Controls.AddRange([state, date, remaining]);
                StyleCard(tile);
                box.Controls.Add(tile);
                box.Resize += (_, _) => {
                    tile.Width = Math.Max(1, (box.Width - 48) / 3); tile.Left = 16 + column * (tile.Width + 8);
                    state.Width = date.Width = remaining.Width = Math.Max(0, tile.Width - 16);
                };
            }
            top += (shown + 2) / 3 * 82;
            if (resets.Cards.Count > 3)
            {
                var toggle = new RoundedActionButton(theme) { Name = "account-reset-toggle", Text = expandedResetCredits ? "收起到期明细" : $"查看全部 {resets.Cards.Count} 条明细",
                    Left = 16, Top = top, Height = 28, AccentText = true, Font = new Font(Font.FontFamily, 8.5F) };
                toggle.FlatAppearance.BorderColor = theme.Border;
                toggle.Click += (_, _) => {
                    expandedResetCredits = !expandedResetCredits; var scroll = content.AutoScrollPosition;
                    using var snapshot = JsonDocument.Parse(lastSnapshot!); Render(snapshot.RootElement);
                    content.PerformLayout(); content.AutoScrollPosition = new Point(-scroll.X, -scroll.Y);
                };
                box.Controls.Add(toggle); box.Resize += (_, _) => toggle.Width = Math.Max(0, box.Width - 32); top += 36;
            }
        }
        return top - start + (top > start ? 8 : 0);
    }

    void RenderAccountDetailsPreviews(Action<string> save)
    {
        string original = lastSnapshot!;
        var sample = JsonNode.Parse(original)!;
        var cards = (JsonArray)sample["account"]!["reset_cards"]!["value"]!["cards"]!;
        cards.Add(new JsonObject { ["status"] = "available", ["expires_at"] = new JsonObject { ["epoch_seconds"] = ForecastDemoNow.AddHours(-1).ToUnixTimeSeconds() } });
        cards.Add(new JsonObject { ["status"] = "redeeming", ["expires_at"] = null });
        cards.Add(new JsonObject { ["status"] = "unknown", ["expires_at"] = null });
        sample["account"]!["reset_cards"]!["value"]!["available_count"] = 4;
        Size = new Size(420, 900); expandedResetCredits = false;
        using (var document = JsonDocument.Parse(sample.ToJsonString())) Render(document.RootElement);
        SetView(View.Accounts);
        IEnumerable<Control> Tiles() => content.Controls.OfType<RoundedCard>().SelectMany(card => card.Controls.Cast<Control>()).Where(child => child.Name == "account-reset-tile");
        Button Toggle() => content.Controls.OfType<RoundedCard>().SelectMany(card => card.Controls.OfType<Button>()).Single(button => button.Name == "account-reset-toggle");
        if (Tiles().Count() != 3) throw new InvalidOperationException("重置卡默认明细数量错误");
        Toggle().PerformClick(); Application.DoEvents();
        if (Tiles().Count() != 6 || !Tiles().SelectMany(tile => tile.Controls.OfType<Label>()).Any(label => label.Text == "已到期 · 待刷新"))
            throw new InvalidOperationException("重置卡展开或到期状态错误");
        content.AutoScrollPosition = new Point(0, 160); save("aurora-account-reset-expanded");
        SetTheme(VisualThemes.Find("porcelain")); content.AutoScrollPosition = new Point(0, 160); save("porcelain-account-reset-expanded");
        Toggle().PerformClick(); Application.DoEvents();
        if (Tiles().Count() != 3 || expandedResetCredits) throw new InvalidOperationException("重置卡收起失败");
        sample["account"]!["reset_cards"]!["value"]!["cards"] = null;
        sample["account"]!["reset_cards"]!["value"]!["details_state"] = "unknown";
        SetTheme(VisualThemes.Find("aurora"));
        using (var document = JsonDocument.Parse(sample.ToJsonString())) Render(document.RootElement);
        content.AutoScrollPosition = Point.Empty; save("aurora-account-reset-unknown");
        if (Tiles().Any() || !content.Controls.OfType<RoundedCard>().SelectMany(card => card.Controls.OfType<Label>()).Any(label => label.Text == "4 张 · 服务报告"))
            throw new InvalidOperationException("缺少明细时不能丢失服务报告的总数");
        Size = new Size(420, 760);
        using (var document = JsonDocument.Parse(original)) Render(document.RootElement);
    }
}
