namespace AgentMeter.Windows;

/// <summary>只在可见的应用页面按间隔更新本机活动，避免与完整刷新并行。</summary>
internal static class ActivityRefreshPolicy
{
    public static bool CanRefresh(bool demo, bool visible, bool applicationsView, bool fullRefreshBusy,
        bool activityRefreshBusy, bool hasSnapshot, DateTimeOffset lastAttempt, DateTimeOffset now) =>
        !demo && visible && applicationsView && !fullRefreshBusy && !activityRefreshBusy && hasSnapshot &&
        now - lastAttempt >= TimeSpan.FromSeconds(60);
}
