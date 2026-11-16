using System.Globalization;
using System.Text.Json;

namespace AgentMeter.Windows;

internal sealed record RankedModel(string Model, string Source, double Tokens, decimal? Cost, bool CostPartial)
{
    internal string CostDisplay => Cost switch { null => "—", > 0 and < 0.0001m => "<$0.0001", _ => "$" + Cost.Value.ToString("0.####", CultureInfo.InvariantCulture) };
}

/// <summary>按所选周期与本机来源显示模型；未知金额不按零处理。</summary>
internal sealed record ModelRanking(IReadOnlyList<RankedModel> Rows, bool Incomplete)
{
    static JsonElement Get(JsonElement value, string key) => value.ValueKind == JsonValueKind.Object && value.TryGetProperty(key, out var item) ? item : default;
    static string Text(JsonElement value, string key) => Get(value, key).ValueKind == JsonValueKind.String ? Get(value, key).GetString() ?? "" : "";
    static double? Number(JsonElement value, string key) => Get(value, key).ValueKind == JsonValueKind.Number && Get(value, key).TryGetDouble(out double n) && double.IsFinite(n) && n >= 0 ? n : null;
    static string Clean(string text) => new(text.Where(c => !char.IsControl(c)).Take(64).ToArray());
    internal static ModelRanking Read(JsonElement history, string period)
    {
        if (history.ValueKind != JsonValueKind.Object || !UsagePeriodPreferences.Valid(period)) return new([], true);
        var rows = new List<RankedModel>(); bool incomplete = false;
        foreach (var entry in history.EnumerateObject())
        {
            var source = entry.Value; string state = Text(source, "status"), reason = Text(source, "reason");
            if (state is "error" or "partial" || state == "unavailable" && !reason.EndsWith("_not_found", StringComparison.Ordinal)) incomplete = true;
            if (state is not ("available" or "partial")) continue;
            var window = Get(Get(Get(source, "value"), "periods"), period);
            var total = Number(Get(window, "totals"), "total_tokens");
            if (!total.HasValue) { incomplete = true; continue; }
            if (total.Value == 0) continue;
            var groups = Get(window, "groups");
            if (groups.ValueKind != JsonValueKind.Array) { incomplete = true; continue; }
            double grouped = 0; var costs = Get(window, "model_costs");
            string sourceName = Clean(entry.Name); if (sourceName.Length == 0) sourceName = "未命名来源";
            foreach (var group in groups.EnumerateArray())
            {
                string model = Clean(Text(group, "model")); var tokens = Number(group, "total_tokens");
                if (model.Length == 0 || !tokens.HasValue || !double.IsFinite(grouped + tokens.Value)) { incomplete = true; continue; }
                grouped += tokens.Value;
                if (tokens.Value == 0) continue;
                var costData = Get(costs, model); string raw = Text(costData, "amount_usd");
                decimal? cost = decimal.TryParse(raw, NumberStyles.Float, CultureInfo.InvariantCulture, out var amount) && amount >= 0 && amount <= 1_000_000_000_000_000m ? amount : null;
                bool costPartial = state == "partial" || Get(costData, "partial").ValueKind == JsonValueKind.True;
                rows.Add(new RankedModel(model, sourceName, tokens.Value, cost, costPartial));
            }
            if (Math.Abs(grouped - total.Value) > 0.5 || Get(window, "groups_truncated").ValueKind == JsonValueKind.True ||
                Get(window, "groups_incomplete").ValueKind == JsonValueKind.True) incomplete = true;
        }
        return new(rows.OrderByDescending(row => row.Tokens).ThenBy(row => row.Source, StringComparer.Ordinal).ThenBy(row => row.Model, StringComparer.Ordinal).Take(5).ToArray(), incomplete);
    }
}
