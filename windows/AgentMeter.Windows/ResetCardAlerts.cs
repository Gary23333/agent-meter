using System.Text.Json;

namespace AgentMeter.Windows;

/// <summary>仅提醒当前可用的 Codex 重置卡，按到期时间与阶段在进程内去重。</summary>
internal sealed class ResetCardAlerts
{
    readonly HashSet<(long Expiry, int Level)> alerted = [];
    public void Clear() => alerted.Clear();
    public IReadOnlyList<string> Evaluate(JsonElement snapshot, DateTimeOffset? observedAt = null)
    {
        var now = observedAt ?? DateTimeOffset.UtcNow;
        var sampled = ForecastPresentation.Stamp(snapshot, "observed_at");
        if (sampled is null || now - sampled > TimeSpan.FromMinutes(30) || sampled - now > TimeSpan.FromMinutes(5)) return [];
        var account = ForecastPresentation.Field(snapshot, "account");
        if (ForecastPresentation.Text(account, "status") is not ("available" or "partial")) return [];
        var metric = ForecastPresentation.Field(account, "reset_cards");
        var status = ForecastPresentation.Text(metric, "status");
        if (status.Length > 0 && status is not ("available" or "partial")) return [];
        var value = ForecastPresentation.Field(metric, "value");
        var cards = ForecastPresentation.Field(value, "cards");
        var groups = new Dictionary<long, int>();
        if (cards.ValueKind == JsonValueKind.Array)
        {
            foreach (var card in cards.EnumerateArray().Take(100))
            {
                if (ForecastPresentation.Text(card, "status") != "available") continue;
                var expiry = ForecastPresentation.Stamp(ForecastPresentation.Field(card, "expires_at"), "epoch_seconds");
                if (expiry is not null) groups[expiry.Value.ToUnixTimeSeconds()] = groups.GetValueOrDefault(expiry.Value.ToUnixTimeSeconds()) + 1;
            }
        }
        // 服务仅提供最近到期时间时，不推断具体张数。
        bool fallback = groups.Count == 0;
        if (fallback)
        {
            var count = ForecastPresentation.Field(value, "available_count");
            var next = ForecastPresentation.Stamp(ForecastPresentation.Field(value, "next_known_expiry"), "epoch_seconds");
            if (count.ValueKind == JsonValueKind.Number && count.TryGetInt32(out int n) && n > 0 && next is not null)
                groups[next.Value.ToUnixTimeSeconds()] = 0;
        }
        long nowSeconds = now.ToUnixTimeSeconds();
        alerted.RemoveWhere(item => item.Expiry <= nowSeconds);
        var messages = new List<string>();
        foreach (var (expiry, count) in groups.OrderBy(item => item.Key))
        {
            long seconds = expiry - nowSeconds;
            int level = seconds > 0 && seconds <= 86400 ? 1 : seconds > 0 && seconds <= 3 * 86400 ? 3 : 0;
            if (level == 0 || !alerted.Add((expiry, level))) continue;
            string amount = count > 0 ? $"{count} 张重置卡" : "有重置卡";
            messages.Add($"Codex {amount}将在 {level} 天内到期");
        }
        return messages;
    }
}
