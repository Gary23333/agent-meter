using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Text;
using System.Globalization;
using System.Text.Json;

namespace AgentMeter.Windows;

/// <summary>从报告汇总生成本地分享图，不读取账户或对话内容。</summary>
internal static class ShareCardRenderer
{
    public static Bitmap Render(JsonElement snapshot, VisualTheme theme, bool demo = false)
    {
        _ = CalendarReportExport.Create(snapshot, demo); // 复用日期、计数和隐私边界校验。
        var report = snapshot.GetProperty("calendar_report");
        var periods = report.GetProperty("periods");
        var week = periods.GetProperty("week"); var month = periods.GetProperty("month");
        bool incomplete = report.TryGetProperty("incomplete", out var flag) && flag.ValueKind == JsonValueKind.True;
        var bitmap = new Bitmap(1200, 860);
        try
        {
            using var graphics = Graphics.FromImage(bitmap);
            graphics.SmoothingMode = SmoothingMode.AntiAlias;
            graphics.TextRenderingHint = TextRenderingHint.ClearTypeGridFit;
            using var background = new LinearGradientBrush(new Rectangle(0, 0, 1200, 860), theme.Background, theme.CardEnd, 35F);
            graphics.FillRectangle(background, 0, 0, 1200, 860);
            using var title = new Font("Microsoft YaHei UI", 37, FontStyle.Bold);
            using var brand = new Font("Segoe UI", 14, FontStyle.Bold);
            using var label = new Font("Microsoft YaHei UI", 17, FontStyle.Bold);
            using var number = new Font("Segoe UI", 35, FontStyle.Bold);
            using var small = new Font("Microsoft YaHei UI", 12);
            using var primary = new SolidBrush(theme.Primary);
            using var muted = new SolidBrush(theme.Secondary);
            using var accent = new SolidBrush(theme.Accent);
            graphics.FillEllipse(accent, 66, 58, 15, 15);
            graphics.DrawString("AGENT METER", brand, primary, 92, 51);
            graphics.DrawString("本机用量报告", title, primary, 62, 105);
            graphics.DrawString("自然周期  ·  北京时间  ·  本机账本汇总", small, muted, 66, 174);
            if (demo) graphics.DrawString("虚构演示数据", small, accent, 966, 57);
            DrawCard(graphics, new Rectangle(62, 225, 523, 185), theme, label, number, small,
                     "本周 · 截至当前日期", ReadCount(week, "current_tokens"), ReadDate(week, "current_start"), ReadDate(week, "current_end"));
            DrawCard(graphics, new Rectangle(615, 225, 523, 185), theme, label, number, small,
                     "上周 · 完整周期", ReadCount(week, "previous_tokens"), ReadDate(week, "previous_start"), PreviousEnd(week));
            DrawCard(graphics, new Rectangle(62, 438, 523, 185), theme, label, number, small,
                     "本月 · 截至当前日期", ReadCount(month, "current_tokens"), ReadDate(month, "current_start"), ReadDate(month, "current_end"));
            DrawCard(graphics, new Rectangle(615, 438, 523, 185), theme, label, number, small,
                     "上月 · 完整周期", ReadCount(month, "previous_tokens"), ReadDate(month, "previous_start"), PreviousEnd(month));
            graphics.DrawString(incomplete ? "部分来源不完整 · 本机账本可能重叠" : "本机账本可能重叠，不等于账户总量或账单", small, muted, 66, 685);
            graphics.DrawString("当前周期尚未结束，不宜与完整上期作等长比较。", small, muted, 66, 720);
            using var line = new Pen(theme.Border, 2);
            graphics.DrawLine(line, 66, 775, 1134, 775);
            graphics.DrawString("github.com/FoxBai/agent-meter-windows", small, muted, 66, 790);
            return bitmap;
        }
        catch { bitmap.Dispose(); throw; }
    }
    static void DrawCard(Graphics graphics, Rectangle rect, VisualTheme theme, Font label, Font number, Font small,
                         string name, long tokens, string start, string end)
    {
        using var path = Rounded(rect, 20);
        using var fill = new LinearGradientBrush(rect, theme.Card, theme.CardEnd, 90F);
        graphics.FillPath(fill, path);
        if (!theme.Minimal) { using var edge = new Pen(theme.Border, 2); graphics.DrawPath(edge, path); }
        using var primary = new SolidBrush(theme.Primary);
        using var muted = new SolidBrush(theme.Secondary);
        using var accent = new SolidBrush(theme.Accent);
        graphics.DrawString(name, label, muted, rect.X + 28, rect.Y + 20);
        graphics.DrawString(FormatTokens(tokens), number, primary, rect.X + 24, rect.Y + 60);
        graphics.DrawString("TOKEN", small, accent, rect.X + 370, rect.Y + 98);
        graphics.DrawString(start + " — " + end, small, muted, rect.X + 29, rect.Y + 142);
    }
    static GraphicsPath Rounded(Rectangle rect, int radius)
    {
        var path = new GraphicsPath();
        int diameter = radius * 2;
        path.AddArc(rect.X, rect.Y, diameter, diameter, 180, 90);
        path.AddArc(rect.Right - diameter, rect.Y, diameter, diameter, 270, 90);
        path.AddArc(rect.Right - diameter, rect.Bottom - diameter, diameter, diameter, 0, 90);
        path.AddArc(rect.X, rect.Bottom - diameter, diameter, diameter, 90, 90); path.CloseFigure();
        return path;
    }
    static long ReadCount(JsonElement period, string key) => period.GetProperty(key).GetInt64();
    static string ReadDate(JsonElement period, string key) => period.GetProperty(key).GetString()!;
    static string PreviousEnd(JsonElement period) => DateOnly.ParseExact(ReadDate(period, "current_start"), "yyyy-MM-dd", CultureInfo.InvariantCulture)
        .AddDays(-1).ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
    static string FormatTokens(long count) => count >= 1_000_000_000_000_000 ? (count / 1_000_000_000_000_000d).ToString("0.##", CultureInfo.InvariantCulture) + "P" :
        count >= 1_000_000_000_000 ? (count / 1_000_000_000_000d).ToString("0.##", CultureInfo.InvariantCulture) + "T" :
        count >= 1_000_000_000 ? (count / 1_000_000_000d).ToString("0.##", CultureInfo.InvariantCulture) + "B" :
        count >= 1_000_000 ? (count / 1_000_000d).ToString("0.##", CultureInfo.InvariantCulture) + "M" :
        count >= 1_000 ? (count / 1_000d).ToString("0.##", CultureInfo.InvariantCulture) + "K" : count.ToString(CultureInfo.InvariantCulture);
}
