namespace AgentMeter.Windows;

/// <summary>应用内登录只允许小米 MiMo 平台及其小米账号 HTTPS 跳转。</summary>
internal static class MiMoNavigation
{
    static readonly string[] Domains = ["xiaomimimo.com", "xiaomi.com", "mi.com"];
    public static bool Allowed(string? address)
    {
        if (address == "about:blank") return true;
        if (!Uri.TryCreate(address, UriKind.Absolute, out var uri) || uri.Scheme != Uri.UriSchemeHttps ||
            !uri.IsDefaultPort || !string.IsNullOrEmpty(uri.UserInfo)) return false;
        string host = uri.IdnHost.TrimEnd('.').ToLowerInvariant();
        return Domains.Any(domain => host == domain || host.EndsWith("." + domain, StringComparison.Ordinal));
    }
    public static bool IsPlatform(string? address)
    {
        if (!Allowed(address) || !Uri.TryCreate(address, UriKind.Absolute, out var uri) || uri.Scheme != Uri.UriSchemeHttps) return false;
        return uri.IdnHost.Equals("platform.xiaomimimo.com", StringComparison.OrdinalIgnoreCase);
    }
}
