import AppKit
import WebKit

/// Keeps a short-lived captured token fresh without a manual login: a hidden
/// webview reuses the login window's persistent cookies, opens pages that make
/// the site call its own API, and records the header the page already sends.
/// Only the page's existing requests are observed — nothing is triggered,
/// redeemed or submitted.
@MainActor
final class TokenRenewer {
    static let shared = TokenRenewer()

    /// Trae's Cloud-IDE-JWT only stays valid for a short while, so renew well
    /// before it dies instead of letting the card blink "登录已失效".
    private let renewAfter: TimeInterval = 15 * 60
    /// A renewal that found no login means the website session is gone too.
    /// Give up for a while rather than reopening hidden windows forever.
    private let retryWait: TimeInterval = 10 * 60
    private let maxFailures = 3

    private var running: [String: Task<Bool, Never>] = [:]
    /// A webview with no window is only kept alive by a strong reference.
    private var captures: [String: Capture] = [:]
    private var lastFailure: [String: Date] = [:]

    private let renewedKey = "tokenRenewedAt."
    private let failKey = "tokenRenewFails."

    func isRenewing(_ slot: String) -> Bool { running[slot] != nil }

    /// Called after every snapshot.
    func consider(_ snapshot: Snapshot) {
        // The backend says the token died: renew that account.
        for source in snapshot.sources
        where WebProvider.isAutoRenew(source.id) && source.status == "not_connected" && source.reason == "not_authenticated" {
            guard let slot = ConnectionManager.shared.slot(forSourceID: source.id) else { continue }
            Task { await renew(slot) }
        }
        // Otherwise renew on schedule, so the card never shows a gap.
        for provider in WebProvider.all where WebProvider.autoRenew.contains(provider.id) {
            for slot in ConnectionManager.shared.slots(for: provider.id) {
                let at = UserDefaults.standard.double(forKey: renewedKey + slot)
                if Date().timeIntervalSince1970 - at > renewAfter { Task { await renew(slot) } }
            }
        }
    }

    /// A completed manual login starts renewal attempts afresh for that slot.
    func reset(slot: String) {
        UserDefaults.standard.set(0, forKey: failKey + slot)
        lastFailure[slot] = nil
    }

    @discardableResult
    func renew(_ slot: String) async -> Bool {
        guard WebProvider.isAutoRenew(slot), running[slot] == nil else { return false }
        guard let provider = WebProvider.find(ConnectionManager.provider(ofSlot: slot)),
              provider.tokenCapture != nil else { return false }
        // Only accounts that already have a stored login are renewed; a pasted
        // key without a website session has nothing to renew from. The cached
        // copy is read here because a Keychain read on the main thread is denied
        // (see ConnectionManager.storedSessions).
        guard UsageStore.shared.session(for: slot) != nil else { return false }
        if let failed = lastFailure[slot], Date().timeIntervalSince(failed) < retryWait { return false }
        if UserDefaults.standard.integer(forKey: failKey + slot) >= maxFailures { return false }

        UsageStore.shared.renewingSlots.insert(slot)
        NSLog("AgentMeterBar renew: %@ starts a hidden window", slot)
        let capture = Capture(provider: provider, slot: slot)
        captures[slot] = capture
        let task = Task { @MainActor in
            guard let token = await capture.start() else { return false }
            return Self.save(token, for: slot, provider: provider)
        }
        running[slot] = task
        let ok = await task.value
        running[slot] = nil
        captures[slot] = nil
        UsageStore.shared.renewingSlots.remove(slot)

        if ok {
            reset(slot: slot)
            UserDefaults.standard.set(Date().timeIntervalSince1970, forKey: renewedKey + slot)
            NSLog("AgentMeterBar renew: %@ captured a fresh credential", slot)
        } else {
            lastFailure[slot] = Date()
            let fails = UserDefaults.standard.integer(forKey: failKey + slot) + 1
            UserDefaults.standard.set(fails, forKey: failKey + slot)
            // No credential found means the saved website login is gone as well;
            // the user has to log in again, so stop opening windows.
            NSLog("AgentMeterBar renew: %@ captured nothing (fail %d/%d)", slot, fails, maxFailures)
        }
        return ok
    }

    /// Keeps the account's other fields, replaces only the captured credential.
    private static func save(_ token: String, for slot: String, provider: WebProvider) -> Bool {
        var session = UsageStore.shared.session(for: slot) ?? [:]
        session[provider.tokenCapture?.field ?? "token"] = token
        session["user_agent"] = WebProvider.userAgent
        guard !session.isEmpty else { return false }
        ConnectionManager.shared.save(slot, session)   // Keychain, then the backend
        return true
    }
}

/// One hidden webview session that visits pages until the observer reports a token.
private final class Capture: NSObject, WKScriptMessageHandler {
    private let web: WKWebView
    private let urls: [URL]
    private let strip: String?
    /// A page needs a moment to boot and fire its own requests.
    private let pageWindow: TimeInterval = 8
    private var continuation: CheckedContinuation<String?, Never>?
    private var index = 0
    private var done = false

    init(provider: WebProvider, slot: String) {
        urls = provider.renewURLs()
        strip = provider.tokenCapture?.strip
        let config = WKWebViewConfiguration()
        config.websiteDataStore = WebProvider.dataStore(forSlot: slot)
        web = WKWebView(frame: CGRect(x: 0, y: 0, width: 1280, height: 900), configuration: config)
        web.customUserAgent = WebProvider.userAgent
        super.init()
        let controller = config.userContentController
        controller.add(self, name: "agentMeterAuth")
        controller.addUserScript(WKUserScript(source: AuthCapture.script(provider.tokenCapture!),
                                              injectionTime: .atDocumentStart, forMainFrameOnly: false))
    }

    func start() async -> String? {
        await withCheckedContinuation { continuation in
            self.continuation = continuation
            loadNext()
        }
    }

    private func loadNext() {
        guard !done else { return }
        guard index < urls.count else { finish(nil); return }
        let url = urls[index]
        index += 1
        web.load(URLRequest(url: url))
        Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(self?.pageWindow ?? 8))
            self?.loadNext()
        }
    }

    private func finish(_ token: String?) {
        guard !done else { return }
        done = true
        continuation?.resume(returning: token)
        continuation = nil
    }

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let body = message.body as? [String: Any], let value = body["value"] as? String else { return }
        guard let token = AuthCapture.normalize(value, strip: strip) else { return }
        finish(token)
    }
}
