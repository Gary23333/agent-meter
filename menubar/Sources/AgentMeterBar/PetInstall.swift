import AppKit
import Foundation
import UniformTypeIdentifiers

/// Installs a dropped `.agentpet` with the existing validator (`pets/tools/petpack.py install`): the tool owns
/// every safety rule (zip-slip, scripts, symlinks, sizes); this only finds it, runs it and turns its answer
/// into words the user can read. Nothing is installed silently and nothing runs from inside the pack.
@MainActor
enum PetInstaller {
    enum InstallError: LocalizedError {
        case notAPetFile
        case toolMissing
        case pythonMissing
        case failed(String)

        var errorDescription: String? {
            switch self {
            case .notAPetFile: return "这不是 .agentpet 形象包文件。"
            case .toolMissing: return "找不到安装工具 petpack.py（需要应用资源或源码目录里的 pets/tools）。"
            case .pythonMissing: return "找不到 python3，无法运行形象包校验器。"
            case .failed(let text): return text
            }
        }
    }

    static func accepts(_ urls: [URL]) -> Bool {
        !urls.isEmpty && urls.allSatisfy { $0.pathExtension.lowercased() == "agentpet" }
    }

    /// File URLs out of a SwiftUI drop; providers may hand over an NSURL or its data representation.
    static func urls(from providers: [NSItemProvider]) async -> [URL] {
        var urls: [URL] = []
        for provider in providers where provider.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier) {
            guard let item = try? await provider.loadItem(forTypeIdentifier: UTType.fileURL.identifier) else { continue }
            if let url = item as? URL { urls.append(url) }
            else if let data = item as? Data, let url = URL(dataRepresentation: data, relativeTo: nil) { urls.append(url) }
        }
        return urls
    }

    /// The tool ships with a source checkout; a packaged app carries it under its Pet resources when present.
    static func toolURL(root: URL? = PetResources.root(), project: URL? = nil,
                        fileManager: FileManager = .default) -> URL? {
        var candidates: [URL] = []
        if let root { candidates.append(root.appendingPathComponent("tools/petpack.py")) }
        if let project = project ?? UsageStore.shared.projectDirectory {
            candidates.append(project.appendingPathComponent("pets/tools/petpack.py"))
        }
        return candidates.first { fileManager.isReadableFile(atPath: $0.path) }
    }

    /// GUI apps inherit a minimal PATH; look in the same places the backend launcher does.
    static func pythonURL(environment: [String: String] = ProcessInfo.processInfo.environment,
                          fileManager: FileManager = .default) -> URL? {
        var dirs = (environment["PATH"] ?? "").split(separator: ":").map(String.init)
        dirs += ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"]
        for dir in dirs where !dir.isEmpty {
            let url = URL(fileURLWithPath: dir).appendingPathComponent("python3")
            if fileManager.isExecutableFile(atPath: url.path) { return url }
        }
        return nil
    }

    /// Runs the installer off the main thread; the completion lands back on it.
    static func install(_ file: URL, completion: @escaping (Result<String, Error>) -> Void) {
        guard file.pathExtension.lowercased() == "agentpet" else { completion(.failure(InstallError.notAPetFile)); return }
        guard let tool = toolURL() else { completion(.failure(InstallError.toolMissing)); return }
        guard let python = pythonURL() else { completion(.failure(InstallError.pythonMissing)); return }
        let fallback = file.deletingPathExtension().lastPathComponent
        DispatchQueue.global(qos: .userInitiated).async {
            let process = Process()
            process.executableURL = python
            process.arguments = [tool.path, "install", file.path]
            let out = Pipe(), err = Pipe()
            process.standardOutput = out
            process.standardError = err
            process.standardInput = FileHandle.nullDevice
            do { try process.run() } catch {
                DispatchQueue.main.async { completion(.failure(InstallError.failed("无法启动安装器：\(error.localizedDescription)"))) }
                return
            }
            let outData = out.fileHandleForReading.readDataToEndOfFile()
            let errData = err.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            let stdout = String(data: outData, encoding: .utf8) ?? ""
            let stderr = String(data: errData, encoding: .utf8) ?? ""
            let status = process.terminationStatus
            DispatchQueue.main.async {
                if status == 0 {
                    completion(.success(installedName(stdout, fallback: fallback)))
                } else {
                    completion(.failure(InstallError.failed(readableFailure(stderr, stdout: stdout))))
                }
            }
        }
    }

    /// "installed -> /…/pets/my-pet" -> "my-pet"; anything else falls back to the file name.
    static func installedName(_ stdout: String, fallback: String) -> String {
        for line in stdout.split(separator: "\n") where line.hasPrefix("installed ->") {
            let path = line.dropFirst("installed ->".count).trimmingCharacters(in: .whitespaces)
            if !path.isEmpty { return URL(fileURLWithPath: path).lastPathComponent }
        }
        return fallback
    }

    /// The validator's own words (its SystemExit text), trimmed and bounded. A crashed tool leaves a Python
    /// traceback; its last line is the only part worth showing.
    static func readableFailure(_ stderr: String, stdout: String) -> String {
        var text = (stderr.isEmpty ? stdout : stderr).trimmingCharacters(in: .whitespacesAndNewlines)
        if text.hasPrefix("Traceback (most recent call last):"), let last = text.split(separator: "\n").last, !last.isEmpty {
            text = String(last).trimmingCharacters(in: .whitespaces)
        }
        guard !text.isEmpty else { return "安装失败（校验器没有给出原因）。" }
        return String(text.prefix(400))
    }
}