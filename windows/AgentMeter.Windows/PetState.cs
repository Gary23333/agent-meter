using System.Text.Json;

namespace AgentMeter.Windows;

internal sealed record PetMood(string Animation, string Description, double? Remaining = null);

/// <summary>只依据可用额度和最近记录更新选择状态，不把缺失数据当作耗尽。</summary>
internal static class PetState
{
    public static PetMood Select(JsonElement snapshot, long now)
    {
        var observed = Number(snapshot, "observed_at");
        bool freshAccount = observed.HasValue && observed.Value <= now && now - observed.Value <= 20 * 60;
        double? remaining = null;
        if (freshAccount)
        {
            remaining = Lowest(Field(snapshot, "account"), now);
            var others = Field(snapshot, "other_accounts");
            if (others.ValueKind == JsonValueKind.Object)
                foreach (var entry in others.EnumerateObject())
                {
                    if (entry.Value.ValueKind == JsonValueKind.Array)
                    {
                        foreach (var account in entry.Value.EnumerateArray())
                            remaining = Minimum(remaining, Lowest(account, now));
                    }
                    else remaining = Minimum(remaining, Lowest(entry.Value, now));
                }
        }
        if (remaining is < 20) return new PetMood("alarm", "账户额度偏低", remaining);
        var activity = Field(snapshot, "activity");
        var apps = Field(activity, "apps");
        if (Text(activity, "status") is "available" or "partial" && apps.ValueKind == JsonValueKind.Array)
            foreach (var app in apps.EnumerateArray())
            {
                var updated = Number(app, "last_updated");
                if (updated.HasValue && updated.Value <= now && now - updated.Value <= 15 * 60)
                    return new PetMood("working", "近期本机记录有更新", remaining);
            }
        return new PetMood("idle", "待机", remaining);
    }

    static double? Minimum(double? left, double? right) => left.HasValue && right.HasValue ? Math.Min(left.Value, right.Value) : left ?? right;

    static double? Lowest(JsonElement account, long now)
    {
        if (Text(account, "status") is not ("available" or "partial")) return null;
        var quotas = Field(Field(account, "quota"), "value");
        if (quotas.ValueKind != JsonValueKind.Array) return null;
        double? lowest = null;
        foreach (var quota in quotas.EnumerateArray())
        {
            var remaining = Number(quota, "remaining_percent");
            var reset = Number(Field(quota, "resets_at"), "epoch_seconds");
            if (remaining is >= 0 and <= 100 && (!reset.HasValue || reset.Value > now)) lowest = Minimum(lowest, remaining);
        }
        return lowest;
    }
    static JsonElement Field(JsonElement e, string key) => e.ValueKind == JsonValueKind.Object && e.TryGetProperty(key, out var value) ? value : default;
    static string Text(JsonElement e, string key) { var value = Field(e, key); return value.ValueKind == JsonValueKind.String ? value.GetString() ?? "" : ""; }
    static double? Number(JsonElement e, string key)
    {
        var value = Field(e, key);
        return value.ValueKind == JsonValueKind.Number && value.TryGetDouble(out double n) && double.IsFinite(n) ? n : null;
    }
}
