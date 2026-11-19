using System.Globalization;
using System.Text.Json;

namespace AgentMeter.Windows;

/// <summary>比较已结束自然日，当前日尚未结束，因此不参与计算。</summary>
internal sealed record ReportComparison(int Days, long Current, long Previous)
{
    public static ReportComparison? Read(JsonElement period)
    {
        if (period.ValueKind != JsonValueKind.Object || !period.TryGetProperty("comparable_days", out var days) ||
            days.ValueKind != JsonValueKind.Number || !days.TryGetInt32(out int count) || count is < 1 or > 31 ||
            !period.TryGetProperty("current_comparable_tokens", out var current) || current.ValueKind != JsonValueKind.Number || !current.TryGetInt64(out long a) || a < 0 ||
            !period.TryGetProperty("previous_comparable_tokens", out var previous) || previous.ValueKind != JsonValueKind.Number || !previous.TryGetInt64(out long b) || b < 0)
            return null;
        return new(count, a, b);
    }
    public string Change
    {
        get
        {
            if (Previous == 0) return Current == 0 ? "双方均为 0" : "上期为 0 · 不计算增幅";
            decimal delta = ((decimal)Current - Previous) / Previous;
            if (delta * 100 > 99999) return ">99999%";
            return (delta > 0 ? "+" : "") + (delta * 100).ToString("0.#", CultureInfo.InvariantCulture) + "%";
        }
    }
}
