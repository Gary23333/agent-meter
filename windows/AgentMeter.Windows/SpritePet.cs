using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Text.Json;

namespace AgentMeter.Windows;

/// <summary>只读取内置的上游 CC0 精灵图，按清单解码和缓存帧。</summary>
internal sealed class SpritePet : IDisposable
{
    sealed record Animation(string Name, int Frames, int FramesPerSecond);
    readonly string id;
    readonly int frameWidth, frameHeight;
    readonly bool pixelated;
    readonly Dictionary<string, Animation> animations = new(StringComparer.Ordinal);
    readonly Dictionary<string, Bitmap> sheets = new(StringComparer.Ordinal);
    readonly Dictionary<(string State, int Frame, int Size), Bitmap> rendered = new();
    static readonly HashSet<string> AllowedStates = new(StringComparer.Ordinal)
        { "idle", "working", "tired", "alarm", "sleeping", "celebrate", "offline", "waiting" };

    public SpritePet(string id)
    {
        if (id is not ("mochi" or "bit")) throw new ArgumentException("不支持的桌宠形象", nameof(id));
        this.id = id;
        using var stream = Resource($"AgentMeter.Pet.{id}.pet.json");
        using var doc = JsonDocument.Parse(stream);
        var root = doc.RootElement;
        if (root.GetProperty("id").GetString() != id || root.GetProperty("renderer").GetString() != "sprite" ||
            root.GetProperty("license").GetString() != "CC0-1.0") throw new InvalidDataException("桌宠清单不正确");
        var sprite = root.GetProperty("sprite"); var frame = sprite.GetProperty("frame");
        frameWidth = frame.GetProperty("width").GetInt32(); frameHeight = frame.GetProperty("height").GetInt32();
        if (frameWidth is < 1 or > 512 || frameHeight is < 1 or > 512) throw new InvalidDataException("桌宠帧尺寸不正确");
        pixelated = sprite.TryGetProperty("pixelated", out var pixel) && pixel.ValueKind == JsonValueKind.True;
        foreach (var state in sprite.GetProperty("states").EnumerateObject())
        {
            if (!AllowedStates.Contains(state.Name)) continue;
            string image = state.Value.GetProperty("image").GetString() ?? "";
            int frames = state.Value.GetProperty("frames").GetInt32(), fps = state.Value.GetProperty("fps").GetInt32();
            if (image != $"sprites/{state.Name}.png" || frames is < 1 or > 16 || fps is < 1 or > 30)
                throw new InvalidDataException("桌宠动画清单不正确");
            animations[state.Name] = new Animation(state.Name, frames, fps);
        }
        if (!animations.ContainsKey("idle")) throw new InvalidDataException("桌宠缺少待机动画");
    }

    static Stream Resource(string name) => typeof(SpritePet).Assembly.GetManifestResourceStream(name) ?? throw new InvalidDataException("桌宠资源缺失");
    Animation AnimationFor(string state) => animations.GetValueOrDefault(state) ?? animations["idle"];
    public int FrameCount(string state) => AnimationFor(state).Frames;
    public int FramesPerSecond(string state) => AnimationFor(state).FramesPerSecond;

    public Bitmap Frame(string state, int frame, int size)
    {
        if (size is < 32 or > 512) throw new ArgumentOutOfRangeException(nameof(size));
        var animation = AnimationFor(state);
        int index = ((frame % animation.Frames) + animation.Frames) % animation.Frames;
        var key = (animation.Name, index, size);
        if (rendered.TryGetValue(key, out var cached)) return cached;
        if (!sheets.TryGetValue(animation.Name, out var sheet))
        {
            using var stream = Resource($"AgentMeter.Pet.{id}.{animation.Name}.png");
            using var original = Image.FromStream(stream, useEmbeddedColorManagement: false, validateImageData: true);
            if (original.Width != frameWidth * animation.Frames || original.Height != frameHeight)
                throw new InvalidDataException("桌宠精灵图尺寸不正确");
            sheet = new Bitmap(original); sheets[animation.Name] = sheet;
        }
        var image = new Bitmap(size, size, PixelFormat.Format32bppPArgb);
        try
        {
            using var graphics = Graphics.FromImage(image);
            graphics.Clear(Color.Transparent);
            graphics.CompositingMode = CompositingMode.SourceCopy;
            graphics.InterpolationMode = pixelated ? InterpolationMode.NearestNeighbor : InterpolationMode.HighQualityBicubic;
            graphics.PixelOffsetMode = pixelated ? PixelOffsetMode.Half : PixelOffsetMode.HighQuality;
            graphics.DrawImage(sheet, new Rectangle(0, 0, size, size), index * frameWidth, 0, frameWidth, frameHeight, GraphicsUnit.Pixel);
            rendered[key] = image;
            return image;
        }
        catch { image.Dispose(); throw; }
    }
    public void Dispose()
    {
        foreach (var image in rendered.Values) image.Dispose();
        foreach (var sheet in sheets.Values) sheet.Dispose();
        rendered.Clear(); sheets.Clear();
    }
}
