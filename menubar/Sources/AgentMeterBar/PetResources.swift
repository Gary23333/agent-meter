import Foundation
import WebKit

/// Where the pet's web runtime and packs live, which packs exist, and how `agentpet://` URLs map to files.
/// Everything here is plain file-system logic so the security-relevant parts can be unit tested.
enum PetResources {
    static let scheme = "agentpet"
    static let host = "app"

    /// Directory holding `runtime/` and `presets/`: the app bundle, then `AGENT_METER_HOME/pets`, then a
    /// `pets/` folder next to a source checkout (development).
    static func root(environment: [String: String] = ProcessInfo.processInfo.environment,
                     bundle: Bundle = .main, fileManager: FileManager = .default) -> URL? {
        func has(_ dir: URL) -> Bool { fileManager.fileExists(atPath: dir.appendingPathComponent("runtime/index.html").path) }
        if let bundled = bundle.resourceURL?.appendingPathComponent("Pet", isDirectory: true), has(bundled) { return bundled }
        if let home = environment["AGENT_METER_HOME"] {
            let dir = URL(fileURLWithPath: home).appendingPathComponent("pets", isDirectory: true)
            if has(dir) { return dir }
        }
        var dir = bundle.executableURL?.deletingLastPathComponent()
        for _ in 0..<8 {
            guard let d = dir else { break }
            let candidate = d.appendingPathComponent("pets", isDirectory: true)
            if has(candidate) { return candidate }
            dir = d.deletingLastPathComponent()
        }
        return nil
    }

    /// Packs the user installed (never part of the app bundle).
    static var userPacksDirectory: URL {
        let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library/Application Support")
        return support.appendingPathComponent("AgentMeter/pets", isDirectory: true)
    }

    struct Pack: Identifiable, Equatable {
        let id: String
        let name: String
        let renderer: String
        let directory: URL
        let builtin: Bool
        /// Logical stage size in points from pet.json (the window is sized from it).
        let stage: CGSize
    }

    static func validID(_ s: String) -> Bool {
        guard (2...31).contains(s.count), let first = s.unicodeScalars.first,
              CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyz0123456789").contains(first) else { return false }
        return s.unicodeScalars.allSatisfy { CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyz0123456789-").contains($0) }
    }

    /// Light checks only; `pets/tools/petpack.py validate` is the strict validator. Later roots win, so a
    /// user pack with a built-in id replaces it.
    static func discover(roots: [(url: URL, builtin: Bool)], fileManager: FileManager = .default) -> [Pack] {
        var byID: [String: Pack] = [:]
        var order: [String] = []
        for (dir, builtin) in roots {
            let keys: [URLResourceKey] = [.isDirectoryKey, .isSymbolicLinkKey]
            guard let items = try? fileManager.contentsOfDirectory(at: dir, includingPropertiesForKeys: keys, options: [.skipsHiddenFiles]) else { continue }
            for item in items.sorted(by: { $0.lastPathComponent < $1.lastPathComponent }) {
                let values = try? item.resourceValues(forKeys: Set(keys))
                guard values?.isDirectory == true, values?.isSymbolicLink != true else { continue }
                guard let data = try? Data(contentsOf: item.appendingPathComponent("pet.json")), data.count < 262_144,
                      let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      object["format"] as? String == "agentmeter-pet/1",
                      let id = object["id"] as? String, id == item.lastPathComponent, validID(id),
                      let renderer = object["renderer"] as? String, ["three", "sprite"].contains(renderer) else { continue }
                let stage = object["stage"] as? [String: Any]
                let width = min(480, max(120, (stage?["width"] as? Double) ?? 240))
                let height = min(520, max(120, (stage?["height"] as? Double) ?? 260))
                let name = (object["name"] as? String).map { String($0.prefix(24)) } ?? id
                if byID[id] == nil { order.append(id) }
                byID[id] = Pack(id: id, name: name, renderer: renderer, directory: item, builtin: builtin,
                                stage: CGSize(width: width, height: height))
            }
        }
        return order.compactMap { byID[$0] }
    }

    static func allPacks() -> [Pack] {
        var roots: [(url: URL, builtin: Bool)] = []
        if let r = root() { roots.append((r.appendingPathComponent("presets", isDirectory: true), true)) }
        roots.append((userPacksDirectory, false))
        return discover(roots: roots)
    }
}

/// `agentpet://app/runtime/<path>` and `agentpet://app/pack/<id>/<path>`, and the rules that keep them inside
/// their folders: no dot segments (decoded), no hidden files, symlinks resolved before the prefix check, and
/// only data/image/script-for-the-runtime extensions are served.
enum PetPath {
    enum Route: Equatable {
        case runtime(String)
        case pack(id: String, path: String)
    }

    static let mimeTypes: [String: String] = [
        "html": "text/html; charset=utf-8", "js": "text/javascript; charset=utf-8", "mjs": "text/javascript; charset=utf-8",
        "css": "text/css; charset=utf-8", "json": "application/json; charset=utf-8", "png": "image/png",
        "webp": "image/webp", "jpg": "image/jpeg", "jpeg": "image/jpeg", "txt": "text/plain; charset=utf-8",
        "md": "text/plain; charset=utf-8",
    ]

    static func route(for url: URL) -> Route? {
        guard url.scheme == PetResources.scheme, url.host == PetResources.host else { return nil }
        let parts = url.path.split(separator: "/", omittingEmptySubsequences: true).map(String.init)
        guard let first = parts.first else { return nil }
        if first == "runtime", parts.count >= 2 { return .runtime(parts.dropFirst().joined(separator: "/")) }
        if first == "pack", parts.count >= 3, PetResources.validID(parts[1]) {
            return .pack(id: parts[1], path: parts.dropFirst(2).joined(separator: "/"))
        }
        return nil
    }

    /// The file to serve, or nil. It must stay inside `base` once symlinks are resolved, be a regular file and
    /// have a served extension. Packs from outside the app are only ever read through here.
    static func resolve(base: URL, relative: String, fileManager: FileManager = .default) -> URL? {
        guard !relative.isEmpty, !relative.contains("\0"), !relative.contains("\\") else { return nil }
        let segments = relative.split(separator: "/", omittingEmptySubsequences: false).map(String.init)
        guard !segments.contains(where: { $0.isEmpty || $0.hasPrefix(".") }) else { return nil }
        let root = base.standardizedFileURL.resolvingSymlinksInPath()
        let file = base.appendingPathComponent(relative).standardizedFileURL.resolvingSymlinksInPath()
        guard file.path.hasPrefix(root.path + "/"), mimeTypes[file.pathExtension.lowercased()] != nil else { return nil }
        var isDirectory: ObjCBool = false
        guard fileManager.fileExists(atPath: file.path, isDirectory: &isDirectory), !isDirectory.boolValue else { return nil }
        return file
    }
}

/// Serves the pet runtime and packs to the WKWebView. The page gets no network and no file access beyond this.
final class PetSchemeHandler: NSObject, WKURLSchemeHandler {
    static let policy = "default-src 'none'; script-src agentpet:; style-src agentpet: 'unsafe-inline'; img-src agentpet: data: blob:; "
        + "connect-src agentpet:; font-src agentpet:; base-uri 'none'; form-action 'none'"
    private static let maxBytes = 8 * 1024 * 1024

    private let root: () -> URL?
    private let packs: () -> [PetResources.Pack]

    init(root: @escaping () -> URL? = { PetResources.root() }, packs: @escaping () -> [PetResources.Pack] = { PetResources.allPacks() }) {
        self.root = root
        self.packs = packs
    }

    func file(for url: URL) -> URL? {
        guard let route = PetPath.route(for: url) else { return nil }
        switch route {
        case .runtime(let relative):
            return root().flatMap { PetPath.resolve(base: $0.appendingPathComponent("runtime", isDirectory: true), relative: relative) }
        case .pack(let id, let relative):
            return packs().first { $0.id == id }.flatMap { PetPath.resolve(base: $0.directory, relative: relative) }
        }
    }

    func webView(_ webView: WKWebView, start urlSchemeTask: WKURLSchemeTask) {
        let request = urlSchemeTask.request
        let url = request.url ?? URL(string: "agentpet://app/")!
        guard (request.httpMethod ?? "GET") == "GET", let file = file(for: url),
              let data = try? Data(contentsOf: file, options: .mappedIfSafe), data.count <= Self.maxBytes else {
            respond(urlSchemeTask, url: url, status: 404, mime: "text/plain; charset=utf-8", body: Data("not found".utf8))
            return
        }
        respond(urlSchemeTask, url: url, status: 200, mime: PetPath.mimeTypes[file.pathExtension.lowercased()] ?? "application/octet-stream", body: data)
    }

    func webView(_ webView: WKWebView, stop urlSchemeTask: WKURLSchemeTask) {}

    private func respond(_ task: WKURLSchemeTask, url: URL, status: Int, mime: String, body: Data) {
        let headers = ["Content-Type": mime, "Content-Length": "\(body.count)", "Cache-Control": "no-store",
                       "X-Content-Type-Options": "nosniff", "Content-Security-Policy": Self.policy]
        guard let response = HTTPURLResponse(url: url, statusCode: status, httpVersion: "HTTP/1.1", headerFields: headers) else {
            task.didFailWithError(URLError(.badServerResponse))
            return
        }
        task.didReceive(response)
        task.didReceive(body)
        task.didFinish()
    }
}

/// The address of the pet page and the parameters the native side passes (see `pets/runtime/js/main.js`).
enum PetPage {
    enum Mode {
        /// The floating desktop window: native overlay for input, HUD under the pet.
        case window
        /// The stage inside the panel's 桌宠 tab: DOM pointer events, headroom for the speech bubble.
        case embed
        /// A gallery thumbnail: the pet at its best, no chatter, `body[data-settled]` once drawn.
        case still
    }

    static func url(pack: String, theme: String, scheme: String, scale: Double = 1, hud: String = "pill",
                    reduceMotion: Bool = false, calm: Bool = false, mode: Mode = .window) -> URL? {
        var components = URLComponents()
        components.scheme = PetResources.scheme
        components.host = PetResources.host
        components.path = "/runtime/index.html"
        var items = [
            URLQueryItem(name: "pack", value: pack),
            URLQueryItem(name: "packRoot", value: "\(PetResources.scheme)://\(PetResources.host)/pack/"),
            URLQueryItem(name: "theme", value: theme),
            URLQueryItem(name: "scheme", value: scheme),
            URLQueryItem(name: "scale", value: String(scale)),
            URLQueryItem(name: "hud", value: hud),
            URLQueryItem(name: "reduceMotion", value: reduceMotion ? "1" : "0"),
            URLQueryItem(name: "calm", value: calm ? "1" : "0"),
        ]
        switch mode {
        case .window: break
        case .embed: items.append(URLQueryItem(name: "embed", value: "1"))
        case .still: items.append(URLQueryItem(name: "still", value: "1"))
        }
        components.queryItems = items
        return components.url
    }
}
