using System.Text.Json;

namespace AgentMeter.Windows;

/// <summary>仅在非负拆分与总数一致时展示构成；显式未知或异常数据不冒充零。</summary>
internal static class UsageBreakdown
{
    public static bool TryRead(JsonElement totals, double total, out double[] parts)
    {
        parts = new double[5];
        if (totals.ValueKind != JsonValueKind.Object || !double.IsFinite(total) || total < 0) return false;
        string[] keys = ["fresh_input", "output", "reasoning", "cache_read", "cache_write", "unclassified"];
        var numbers = new double[keys.Length];
        for (int i = 0; i < keys.Length; i++)
        {
            if (!totals.TryGetProperty(keys[i], out var value)) continue;
            if (value.ValueKind != JsonValueKind.Number || !value.TryGetDouble(out double number) || !double.IsFinite(number) || number < 0)
                return false;
            numbers[i] = number;
        }
        parts = [numbers[0], numbers[1] + numbers[2], numbers[3], numbers[4], numbers[5]];
        double sum = parts.Sum();
        return double.IsFinite(sum) && Math.Abs(sum - total) <= 0.5;
    }
    public static double? CacheHitRate(double[] parts)
    {
        if (parts.Length != 5 || parts.Any(value => !double.IsFinite(value) || value < 0) || parts[4] > 0) return null;
        double input = parts[0] + parts[2] + parts[3];
        return double.IsFinite(input) && input > 0 ? parts[2] / input : null;
    }
}
