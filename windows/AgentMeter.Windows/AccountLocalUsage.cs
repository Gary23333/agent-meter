using System.Globalization;
using System.Text.Json;

namespace AgentMeter.Windows;

/// <summary>从本机账本提取可展示的汇总；不推断账本与当前登录账户的归属。</summary>
internal sealed record AccountLocalUsage(double? Today, double? ThirtyDays, double? All,
    IReadOnlyList<double>? Trend, bool Incomplete)
{
    public static AccountLocalUsage? Read(JsonElement item)
    {
        static JsonElement Value(JsonElement value, string key) =>
            value.ValueKind == JsonValueKind.Object && value.TryGetProperty(key, out var found) ? found : default;
        static double? Number(JsonElement value) => value.ValueKind == JsonValueKind.Number && value.TryGetDouble(out var n) &&
            double.IsFinite(n) && n >= 0 ? n : null;
        string status = Value(item, "status").ValueKind == JsonValueKind.String ? Value(item, "status").GetString() ?? "" : "";
        if (status is not ("available" or "partial")) return null;
        var data = Value(item, "value"); var periods = Value(data, "periods");
        double? Period(string key) => Number(Value(Value(Value(periods, key), "totals"), "total_tokens"));
        double? today = Period("today"), thirtyDays = Period("30d"), all = Period("all");
        var trend = Value(data, "daily_trend"); var rows = Value(trend, "days");
        List<double>? points = null;
        if (rows.ValueKind == JsonValueKind.Array && rows.GetArrayLength() == 30)
        {
            var valid = new List<double>(); DateOnly? previous = null;
            foreach (var row in rows.EnumerateArray())
            {
                var date = Value(row, "date"); var count = Number(Value(row, "tokens"));
                if (date.ValueKind != JsonValueKind.String ||
                    !DateOnly.TryParseExact(date.GetString(), "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var day) ||
                    (previous.HasValue && day.DayNumber != previous.Value.DayNumber + 1) || !count.HasValue)
                { valid.Clear(); break; }
                previous = day; valid.Add(count.Value);
            }
            if (valid.Count == 30) points = valid;
        }
        bool incomplete = status == "partial" || Value(trend, "incomplete").ValueKind == JsonValueKind.True;
        return today.HasValue || thirtyDays.HasValue || all.HasValue || points is not null
            ? new AccountLocalUsage(today, thirtyDays, all, points, incomplete) : null;
    }
}
