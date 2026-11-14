using System.Text.Json;

namespace AgentMeter.Windows;

/// <summary>账户周期时钟只使用服务给出的时间，与第三方全局预测分开。</summary>
internal static class QuotaResetClock
{
    public static long? Read(JsonElement quota)
    {
        var value = ForecastPresentation.Stamp(ForecastPresentation.Field(quota, "resets_at"), "epoch_seconds");
        return value?.ToUnixTimeSeconds();
    }
    public static string Short(long? epoch, DateTimeOffset now)
    {
        if (epoch is null || epoch < 0 || epoch > 253402300799) return "重置时间未知";
        var remaining = DateTimeOffset.FromUnixTimeSeconds(epoch.Value) - now;
        if (remaining <= TimeSpan.Zero) return "已到时间 · 待刷新";
        long minutes = (long)Math.Ceiling(remaining.TotalMinutes);
        return minutes >= 1440 ? $"{minutes / 1440} 天 {minutes % 1440 / 60} 时后" :
               minutes >= 60 ? $"{minutes / 60} 时 {minutes % 60} 分后" : $"{minutes} 分后";
    }
    public static string Detail(long? epoch, DateTimeOffset now)
    {
        if (epoch is null || epoch < 0 || epoch > 253402300799) return "重置时间未提供";
        string duration = Short(epoch, now);
        return duration + (epoch > now.ToUnixTimeSeconds() ? "重置" : "") + " · " + DateTimeOffset.FromUnixTimeSeconds(epoch.Value).LocalDateTime.ToString("MM-dd HH:mm");
    }
}
