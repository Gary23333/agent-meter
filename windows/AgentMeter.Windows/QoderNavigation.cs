namespace AgentMeter.Windows;

/// <summary>限制应用内登录窗口只访问 Qoder 中国区的 HTTPS 站点。</summary>
internal static class QoderNavigation
{
    static readonly string[] Domains = ["qoder.com.cn"];

    public static bool Allowed(string? address)
    {
        if (address == "about:blank") return true;
        if (!Uri.TryCreate(address, UriKind.Absolute, out var uri) || uri.Scheme != Uri.UriSchemeHttps ||
            !uri.IsDefaultPort || !string.IsNullOrEmpty(uri.UserInfo)) return false;
        string host = uri.IdnHost.TrimEnd('.').ToLowerInvariant();
        return Domains.Any(domain => host == domain || host.EndsWith("." + domain, StringComparison.Ordinal));
    }

    public static bool IsQoder(string? address)
    {
        if (!Allowed(address) || !Uri.TryCreate(address, UriKind.Absolute, out var uri) || uri.Scheme != Uri.UriSchemeHttps) return false;
        string host = uri.IdnHost.TrimEnd('.').ToLowerInvariant();
        return host == "qoder.com.cn" || host.EndsWith(".qoder.com.cn", StringComparison.Ordinal);
    }
}
