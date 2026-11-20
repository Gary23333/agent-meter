using System.Text.Json;

namespace AgentMeter.Windows;

internal sealed record RewardRow(string Id, string Title, string Today, string Claimed, string Checked, string Detail);

/// <summary>把后端领取结果整理为可展示的行；不猜测缺失字段。</summary>
internal static class RewardsReport
{
    public static IReadOnlyList<RewardRow> Read(string? json)
    {
        var rows = new List<RewardRow>();
        if (string.IsNullOrWhiteSpace(json)) return rows;
        try
        {
            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;
            if (root.ValueKind != JsonValueKind.Object) return rows;
            var accounts = Get(root, "accounts");
            if (accounts.ValueKind == JsonValueKind.Array)
                foreach (var account in accounts.EnumerateArray())
                    if (account.ValueKind == JsonValueKind.Object) rows.Add(ReadAccount(account));
            var unsupported = Get(root, "unsupported");
            if (unsupported.ValueKind == JsonValueKind.Array)
                foreach (var item in unsupported.EnumerateArray())
                {
                    if (item.ValueKind != JsonValueKind.Object) continue;
                    string provider = Text(item, "provider");
                    string reason = Text(item, "reason");
                    rows.Add(new($"unsupported:{provider}", ProviderTitle(provider), "暂不支持", "—", "—", ReasonText(reason)));
                }
        }
        catch (Exception ex) when (ex is JsonException or InvalidOperationException or FormatException or OverflowException) { }
        return rows;
    }

    static RewardRow ReadAccount(JsonElement account)
    {
        string id = Text(account, "id");
        string provider = Text(account, "provider");
        if (provider.Length == 0) provider = id.Split('#')[0];
        string title = ProviderTitle(provider);
        if (id.Contains('#')) title += " · 账户 " + id[(id.IndexOf('#') + 1)..];
        string status = Text(account, "status");
        string reason = Text(account, "reason");
        string today = "—";
        var todayNode = Get(account, "today");
        if (status != "available")
            today = ReasonText(reason);
        else if (todayNode.ValueKind == JsonValueKind.Object)
            today = TodayText(todayNode);
        int claimed = Number(account, "claimed_credits_today");
        string claimedText = claimed > 0 ? $"{claimed} 积分" : "—";
        var checkedAt = Get(account, "checked_at");
        string checkedText = Text(checkedAt, "display");
        if (checkedText.Length == 0) checkedText = "—";
        var details = new List<string>();
        int streak = Number(account, "streak_days");
        if (streak > 0) details.Add($"连续 {streak} 天");
        var next = Get(account, "next_claim_at");
        string clock = Text(account, "claim_time");
        if (next.ValueKind == JsonValueKind.Object && clock.Length > 0) details.Add($"自动 {clock}");
        if (status == "error" && reason.Length == 0) details.Add("领取请求失败，已保留上次结果");
        string detail = details.Count > 0 ? string.Join(" · ", details) : "";
        return new RewardRow(id.Length > 0 ? id : provider, title, today, claimedText, checkedText, detail);
    }

    static string TodayText(JsonElement today)
    {
        if (today.TryGetProperty("signed_in", out var signed) && signed.ValueKind is JsonValueKind.True or JsonValueKind.False)
            return signed.GetBoolean() ? "已签到" : "未签到";
        var claimable = Get(today, "claimable");
        if (claimable.ValueKind == JsonValueKind.Array)
        {
            int count = claimable.GetArrayLength();
            int credits = 0;
            foreach (var item in claimable.EnumerateArray()) credits += Math.Max(0, Number(item, "credits"));
            return count > 0 ? $"{count} 项待领" + (credits > 0 ? $" · {credits} 积分" : "") : "暂无待领";
        }
        int open = Number(today, "open_tasks");
        if (open > 0) return $"{open} 项未完成";
        var tasks = Get(today, "tasks");
        if (tasks.ValueKind == JsonValueKind.Array && tasks.GetArrayLength() > 0) return $"{tasks.GetArrayLength()} 项待办";
        return "已读取";
    }

    static string ProviderTitle(string provider) => provider switch
    {
        "trae_cn" => "TRAE 每日签到",
        "workbuddy" => "WorkBuddy 成长任务",
        "qoder" => "Qoder 每日活动",
        "minimax_code" => "MiniMax Code 签到",
        _ => provider
    };

    static string ReasonText(string reason) => reason switch
    {
        "not_authenticated" => "登录已失效",
        "not_checked_yet" => "尚未读取",
        "not_checked_out" => "尚未读取",
        "disabled_by_user" => "已关闭",
        "qoder_desktop_credentials_macos_only" => "Windows 暂不支持桌面凭据",
        "minimax_code_not_supported" => "暂无签到接口",
        "rewards_session_unavailable" => "没有可用的登录会话",
        "refresh_in_progress" => "正在刷新，请稍后",
        "rewards_in_progress" => "正在领取，请稍后",
        "" => "暂时读不到",
        _ => "暂时读不到"
    };

    static JsonElement Get(JsonElement element, string name) =>
        element.ValueKind == JsonValueKind.Object && element.TryGetProperty(name, out var value) ? value : default;

    static string Text(JsonElement element, string name)
    {
        var value = Get(element, name);
        return value.ValueKind == JsonValueKind.String ? value.GetString() ?? "" : "";
    }

    static int Number(JsonElement element, string name)
    {
        var value = Get(element, name);
        if (value.ValueKind != JsonValueKind.Number || !value.TryGetInt32(out int number) || number < 0) return 0;
        return number;
    }
}
