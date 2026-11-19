using System.Globalization;
using System.Text.Json;

namespace AgentMeter.Windows;

/// <summary>从当前周期的本机账本生成来源对比；不推断账号归属，也不把缺失价格当作零。</summary>
internal sealed record UsageSource(string Name, double Tokens, decimal? Cost, bool Partial)
{
    static JsonElement Get(JsonElement value, string key) => value.ValueKind == JsonValueKind.Object && value.TryGetProperty(key, out var item) ? item : default;
    static string Text(JsonElement value, string key) => Get(value, key).ValueKind == JsonValueKind.String ? Get(value, key).GetString() ?? "" : "";
    internal string CostDisplay => Cost switch { null => "—", > 0 and < 0.0001m => "<$0.0001", _ => "$" + Cost.Value.ToString("0.####", CultureInfo.InvariantCulture) };

    internal static IReadOnlyList<UsageSource> Read(JsonElement history, string period)
    {
        if (history.ValueKind != JsonValueKind.Object || !UsagePeriodPreferences.Valid(period)) return [];
        var rows = new List<UsageSource>();
        foreach (var entry in history.EnumerateObject())
        {
            var item = entry.Value;
            string state = Text(item, "status");
            if (state is not ("available" or "partial")) continue;
            var total = Get(Get(Get(Get(item, "value"), "periods"), period), "totals");
            var count = Get(total, "total_tokens");
            if (count.ValueKind != JsonValueKind.Number || !count.TryGetDouble(out var tokens) || !double.IsFinite(tokens) || tokens <= 0) continue;
            var estimate = Get(Get(item, "estimates"), period);
            if (period == "today" && estimate.ValueKind != JsonValueKind.Object) estimate = Get(item, "estimate");
            string amountText = Text(estimate, "amount_usd");
            decimal? cost = decimal.TryParse(amountText, NumberStyles.Float, CultureInfo.InvariantCulture, out var amount) && amount >= 0 && amount <= 1_000_000_000_000_000m ? amount : null;
            string name = new(entry.Name.Where(c => !char.IsControl(c)).Take(64).ToArray());
            if (name.Length == 0) name = "未命名来源";
            rows.Add(new UsageSource(name, tokens, cost, state == "partial" || Get(estimate, "partial").ValueKind == JsonValueKind.True));
        }
        return rows.OrderByDescending(row => row.Tokens).ThenBy(row => row.Name, StringComparer.Ordinal).ToArray();
    }
}
