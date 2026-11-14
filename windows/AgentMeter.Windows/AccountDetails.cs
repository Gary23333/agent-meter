using System.Globalization;
using System.Text.Json;

namespace AgentMeter.Windows;

internal sealed record AccountAmount(string Label, string Value, string? Note = null);
internal sealed record ResetCredit(string Status, DateTimeOffset? Expires)
{
    public bool Expired(DateTimeOffset now) => Expires.HasValue && Expires <= now;
    public string State(DateTimeOffset now) => Status switch {
        "redeeming" => "兑换中", "redeemed" => "已兑换", "unknown" => "状态未明",
        _ when Expired(now) => "已到期 · 待刷新",
        _ when Expires is null => "到期时间未提供",
        _ => Remaining(Expires!.Value - now) };
    static string Remaining(TimeSpan span) => span.TotalDays >= 1 ? $"{(int)Math.Ceiling(span.TotalDays)} 天内到期" :
        span.TotalHours >= 1 ? $"{(int)Math.Ceiling(span.TotalHours)} 小时内到期" : "1 小时内到期";
}
internal sealed record ResetCredits(int Count, IReadOnlyList<ResetCredit> Cards, bool Incomplete);

/// <summary>账户附加信息只读投影。服务报告的数量不由到期明细反推，不合并不同积分池。</summary>
internal sealed record AccountDetails(string? Plan, IReadOnlyList<AccountAmount> Amounts, ResetCredits? ResetCredits)
{
    public bool HasContent => Plan is not null || Amounts.Count > 0 || ResetCredits is not null;
    public static readonly AccountDetails Empty = new(null, [], null);
    static JsonElement Field(JsonElement e, string key) => e.ValueKind == JsonValueKind.Object && e.TryGetProperty(key, out var v) ? v : default;
    static string Text(JsonElement e, string key) => Field(e, key).ValueKind == JsonValueKind.String ? Field(e, key).GetString() ?? "" : "";
    static string? Amount(JsonElement e, string key, bool negative = false)
    {
        var field = Field(e, key);
        string raw = field.ValueKind == JsonValueKind.String ? field.GetString() ?? "" : field.ValueKind == JsonValueKind.Number ? field.GetRawText() : "";
        return raw.Length <= 40 && decimal.TryParse(raw, NumberStyles.AllowDecimalPoint | NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out var number) &&
            (negative || number >= 0) ? number.ToString("0.########", CultureInfo.InvariantCulture) : null;
    }
    static DateTimeOffset? Stamp(JsonElement e)
        => ForecastPresentation.Stamp(e, "epoch_seconds");
    static string? PlanName(JsonElement account)
    {
        string name = Text(Field(account, "subscription"), "plan").Trim();
        return name.Length is > 0 and <= 48 && name.All(c => char.IsLetterOrDigit(c) || " ._-+()（）".Contains(c)) ? name : null;
    }
    public static AccountDetails Read(string provider, JsonElement account)
    {
        if (Text(account, "status") is not ("available" or "partial")) return Empty;
        var amounts = new List<AccountAmount>();
        var credits = Field(Field(account, "credits"), "value");
        if (provider == "Codex" && credits.ValueKind == JsonValueKind.Array)
        {
            int index = 0;
            foreach (var credit in credits.EnumerateArray().Take(5))
            {
                string? amount = Field(credit, "unlimited").ValueKind == JsonValueKind.True ? "不限额" : Amount(credit, "balance", negative: true);
                if (amount is not null) amounts.Add(new AccountAmount(++index == 1 ? "账户积分" : $"账户积分池 {index}", amount, "不同积分池独立计量"));
            }
        }
        else if (provider == "Kimi Code")
        {
            string? amount = Amount(credits, "amount", negative: true);
            string unit = Text(credits, "unit");
            if (amount is not null && unit is "CNY" or "USD") amounts.Add(new AccountAmount("额外用量钱包", amount + " " + unit));
        }
        else if (provider == "WorkBuddy")
        {
            string? balance = Amount(credits, "balance"), total = Amount(credits, "total"), frozen = Amount(credits, "frozen");
            if (balance is not null) amounts.Add(new AccountAmount("积分余额", balance + " 积分",
                total is null ? null : "总额 " + total + (frozen is null ? "" : " · 冻结 " + frozen)));
        }
        else if (provider == "DeepSeek API" && credits.ValueKind == JsonValueKind.Array)
        {
            foreach (var credit in credits.EnumerateArray().Take(2))
            {
                string unit = Text(credit, "unit"); string? total = Amount(credit, "total"), granted = Amount(credit, "granted"), topped = Amount(credit, "topped_up");
                if (total is null || unit is not ("CNY" or "USD")) continue;
                amounts.Add(new AccountAmount("API 账户余额", total + " " + unit, granted is not null && topped is not null ? $"赠金 {granted} · 充值 {topped}" : null));
            }
        }
        ResetCredits? resets = null;
        var raw = Field(Field(account, "reset_cards"), "value");
        var count = Field(raw, "available_count");
        if (provider == "Codex" && count.ValueKind == JsonValueKind.Number && count.TryGetInt32(out int n) && n is >= 0 and <= 100000)
        {
            var cards = new List<ResetCredit>();
            var items = Field(raw, "cards");
            bool incomplete = Text(raw, "details_state") is "unknown" or "truncated" || items.ValueKind != JsonValueKind.Array;
            if (items.ValueKind == JsonValueKind.Array)
            {
                if (items.GetArrayLength() > 100) incomplete = true;
                foreach (var item in items.EnumerateArray().Take(100))
                {
                    string state = Text(item, "status");
                    if (state is not ("available" or "redeeming" or "redeemed" or "unknown")) { incomplete = true; continue; }
                    cards.Add(new ResetCredit(state, Stamp(Field(item, "expires_at"))));
                }
            }
            if (cards.Count(card => card.Status == "available") != n) incomplete = true;
            resets = new ResetCredits(n, cards.OrderBy(card => card.Status is "available" or "redeeming" ? 0 : 1)
                .ThenBy(card => card.Expires ?? DateTimeOffset.MaxValue).ToArray(), incomplete);
        }
        return new(PlanName(account), amounts, resets);
    }
}
