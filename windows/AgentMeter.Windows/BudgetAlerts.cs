using System.Globalization;
using System.Text.Json;

namespace AgentMeter.Windows;

/// <summary>预算提醒按自然日／周去重，并在本机保存已通知的事件。</summary>
internal static class BudgetAlerts
{
    static JsonElement Get(JsonElement value, string key) => value.ValueKind == JsonValueKind.Object && value.TryGetProperty(key, out var item) ? item : default;
    static string Text(JsonElement value, string key) => Get(value, key).ValueKind == JsonValueKind.String ? Get(value, key).GetString() ?? "" : "";
    static decimal? Amount(JsonElement value, string key) => decimal.TryParse(Text(value, key), NumberStyles.Float, CultureInfo.InvariantCulture, out var amount) &&
        amount >= 0 && amount <= 1_000_000_000_000_000m ? amount : null;
    static string Money(decimal amount) => amount is > 0 and < 0.01m ? "<¥0.01" :
        "¥" + Math.Round(amount, 2, MidpointRounding.AwayFromZero).ToString("0.##", CultureInfo.InvariantCulture);

    internal static IReadOnlyList<string> TakePending(JsonElement budget, string directory, DateTimeOffset now)
    {
        if (Text(budget, "status") != "ok" || Get(budget, "alerts_enabled").ValueKind != JsonValueKind.True) return [];
        var sampled = ForecastPresentation.Stamp(Get(budget, "generated_at"), "epoch_seconds");
        if (sampled is null || now - sampled > TimeSpan.FromMinutes(30) || sampled - now > TimeSpan.FromMinutes(5)) return [];
        var events = Get(budget, "events"); if (events.ValueKind != JsonValueKind.Array) return [];
        string path = Path.Combine(directory, "budget-alerts.json");
        Dictionary<string, long> fired;
        try
        {
            if (new FileInfo(path).Length > 65536) throw new InvalidDataException("预算提醒记录过大");
            using var document = JsonDocument.Parse(File.ReadAllText(path));
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object || Get(root, "schema").ValueKind != JsonValueKind.Number || Get(root, "schema").GetInt32() != 1 ||
                Get(root, "events").ValueKind != JsonValueKind.Object) throw new InvalidDataException("预算提醒记录无效");
            fired = new Dictionary<string, long>(StringComparer.Ordinal);
            foreach (var entry in Get(root, "events").EnumerateObject())
            {
                if (entry.Name.Length > 100 || entry.Value.ValueKind != JsonValueKind.Number || !entry.Value.TryGetInt64(out long stamp) || stamp < 0)
                    throw new InvalidDataException("预算提醒记录无效");
                if (now.ToUnixTimeSeconds() - stamp <= 90L * 86400 && stamp <= now.ToUnixTimeSeconds() + 300) fired[entry.Name] = stamp;
            }
        }
        catch (FileNotFoundException) { fired = new(StringComparer.Ordinal); }
        catch (DirectoryNotFoundException) { fired = new(StringComparer.Ordinal); }
        catch (Exception ex) when (ex is JsonException or InvalidOperationException or FormatException or OverflowException)
        { throw new InvalidDataException("预算提醒记录无效", ex); }
        var messages = new List<string>();
        foreach (var item in events.EnumerateArray().Take(10))
        {
            string kind = Text(item, "kind"), date = Text(item, "date"), id = Text(item, "id");
            string prefix = kind switch { "daily_exceeded" => "budget_daily_exceeded:", "weekly_exceeded" => "budget_weekly_exceeded:", "anomaly" => "budget_anomaly:", _ => "" };
            var today = DateOnly.FromDateTime(now.ToOffset(TimeSpan.FromHours(8)).DateTime);
            var weekStart = today.AddDays(-((int)today.DayOfWeek + 6) % 7);
            if (prefix.Length == 0 || id != prefix + date || !DateOnly.TryParseExact(date, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var eventDate) ||
                eventDate != (kind == "weekly_exceeded" ? weekStart : today) || fired.ContainsKey(id)) continue;
            var spent = Amount(item, "spent_cny"); if (!spent.HasValue) continue;
            string message;
            if (kind == "anomaly")
            {
                var rate = Amount(item, "rate_cny_per_hour"); var multiplier = Amount(item, "multiplier");
                if (!rate.HasValue || !multiplier.HasValue || multiplier <= 0) continue;
                message = $"今日估算 {Money(spent.Value)}，约 {Money(rate.Value)}/小时，超过近期基准 {multiplier:0.##} 倍。";
            }
            else
            {
                var limit = Amount(item, "budget_cny"); if (!limit.HasValue) continue;
                var section = Get(budget, kind == "daily_exceeded" ? "daily" : "weekly");
                string lowerBound = Get(section, "partial").ValueKind == JsonValueKind.True ? "至少 " : "";
                message = $"{(kind == "daily_exceeded" ? "今日" : "本周")}估算{lowerBound}{Money(spent.Value)}，超过预算 {Money(limit.Value)}。";
            }
            messages.Add(message + "本机 API 等价估算，非实际账单。");
            fired[id] = now.ToUnixTimeSeconds();
        }
        if (messages.Count == 0) return messages;
        Directory.CreateDirectory(directory);
        string temporary = Path.Combine(directory, Path.GetRandomFileName()); bool created = false;
        try
        {
            using (var file = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            { created = true; JsonSerializer.Serialize(file, new { schema = 1, events = fired }); }
            File.Move(temporary, path, overwrite: true);
        }
        finally { try { if (created) File.Delete(temporary); } catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException) { } }
        return messages;
    }
}
