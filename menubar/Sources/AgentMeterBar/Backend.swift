import Foundation

enum BackendError: LocalizedError {
    case projectNotFound
    case tokenMissing
    case unauthorized
    case unreachable
    case startFailed
    case http(Int, String?)
    case invalidResponse

    var errorDescription: String? {
        switch self {
        case .projectNotFound: return "找不到后端项目目录（需包含 agent_meter）。可设置环境变量 AGENT_METER_HOME。"
        case .tokenMissing: return "未找到 .runtime/api.token，后端可能尚未启动。"
        case .unauthorized: return "本地 token 不匹配。\(BackendClient.port) 端口上可能是另一个后端实例。"
        case .unreachable: return "无法连接本机后端 127.0.0.1:\(BackendClient.port)。"
        case .startFailed: return "后端启动失败，详见 .runtime/menubar-backend.log。"
        case .http(let code, let err): return "后端返回 \(code)\(err.map { "（\($0)）" } ?? "")。"
        case .invalidResponse: return "后端返回了无法解析的数据。"
        }
    }
}

/// Talks to `python3 -m agent_meter serve`. No Origin header is sent, so the
/// backend's browser rejection does not apply; Host is 127.0.0.1:<port>.
struct BackendClient {
    static let defaultPort = 8769
    /// 8769, unless `AGENT_METER_PORT` says otherwise. That is for development only: it lets a build under test
    /// run next to the installed app, which owns 8769 and its data.
    static let port: Int = port(from: ProcessInfo.processInfo.environment)

    static func port(from environment: [String: String]) -> Int {
        if let raw = environment["AGENT_METER_PORT"], let value = Int(raw), (1024...65535).contains(value) { return value }
        return defaultPort
    }

    let project: URL
    let base = URL(string: "http://127.0.0.1:\(BackendClient.port)")!

    private var tokenURL: URL { project.appendingPathComponent(".runtime/api.token") }

    private func token() throws -> String {
        guard let raw = try? String(contentsOf: tokenURL, encoding: .utf8) else { throw BackendError.tokenMissing }
        let t = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard t.count >= 32 else { throw BackendError.tokenMissing }
        return t
    }

    private static let session: URLSession = {
        let c = URLSessionConfiguration.ephemeral
        c.timeoutIntervalForRequest = 120
        c.requestCachePolicy = .reloadIgnoringLocalCacheData
        return URLSession(configuration: c)
    }()

    private func request(_ path: String, method: String = "GET", timeout: TimeInterval) throws -> URLRequest {
        var r = URLRequest(url: base.appendingPathComponent(path), timeoutInterval: timeout)
        r.httpMethod = method
        r.setValue("Bearer " + (try token()), forHTTPHeaderField: "Authorization")
        if method == "POST" { r.httpBody = Data() }
        return r
    }

    /// True when something answers /v1/health with our token.
    func healthy() async -> Bool {
        guard let r = try? request("v1/health", timeout: 2),
              let (_, resp) = try? await Self.session.data(for: r),
              let http = resp as? HTTPURLResponse else { return false }
        return http.statusCode == 200
    }

    /// Whether any process listens on the port, regardless of auth.
    func portInUse() async -> Bool {
        var r = URLRequest(url: base.appendingPathComponent("v1/health"), timeoutInterval: 2)
        r.httpMethod = "GET"
        return (try? await Self.session.data(for: r)) != nil
    }

    /// Hands website logins to the backend's memory (never persisted there).
    func putSessions(_ sessions: [String: [String: String]]) async throws {
        var r = try request("v1/web-sessions", method: "PUT", timeout: 10)
        r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        // Send every known provider so a disconnect clears the backend copy;
        // several accounts go as a list in slot order ("qoder", "qoder#2"...).
        var body: [String: [[String: String]]?] = [:]
        for p in WebProvider.apiKeyProviders { body[p.id] = sessions[p.id].map { [$0] } }
        for p in WebProvider.all where p.backendManaged {
            let list = sessions.filter { ConnectionManager.provider(ofSlot: $0.key) == p.id }
                .sorted { ConnectionManager.order(ofSlot: $0.key) < ConnectionManager.order(ofSlot: $1.key) }
                .map(\.value)
            body[p.id] = list.isEmpty ? nil : list
        }
        r.httpBody = try JSONEncoder().encode(body)
        let (_, resp) = try await Self.session.data(for: r)
        guard let http = resp as? HTTPURLResponse else { throw BackendError.invalidResponse }
        if http.statusCode == 401 { throw BackendError.unauthorized }
        guard http.statusCode == 200 else { throw BackendError.http(http.statusCode, nil) }
    }

    /// Allowlisted 即梦 page observations (see DreaminaMonitor).
    func putObservations(_ dreamina: [[String: Any]]) async throws {
        var r = try request("v1/observations", method: "PUT", timeout: 10)
        r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        r.httpBody = try JSONSerialization.data(withJSONObject: ["dreamina": dreamina])
        let (_, resp) = try await Self.session.data(for: r)
        guard let http = resp as? HTTPURLResponse else { throw BackendError.invalidResponse }
        guard http.statusCode == 200 else { throw BackendError.http(http.statusCode, nil) }
    }

    /// Runtime on/off switches for sources, the low-resource mode and the
    /// auto-claim settings (kept in backend memory). Every key is sent so the
    /// backend copy stays complete.
    func putPreferences(disabled: [String], lowResource: Bool = false, skipLedgers: [String] = [],
                        autoClaim: [String] = [], claimTime: String = "00:05") async throws {
        var r = try request("v1/preferences", method: "PUT", timeout: 10)
        r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        r.httpBody = try JSONSerialization.data(withJSONObject: [
            "disabled_sources": disabled,
            "low_resource_mode": lowResource,
            "skip_ledgers_low_resource": skipLedgers,
            "auto_claim": autoClaim,
            "claim_time": claimTime])
        let (_, resp) = try await Self.session.data(for: r)
        guard let http = resp as? HTTPURLResponse, http.statusCode == 200 else { throw BackendError.invalidResponse }
    }

    /// Project attribution / calendar comparison / collection status are all
    /// projections of the backend's cached snapshot, never a new collection.
    func getProjects() async throws -> JSON { try await projection("v1/projects", timeout: 90) }
    func getPeriods(kind: String) async throws -> JSON { try await projection("v1/periods/" + kind, timeout: 30) }
    func getStatus() async throws -> JSON { try await projection("v1/status", timeout: 15) }

    private func projection(_ path: String, timeout: TimeInterval) async throws -> JSON {
        let r = try request(path, timeout: timeout)
        let data: Data, resp: URLResponse
        do { (data, resp) = try await Self.session.data(for: r) } catch { throw BackendError.unreachable }
        guard let http = resp as? HTTPURLResponse else { throw BackendError.invalidResponse }
        if http.statusCode == 401 { throw BackendError.unauthorized }
        guard http.statusCode == 200,
              let json = try? JSONDecoder().decode(JSON.self, from: data) else { throw BackendError.invalidResponse }
        return json
    }

    /// Claims one account's daily rewards now ("trae_cn", "workbuddy#2"...).
    /// The path component percent-encodes "#".
    func claimReward(_ slot: String) async throws {
        let r = try request("v1/rewards/claim/" + slot, method: "POST", timeout: 60)
        let (_, resp) = try await Self.session.data(for: r)
        guard let http = resp as? HTTPURLResponse else { throw BackendError.invalidResponse }
        guard http.statusCode == 200 else { throw BackendError.http(http.statusCode, nil) }
    }

    /// Local price table (GET/PUT /v1/prices).
    func getPrices(currency: String? = nil) async throws -> JSON {
        let path = currency.map { "v1/prices/" + $0 } ?? "v1/prices"
        let r = try request(path, timeout: 10)
        let data: Data, resp: URLResponse
        do { (data, resp) = try await Self.session.data(for: r) } catch { throw BackendError.unreachable }
        guard let http = resp as? HTTPURLResponse, http.statusCode == 200,
              let json = try? JSONDecoder().decode(JSON.self, from: data) else { throw BackendError.invalidResponse }
        return json
    }

    func putPrices(currency: String, models: [String: [String: Double]], aliases: [String: String],
                   peakMultipliers: [String: Double]) async throws -> JSON {
        var r = try request("v1/prices", method: "PUT", timeout: 10)
        r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        r.httpBody = try JSONSerialization.data(withJSONObject: ["currency": currency, "models": models,
                                                                 "aliases": aliases, "peak_multipliers": peakMultipliers])
        let (_, resp) = try await Self.session.data(for: r)
        guard let http = resp as? HTTPURLResponse else { throw BackendError.invalidResponse }
        guard (200..<300).contains(http.statusCode) else { throw BackendError.http(http.statusCode, nil) }
        return .null
    }

    /// Refresh model names and public list prices. Daily throttling and stale
    /// fallback are owned by the backend; failures never clear the local table.
    func syncPrices() async throws -> JSON {
        let r = try request("v1/prices/sync", method: "POST", timeout: 25)
        let data: Data, resp: URLResponse
        do { (data, resp) = try await Self.session.data(for: r) } catch { throw BackendError.unreachable }
        guard let http = resp as? HTTPURLResponse,
              let json = try? JSONDecoder().decode(JSON.self, from: data) else { throw BackendError.invalidResponse }
        guard http.statusCode == 200 else { throw BackendError.http(http.statusCode, json["last_error"].string) }
        return json
    }

    /// Budget config + estimate-based progress (GET/PUT /v1/budget). GET never
    /// triggers a collection; it uses the backend's current snapshot.
    func getBudget() async throws -> JSON {
        let r = try request("v1/budget", timeout: 10)
        let data: Data, resp: URLResponse
        do { (data, resp) = try await Self.session.data(for: r) } catch { throw BackendError.unreachable }
        guard let http = resp as? HTTPURLResponse, http.statusCode == 200,
              let json = try? JSONDecoder().decode(JSON.self, from: data) else { throw BackendError.invalidResponse }
        return json
    }

    /// nil amounts clear the budget (no alerts). Amounts travel as Decimal
    /// strings; the backend rejects anything non-numeric or negative.
    func putBudget(daily: String?, weekly: String?, multiplier: String) async throws -> JSON {
        var r = try request("v1/budget", method: "PUT", timeout: 10)
        r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let body: [String: Any] = ["daily_cny": (daily as Any?) ?? NSNull(),
                                   "weekly_cny": (weekly as Any?) ?? NSNull(),
                                   "anomaly_multiplier": multiplier]
        r.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, resp) = try await Self.session.data(for: r)
        guard let http = resp as? HTTPURLResponse else { throw BackendError.invalidResponse }
        guard http.statusCode == 200 else {
            let err = (try? JSONDecoder().decode(JSON.self, from: data))?["error"].string
            throw BackendError.http(http.statusCode, err)
        }
        guard let json = try? JSONDecoder().decode(JSON.self, from: data) else { throw BackendError.invalidResponse }
        return json
    }

    /// Recent session/turn activity. A lightweight local scan on the backend;
    /// unlike snapshot() this never triggers full account collection.
    func activity() async throws -> ActivityFeed {
        let r = try request("v1/activity", timeout: 30)
        let data: Data, resp: URLResponse
        do { (data, resp) = try await Self.session.data(for: r) } catch { throw BackendError.unreachable }
        guard let http = resp as? HTTPURLResponse else { throw BackendError.invalidResponse }
        if http.statusCode == 401 { throw BackendError.unauthorized }
        guard http.statusCode == 200 else {
            let err = (try? JSONDecoder().decode(JSON.self, from: data))?["error"].string
            throw BackendError.http(http.statusCode, err)
        }
        guard let json = try? JSONDecoder().decode(JSON.self, from: data) else { throw BackendError.invalidResponse }
        return ActivityFeed(json)
    }

    /// The desktop pet's current frame (raw JSON, forwarded to the web view). Cheap: it only interprets
    /// cached data and never triggers a collection.
    func petFrame() async throws -> Data {
        let r = try request("v1/pet", timeout: 10)
        let data: Data, resp: URLResponse
        do { (data, resp) = try await Self.session.data(for: r) } catch { throw BackendError.unreachable }
        guard let http = resp as? HTTPURLResponse else { throw BackendError.invalidResponse }
        if http.statusCode == 401 { throw BackendError.unauthorized }
        guard http.statusCode == 200 else { throw BackendError.http(http.statusCode, nil) }
        return data
    }

    /// Hook-style events for the pet (focus timer, price sync ...). In-memory on the backend, never persisted.
    func petEvent(_ payload: [String: Any]) async throws {
        var r = try request("v1/pet/events", method: "POST", timeout: 5)
        r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        r.httpBody = try JSONSerialization.data(withJSONObject: payload)
        let (_, resp) = try await Self.session.data(for: r)
        guard let http = resp as? HTTPURLResponse, http.statusCode == 200 else { throw BackendError.invalidResponse }
    }

    func putPetPreferences(_ preferences: [String: Any]) async throws {
        var r = try request("v1/pet/preferences", method: "PUT", timeout: 5)
        r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        r.httpBody = try JSONSerialization.data(withJSONObject: preferences)
        let (_, resp) = try await Self.session.data(for: r)
        guard let http = resp as? HTTPURLResponse, http.statusCode == 200 else { throw BackendError.invalidResponse }
    }

    func snapshot(force: Bool) async throws -> Snapshot {
        let r = try request(force ? "v1/refresh" : "v1/snapshot", method: force ? "POST" : "GET", timeout: 120)
        let data: Data, resp: URLResponse
        do { (data, resp) = try await Self.session.data(for: r) } catch { throw BackendError.unreachable }
        guard let http = resp as? HTTPURLResponse else { throw BackendError.invalidResponse }
        if http.statusCode == 401 { throw BackendError.unauthorized }
        guard http.statusCode == 200 else {
            let err = (try? JSONDecoder().decode(JSON.self, from: data))?["error"].string
            throw BackendError.http(http.statusCode, err)
        }
        guard let json = try? JSONDecoder().decode(JSON.self, from: data) else { throw BackendError.invalidResponse }
        return Snapshot(json)
    }
}

/// Owns a backend child process when none is already running.
final class BackendProcess {
    private var process: Process?
    var isOwned: Bool { process?.isRunning == true }

    private static var bundledExecutable: URL? {
        guard let url = Bundle.main.resourceURL?.appendingPathComponent("backend/agent-meter-backend"),
              FileManager.default.isExecutableFile(atPath: url.path) else { return nil }
        return url
    }

    /// Explicit development override first, then a writable data directory for
    /// the bundled backend. Installing or updating the app preserves this data.
    static func projectDirectory() -> URL? {
        var candidates: [String] = []
        if let v = ProcessInfo.processInfo.environment["AGENT_METER_HOME"],
           FileManager.default.fileExists(atPath: URL(fileURLWithPath: v).appendingPathComponent("agent_meter/__init__.py").path) {
            return URL(fileURLWithPath: v)
        }
        if bundledExecutable != nil {
            guard let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first else { return nil }
            let data = support.appendingPathComponent("AgentMeter", isDirectory: true)
            do {
                try FileManager.default.createDirectory(at: data, withIntermediateDirectories: true,
                                                        attributes: [.posixPermissions: 0o700])
                return data
            } catch { return nil }
        }
        if let v = UserDefaults.standard.string(forKey: "projectDirectory") { candidates.append(v) }
        if let v = Bundle.main.object(forInfoDictionaryKey: "AgentMeterProjectDir") as? String { candidates.append(v) }
        var dir = Bundle.main.executableURL?.deletingLastPathComponent()
        for _ in 0..<8 {
            guard let d = dir else { break }
            candidates.append(d.path)
            dir = d.deletingLastPathComponent()
        }
        return candidates.lazy.map { URL(fileURLWithPath: ($0 as NSString).expandingTildeInPath) }
            .first { FileManager.default.fileExists(atPath: $0.appendingPathComponent("agent_meter/__init__.py").path) }
    }

    /// GUI apps inherit a minimal PATH; add the places the backend's CLIs live.
    private static func searchPath() -> String {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let extra = ["/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin",
                     home + "/.local/bin", home + "/.kimi-code/bin",
                     "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
        let existing = (ProcessInfo.processInfo.environment["PATH"] ?? "").split(separator: ":").map(String.init)
        var seen = Set<String>()
        return (extra + existing).filter { seen.insert($0).inserted }.joined(separator: ":")
    }

    func start(project: URL) throws {
        let runtime = project.appendingPathComponent(".runtime")
        try? FileManager.default.createDirectory(at: runtime, withIntermediateDirectories: true,
                                                 attributes: [.posixPermissions: 0o700])
        let logURL = runtime.appendingPathComponent("menubar-backend.log")
        FileManager.default.createFile(atPath: logURL.path, contents: nil, attributes: [.posixPermissions: 0o600])
        let log = try? FileHandle(forWritingTo: logURL)

        let p = Process()
        // A login shell picks up credentials exported in the user's profile
        // (MINIMAX_TOKEN_PLAN_KEY, DEEPSEEK_API_KEY); exec keeps the PID.
        p.executableURL = URL(fileURLWithPath: "/bin/zsh")
        // A build on a development port does not start the Kimi helper: that belongs to the installed app.
        let flags = BackendClient.port == BackendClient.defaultPort ? "--start-kimi-server" : "--port \(BackendClient.port)"
        if Self.bundledExecutable != nil,
           !FileManager.default.fileExists(atPath: project.appendingPathComponent("agent_meter/__init__.py").path) {
            p.arguments = ["-lc", "export PATH=\"$AGENT_METER_PATH:$PATH\"; exec \"$AGENT_METER_BACKEND\" serve \(flags)"]
            // The path is passed as data, so spaces and shell characters in an
            // installation directory cannot alter the command.
        } else {
            p.arguments = ["-lc", "export PATH=\"$AGENT_METER_PATH:$PATH\"; exec python3 -m agent_meter serve \(flags)"]
        }
        p.currentDirectoryURL = project
        var env = ProcessInfo.processInfo.environment
        env["AGENT_METER_PATH"] = Self.searchPath()
        env["PATH"] = Self.searchPath()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        if let executable = Self.bundledExecutable { env["AGENT_METER_BACKEND"] = executable.path }
        p.environment = env
        p.standardOutput = log ?? FileHandle.nullDevice
        p.standardError = log ?? FileHandle.nullDevice
        p.standardInput = FileHandle.nullDevice
        do { try p.run() } catch { throw BackendError.startFailed }
        process = p
    }

    func stop() {
        guard let p = process, p.isRunning else { return }
        p.terminate()
        p.waitUntilExit()
        process = nil
    }
}
