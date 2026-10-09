import AppKit
import SwiftUI
import WebKit

/// A source that reads usage with a website login.
struct WebProvider: Identifiable {
    let id: String              // backend source id
    let loginURL: URL
    let cookieDomain: String?   // cookie-based providers
    let capturesToken: Bool     // TRAE: Cloud-IDE-JWT from the page's own API calls
    let note: String
    /// Records the structure (never values) of the page's own JSON responses.
    var discovers = false
    /// False when the app, not the backend, uses the login (即梦).
    var backendManaged = true

    static let all: [WebProvider] = [
        WebProvider(id: "claude", loginURL: URL(string: "https://claude.ai/login")!,
                    cookieDomain: "claude.ai", capturesToken: false,
                    note: "与 Claude 桌面客户端同一账户，读取 5 小时 / 7 天额度。Google 登录可能拒绝内嵌窗口，建议用邮箱验证码登录。"),
        WebProvider(id: "qoder", loginURL: URL(string: "https://qoder.com.cn/account/usage")!,
                    cookieDomain: "qoder.com.cn", capturesToken: false,
                    note: "中国区账户额度，登录后替代读取失败的 Qoder SDK。"),
        WebProvider(id: "workbuddy", loginURL: URL(string: "https://www.workbuddy.cn/profile/plans-usage")!,
                    cookieDomain: "workbuddy.cn", capturesToken: false,
                    note: "积分包剩余、冻结与套餐；登录态与本窗口的浏览器标识绑定。"),
        WebProvider(id: "trae_cn", loginURL: URL(string: "https://www.trae.cn/")!,
                    cookieDomain: nil, capturesToken: true,
                    note: "实验性：登录后打开用量/账户页，自动捕获 Cloud-IDE-JWT；也可手动粘贴。"),
        WebProvider(id: "dreamina", loginURL: URL(string: "https://jimeng.jianying.com/ai-tool/home")!,
                    cookieDomain: "jianying.com", capturesToken: false,
                    note: "实验性：登录后请打开「会员 / 积分」相关页面，再点「完成连接」。本步只记录页面接口的字段结构，用来定位续费与积分更新时间。",
                    discovers: true, backendManaged: false),
    ]

    static func find(_ id: String) -> WebProvider? { all.first { $0.id == id } }

    /// Sources that take an API key typed into the app instead of a web login.
    static let apiKeyProviders: [(id: String, hint: String)] = [
        ("deepseek_api", "DeepSeek 开放平台的 API Key（sk-…），用于查询余额。"),
        ("minimax_code", "MiniMax Token Plan 的 API Key（国内版），优先于 CC Switch 里的供应方。"),
    ]
    static func isAPIKeyProvider(_ id: String) -> Bool { apiKeyProviders.contains { $0.id == id } }

    /// Must match the backend default so WorkBuddy's UA binding holds.
    static let userAgent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"
}

/// Owns stored sessions and keeps the backend in sync with them. Each login
/// is a Keychain slot: "qoder" for the first account, "qoder#2"... for more.
@MainActor
final class ConnectionManager {
    static let shared = ConnectionManager()
    static let maxAccounts = 5
    private var windows: [String: NSWindow] = [:]
    private var connectionsWindow: NSWindow?

    nonisolated static func provider(ofSlot slot: String) -> String {
        String(slot.split(separator: "#", maxSplits: 1).first ?? Substring(slot))
    }

    nonisolated static func order(ofSlot slot: String) -> Int {
        slot.split(separator: "#").dropFirst().first.flatMap { Int($0) } ?? 1
    }

    /// Saved slots for a provider, in the order the backend numbers them.
    func slots(for provider: String) -> [String] {
        SessionKeychain.slots().filter { Self.provider(ofSlot: $0) == provider }
            .sorted { Self.order(ofSlot: $0) < Self.order(ofSlot: $1) }
    }

    /// Source ids are positional ("qoder", "qoder#2"), slots may have gaps.
    func slot(forSourceID id: String) -> String? {
        let provider = Self.provider(ofSlot: id)
        let index = Self.order(ofSlot: id) - 1
        let list = slots(for: provider)
        return list.indices.contains(index) ? list[index] : nil
    }

    func isConnected(_ sourceID: String) -> Bool { slot(forSourceID: sourceID) != nil }

    private func nextSlot(for provider: String) -> String? {
        let used = Set(slots(for: provider).map(Self.order(ofSlot:)))
        guard let n = (1...Self.maxAccounts).first(where: { !used.contains($0) }) else { return nil }
        return n == 1 ? provider : provider + "#" + String(n)
    }

    /// Off the main thread: a Keychain prompt must not freeze the app.
    nonisolated func storedSessions() async -> [String: [String: String]] {
        let ids = Set(WebProvider.all.map(\.id) + WebProvider.apiKeyProviders.map(\.id))
        return await Task.detached {
            var out: [String: [String: String]] = [:]
            for slot in SessionKeychain.slots() where ids.contains(ConnectionManager.provider(ofSlot: slot)) {
                if let s = SessionKeychain.load(slot) { out[slot] = s }
            }
            return out
        }.value
    }

    func save(_ slot: String, _ session: [String: String]) {
        SessionKeychain.save(slot, session)
        UsageStore.shared.cacheSession(slot, session)
        UsageStore.shared.syncSessionsAndRefresh()
    }

    func disconnect(_ slot: String) {
        SessionKeychain.delete(slot)
        UsageStore.shared.cacheSession(slot, nil)
        UsageStore.shared.syncSessionsAndRefresh()
    }

    func showConnections() {
        if connectionsWindow == nil {
            let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 480, height: 560),
                                  styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
            window.title = "连接网页账户 / API 密钥"
            window.isReleasedWhenClosed = false
            window.contentView = NSHostingView(rootView: ConnectionsView().environment(UsageStore.shared))
            window.center()
            connectionsWindow = window
        }
        NSApp.activate(ignoringOtherApps: true)
        connectionsWindow?.makeKeyAndOrderFront(nil)
    }

    /// Re-login an existing account (slot) or add a new one (slot nil).
    func login(_ provider: WebProvider, slot existing: String? = nil) {
        guard let slot = existing ?? nextSlot(for: provider.id) else { return }
        if let w = windows[slot] { NSApp.activate(ignoringOtherApps: true); w.makeKeyAndOrderFront(nil); return }
        let label = existing.flatMap { UsageStore.shared.session(for: $0)?["label"] }
            ?? (slot == provider.id ? "" : "账号 \(Self.order(ofSlot: slot))")
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1000, height: 760),
                              styleMask: [.titled, .closable, .resizable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "登录 " + Catalog.brand(provider.id).name
        window.isReleasedWhenClosed = false
        let model = WebLoginModel(provider: provider, slot: slot, label: label)
        window.contentView = NSHostingView(rootView: WebLoginView(model: model) { [weak self, weak window] in
            window?.close()
            self?.windows[slot] = nil
        })
        window.center()
        windows[slot] = window
        NSApp.activate(ignoringOtherApps: true)
        window.makeKeyAndOrderFront(nil)
    }

    /// Login button for a source row ("qoder#2" re-logs that account).
    func login(sourceID: String) {
        guard let provider = WebProvider.find(Self.provider(ofSlot: sourceID)) else { return }
        login(provider, slot: slot(forSourceID: sourceID))
    }
}

// MARK: Login window

@MainActor @Observable
final class WebLoginModel: NSObject, WKScriptMessageHandler {
    let provider: WebProvider
    let slot: String
    var label: String
    let webView: WKWebView
    var capturedToken: String?
    @ObservationIgnored let discovery = DreaminaDiscovery()
    var status = "请在下方完成登录，然后点「完成连接」。"
    var saving = false

    init(provider: WebProvider, slot: String, label: String) {
        self.provider = provider
        self.slot = slot
        self.label = label
        let config = WKWebViewConfiguration()
        // A private store: the session leaves this window only via the Keychain.
        config.websiteDataStore = .nonPersistent()
        let web = WKWebView(frame: .zero, configuration: config)
        web.customUserAgent = WebProvider.userAgent
        self.webView = web
        super.init()
        if provider.discovers {
            config.userContentController.add(self, name: DreaminaDiscovery.handlerName)
            config.userContentController.addUserScript(WKUserScript(source: DreaminaDiscovery.script,
                                                                    injectionTime: .atDocumentStart, forMainFrameOnly: false))
        }
        if provider.capturesToken {
            config.userContentController.add(self, name: "agentMeterAuth")
            config.userContentController.addUserScript(WKUserScript(source: Self.captureScript,
                                                                    injectionTime: .atDocumentStart, forMainFrameOnly: false))
        }
        web.load(URLRequest(url: provider.loginURL))
    }

    /// Observes (never alters) the page's own API calls to api.trae.cn.
    private static let captureScript = """
    (function(){
      const send = v => { try { window.webkit.messageHandlers.agentMeterAuth.postMessage(String(v)); } catch (e) {} };
      const pick = (url, h) => { try {
        if (!/^https:\\/\\/api\\.trae\\.cn\\//.test(String(url))) return;
        let v = null;
        if (h instanceof Headers) v = h.get('Authorization');
        else if (Array.isArray(h)) { for (const [k, x] of h) if (String(k).toLowerCase() === 'authorization') v = x; }
        else if (h) { for (const k in h) if (k.toLowerCase() === 'authorization') v = h[k]; }
        if (v && /^Cloud-IDE-JWT\\s+\\S+$/i.test(v)) send(v);
      } catch (e) {} };
      const f = window.fetch;
      window.fetch = function(input, init) {
        try { pick(typeof input === 'string' ? input : input.url, (init && init.headers) || (input && input.headers)); } catch (e) {}
        return f.apply(this, arguments);
      };
      const open = XMLHttpRequest.prototype.open, set = XMLHttpRequest.prototype.setRequestHeader;
      XMLHttpRequest.prototype.open = function(m, u) { this.__amUrl = u; return open.apply(this, arguments); };
      XMLHttpRequest.prototype.setRequestHeader = function(k, v) {
        if (String(k).toLowerCase() === 'authorization') pick(this.__amUrl, { authorization: v });
        return set.apply(this, arguments);
      };
    })();
    """

    nonisolated func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        if message.name == DreaminaDiscovery.handlerName {
            guard let body = message.body as? [String: Any], let url = body["url"] as? String,
                  let json = body["json"] as? String else { return }
            Task { @MainActor in
                if self.discovery.record(url: url, json: json) {
                    self.status = "已记录 \(self.discovery.count) 个接口结构。打开会员 / 积分页面后点「完成连接」。"
                }
            }
            return
        }
        guard let value = message.body as? String else { return }
        let token = value.replacingOccurrences(of: "Cloud-IDE-JWT ", with: "", options: [.caseInsensitive, .anchored])
            .trimmingCharacters(in: .whitespaces)
        Task { @MainActor in
            guard !token.isEmpty, token.count < 8000 else { return }
            self.capturedToken = token
            self.status = "已捕获登录凭据，可以点「完成连接」。"
        }
    }

    func finish() async -> Bool {
        saving = true
        defer { saving = false }
        var session = ["user_agent": WebProvider.userAgent]
        let cleanLabel = label.trimmingCharacters(in: .whitespacesAndNewlines).prefix(40)
        if !cleanLabel.isEmpty { session["label"] = String(cleanLabel) }
        if provider.capturesToken {
            guard let token = capturedToken else {
                status = "还没有捕获到凭据：登录后打开账户 / 用量页面再试，或在连接窗口手动粘贴。"
                return false
            }
            session["token"] = token
        }
        if let domain = provider.cookieDomain {
            let cookies = await webView.configuration.websiteDataStore.httpCookieStore.allCookies()
            let now = Date()
            let header = cookies
                .filter { c in
                    let d = c.domain.hasPrefix(".") ? String(c.domain.dropFirst()) : c.domain
                    return (d == domain || d.hasSuffix("." + domain)) && (c.expiresDate ?? .distantFuture) > now
                }
                .map { "\($0.name)=\($0.value)" }
                .joined(separator: "; ")
            guard !header.isEmpty else {
                status = "没有找到 \(domain) 的登录 Cookie，请先完成登录。"
                return false
            }
            guard header.utf8.count < 16 * 1024 else { status = "Cookie 过大，无法保存。"; return false }
            session["cookie"] = header
        }
        if provider.discovers, let dir = UsageStore.shared.projectDirectory {
            discovery.write(to: dir.appendingPathComponent(".runtime/dreamina-discovery.json"))
        }
        ConnectionManager.shared.save(slot, session)
        return true
    }
}

private struct WebViewHost: NSViewRepresentable {
    let webView: WKWebView
    func makeNSView(context: Context) -> WKWebView { webView }
    func updateNSView(_ nsView: WKWebView, context: Context) {}
}

struct WebLoginView: View {
    @Bindable var model: WebLoginModel
    let close: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                BrandBadge(brand: Catalog.brand(model.provider.id), size: 22)
                VStack(alignment: .leading, spacing: 1) {
                    Text("登录 \(Catalog.brand(model.provider.id).name)").font(.system(size: 13, weight: .semibold))
                    Text(model.status).font(.system(size: 11)).foregroundStyle(.secondary).lineLimit(2)
                }
                Spacer()
                TextField("账号备注（可选）", text: $model.label)
                    .textFieldStyle(.roundedBorder)
                    .frame(width: 150)
                    .help("用来区分多个账号，例如「主号」「小号」")
                Button("取消", action: close)
                Button("完成连接") {
                    Task { if await model.finish() { close() } }
                }
                .keyboardShortcut(.defaultAction)
                .disabled(model.saving)
            }
            .padding(12)
            Divider()
            WebViewHost(webView: model.webView)
            Divider()
            Label("登录只在本窗口内进行。保存的 Cookie / 凭据仅存入钥匙串，并只发送给本机后端用于读取用量。",
                  systemImage: "lock.shield")
                .font(.system(size: 10.5)).foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 12).padding(.vertical, 6)
        }
    }
}

// MARK: Connections window

struct ConnectionsView: View {
    @Environment(UsageStore.self) private var store
    @State private var slots: [String: [String]] = [:]
    @State private var pastedToken = ""
    @State private var apiKeys: [String: String] = [:]
    @State private var savedKeys: Set<String> = []

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Text("API 密钥").font(.system(size: 14, weight: .semibold))
                Card { apiKeySection }
                Text("需要网页登录的来源").font(.system(size: 14, weight: .semibold)).padding(.top, 4)
                Text("每个来源最多 \(ConnectionManager.maxAccounts) 个账号；不同账号的余额分开显示，不会相加。")
                    .font(.system(size: 11)).foregroundStyle(.secondary)
                ForEach(WebProvider.all) { p in
                    Card(tint: Catalog.brand(p.id).tint) { section(p) }
                }
            }
            .padding(16)
        }
        .frame(width: 480)
        .frame(minHeight: 420)
        .onAppear(perform: reload)
        .onChange(of: store.snapshot?.collectedAt) { _, _ in reload() }
    }

    private func reload() {
        slots = Dictionary(uniqueKeysWithValues: WebProvider.all.map { ($0.id, ConnectionManager.shared.slots(for: $0.id)) })
        savedKeys = Set(WebProvider.apiKeyProviders.map(\.id).filter { SessionKeychain.exists($0) })
    }

    /// Keys are written to the Keychain and only ever sent to the local backend.
    @ViewBuilder private var apiKeySection: some View {
        ForEach(Array(WebProvider.apiKeyProviders.enumerated()), id: \.element.id) { index, p in
            if index > 0 { Divider().opacity(0.4) }
            let source = store.snapshot?.sources.first { $0.id == p.id }
            HStack(spacing: 8) {
                BrandBadge(brand: Catalog.brand(p.id), size: 22, icon: AppLauncher.icon(for: p.id, in: store.snapshot))
                VStack(alignment: .leading, spacing: 1) {
                    Text(Catalog.brand(p.id).name).font(.system(size: 12.5, weight: .semibold))
                    Text(p.hint).font(.system(size: 10.5)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }
                Spacer()
                if savedKeys.contains(p.id) {
                    StatusPill(status: source?.status ?? "not_provided",
                               text: source.map { $0.status == "available" ? "已连接" : Catalog.statusLabel($0.status) } ?? "已保存")
                        .help(Catalog.reason(source?.reason))
                }
            }
            HStack {
                SecureField(savedKeys.contains(p.id) ? "已保存（输入新密钥可替换）" : "粘贴 API Key",
                            text: Binding(get: { apiKeys[p.id] ?? "" }, set: { apiKeys[p.id] = $0 }))
                    .textFieldStyle(.roundedBorder)
                Button("保存") {
                    let key = (apiKeys[p.id] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                    guard !key.isEmpty, !key.contains("\n"), key.count < 512 else { return }
                    ConnectionManager.shared.save(p.id, ["api_key": key])
                    apiKeys[p.id] = ""
                    reload()
                }
                .disabled((apiKeys[p.id] ?? "").trimmingCharacters(in: .whitespaces).isEmpty)
                if savedKeys.contains(p.id) {
                    Button("清除", role: .destructive) { ConnectionManager.shared.disconnect(p.id); reload() }
                }
            }
            .controlSize(.small)
        }
    }

    @ViewBuilder private func section(_ p: WebProvider) -> some View {
        let brand = Catalog.brand(p.id)
        let list = slots[p.id] ?? []
        HStack(spacing: 10) {
            BrandBadge(brand: brand, icon: AppLauncher.icon(for: p.id, in: store.snapshot))
            VStack(alignment: .leading, spacing: 2) {
                Text(brand.name).font(.system(size: 13, weight: .semibold))
                Text(p.note).font(.system(size: 10.5)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
            Spacer()
        }
        ForEach(Array(list.enumerated()), id: \.element) { index, slot in
            // The backend numbers accounts by this order: "qoder", "qoder#2"...
            let sourceID = index == 0 ? p.id : p.id + "#" + String(index + 1)
            let source = store.snapshot?.sources.first { $0.id == sourceID }
            HStack(spacing: 8) {
                Image(systemName: "person.crop.circle.fill").foregroundStyle(brand.tint)
                Text(source?.accountLabel ?? store.session(for: slot)?["label"] ?? "账号 \(index + 1)")
                    .font(.system(size: 12, weight: .medium))
                if p.backendManaged {
                    StatusPill(status: source?.status ?? "not_provided",
                               text: source.map { $0.status == "available" ? "已连接" : Catalog.statusLabel($0.status) } ?? "已保存")
                        .help(Catalog.reason(source?.reason))
                } else {
                    StatusPill(status: "available", text: "已保存")
                }
                Spacer()
                Button("重新登录") { ConnectionManager.shared.login(p, slot: slot) }
                Button("断开", role: .destructive) { ConnectionManager.shared.disconnect(slot); reload() }
            }
            .controlSize(.small)
        }
        HStack {
            Button(list.isEmpty ? "登录…" : "添加账号…") { ConnectionManager.shared.login(p) }
                .disabled(list.count >= ConnectionManager.maxAccounts)
            Spacer()
        }
        .controlSize(.small)
        if p.capturesToken {
            HStack {
                SecureField("或粘贴 Cloud-IDE-JWT（新增一个账号）", text: $pastedToken).textFieldStyle(.roundedBorder)
                Button("保存") {
                    let token = pastedToken.replacingOccurrences(of: "Cloud-IDE-JWT ", with: "", options: [.caseInsensitive, .anchored])
                        .trimmingCharacters(in: .whitespacesAndNewlines)
                    guard !token.isEmpty, !token.contains("\n") else { return }
                    let used = Set(list.map(ConnectionManager.order(ofSlot:)))
                    guard let n = (1...ConnectionManager.maxAccounts).first(where: { !used.contains($0) }) else { return }
                    ConnectionManager.shared.save(n == 1 ? p.id : p.id + "#\(n)", ["token": token, "user_agent": WebProvider.userAgent])
                    pastedToken = ""
                    reload()
                }
                .disabled(pastedToken.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            .controlSize(.small)
        }
    }
}
