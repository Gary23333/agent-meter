using System.Text.Json.Nodes;

namespace AgentMeter.Windows;

/// <summary>向本地卡册进程只传额度与必要账户标识，不传钱包、重置卡或凭据。</summary>
internal static class CardInput
{
    public static string Create(JsonObject snapshot)
    {
        static JsonNode? Quota(JsonNode? node)
        {
            if (node is not JsonObject quota || quota["value"] is not JsonArray rows) return null;
            var projected = new JsonArray();
            foreach (var item in rows)
            {
                if (item is not JsonObject row) continue;
                var reset = row["resets_at"] as JsonObject;
                var window = row["window"] as JsonObject;
                projected.Add(new JsonObject {
                    ["bucket"] = row["bucket"]?.DeepClone(), ["remaining_percent"] = row["remaining_percent"]?.DeepClone(),
                    ["window_minutes"] = row["window_minutes"]?.DeepClone(),
                    ["resets_at"] = reset is null ? null : new JsonObject { ["epoch_seconds"] = reset["epoch_seconds"]?.DeepClone() },
                    ["window"] = window is null ? null : new JsonObject { ["duration"] = window["duration"]?.DeepClone(), ["unit"] = window["unit"]?.DeepClone() }
                });
            }
            return new JsonObject { ["status"] = quota["status"]?.DeepClone(), ["value"] = projected };
        }
        static JsonNode? Project(JsonNode? node)
        {
            if (node is JsonArray rows)
            {
                var projected = new JsonArray();
                foreach (var row in rows) if (Project(row) is { } item) projected.Add(item);
                return projected;
            }
            if (node is not JsonObject account) return null;
            return new JsonObject { ["status"] = account["status"]?.DeepClone(), ["label"] = account["label"]?.DeepClone(),
                                    ["quota"] = Quota(account["quota"]) };
        }
        var source = snapshot["other_accounts"] as JsonObject;
        var others = new JsonObject();
        foreach (var name in new[] { "Kimi Code", "Claude Code", "MiniMax Code" })
            if (source is not null && source[name] is not null) others[name] = Project(source[name]);
        return new JsonObject { ["account"] = Project(snapshot["account"]), ["other_accounts"] = others }.ToJsonString();
    }
}
