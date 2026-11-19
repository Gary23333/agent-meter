using System.Text.Json;
using System.Text.Json.Nodes;

namespace AgentMeter.Windows;

internal sealed partial class MeterWindow
{
    /// <summary>每个来源完成后立即合并，避免慢来源挡住已完成的账户或本机数据。</summary>
    async Task ApplyRefreshPartsAsync(JsonObject snapshot, List<(string Name, Task<string> Task)> pending, bool partialFailure,
        bool profilesInvalid = false, Func<JsonObject, Task<string>>? startCards = null)
    {
        int finished = 0;
        while (pending.Count > 0)
        {
            var ready = await Task.WhenAny(pending.Select(part => part.Task));
            int index = pending.FindIndex(part => ReferenceEquals(part.Task, ready));
            var (name, task) = pending[index]; pending.RemoveAt(index);
            try
            {
                var data = JsonNode.Parse(await task) as JsonObject ?? throw new JsonException("refresh_part_not_object");
                if (name == "accounts")
                {
                    if (data["account"] is not JsonObject || data["other_accounts"] is not JsonObject)
                        throw new JsonException("account_bundle_incomplete");
                    snapshot["version"] = data["version"]?.DeepClone();
                    snapshot["observed_at"] = data["observed_at"]?.DeepClone() ?? snapshot["observed_at"]?.DeepClone();
                    snapshot["account"] = data["account"]?.DeepClone() ?? new JsonObject { ["status"] = "error", ["reason"] = "account_read_failed" };
                    var others = data["other_accounts"] as JsonObject;
                    foreach (string key in new[] { "Kimi Code", "Claude Code", "MiniMax Code" })
                        snapshot["other_accounts"]![key] = others?[key]?.DeepClone() ?? new JsonObject { ["status"] = "error" };
                    if (profilesInvalid) snapshot["other_accounts"]!["MiniMax Code"] = new JsonObject { ["status"] = "error", ["reason"] = "minimax_profiles_invalid" };
                }
                else if (name == "history")
                {
                    if (data["history"] is not JsonObject) throw new JsonException("history_bundle_incomplete");
                    foreach (string key in new[] { "history", "local_credits", "image_files", "daily_trend", "calendar_report", "local_medals", "activity", "price_status", "budget" })
                        snapshot[key] = data[key]?.DeepClone();
                    lastActivityAttempt = DateTimeOffset.UtcNow;
                }
                else if (name == "quota_cards" || name == "forecast") snapshot[name] = data;
                else snapshot["other_accounts"]![name] = data;
            }
            catch (Exception ex) when (!shutdown.IsCancellationRequested && ex is IOException or InvalidOperationException or JsonException or System.ComponentModel.Win32Exception or OperationCanceledException)
            {
                partialFailure = true;
                if (name == "accounts")
                {
                    snapshot["account"] = new JsonObject { ["status"] = "error", ["reason"] = "account_read_failed" };
                    foreach (string key in new[] { "Kimi Code", "Claude Code", "MiniMax Code" })
                        snapshot["other_accounts"]![key] = new JsonObject { ["status"] = "error" };
                    if (profilesInvalid) snapshot["other_accounts"]!["MiniMax Code"] = new JsonObject { ["status"] = "error", ["reason"] = "minimax_profiles_invalid" };
                }
                else if (name == "history")
                {
                    snapshot["history"] = new JsonObject { ["历史统计"] = new JsonObject { ["status"] = "error", ["reason"] = "history_scan_failed" } };
                    snapshot["local_medals"] = new JsonObject { ["status"] = "error", ["incomplete"] = true, ["medals"] = new JsonArray() };
                }
                else if (name == "quota_cards" || name == "forecast") snapshot[name] = new JsonObject { ["status"] = "error" };
                else snapshot["other_accounts"]![name] = new JsonObject { ["status"] = "error" };
            }
            ApplyAccountPreferences(snapshot);
            if (!demo) BudgetState.Apply(snapshot, AccountPreferences.DefaultDirectory);
            static bool HasError(JsonNode? node) => node is JsonArray items ? items.Any(HasError) :
                node is JsonObject item && item["status"] is JsonValue value && value.TryGetValue<string>(out var state) && state == "error";
            if (name == "accounts")
                partialFailure |= HasError(snapshot["account"]) || new[] { "Kimi Code", "Claude Code", "MiniMax Code" }.Any(key => HasError(snapshot["other_accounts"]![key]));
            else if (name == "history" && snapshot["history"] is JsonObject histories)
                partialFailure |= histories.Any(item => HasError(item.Value));
            else if (name is "quota_cards" or "forecast") partialFailure |= HasError(snapshot[name]);
            else partialFailure |= HasError(snapshot["other_accounts"]![name]);
            if (name == "accounts" && startCards is not null) pending.Add(("quota_cards", startCards(snapshot)));
            using (var document = JsonDocument.Parse(snapshot.ToJsonString()))
            {
                Render(document.RootElement);
                NotifyLowQuota(document.RootElement);
                if (name == "history" && !demo && BudgetTriggered is not null)
                {
                    try
                    {
                        var alerts = BudgetAlerts.TakePending(GetValue(document.RootElement, "budget"), AccountPreferences.DefaultDirectory, DateTimeOffset.UtcNow);
                        if (alerts.Count > 0) BudgetTriggered.Invoke(alerts);
                    }
                    catch (Exception ex) when (ex is InvalidDataException or IOException or UnauthorizedAccessException or System.Security.SecurityException)
                    { partialFailure = true; }
                }
            }
            finished++;
            status.Text = pending.Count > 0 ? $"正在刷新 · 已完成 {finished} 项" : partialFailure
                ? "部分数据读取失败 · 请稍后刷新" : $"更新于 {DateTime.Now:HH:mm:ss}  ·  本机历史 ≠ 账户总用量";
        }
    }

    internal async Task SyntheticRefreshPartsSmokeAsync()
    {
        if (!demo) throw new InvalidOperationException("仅允许演示数据检查刷新顺序");
        var original = preferences;
        var accounts = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
        var history = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
        var workbuddy = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
        var qoder = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
        var cards = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
        try
        {
            preferences = preferences with { WorkBuddy = true, Qoder = true };
            var snapshot = JsonNode.Parse(DemoData)!.AsObject();
            snapshot["account"] = JsonNode.Parse("""{"status":"loading"}""");
            snapshot["history"] = JsonNode.Parse("""{"历史统计":{"status":"loading"}}""");
            snapshot["other_accounts"]!["WorkBuddy"] = JsonNode.Parse("""{"status":"loading"}""");
            var pending = new List<(string Name, Task<string> Task)> {
                ("accounts", accounts.Task), ("history", history.Task), ("WorkBuddy", workbuddy.Task), ("Qoder CN", qoder.Task) };
            bool cardStarted = false;
            var running = ApplyRefreshPartsAsync(snapshot, pending, false, startCards: input =>
            {
                cardStarted = true;
                if (input["account"]!["status"]!.GetValue<string>() != "available") throw new InvalidOperationException("卡册必须等待账户结果");
                return cards.Task;
            });
            workbuddy.SetResult("""{"status":"available","credits":{"value":{"amount":"8"}}}""");
            for (int i = 0; i < 100 && snapshot["other_accounts"]!["WorkBuddy"]!["status"]!.GetValue<string>() != "available"; i++)
                await Task.Delay(10);
            if (running.IsCompleted || snapshot["other_accounts"]!["WorkBuddy"]!["status"]!.GetValue<string>() != "available" ||
                !lastSnapshot!.Contains("\"WorkBuddy\":{\"status\":\"available\"", StringComparison.Ordinal) ||
                snapshot["history"]!["历史统计"]!["status"]!.GetValue<string>() != "loading")
                throw new InvalidOperationException("已完成的账户不应等待慢速本机扫描");
            history.SetResult("""{"history":{"Codex":{"status":"available"}},"activity":{"status":"available","apps":[]}}""");
            for (int i = 0; i < 100 && snapshot["history"]!["Codex"] is null; i++) await Task.Delay(10);
            if (running.IsCompleted || cardStarted || snapshot["account"]!["status"]!.GetValue<string>() != "loading" ||
                snapshot["history"]!["Codex"]!["status"]!.GetValue<string>() != "available")
                throw new InvalidOperationException("已完成的本机扫描不应等待慢速账户");
            preferences = preferences with { Qoder = false };
            qoder.SetResult("""{"status":"available","quota":{"value":[{"remaining_percent":55}]}}""");
            accounts.SetResult("""{"version":1,"observed_at":1800000000,"account":{"status":"available"},"other_accounts":{}}""");
            cards.SetException(new IOException("synthetic_failure"));
            await running;
            if (!cardStarted || snapshot["other_accounts"]!["WorkBuddy"]!["status"]!.GetValue<string>() != "available" ||
                snapshot["other_accounts"]!["Qoder CN"]!["status"]!.GetValue<string>() != "disabled" ||
                snapshot["history"]!["Codex"]!["status"]!.GetValue<string>() != "available" ||
                snapshot["quota_cards"]!["status"]!.GetValue<string>() != "error" || !status.Text.Contains("部分数据读取失败"))
                throw new InvalidOperationException("刷新结果合并、关闭来源或部分失败处理错误");

            var malformed = JsonNode.Parse(DemoData)!.AsObject();
            var invalidParts = new List<(string Name, Task<string> Task)> {
                ("accounts", Task.FromResult("{}")),
                ("history", Task.FromResult("""{"history":{"Codex":{"status":"available"}}}""")) };
            await ApplyRefreshPartsAsync(malformed, invalidParts, false, startCards: _ => Task.FromResult("""{"status":"available"}"""));
            if (malformed["account"]!["status"]!.GetValue<string>() != "error" ||
                malformed["history"]!["Codex"]!["status"]!.GetValue<string>() != "available" ||
                malformed["quota_cards"]!["status"]!.GetValue<string>() != "available" || !status.Text.Contains("部分数据读取失败"))
                throw new InvalidOperationException("损坏的账户结果不应覆盖可用本机记录");
            var reportedFailure = JsonNode.Parse(DemoData)!.AsObject();
            await ApplyRefreshPartsAsync(reportedFailure, [("quota_cards", Task.FromResult("""{"status":"error"}"""))], false);
            if (!status.Text.Contains("部分数据读取失败")) throw new InvalidOperationException("来源返回错误状态时应提示部分失败");
        }
        finally { preferences = original; }
    }

    internal async Task SyntheticFullRefreshSmokeAsync()
    {
        // 此入口仅供隔离构建机调用；关闭所有账户和预测，读取测试专用空目录。
        if (Environment.GetEnvironmentVariable("AGENT_METER_ISOLATED_SMOKE") != "1") throw new InvalidOperationException("仅允许隔离环境检查完整刷新");
        preferences = AccountPreferences.Disabled; forecastEnabled = false;
        await RefreshData();
        using var snapshot = JsonDocument.Parse(lastSnapshot ?? throw new InvalidOperationException("完整刷新未生成结果"));
        var root = snapshot.RootElement;
        if (GetString(GetValue(root, "account"), "status", "") != "disabled" ||
            GetString(GetValue(GetValue(root, "history"), "Codex"), "reason", "") != "codex_sessions_not_found" ||
            GetString(GetValue(root, "quota_cards"), "status", "") != "available" ||
            !status.Text.StartsWith("更新于", StringComparison.Ordinal))
            throw new InvalidOperationException("打包程序的隔离完整刷新结果错误");
    }
}
