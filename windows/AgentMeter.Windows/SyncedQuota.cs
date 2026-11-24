using System.Text.Json;

namespace AgentMeter.Windows;

internal sealed record SyncedQuotaAccount(string Heading, IReadOnlyList<QuotaWindow> Windows);

/// <summary>只有其他设备能读取的账户额度；同账户已由后台按额度去重。</summary>
internal static class SyncedQuota
{
    const int MaxAccounts = 20;
    static readonly Dictionary<string, string> Names = new()
    {
        ["codex"] = "CODEX", ["claude"] = "CLAUDE CODE", ["kimi"] = "KIMI CODE", ["minimax_code"] = "MINIMAX CODE",
        ["workbuddy"] = "WORKBUDDY", ["zcode"] = "ZCODE", ["volcengine"] = "火山方舟", ["qoder"] = "QODER CN",
        ["trae_cn"] = "TRAE CN", ["mimo"] = "MiMo 平台", ["deepseek_api"] = "DEEPSEEK API", ["doubao"] = "豆包",
    };

    public static IReadOnlyList<SyncedQuotaAccount> Read(JsonElement view)
    {
        if (view.ValueKind != JsonValueKind.Object || !view.TryGetProperty("accounts", out var accounts) ||
            accounts.ValueKind != JsonValueKind.Array) return [];
        var output = new List<SyncedQuotaAccount>();
        foreach (var account in accounts.EnumerateArray().Take(MaxAccounts))
        {
            if (account.ValueKind != JsonValueKind.Object) continue;
            var windows = QuotaWindows.All(account).ToList();
            if (windows.Count == 0) continue;
            // 与本机账户卡片同样呈现，不标注来源设备，两台设备看起来像一台。
            string provider = Clean(account, "provider", 40);
            string name = Names.TryGetValue(provider, out var known) ? known : provider.ToUpperInvariant();
            output.Add(new SyncedQuotaAccount(name, windows));
        }
        return output;
    }

    static string Clean(JsonElement item, string key, int limit) =>
        item.TryGetProperty(key, out var value) && value.ValueKind == JsonValueKind.String
            ? new string((value.GetString() ?? "").Where(c => !char.IsControl(c)).Take(limit).ToArray()) : "";
}
