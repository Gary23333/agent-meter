using System.Diagnostics;
using System.Text;
using System.Text.Json;

namespace AgentMeter.Windows;

/// <summary>调用随包后台进程；主密钥只经标准输入传入，不进命令行、不进日志。</summary>
internal static class SyncBackendClient
{
    static string Executable => Path.Combine(AppContext.BaseDirectory, "backend", "AgentMeterBackend.exe");

    public static async Task<string> RunAsync(string mode, string input, CancellationToken cancellation)
    {
        using var process = Start(mode, redirectInput: true);
        var output = process.StandardOutput.ReadToEndAsync();
        var error = process.StandardError.ReadToEndAsync();
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        timeout.CancelAfter(TimeSpan.FromSeconds(45));
        try
        {
            await process.StandardInput.WriteAsync(input.AsMemory(), timeout.Token);
            await process.StandardInput.FlushAsync(timeout.Token);
            process.StandardInput.Close();
            await process.WaitForExitAsync(timeout.Token);
        }
        catch (Exception ex) when (ex is OperationCanceledException or IOException or ObjectDisposedException)
        {
            Kill(process);
            throw;
        }
        await error;
        if (process.ExitCode != 0) throw new InvalidOperationException("sync_backend_failed");
        return await output;
    }

    /// <summary>配对是长轮询：逐行读取事件，界面在拿到短码后立刻显示。</summary>
    public static async Task PairAsync(string mode, string input, Action<JsonElement> onEvent,
                                       CancellationToken cancellation)
    {
        using var process = Start(mode, redirectInput: true);
        var error = process.StandardError.ReadToEndAsync();
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        timeout.CancelAfter(TimeSpan.FromMinutes(6));
        try
        {
            await process.StandardInput.WriteAsync(input.AsMemory(), timeout.Token);
            await process.StandardInput.FlushAsync(timeout.Token);
            process.StandardInput.Close();
            while (true)
            {
                string? line = await process.StandardOutput.ReadLineAsync(timeout.Token);
                if (line is null) break;
                if (string.IsNullOrWhiteSpace(line)) continue;
                try
                {
                    using var document = JsonDocument.Parse(line);
                    if (document.RootElement.ValueKind == JsonValueKind.Object)
                        onEvent(document.RootElement.Clone());
                }
                catch (JsonException) { }
            }
            await process.WaitForExitAsync(timeout.Token);
        }
        catch (Exception ex) when (ex is OperationCanceledException or IOException or ObjectDisposedException)
        {
            Kill(process);
            throw;
        }
        await error;
    }

    static Process Start(string mode, bool redirectInput)
    {
        var path = Executable;
        if (!File.Exists(path)) throw new IOException("sync_backend_missing");
        var process = new Process
        {
            StartInfo = new ProcessStartInfo(path, mode)
            {
                UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true,
                RedirectStandardError = true, StandardOutputEncoding = Encoding.UTF8,
                StandardInputEncoding = new UTF8Encoding(false), RedirectStandardInput = redirectInput,
            }
        };
        if (!process.Start()) throw new InvalidOperationException("sync_backend_start_failed");
        return process;
    }

    static void Kill(Process process)
    {
        try { process.Kill(true); }
        catch (Exception ex) when (ex is InvalidOperationException or System.ComponentModel.Win32Exception or NotSupportedException) { }
    }
}
