using System.Text.Json;

namespace AgentMeter.Windows;

internal sealed record TrayReading(string Provider, string Window, double Remaining, DateTimeOffset? ResetAt, bool Partial);
internal sealed record TrayIndicator(TrayReading? Reading, string Tooltip)
{
    public static readonly (string Id, string Label)[] Choices = [
        ("lowest", "最低余量（自动）"), ("codex", "Codex"), ("claude", "Claude Code"), ("kimi", "Kimi Code"),
        ("minimax", "MiniMax（最低账户）"), ("workbuddy", "WorkBuddy"), ("brand", "仅显示应用图标") ];
    public static bool IsChoice(string mode) => Choices.Any(choice => choice.Id == mode);
    public string IconKey => Reading is null ? "brand" : $"{Math.Round(Reading.Remaining, MidpointRounding.AwayFromZero)}:{(Reading.Remaining < 20 ? 0 : Reading.Remaining < 50 ? 1 : 2)}";

    /// <summary>只比较可用账户的额度窗口；不把未知值、过期窗口、余额或积分绝对值混入百分比。</summary>
    public static TrayIndicator Build(JsonElement root, string mode, DateTimeOffset now, bool demo = false)
    {
        string prefix = demo ? "Agent Meter · 演示数据" : "Agent Meter";
        if (mode == "brand" || !IsChoice(mode)) return new(null, prefix + " · AI 用量");
        var observed = ForecastPresentation.Stamp(root, "observed_at");
        if (observed is null) return new(null, prefix + "\n尚无可信的账户采集时间");
        if (!demo && (now - observed > TimeSpan.FromMinutes(30) || observed - now > TimeSpan.FromMinutes(5)))
            return new(null, prefix + "\n账户快照已过期或时钟异常，请刷新");
        var readings = new List<TrayReading>();
        void Add(string id, string provider, JsonElement account)
        {
            if (mode != "lowest" && mode != id) return;
            string status = ForecastPresentation.Text(account, "status");
            if (status is not ("available" or "partial")) return;
            foreach (var window in QuotaWindows.All(account))
            {
                DateTimeOffset? reset = window.ResetAt.HasValue ? DateTimeOffset.FromUnixTimeSeconds(window.ResetAt.Value) : null;
                if (!demo && reset <= now) continue;
                readings.Add(new(provider, window.Label, window.Remaining, reset, status == "partial"));
            }
        }
        var others = ForecastPresentation.Field(root, "other_accounts");
        Add("codex", "Codex", ForecastPresentation.Field(root, "account"));
        Add("claude", "Claude Code", ForecastPresentation.Field(others, "Claude Code"));
        Add("kimi", "Kimi Code", ForecastPresentation.Field(others, "Kimi Code"));
        var minimax = ForecastPresentation.Field(others, "MiniMax Code");
        if (minimax.ValueKind == JsonValueKind.Array)
            foreach (var account in minimax.EnumerateArray().Take(5)) Add("minimax", "MiniMax · 多账户", account);
        else Add("minimax", "MiniMax", minimax);
        Add("workbuddy", "WorkBuddy", ForecastPresentation.Field(others, "WorkBuddy"));
        var chosen = readings.OrderBy(reading => reading.Remaining).FirstOrDefault();
        if (chosen is null) return new(null, prefix + "\n所选来源暂无可用额度，请打开面板查看");
        string text = $"{prefix}\n{chosen.Provider} · {chosen.Window}剩余 {chosen.Remaining:0.#}%" +
            (chosen.Partial ? " · 部分数据" : "") +
            (chosen.ResetAt.HasValue ? "\n重置 " + chosen.ResetAt.Value.LocalDateTime.ToString("MM-dd HH:mm") : "") +
            "\n采集 " + observed.Value.LocalDateTime.ToString("HH:mm:ss");
        return new(chosen, text.Length > 127 ? text[..126] + "…" : text);
    }
}

/// <summary>仅保存显示来源，不保存账户快照或账户别名。</summary>
internal static class TrayIndicatorPreferences
{
    public static string Load(string directory)
    {
        try
        {
            using var document = JsonDocument.Parse(File.ReadAllText(Path.Combine(directory, "tray-display.json")));
            string mode = ForecastPresentation.Text(document.RootElement, "mode");
            return TrayIndicator.IsChoice(mode) ? mode : "brand";
        }
        catch (FileNotFoundException) { return "lowest"; }
        catch (DirectoryNotFoundException) { return "lowest"; }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException or System.Security.SecurityException) { return "brand"; }
    }
    public static void Save(string directory, string mode)
    {
        if (!TrayIndicator.IsChoice(mode)) throw new ArgumentException("未知托盘显示来源");
        Directory.CreateDirectory(directory);
        string temporary = Path.Combine(directory, Path.GetRandomFileName());
        bool created = false;
        try
        {
            using (var file = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            { created = true; JsonSerializer.Serialize(file, new { mode }); }
            File.Move(temporary, Path.Combine(directory, "tray-display.json"), overwrite: true);
        }
        finally
        {
            try { if (created) File.Delete(temporary); }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException) { }
        }
    }
}
