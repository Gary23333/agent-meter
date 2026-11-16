using System.Drawing.Imaging;

namespace AgentMeter.Windows;

/// <summary>仅在隔离构建机运行：验证实际渲染器、透明像素、动画和悬浮窗。</summary>
internal static class Pet3dSmoke
{
    public static void Run(string outputDirectory)
    {
        using var form = new Form { ShowInTaskbar = false, StartPosition = FormStartPosition.Manual,
            Location = new Point(-32000, -32000), ClientSize = new Size(1, 1) };
        form.Shown += async (_, _) =>
        {
            try { await CheckAsync(outputDirectory); }
            catch (Exception error)
            {
                Console.Error.WriteLine($"3D 桌宠隔离检查失败：{error.GetType().Name}: {error.Message}");
                Environment.ExitCode = 1;
            }
            finally { form.Close(); }
        };
        Application.Run(form);
    }

    static async Task CheckAsync(string outputDirectory)
    {
        string directory = Path.Combine(Path.GetTempPath(), "AgentMeterPetSmoke-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(outputDirectory);
        foreach (string pack in new[] { "gauge", "cat", "bot", "tibo", "blob" })
        {
            using var renderer = new Pet3dRenderer(directory, pack);
            await renderer.StartAsync();
            if (pack == "gauge" && !await renderer.SyntheticNetworkBlockAsync()) throw new InvalidOperationException("桌宠网络隔离检查失败");
            using var first = await renderer.FrameAsync(new PetMood("idle", "待机"), 0.1);
            using var second = await renderer.FrameAsync(new PetMood("working", "近期本机记录有更新", 42), 0.25);
            int transparent = 0, painted = 0, changed = 0;
            for (int y = 0; y < first.Height; y += 3)
                for (int x = 0; x < first.Width; x += 3)
                {
                    Color pixel = first.GetPixel(x, y);
                    if (pixel.A == 0) transparent++; else if (pixel.A > 128) painted++;
                    if (pixel.ToArgb() != second.GetPixel(x, y).ToArgb()) changed++;
                }
            if (transparent < 100 || painted < 100) throw new InvalidOperationException($"{pack} 透明或可见区域异常");
            if (changed < 10) throw new InvalidOperationException($"{pack} 状态或姿态没有变化");
            first.Save(Path.Combine(outputDirectory, pack + ".png"), ImageFormat.Png);
        }
        using var pet = new Pet3dWindow("cat", new Point(-32000, -32000), directory);
        pet.SetSnapshot("{\"observed_at\":" + DateTimeOffset.UtcNow.ToUnixTimeSeconds() + ",\"account\":{\"status\":\"available\",\"quota\":{\"value\":[{\"remaining_percent\":10}]}}}");
        pet.Show();
        if (!await pet.FirstFrame.Task.WaitAsync(TimeSpan.FromSeconds(30))) throw new InvalidOperationException("原生桌宠窗口绘制失败");
    }
}
