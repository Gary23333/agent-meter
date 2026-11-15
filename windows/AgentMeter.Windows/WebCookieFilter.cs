namespace AgentMeter.Windows;

/// <summary>只从应用自己的 WebView2 配置中选取目标接口可用的 Cookie。</summary>
internal static class WebCookieFilter
{
    internal sealed record Cookie(string Name, string Value, string Domain, string Path);
    const int MaxHeaderLength = 16000;

    public static string? WorkBuddyHeader(IEnumerable<Cookie> cookies)
    {
        const string endpointPath = "/billing/meter/get-user-resource-summary";
        var pieces = new List<string>();
        int length = 0;
        foreach (var cookie in cookies)
        {
            string domain = cookie.Domain.TrimStart('.').ToLowerInvariant();
            if (domain is not ("workbuddy.cn" or "www.workbuddy.cn")) continue;
            string path = cookie.Path;
            if (string.IsNullOrEmpty(path) || path[0] != '/' || !endpointPath.StartsWith(path, StringComparison.Ordinal) ||
                (path.Length > 1 && !path.EndsWith('/') && endpointPath.Length > path.Length && endpointPath[path.Length] != '/')) continue;
            if (cookie.Name.Length is < 1 or > 256 || cookie.Value.Length > 4096 ||
                cookie.Name.Any(c => c > 126 || c < 33 || "()<>@,;:\\\"/[]?={} \t".Contains(c)) ||
                cookie.Value.Any(c => c < 33 || c > 126 || c is ';' or ',' or '\\' or '"')) return null;
            string part = cookie.Name + "=" + cookie.Value;
            length += part.Length + (pieces.Count == 0 ? 0 : 2);
            if (length > MaxHeaderLength) return null;
            pieces.Add(part);
        }
        return pieces.Count == 0 ? null : string.Join("; ", pieces);
    }

    /// <summary>只选应用内 Qoder 资料中可发送至固定只读接口的 Cookie。</summary>
    public static string? QoderHeader(IEnumerable<Cookie> cookies)
    {
        const string endpointPath = "/api/v2/me/usages/big_model_credits";
        var pieces = new List<string>(); var seen = new HashSet<string>(StringComparer.Ordinal); int length = 0;
        foreach (var cookie in cookies)
        {
            string domain = cookie.Domain.TrimStart('.').ToLowerInvariant();
            if (domain != "qoder.com.cn") continue;
            string path = cookie.Path;
            if (string.IsNullOrEmpty(path) || path[0] != '/' || !endpointPath.StartsWith(path, StringComparison.Ordinal) ||
                (path.Length > 1 && !path.EndsWith('/') && endpointPath.Length > path.Length && endpointPath[path.Length] != '/')) continue;
            if (cookie.Name.Length is < 1 or > 256 || cookie.Value.Length > 4096 || !seen.Add(cookie.Name) ||
                cookie.Name.Any(c => c > 126 || c < 33 || "()<>@,;:\"/[]?={} \t".Contains(c)) ||
                cookie.Value.Any(c => c < 33 || c > 126 || c is ';' or ',' or '\\' or '"')) return null;
            string part = cookie.Name + "=" + cookie.Value;
            length += part.Length + (pieces.Count == 0 ? 0 : 2);
            if (length > MaxHeaderLength) return null;
            pieces.Add(part);
        }
        return pieces.Count == 0 ? null : string.Join("; ", pieces);
    }

    /// <summary>MiMo 的三个接口共用请求头，只接受同时覆盖三个路径的指定 Cookie。</summary>
    public static string? MiMoHeader(IEnumerable<Cookie> cookies)
    {
        string[] paths = ["/api/v1/balance", "/api/v1/tokenPlan/detail", "/api/v1/tokenPlan/usage"];
        var allowed = new HashSet<string>(["api-platform_serviceToken", "userId", "api-platform_ph", "api-platform_slh"], StringComparer.Ordinal);
        var seen = new HashSet<string>(StringComparer.Ordinal);
        var pieces = new List<string>(); int length = 0;
        foreach (var cookie in cookies)
        {
            string domain = cookie.Domain.TrimStart('.').ToLowerInvariant();
            if (domain is not ("xiaomimimo.com" or "platform.xiaomimimo.com") || !allowed.Contains(cookie.Name)) continue;
            string path = cookie.Path;
            if (string.IsNullOrEmpty(path) || path[0] != '/' || paths.Any(endpoint => !endpoint.StartsWith(path, StringComparison.Ordinal) ||
                (path.Length > 1 && !path.EndsWith('/') && endpoint.Length > path.Length && endpoint[path.Length] != '/'))) continue;
            if (!seen.Add(cookie.Name) || cookie.Value.Length is < 1 or > 4096 ||
                cookie.Value.Any(c => c < 33 || c > 126 || c is ';' or ',' or '\\' or '"')) return null;
            string part = cookie.Name + "=" + cookie.Value;
            length += part.Length + (pieces.Count == 0 ? 0 : 2);
            if (length > MaxHeaderLength) return null;
            pieces.Add(part);
        }
        return seen.Contains("api-platform_serviceToken") && seen.Contains("userId") ? string.Join("; ", pieces) : null;
    }
}
