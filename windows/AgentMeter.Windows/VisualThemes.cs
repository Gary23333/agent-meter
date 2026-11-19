using System.Drawing;
using System.Text.Json;

namespace AgentMeter.Windows;

internal sealed record VisualTheme(string Id, string Name, Color Background, Color Card, Color CardEnd,
    Color Primary, Color Secondary, Color Accent, Color Selected, Color Border, bool Minimal = false, bool Light = false);

/// <summary>Windows 面板的七种配色及本机外观偏好。</summary>
internal static class VisualThemes
{
    static Color C(int r, int g, int b) => Color.FromArgb(r, g, b);
    public static readonly IReadOnlyList<VisualTheme> All = new[]
    {
        new VisualTheme("minimal", "极简", C(13,13,13), C(20,20,20), C(20,20,20), C(245,245,245), C(185,185,185), C(220,220,220), C(64,64,64), C(42,42,42), Minimal:true),
        new VisualTheme("native", "原生", C(22,24,28), C(35,38,43), C(35,38,43), C(247,248,250), C(180,188,200), C(116,194,255), C(44,95,153), C(70,77,88)),
        new VisualTheme("porcelain", "瓷白", C(239,242,247), C(253,254,255), C(242,245,251), C(24,32,45), C(75,86,103), C(17,113,104), C(71,83,138), C(198,207,220), Light:true),
        new VisualTheme("aurora", "极光", C(15,19,30), C(26,32,47), C(31,31,53), C(245,245,255), C(158,170,190), C(117,220,194), C(115,76,219), C(65,74,100)),
        new VisualTheme("titanium", "钛影", C(21,24,28), C(38,43,49), C(28,33,39), C(243,247,251), C(184,199,213), C(135,197,219), C(69,91,108), C(85,99,111)),
        new VisualTheme("neon", "霓虹", C(8,5,22), C(25,13,43), C(20,11,40), C(241,248,255), C(182,198,221), C(38,233,245), C(145,34,132), C(121,50,135)),
        new VisualTheme("prism", "棱镜", C(11,14,34), C(27,29,59), C(41,26,65), C(244,248,255), C(181,198,221), C(91,226,233), C(96,60,164), C(102,84,152)),
    };
    public static VisualTheme Find(string? id) => All.FirstOrDefault(theme => theme.Id == id) ?? All[3];

    public static VisualTheme Load(string directory)
    {
        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(directory, "appearance.json")));
            return Find(doc.RootElement.GetProperty("theme").GetString());
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException or InvalidOperationException or KeyNotFoundException or System.Security.SecurityException)
        { return Find("aurora"); }
    }

    public static void Save(string directory, VisualTheme theme)
    {
        Directory.CreateDirectory(directory);
        string temporary = Path.Combine(directory, Path.GetRandomFileName());
        bool created = false;
        try
        {
            using (var file = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                created = true;
                JsonSerializer.Serialize(file, new Dictionary<string, string> { ["theme"] = theme.Id });
            }
            File.Move(temporary, Path.Combine(directory, "appearance.json"), overwrite: true);
        }
        finally
        {
            try { if (created) File.Delete(temporary); }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException) { }
        }
    }
}
