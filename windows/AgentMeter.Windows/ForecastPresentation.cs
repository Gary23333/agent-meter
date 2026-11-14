using System.Text.Json;

namespace AgentMeter.Windows;

internal sealed record ForecastRange(double Median, double Minimum, double Maximum, int Sources, bool HasModel)
{
    public static ForecastRange? Read(JsonElement value)
    {
        double? median = ForecastPresentation.Number(value, "weighted_median"), low = ForecastPresentation.Number(value, "min"), high = ForecastPresentation.Number(value, "max");
        double? count = ForecastPresentation.Number(value, "n");
        if (median is null || low is null || high is null || count is null || low < 0 || high > 100 ||
            low > median || median > high || count < 1 || count > 3 || count != Math.Truncate(count.Value)) return null;
        return new(median.Value, low.Value, high.Value, (int)count, ForecastPresentation.Field(value, "has_model").ValueKind == JsonValueKind.True);
    }
}

internal sealed record ForecastWindow(bool Typical, DateTimeOffset? Open, DateTimeOffset Close, string Sources)
{
    public static ForecastWindow? Read(JsonElement value)
    {
        string kind = ForecastPresentation.Text(value, "kind");
        var close = ForecastPresentation.Stamp(value, "close_at");
        var open = ForecastPresentation.Stamp(value, "open_at");
        string sources = ForecastPresentation.Sources(value);
        if (kind is not ("typical_window" or "promised_reset") || close is null || open > close || sources.Length == 0) return null;
        return new(kind == "typical_window", open, close.Value, sources);
    }
    public string Countdown(DateTimeOffset now)
    {
        if (now >= Close) return Typical ? "时段已结束 · 等待更新" : "时间已过 · 尚待确认";
        if (Open.HasValue && now >= Open) return "时段内 · 距结束 " + ForecastPresentation.Duration(Close - now);
        return (Open.HasValue ? "距时段开始 " : "距站点所述时间 ") + ForecastPresentation.Duration((Open ?? Close) - now);
    }
}

/// <summary>预测的时间展示不依赖联网；到点后只提示待确认，不能宣称已经重置。</summary>
internal static class ForecastPresentation
{
    public static JsonElement Field(JsonElement e, string key) => e.ValueKind == JsonValueKind.Object && e.TryGetProperty(key, out var v) ? v : default;
    public static string Text(JsonElement e, string key) => Field(e, key).ValueKind == JsonValueKind.String ? Field(e, key).GetString() ?? "" : "";
    public static double? Number(JsonElement e, string key) => Field(e, key).ValueKind == JsonValueKind.Number && Field(e, key).TryGetDouble(out double n) && double.IsFinite(n) ? n : null;
    public static DateTimeOffset? Stamp(JsonElement e, string key)
    {
        double? value = Number(e, key);
        if (value is null || value < 0 || value > 253402300799) return null;
        return DateTimeOffset.FromUnixTimeSeconds((long)value.Value);
    }
    public static string Sources(JsonElement e)
    {
        var rows = Field(e, "sources");
        return rows.ValueKind != JsonValueKind.Array ? "" : string.Join(" · ", rows.EnumerateArray()
            .Where(row => row.ValueKind == JsonValueKind.String).Select(row => row.GetString())
            .Where(name => name is "WillReset" or "Tibo Radar" or "Reset Monitor").Distinct());
    }
    public static string Duration(TimeSpan remaining)
    {
        long seconds = (long)Math.Ceiling(Math.Max(0, remaining.TotalSeconds));
        if (seconds >= 86400) return $"{seconds / 86400} 天 {seconds % 86400 / 3600} 小时";
        if (seconds >= 3600) return $"{seconds / 3600} 小时 {seconds % 3600 / 60:00} 分";
        if (seconds >= 60) return $"{seconds / 60} 分 {seconds % 60:00} 秒";
        return $"{seconds} 秒";
    }
    public static string Kind(string kind) => kind switch {
        "reset" => "重置记录", "reset_preview" or "preview" => "重置预告", "banked" or "credits" => "重置卡记录",
        "limits" => "限额调整", "boost" => "加速记录", "milestone" => "里程碑", _ => "事件记录" };
}
