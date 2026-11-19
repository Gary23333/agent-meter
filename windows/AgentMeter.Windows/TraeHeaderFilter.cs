namespace AgentMeter.Windows;

/// <summary>只接受 TRAE 固定 API 来源的短期授权头，不读取请求正文。</summary>
internal static class TraeHeaderFilter
{
    public static string? Token(string? address, string? authorization)
    {
        if (!Uri.TryCreate(address, UriKind.Absolute, out var uri) || uri.Scheme != Uri.UriSchemeHttps ||
            !uri.IsDefaultPort || !string.IsNullOrEmpty(uri.UserInfo) ||
            !uri.IdnHost.Equals("api.trae.cn", StringComparison.OrdinalIgnoreCase)) return null;
        const string prefix = "Cloud-IDE-JWT ";
        if (authorization is null || !authorization.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) return null;
        string token = authorization[prefix.Length..];
        if (token.Length is < 20 or > 4096 || token.Any(c => !char.IsAsciiLetterOrDigit(c) && c is not ('.' or '_' or '-'))) return null;
        return token;
    }
    public static string? Device(string? value) => value is { Length: > 0 and <= 256 } && value.All(c => c is >= '!' and <= '~') ? value : null;
}
