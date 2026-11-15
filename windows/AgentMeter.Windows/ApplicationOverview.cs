using System.Text.Json;

namespace AgentMeter.Windows;

/// <summary>汇总已读取的指标；不根据历史记录推断程序安装或运行状态。</summary>
internal sealed record ApplicationOverview(string Name, string Quota, string Local, double? Today, double? All,
    string Activity, int Sessions, int RecentUpdates, long? LastUpdated)
{
    static JsonElement Get(JsonElement item, string key) => item.ValueKind == JsonValueKind.Object && item.TryGetProperty(key, out var value) ? value : default;
    static string Text(JsonElement item, string key) => Get(item, key).ValueKind == JsonValueKind.String ? Get(item, key).GetString() ?? "" : "";
    static double? Number(JsonElement item, string key)
    {
        var value = Get(item, key);
        return value.ValueKind == JsonValueKind.Number && value.TryGetDouble(out double n) && double.IsFinite(n) && n >= 0 ? n : null;
    }
    static string QuotaState(JsonElement item)
    {
        if (item.ValueKind == JsonValueKind.Array)
        {
            var items = item.EnumerateArray().ToArray();
            if (items.Length == 0) return "未连接";
            var states = items.Select(QuotaState).ToArray();
            return states.All(state => state == "可用") ? "可用" : states.Contains("可用") ? "部分可用" : states[0];
        }
        string status = Text(item, "status");
        if (status == "disabled") return "已关闭";
        if (status == "loading") return "读取中";
        if (status == "partial") return "部分可用";
        if (status == "available")
        {
            var value = Get(Get(item, "quota"), "value");
            return value.ValueKind == JsonValueKind.Array && value.GetArrayLength() > 0 ? "可用" : "未提供";
        }
        return status is "error" or "unavailable" ? "未连接或不可用" : "未提供";
    }
    public static IReadOnlyList<ApplicationOverview> Build(JsonElement root)
    {
        var definitions = new (string Name, string History, string Activity, string? Account)[] {
            ("Codex", "Codex", "Codex", "@codex"), ("Claude Code", "Claude Code", "Claude Code", "Claude Code"),
            ("Kimi Code", "Kimi Code", "Kimi Code", "Kimi Code"), ("MiniMax Code", "MiniMax Code", "MiniMax Code", "MiniMax Code"),
            ("WorkBuddy", "WorkBuddy", "WorkBuddy", "WorkBuddy"), ("ZCode", "ZCode", "ZCode", "ZCode"),
            ("火山方舟", "火山方舟", "火山方舟", "Volcengine"),
            ("MiMo 平台", "MiMo 平台", "MiMo 平台", "MiMo"), ("Qoder CN", "Qoder CN", "Qoder CN", "Qoder CN"),
            ("Gemini CLI", "Gemini CLI", "Gemini CLI", null), ("DeepSeek Harness", "DeepSeek Harness", "DeepSeek Harness", null),
            ("Kimi CLI（旧版）", "Kimi CLI (旧版)", "Kimi CLI（旧版）", null), ("Kimi 桌面端", "Kimi 桌面端", "Kimi 桌面端", null),
            ("OpenCode", "OpenCode", "OpenCode", null), ("MiMo Code", "MiMo Code", "MiMo Code", null),
            ("DevECo", "DevECo", "DevECo", null), ("Codex 生图", "Codex 生图", "Codex 生图", null)
        };
        var history = Get(root, "history"); var accounts = Get(root, "other_accounts");
        var activity = Get(root, "activity"); var sources = Get(activity, "sources"); var entries = Get(activity, "apps");
        bool loading = Text(Get(history, "历史统计"), "status") == "loading";
        var rows = new List<ApplicationOverview>();
        foreach (var definition in definitions)
        {
            var item = Get(history, definition.History);
            string rawLocal = Text(item, "status"), reason = Text(item, "reason");
            string local = rawLocal switch { "available" => "可用", "partial" => "部分可用", "loading" => "读取中",
                "error" => "读取失败", "not_provided" => "无用量记录",
                "unavailable" when reason.EndsWith("_not_found", StringComparison.Ordinal) => "未找到记录",
                "unavailable" => "不可用", _ => "未提供" };
            var totals = Get(Get(item, "value"), "periods");
            double? today = Number(Get(Get(totals, "today"), "totals"), "total_tokens");
            double? all = Number(Get(Get(totals, "all"), "totals"), "total_tokens");
            bool hasLocal = today.HasValue || all.HasValue || Number(Get(Get(totals, "7d"), "totals"), "total_tokens").HasValue ||
                Number(Get(Get(totals, "30d"), "totals"), "total_tokens").HasValue;
            if (!hasLocal && rawLocal == "available") local = "未提供";
            if (!hasLocal && rawLocal == "partial") local = "记录不完整";
            if (rawLocal == "" && loading) local = "读取中";
            var account = definition.Account == "@codex" ? Get(root, "account") : definition.Account is null ? default : Get(accounts, definition.Account);
            string quota = definition.Account is null ? "暂不支持" : QuotaState(account);
            var matched = default(JsonElement);
            if (entries.ValueKind == JsonValueKind.Array)
                foreach (var entry in entries.EnumerateArray())
                    if (Text(entry, "name") == definition.Activity) { matched = entry; break; }
            double? sessionsRaw = Number(matched, "sessions"), recentRaw = Number(matched, "recent_updates"), lastRaw = Number(matched, "last_updated");
            bool validActivity = sessionsRaw.HasValue && recentRaw.HasValue && sessionsRaw <= int.MaxValue && recentRaw <= sessionsRaw &&
                lastRaw.HasValue && lastRaw <= 253402300799 && Math.Floor(sessionsRaw.Value) == sessionsRaw && Math.Floor(recentRaw.Value) == recentRaw;
            int sessions = validActivity ? (int)sessionsRaw!.Value : 0, recent = validActivity ? (int)recentRaw!.Value : 0;
            string source = Text(sources, definition.Activity);
            string activityState = validActivity ? (source == "partial" ? "有记录（部分）" : "有记录") : source switch { "available" => "近 24 小时无记录", "partial" => "记录不完整", "not_found" => "未找到记录",
                "disabled" => "已关闭", "unavailable" => "不可用", _ when loading => "读取中", _ => "未覆盖" };
            bool visible = validActivity || source is "available" or "partial" or "unavailable" || rawLocal is "available" or "partial" or "error" ||
                (rawLocal == "unavailable" && !reason.EndsWith("_not_found", StringComparison.Ordinal)) ||
                (definition.Account is not null && quota is not ("已关闭" or "未提供"));
            if (visible) rows.Add(new ApplicationOverview(definition.Name, quota, local, today, all, activityState,
                sessions, recent, validActivity ? (long)lastRaw!.Value : null));
        }
        return rows.OrderByDescending(row => row.RecentUpdates).ThenByDescending(row => row.LastUpdated ?? 0)
            .ThenBy(row => row.Name, StringComparer.Ordinal).ToArray();
    }
}
