using System.Text.Json.Nodes;

namespace AgentMeter.Windows;

/// <summary>合并异步结果时，以用户当前保存的预算设置为准。</summary>
internal static class BudgetState
{
    internal static void Apply(JsonObject snapshot, string directory)
    {
        if (snapshot["budget"] is not JsonObject budget) return;
        BudgetSettings settings;
        try { settings = BudgetPreferences.Load(directory); }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException)
        { snapshot["budget"] = new JsonObject { ["status"] = "invalid" }; return; }
        if (!settings.Enabled) { snapshot["budget"] = new JsonObject { ["status"] = "disabled" }; return; }
        string? status = budget["status"] is JsonValue statusValue && statusValue.TryGetValue<string>(out var text) ? text : null;
        if (status == "disabled") { snapshot["budget"] = new JsonObject { ["status"] = "loading" }; return; }
        if (status != "ok") return;
        if (budget["config"] is not JsonObject config || !Same(config["daily_cny"], settings.Daily) ||
            !Same(config["weekly_cny"], settings.Weekly) || !Same(config["anomaly_multiplier"], settings.Multiplier))
        { snapshot["budget"] = new JsonObject { ["status"] = "loading" }; return; }
        if (!settings.AlertsEnabled) budget["alerts_enabled"] = false;
    }
    static bool Same(JsonNode? value, decimal? expected)
    {
        if (value is null) return expected is null;
        return value is JsonValue item && item.TryGetValue<string>(out var raw) && BudgetPreferences.TryAmount(raw, out decimal parsed) && parsed == expected;
    }
}
