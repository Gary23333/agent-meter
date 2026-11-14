using System.Text.Json;

namespace AgentMeter.Windows;

internal sealed record QuotaWindow(string Label, double Remaining, long? ResetAt = null);
internal sealed record QuotaWindowPair(QuotaWindow Primary, QuotaWindow? Secondary);

/// <summary>优先配对短窗口与七天窗口，未知窗口只在单独展示时作为后备。</summary>
internal static class QuotaWindows
{
    public static QuotaWindowPair? Select(JsonElement account)
    {
        QuotaWindow? shortWindow = null, longWindow = null, fallback = null;
        foreach (var (window, isShort, isLong) in Parse(account))
        {
            if (isShort && shortWindow is null) shortWindow = window;
            else if (isLong && longWindow is null) longWindow = window;
            else if (fallback is null) fallback = window;
        }
        if (shortWindow is not null) return new QuotaWindowPair(shortWindow, longWindow);
        if (longWindow is not null) return new QuotaWindowPair(longWindow, null);
        return fallback is null ? null : new QuotaWindowPair(fallback, null);
    }
    public static IEnumerable<QuotaWindow> All(JsonElement account) => Parse(account).Select(item => item.Window);

    static IEnumerable<(QuotaWindow Window, bool Short, bool Long)> Parse(JsonElement account)
    {
        var rows = Field(Field(account, "quota"), "value");
        if (rows.ValueKind != JsonValueKind.Array) yield break;
        foreach (var row in rows.EnumerateArray().Take(100))
        {
            var value = Field(row, "remaining_percent");
            if (value.ValueKind != JsonValueKind.Number || !value.TryGetDouble(out double remaining) ||
                !double.IsFinite(remaining) || remaining < 0 || remaining > 100) continue;
            string bucket = Text(row, "bucket");
            var minutes = Field(row, "window_minutes");
            int? duration = minutes.ValueKind == JsonValueKind.Number && minutes.TryGetInt32(out int m) ? m : null;
            bool longSpecific = bucket is "seven_day_opus" or "seven_day_sonnet" or "seven_day_oauth_apps";
            bool isLong = !longSpecific && (duration == 10080 || bucket is "limit7d" or "week" or "seven_day");
            bool isShort = duration == 300 || bucket is "limit5h" or "5h" or "five_hour";
            string label = isShort ? "5 小时" : isLong ? "7 天" : Label(row, bucket, duration);
            long? resetAt = QuotaResetClock.Read(row);
            yield return (new QuotaWindow(label, remaining, resetAt), isShort, isLong);
        }
    }
    static string Label(JsonElement row, string bucket, int? duration)
    {
        if (bucket is "seven_day_opus" or "seven_day_sonnet" or "seven_day_oauth_apps")
            return bucket switch { "seven_day_opus" => "7 天 Opus", "seven_day_sonnet" => "7 天 Sonnet", _ => "7 天 OAuth" };
        var window = Field(row, "window");
        var value = Field(window, "duration");
        if (value.ValueKind == JsonValueKind.Number && value.TryGetDouble(out double n) && double.IsFinite(n) && n > 0 && n <= 100000)
            return $"{n:0.#}" + (Text(window, "unit") switch { "hour" => "小时", "day" => "天", "week" => "周", "month" => "月", "minute" => "分钟", _ => "" });
        if (duration is > 0 and <= 100000) return $"{duration} 分钟";
        return bucket switch { "monthTotal" => "月度总额", "monthCode" => "月度代码", "credits" => "积分", _ => "额度" };
    }
    static JsonElement Field(JsonElement e, string key) => e.ValueKind == JsonValueKind.Object && e.TryGetProperty(key, out var v) ? v : default;
    static string Text(JsonElement e, string key) { var value = Field(e, key); return value.ValueKind == JsonValueKind.String ? value.GetString() ?? "" : ""; }
}
