using System.Text.Json;

namespace AgentMeter.Windows;

internal sealed record PriceRow(string Model, decimal Input, decimal CacheRead, decimal CacheWrite, decimal Output);

/// <summary>本机价格覆盖表；所有价格均为每百万 Token 的美元价格。</summary>
internal static class PriceOverrides
{
    const decimal Limit = 1_000_000m;
    public static List<PriceRow> Load(string directory)
    {
        string path = Path.Combine(directory, "prices.json");
        try
        {
            var info = new FileInfo(path);
            if (info.Length > 1024 * 1024) throw new InvalidDataException("价格文件过大");
            using var doc = JsonDocument.Parse(File.ReadAllText(path));
            var root = doc.RootElement;
            if (root.ValueKind != JsonValueKind.Object || !root.TryGetProperty("currency", out var currency) ||
                currency.ValueKind != JsonValueKind.String || currency.GetString() != "USD" ||
                !root.TryGetProperty("models", out var models) || models.ValueKind != JsonValueKind.Object ||
                root.EnumerateObject().Any(property => property.Name is not ("currency" or "models")) || root.EnumerateObject().Count() != 2)
                throw new InvalidDataException("价格文件格式不正确");
            var rows = new List<PriceRow>();
            foreach (var model in models.EnumerateObject())
            {
                if (model.Value.ValueKind != JsonValueKind.Object || model.Value.EnumerateObject().Count() != 4 ||
                    model.Value.EnumerateObject().Any(property => property.Name is not ("input" or "cache_read" or "cache_write" or "output")))
                    throw new InvalidDataException("价格字段不完整或无法识别");
                decimal Read(string name)
                {
                    if (model.Value.ValueKind != JsonValueKind.Object || !model.Value.TryGetProperty(name, out var value) ||
                        value.ValueKind != JsonValueKind.Number || !value.TryGetDecimal(out var number))
                        throw new InvalidDataException("价格必须是数字");
                    return number;
                }
                rows.Add(new PriceRow(model.Name, Read("input"), Read("cache_read"), Read("cache_write"), Read("output")));
            }
            Validate(rows);
            return rows;
        }
        catch (FileNotFoundException) { return []; }
        catch (DirectoryNotFoundException) { return []; }
        catch (JsonException ex) { throw new InvalidDataException("价格文件格式不正确", ex); }
    }

    public static void Validate(IReadOnlyCollection<PriceRow> rows)
    {
        if (rows.Count > 200) throw new InvalidDataException("自定义价格最多 200 条");
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var row in rows)
        {
            string name = row.Model.Trim();
            string normalized = name.Split('/').Last().Trim().Replace('.', '-');
            if (name.Length is < 1 or > 120 || normalized.Length == 0 || name.Any(char.IsControl) || !seen.Add(normalized))
                throw new InvalidDataException("模型名称无效或重复");
            if (new[] { row.Input, row.CacheRead, row.CacheWrite, row.Output }.Any(n => n < 0 || n > Limit))
                throw new InvalidDataException("价格须在 0 到 1000000 之间");
        }
    }

    public static void Save(string directory, IReadOnlyCollection<PriceRow> rows)
    {
        Validate(rows);
        var models = rows.ToDictionary(row => row.Model.Trim(), row => new Dictionary<string, decimal>
        {
            ["input"] = row.Input, ["cache_read"] = row.CacheRead, ["cache_write"] = row.CacheWrite, ["output"] = row.Output
        });
        Directory.CreateDirectory(directory);
        string temporary = Path.Combine(directory, Path.GetRandomFileName());
        bool created = false;
        try
        {
            using (var file = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                created = true;
                JsonSerializer.Serialize(file, new { currency = "USD", models });
            }
            File.Move(temporary, Path.Combine(directory, "prices.json"), overwrite: true);
        }
        finally
        {
            try { if (created) File.Delete(temporary); }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException) { }
        }
    }
}
