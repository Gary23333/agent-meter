using System.Globalization;
using System.Text.Json;

namespace AgentMeter.Windows;

/// <summary>仅汇总同一周期已知的美元 API 等价估算，不混入账户余额或其他币种。</summary>
internal sealed record UsageCostSummary(decimal? Amount, bool Partial)
{
    static JsonElement Get(JsonElement e, string key) => e.ValueKind == JsonValueKind.Object && e.TryGetProperty(key, out var value) ? value : default;
    static string Text(JsonElement e, string key) => Get(e, key).ValueKind == JsonValueKind.String ? Get(e, key).GetString() ?? "" : "";
    public static UsageCostSummary Read(JsonElement history, string period)
    {
        if (history.ValueKind != JsonValueKind.Object || !UsagePeriodPreferences.Valid(period)) return new(null, true);
        decimal sum = 0; bool known = false, partial = false;
        foreach (var entry in history.EnumerateObject())
        {
            var item = entry.Value; string status = Text(item, "status");
            if (status is "error" or "partial" || status == "unavailable" && !Text(item, "reason").EndsWith("_not_found", StringComparison.Ordinal)) partial = true;
            if (status is not ("available" or "partial")) continue;
            var total = Get(Get(Get(Get(item, "value"), "periods"), period), "totals");
            var count = Get(total, "total_tokens");
            if (count.ValueKind != JsonValueKind.Number || !count.TryGetDouble(out double tokens) || !double.IsFinite(tokens) || tokens < 0)
            { partial = true; continue; }
            var estimate = Get(Get(item, "estimates"), period);
            if (period == "today" && estimate.ValueKind != JsonValueKind.Object) estimate = Get(item, "estimate");
            string raw = Text(estimate, "amount_usd");
            if (!decimal.TryParse(raw, NumberStyles.Float, CultureInfo.InvariantCulture, out decimal amount) || amount < 0 || amount > 1_000_000_000_000_000m)
            { if (tokens > 0) partial = true; continue; }
            known = true; sum += amount;
            if (Get(estimate, "partial").ValueKind == JsonValueKind.True) partial = true;
        }
        return new(known ? sum : null, partial);
    }
    public string Display => Amount switch { null => "—", > 0 and < 0.0001m => "<$0.0001", _ => "$" + Amount.Value.ToString("0.####", CultureInfo.InvariantCulture) };
}
