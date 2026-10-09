import AppKit
import CryptoKit
import WebKit

/// Reads 即梦 membership and credit detail the way a person would: it opens
/// the logged-in 即梦 page in a hidden web view and keeps an allowlisted set
/// of fields from the page's *own* responses (subscription/user_info,
/// benefits/user_credit). Nothing is signed, forged or replayed; the web
/// view is torn down after each run.
@MainActor
final class DreaminaMonitor: NSObject, WKScriptMessageHandler {
    static let shared = DreaminaMonitor()

    private static let pageURL = URL(string: "https://jimeng.jianying.com/ai-tool/home")!
    private static let timeout: TimeInterval = 45

    private var webView: WKWebView?
    private var credit: [String: Any]?
    private var subscription: [String: Any]?
    private var waiter: CheckedContinuation<Void, Never>?
    private(set) var lastRun: Date?
    private var running = false

    /// One observation per saved 即梦 login, in slot order; nil while a run
    /// is already in progress (the caller must not push an empty list then).
    func observe(_ sessions: [(slot: String, session: [String: String])]) async -> [[String: Any]]? {
        guard !running else { return nil }
        running = true
        defer { running = false; lastRun = Date() }
        var out: [[String: Any]] = []
        for (_, session) in sessions {
            guard let cookie = session["cookie"] else { continue }
            if var obs = await run(cookieHeader: cookie) {
                if let label = session["label"] { obs["label"] = String(label.prefix(40)) }
                out.append(obs)
            }
        }
        return out
    }

    private func run(cookieHeader: String) async -> [String: Any]? {
        credit = nil
        subscription = nil
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        config.userContentController.add(self, name: DreaminaDiscovery.handlerName)
        config.userContentController.addUserScript(WKUserScript(source: DreaminaDiscovery.script,
                                                                injectionTime: .atDocumentStart, forMainFrameOnly: false))
        for cookie in Self.cookies(from: cookieHeader) {
            await config.websiteDataStore.httpCookieStore.setCookie(cookie)
        }
        let web = WKWebView(frame: NSRect(x: 0, y: 0, width: 1280, height: 800), configuration: config)
        web.customUserAgent = WebProvider.userAgent
        webView = web
        web.load(URLRequest(url: Self.pageURL))

        await withCheckedContinuation { (c: CheckedContinuation<Void, Never>) in
            waiter = c
            DispatchQueue.main.asyncAfter(deadline: .now() + Self.timeout) { [weak self] in self?.finish() }
        }
        web.stopLoading()
        config.userContentController.removeScriptMessageHandler(forName: DreaminaDiscovery.handlerName)
        webView = nil
        NSLog("AgentMeterBar 即梦 page: credit=%@ subscription=%@", credit == nil ? "no" : "yes", subscription == nil ? "no" : "yes")
        return Self.observation(credit: credit, subscription: subscription)
    }

    private func finish() {
        waiter?.resume()
        waiter = nil
    }

    nonisolated func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let body = message.body as? [String: Any], let url = body["url"] as? String,
              let text = body["json"] as? String, let path = URL(string: url)?.path,
              let root = (try? JSONSerialization.jsonObject(with: Data(text.utf8))) as? [String: Any],
              let data = root["data"] as? [String: Any] else { return }
        // Keep only the two responses we use; everything else is dropped here.
        let isCredit = path.hasSuffix("/commerce/v1/benefits/user_credit")
        let isSubscription = path.hasSuffix("/commerce/v1/subscription/user_info")
        guard isCredit || isSubscription else { return }
        let picked = isCredit ? Self.pickCredit(data) : Self.pickSubscription(data)
        Task { @MainActor in
            if isCredit { self.credit = picked } else { self.subscription = picked }
            if self.credit != nil && self.subscription != nil { self.finish() }
        }
    }

    // MARK: Allowlisted fields

    nonisolated private static func int(_ v: Any?) -> Int? {
        if let n = v as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID() { return n.intValue }
        if let s = v as? String { return Int(s) }
        return nil
    }

    nonisolated private static func pickCredit(_ data: [String: Any]) -> [String: Any] {
        let c = data["credit"] as? [String: Any] ?? [:]
        var details: [[String: Any]] = []
        let groups = data["credits_detail"] as? [String: Any] ?? [:]
        for (key, kind) in [("vip_credits", "vip"), ("gift_credits", "gift"), ("purchase_credits", "purchase")] {
            for row in groups[key] as? [[String: Any]] ?? [] {
                guard let balance = int(row["residual_credits"]) else { continue }
                var d: [String: Any] = ["kind": kind, "balance": balance, "expires_at": int(row["credits_life_end"]) ?? 0]
                if let level = row["vip_level"] as? String { d["level"] = String(level.prefix(40)) }
                details.append(d)
            }
        }
        return ["gift": int(c["gift_credit"]) ?? 0, "purchase": int(c["purchase_credit"]) ?? 0,
                "vip": int(c["vip_credit"]) ?? 0, "details": details]
    }

    nonisolated private static func pickSubscription(_ data: [String: Any]) -> [String: Any] {
        var out: [String: Any] = [
            "end_time": int(data["end_time"]) ?? 0,
            "next_renewal_time": int(data["next_renewal_time"]) ?? 0,
        ]
        if let level = data["cur_vip_level"] as? String, !level.isEmpty { out["level"] = String(level.prefix(40)) }
        if let cancel = data["is_cancel_subscribe"] as? Bool { out["is_cancel_subscribe"] = cancel }
        if let unit = data["cycle_unit"] as? String, !unit.isEmpty { out["cycle_unit"] = String(unit.prefix(20)) }
        if let cycle = int(data["subscribe_cycle"]) { out["subscribe_cycle"] = cycle }
        // The uid only becomes an anonymous fingerprint (same scheme as the backend).
        if let uid = (data["uid"] as? String) ?? int(data["uid"]).map(String.init) {
            out["_account_key"] = accountKey(uid)
        }
        return out
    }

    nonisolated static func accountKey(_ uid: String) -> String {
        let digest = SHA256.hash(data: Data(("dreamina:" + uid).utf8))
        return String(digest.map { String(format: "%02x", $0) }.joined().prefix(24))
    }

    private static func observation(credit: [String: Any]?, subscription: [String: Any]?) -> [String: Any]? {
        guard credit != nil || subscription != nil else { return nil }
        var sub = subscription
        let key = sub?.removeValue(forKey: "_account_key")
        var obs: [String: Any] = ["observed_at": Int(Date().timeIntervalSince1970)]
        if let key { obs["account_key"] = key }
        if let credit { obs["credit"] = credit }
        if let sub { obs["subscription"] = sub }
        return obs
    }

    nonisolated private static func cookies(from header: String) -> [HTTPCookie] {
        header.components(separatedBy: "; ").compactMap { pair in
            guard let eq = pair.firstIndex(of: "=") else { return nil }
            return HTTPCookie(properties: [
                .domain: ".jianying.com", .path: "/", .secure: "TRUE",
                .name: String(pair[..<eq]), .value: String(pair[pair.index(after: eq)...]),
                .expires: Date().addingTimeInterval(3600),
            ])
        }
    }
}
