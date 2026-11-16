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
            if (pack == "cat")
            {
                using var held = await renderer.FrameAsync(new PetMood("idle", "待机"), 0.1, "drag-start");
                if (await renderer.SyntheticLayerAsync() != "drag") throw new InvalidOperationException("桌宠拖动动作未生效");
                if (DifferentPixels(second, held) < 10) throw new InvalidOperationException("桌宠拖动动作没有可见变化");
                using var dropped = await renderer.FrameAsync(new PetMood("idle", "待机"), 0.1, "drag-end");
                if (!(await renderer.SyntheticLayerAsync()).StartsWith("interaction:drop:", StringComparison.Ordinal))
                    throw new InvalidOperationException("桌宠放下动作未生效");
                if (DifferentPixels(held, dropped) < 10) throw new InvalidOperationException("桌宠放下动作没有可见变化");
                using var poked = await renderer.FrameAsync(new PetMood("idle", "待机"), 0.1, "poke");
                if (!(await renderer.SyntheticLayerAsync()).StartsWith("interaction:poke:", StringComparison.Ordinal))
                    throw new InvalidOperationException("桌宠点击动作未生效");
                if (DifferentPixels(dropped, poked) < 10) throw new InvalidOperationException("桌宠点击动作没有可见变化");
                using var refreshed = await renderer.FrameAsync(new PetMood("idle", "待机"), 0.1, "refresh");
                if (!(await renderer.SyntheticLayerAsync()).StartsWith("interaction:refresh:", StringComparison.Ordinal))
                    throw new InvalidOperationException("桌宠刷新动作未生效");
                if (DifferentPixels(poked, refreshed) < 10) throw new InvalidOperationException("桌宠刷新动作没有可见变化");
                using var left = await renderer.FrameAsync(new PetMood("idle", "待机"), 0.25, cursor: new PointF(-1000, 130));
                if (await renderer.SyntheticLookXAsync() is not < 0) throw new InvalidOperationException("桌宠未朝左侧光标注视");
                using var right = await renderer.FrameAsync(new PetMood("idle", "待机"), 0.25, cursor: new PointF(1000, 130));
                if (await renderer.SyntheticLookXAsync() is not > 0 || DifferentPixels(left, right) < 10)
                    throw new InvalidOperationException("桌宠未朝右侧光标注视");
                using var stopped = await renderer.FrameAsync(new PetMood("idle", "待机"), 0.1);
                if (await renderer.SyntheticLookXAsync() is not null) throw new InvalidOperationException("关闭跟随后仍在读取光标方向");
                held.Save(Path.Combine(outputDirectory, "cat-drag.png"), ImageFormat.Png);
                dropped.Save(Path.Combine(outputDirectory, "cat-drop.png"), ImageFormat.Png);
                poked.Save(Path.Combine(outputDirectory, "cat-poke.png"), ImageFormat.Png);
                refreshed.Save(Path.Combine(outputDirectory, "cat-refresh.png"), ImageFormat.Png);
                left.Save(Path.Combine(outputDirectory, "cat-look-left.png"), ImageFormat.Png);
                right.Save(Path.Combine(outputDirectory, "cat-look-right.png"), ImageFormat.Png);
            }
            first.Save(Path.Combine(outputDirectory, pack + ".png"), ImageFormat.Png);
        }
        using var pet = new Pet3dWindow("cat", new Point(-32000, -32000), directory);
        pet.SetSnapshot("{\"observed_at\":" + DateTimeOffset.UtcNow.ToUnixTimeSeconds() + ",\"account\":{\"status\":\"available\",\"quota\":{\"value\":[{\"remaining_percent\":10}]}}}");
        pet.Show();
        if (!await pet.FirstFrame.Task.WaitAsync(TimeSpan.FromSeconds(30))) throw new InvalidOperationException("原生桌宠窗口绘制失败");
    }
    static int DifferentPixels(Bitmap a, Bitmap b)
    {
        int different = 0;
        for (int y = 0; y < a.Height; y += 3)
            for (int x = 0; x < a.Width; x += 3)
                if (a.GetPixel(x, y).ToArgb() != b.GetPixel(x, y).ToArgb()) different++;
        return different;
    }
}
