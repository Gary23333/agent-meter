using System.Text.Json;

namespace AgentMeter.Windows;

/// <summary>额度首次低于阈值时提醒；恢复后或重置周期改变时允许再次提醒。</summary>
internal sealed class QuotaAlerts
{
    readonly Dictionary<string, (long? Reset, DateTimeOffset Sent)> alerted = new(StringComparer.Ordinal);
    public void Clear() => alerted.Clear();

    public IReadOnlyList<string> Evaluate(JsonElement snapshot, DateTimeOffset? observedAt = null, int threshold = 20)
    {
        var messages = new List<string>();
        var now = observedAt ?? DateTimeOffset.UtcNow;
        if (!AlertPreferences.ValidThreshold(threshold)) return messages;
        var sampled = ForecastPresentation.Stamp(snapshot, "observed_at");
        if (sampled is null || now - sampled > TimeSpan.FromMinutes(30) || sampled - now > TimeSpan.FromMinutes(5)) return messages;
        Inspect("Codex", Field(snapshot, "account"), messages, now, threshold);
        var other = Field(snapshot, "other_accounts");
        Inspect("Kimi", Field(other, "Kimi Code"), messages, now, threshold);
        Inspect("Claude", Field(other, "Claude Code"), messages, now, threshold);
        Inspect("WorkBuddy", Field(other, "WorkBuddy"), messages, now, threshold);
        Inspect("ZCode", Field(other, "ZCode"), messages, now, threshold);
        Inspect("火山方舟", Field(other, "Volcengine"), messages, now, threshold);
        Inspect("小米 MiMo", Field(other, "MiMo"), messages, now, threshold);
        Inspect("Qoder CN", Field(other, "Qoder CN"), messages, now, threshold);
        Inspect("TRAE CN", Field(other, "TRAE CN"), messages, now, threshold);
        var minimax = Field(other, "MiniMax Code");
        if (minimax.ValueKind == JsonValueKind.Array)
        {
            foreach (var account in minimax.EnumerateArray())
            {
                string label = Text(account, "label");
                if (label.Length is < 1 or > 32 || label.Any(char.IsControl)) continue;
                Inspect("MiniMax · " + label, account, messages, now, threshold);
            }
        }
        else Inspect("MiniMax", minimax, messages, now, threshold);
        return messages;
    }
    void Inspect(string provider, JsonElement account, List<string> messages, DateTimeOffset now, int threshold)
    {
        string status = Text(account, "status");
        if (status is not ("available" or "partial")) return;
        var quotas = Field(Field(account, "quota"), "value");
        if (quotas.ValueKind != JsonValueKind.Array) return;
        foreach (var quota in quotas.EnumerateArray())
        {
            var value = Field(quota, "remaining_percent");
            if (value.ValueKind != JsonValueKind.Number || !value.TryGetDouble(out double remaining) ||
                !double.IsFinite(remaining) || remaining < 0 || remaining > 100) continue;
            string bucket = Text(quota, "bucket");
            if (bucket.Length > 80 || bucket.Any(char.IsControl)) continue;
            var minutes = Field(quota, "window_minutes");
            string period = minutes.ValueKind == JsonValueKind.Number && minutes.TryGetInt32(out int duration)
                ? duration == 300 ? "5 小时" : duration == 10080 ? "7 天" : duration == 43200 ? "月度" : $"{duration} 分钟"
                : bucket switch { "limit5h" or "5h" => "5 小时", "limit7d" or "week" => "7 天", "monthTotal" => "月度总额", "monthCode" => "月度代码", "credits" => "积分额度", "mcp" => "MCP 调用", "totalQuota" => "账户额度", "sharedQuota" => "共享额度", _ => bucket };
            string limitType = Text(quota, "limit_type") switch { "CREDIT_LIMIT" => "Coding Plan", "TOKENS_LIMIT" => "Token", "TIME_LIMIT" => "MCP", _ => "" };
            if (provider == "ZCode" && limitType is "Coding Plan" or "Token") period = limitType + " · " + period;
            string key = provider + ":" + bucket + ":" + limitType + ":" + period;
            var resetValue = Field(Field(quota, "resets_at"), "epoch_seconds");
            long? reset = resetValue.ValueKind == JsonValueKind.Number && resetValue.TryGetDouble(out double epoch) &&
                double.IsFinite(epoch) && epoch >= 0 && epoch <= 253402300799 ? (long)epoch : null;
            if (reset.HasValue && reset <= now.ToUnixTimeSeconds()) continue;
            if (remaining >= Math.Min(100, threshold + 10)) { alerted.Remove(key); continue; }
            if (remaining >= threshold) continue;
            if (alerted.TryGetValue(key, out var previous) &&
                (previous.Reset == reset || (now >= previous.Sent && now - previous.Sent < TimeSpan.FromMinutes(15)))) continue;
            alerted[key] = (reset, now);
            messages.Add($"{provider} {period}：剩余 {remaining:0.#}%");
        }
    }
    static JsonElement Field(JsonElement element, string key) => element.ValueKind == JsonValueKind.Object && element.TryGetProperty(key, out var value) ? value : default;
    static string Text(JsonElement element, string key) { var value = Field(element, key); return value.ValueKind == JsonValueKind.String ? value.GetString() ?? "" : ""; }
}

internal sealed record AlertSettings(bool Enabled, int Threshold, bool ResetCardsEnabled = false);
/// <summary>只保存提醒开关和阈值；首次安装默认关闭。</summary>
internal static class AlertPreferences
{
    public static readonly int[] Thresholds = [10, 20, 30, 50];
    public static bool ValidThreshold(int threshold) => Thresholds.Contains(threshold);
    public static AlertSettings LoadSettings(string directory)
    {
        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(directory, "alerts.json")));
            if (doc.RootElement.ValueKind != JsonValueKind.Object || !doc.RootElement.TryGetProperty("enabled", out var enabled) ||
                enabled.ValueKind is not (JsonValueKind.True or JsonValueKind.False)) return new(false, 20);
            int threshold = 20;
            if (doc.RootElement.TryGetProperty("threshold", out var saved) &&
                (saved.ValueKind != JsonValueKind.Number || !saved.TryGetInt32(out threshold) || !ValidThreshold(threshold))) return new(false, 20);
            bool resetCards = false;
            if (doc.RootElement.TryGetProperty("reset_cards_enabled", out var cards))
            {
                if (cards.ValueKind is not (JsonValueKind.True or JsonValueKind.False)) return new(false, 20);
                resetCards = cards.ValueKind == JsonValueKind.True;
            }
            return new(enabled.ValueKind == JsonValueKind.True, threshold, resetCards);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException or InvalidOperationException or System.Security.SecurityException) { return new(false, 20); }
    }
    public static bool Load(string directory) => LoadSettings(directory).Enabled;
    public static void Save(string directory, bool enabled)
    {
        var current = LoadSettings(directory);
        Save(directory, current with { Enabled = enabled });
    }
    public static void Save(string directory, AlertSettings settings)
    {
        if (!ValidThreshold(settings.Threshold)) throw new ArgumentException("提醒阈值无效");
        Directory.CreateDirectory(directory);
        string temporary = Path.Combine(directory, Path.GetRandomFileName());
        bool created = false;
        try
        {
            using (var file = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                created = true; JsonSerializer.Serialize(file, new { enabled = settings.Enabled, threshold = settings.Threshold, reset_cards_enabled = settings.ResetCardsEnabled });
            }
            File.Move(temporary, Path.Combine(directory, "alerts.json"), overwrite: true);
        }
        finally
        {
            try { if (created) File.Delete(temporary); }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException) { }
        }
    }
}
