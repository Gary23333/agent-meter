namespace AgentMeter.Windows;

/// <summary>限制应用内窗口只访问 TRAE 与其登录所需的 HTTPS 域名。</summary>
internal static class TraeNavigation
{
    static readonly string[] Domains = ["trae.cn", "trae.com.cn", "bytedance.com"];
    public static bool Allowed(string? address)
    {
        if (address == "about:blank") return true;
        if (!Uri.TryCreate(address, UriKind.Absolute, out var uri) || uri.Scheme != Uri.UriSchemeHttps ||
            !uri.IsDefaultPort || !string.IsNullOrEmpty(uri.UserInfo)) return false;
        string host = uri.IdnHost.TrimEnd('.').ToLowerInvariant();
        return Domains.Any(domain => host == domain || host.EndsWith("." + domain, StringComparison.Ordinal));
    }
    public static bool IsTrae(string? address)
    {
        if (!Allowed(address) || !Uri.TryCreate(address, UriKind.Absolute, out var uri) || uri.Scheme != Uri.UriSchemeHttps) return false;
        string host = uri.IdnHost.TrimEnd('.').ToLowerInvariant();
        return host is "trae.cn" or "trae.com.cn" || host.EndsWith(".trae.cn", StringComparison.Ordinal) || host.EndsWith(".trae.com.cn", StringComparison.Ordinal);
    }
}
