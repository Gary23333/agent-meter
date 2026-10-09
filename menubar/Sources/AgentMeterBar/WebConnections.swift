import AppKit
import SwiftUI
import WebKit

/// A source that reads usage with a website login.
struct WebProvider: Identifiable {
    let id: String              // backend source id
    let loginURL: URL
    let cookieDomain: String?   // cookie-based providers
    let note: String
    /// Records the structure (never values) of the page's own JSON responses.
    var discovers = false
    /// False when the app, not the backend, uses the login (即梦).
    var backendManaged = true
    /// Watches the page's own API calls for one request header (TRAE, ZCode, 火山).
    var tokenCapture: TokenCapture? = nil
    /// Keys typed in instead of logging in; each save adds an account.
    var manual: ManualEntry? = nil
    /// Where to get those keys, shown as a link.
    var keyHelp: (title: String, url: URL)? = nil

    static let all: [WebProvider] = [
        WebProvider(id: "claude", loginURL: URL(string: "https://claude.ai/login")!,
                    cookieDomain: "claude.ai",
                    note: "与 Claude 桌面客户端同一账户，读取 5 小时 / 7 天额度。Google 登录可能拒绝内嵌窗口，建议用邮箱验证码登录。"),
        WebProvider(id: "qoder", loginURL: URL(string: "https://qoder.com.cn/account/usage")!,
                    cookieDomain: "qoder.com.cn",
                    note: "中国区账户额度，登录后替代读取失败的 Qoder SDK。"),
        WebProvider(id: "workbuddy", loginURL: URL(string: "https://www.workbuddy.cn/profile/plans-usage")!,
                    cookieDomain: "workbuddy.cn",
                    note: "积分包剩余、冻结与套餐；登录态与本窗口的浏览器标识绑定。"),
        WebProvider(id: "trae_cn", loginURL: URL(string: "https://www.trae.cn/")!,
                    cookieDomain: nil,
                    note: "实验性：登录后打开用量/账户页，自动捕获 Cloud-IDE-JWT；也可手动粘贴。",
                    tokenCapture: TokenCapture(url: #"^https:\/\/api\.trae\.cn\/"#, value: #"^Cloud-IDE-JWT\s+\S+$"#,
                                               strip: "Cloud-IDE-JWT "),
                    manual: ManualEntry(fields: [KeyField(field: "token", placeholder: "或粘贴 Cloud-IDE-JWT（新增一个账号）")],
                                        strip: "Cloud-IDE-JWT ")),
        WebProvider(id: "zcode", loginURL: URL(string: "https://bigmodel.cn/coding-plan/personal/usage")!,
                    cookieDomain: nil,
                    note: "实验性：登录智谱开放平台（ZCode 的 GLM Coding Plan 账户），打开「用量」页后自动捕获页面自己的查询凭据，读取 5 小时 / 每周额度与 MCP 次数。也可粘贴 Coding Plan API Key。重置卡只在 ZCode 桌面端，暂不读取。",
                    tokenCapture: TokenCapture(url: #"^https:\/\/(open\.)?bigmodel\.cn\/api\/"#,
                                               value: #"^(Bearer\s+)?[A-Za-z0-9._\-]{20,}$"#, urlField: "origin"),
                    manual: ManualEntry(fields: [KeyField(field: "api_key", placeholder: "或粘贴 Coding Plan API Key（新增一个账号）")])),
        WebProvider(id: "volcengine", loginURL: URL(string: "https://console.volcengine.com/ark/region:cn-beijing/subscription/coding-plan")!,
                    cookieDomain: "volcengine.com",
                    note: "推荐：登录火山引擎控制台并停在 Coding Plan 订阅页，看到用量后点「完成连接」，App 记下页面自己的用量查询，不需要任何密钥。也可填写 AccessKey（访问控制 → API 访问密钥）。方舟控制台里的 API Key 只能调用模型，无法查询用量。",
                    tokenCapture: TokenCapture(url: #"^https:\/\/console\.volcengine\.com\/api\/top\/ark\/[^\/?#]+\/[^\/?#]+\/GetCodingPlanUsage"#,
                                               value: #"^[A-Za-z0-9_\-:.]{8,200}$"#, header: "x-csrf-token",
                                               field: "csrf_token", urlField: "usage_url", required: false),
                    manual: ManualEntry(fields: [KeyField(field: "access_key_id", placeholder: "Access Key ID（AKLT…）", mustStartWith: "AK",
                                                          wrongPrefixHint: "这是方舟 API Key，不能查询用量。请填访问控制里的 AccessKey ID（以 AK 开头），或直接点「登录…」。"),
                                                 KeyField(field: "secret_access_key", placeholder: "Secret Access Key")]),
                    keyHelp: ("打开 AccessKey 管理页", URL(string: "https://console.volcengine.com/iam/keymanage")!)),
        WebProvider(id: "dreamina", loginURL: URL(string: "https://jimeng.jianying.com/ai-tool/home")!,
                    cookieDomain: "jianying.com",
                    note: "实验性：登录后请打开「会员 / 积分」相关页面，再点「完成连接」。本步只记录页面接口的字段结构，用来定位续费与积分更新时间。",
                    discovers: true, backendManaged: false),
        WebProvider(id: "mimo", loginURL: URL(string: "https://platform.xiaomimimo.com/#/console/balance")!,
                    cookieDomain: "xiaomimimo.com",
                    note: "小米 MiMo API 开放平台：账户余额（现金 / 赠送）与 Token Plan。登录小米账号后看到余额页再点「完成连接」；API Key 无权查询余额。"),
    ]

    static func find(_ id: String) -> WebProvider? { all.first { $0.id == id } }

    struct TokenCapture {
        /// JS regex sources: which request URLs to watch and which header values to accept.
        let url: String
        let value: String
        var header = "Authorization"
        /// Scheme word removed before saving ("Cloud-IDE-JWT ").
        var strip: String? = nil
        /// Session key for the captured value.
        var field = "token"
        /// Also save the request: "origin" keeps its origin, any other key its full URL.
        var urlField: String? = nil
        /// False when the cookie alone can still work (火山 falls back to its csrf cookie).
        var required = true
    }

    struct ManualEntry {
        let fields: [KeyField]
        var strip: String? = nil
    }

    /// One secret the user types in; `field` is its backend session key.
    struct KeyField {
        let field: String
        let placeholder: String
        var mustStartWith: String? = nil
        var wrongPrefixHint: String? = nil
        var optional = false
    }

    struct APIKeyProvider {
        let id: String
        let hint: String
        var fields = [KeyField(field: "api_key", placeholder: "粘贴 API Key")]
    }

    /// Sources that take keys typed into the app instead of a web login.
    static let apiKeyProviders: [APIKeyProvider] = [
        APIKeyProvider(id: "deepseek_api", hint: "DeepSeek 开放平台的 API Key（sk-…），用于查询余额。",
                       fields: [KeyField(field: "api_key", placeholder: "粘贴 API Key"),
                                KeyField(field: "user_token", placeholder: "网页 userToken（可选，近 30 天用量展示）", optional: true)]),
        APIKeyProvider(id: "minimax_code", hint: "MiniMax Token Plan 的 API Key（国内版），优先于 CC Switch 里的供应方。"),
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

    /// The stored session fields of one slot (Keychain read).
    func session(for slot: String) -> [String: String]? { SessionKeychain.load(slot) }

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
    var capturedOrigin: String?
    var capturedURL: String?
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
        if let capture = provider.tokenCapture {
            config.userContentController.add(self, name: "agentMeterAuth")
            config.userContentController.addUserScript(WKUserScript(source: Self.captureScript(capture),
                                                                    injectionTime: .atDocumentStart, forMainFrameOnly: false))
        }
        web.load(URLRequest(url: provider.loginURL))
    }

    /// Observes (never alters) the page's own API calls to the provider's API host.
    private static func captureScript(_ c: WebProvider.TokenCapture) -> String {
        """
        (function(){
          const URL_RE = new RegExp(\(jsString(c.url))), VALUE_RE = new RegExp(\(jsString(c.value)), 'i');
          const HEADER = \(jsString(c.header.lowercased()));
          const send = (u, v) => { try {
            const parsed = new URL(String(u), location.href);
            window.webkit.messageHandlers.agentMeterAuth.postMessage({ origin: parsed.origin, url: parsed.href, value: String(v) });
          } catch (e) {} };
          const pick = (url, h) => { try {
            const abs = new URL(String(url), location.href).href;
            if (!URL_RE.test(abs)) return;
            let v = null;
            if (h instanceof Headers) v = h.get(HEADER);
            else if (Array.isArray(h)) { for (const [k, x] of h) if (String(k).toLowerCase() === HEADER) v = x; }
            else if (h) { for (const k in h) if (k.toLowerCase() === HEADER) v = h[k]; }
            if (v && VALUE_RE.test(String(v).trim())) send(abs, String(v).trim());
          } catch (e) {} };
          const f = window.fetch;
          window.fetch = function(input, init) {
            try { pick(typeof input === 'string' ? input : input.url, (init && init.headers) || (input && input.headers)); } catch (e) {}
            return f.apply(this, arguments);
          };
          const open = XMLHttpRequest.prototype.open, set = XMLHttpRequest.prototype.setRequestHeader;
          XMLHttpRequest.prototype.open = function(m, u) { this.__amUrl = u; return open.apply(this, arguments); };
          XMLHttpRequest.prototype.setRequestHeader = function(k, v) {
            if (String(k).toLowerCase() === HEADER) pick(this.__amUrl, { [HEADER]: v });
            return set.apply(this, arguments);
          };
        })();
        """
    }

    private static func jsString(_ s: String) -> String {
        let data = try? JSONSerialization.data(withJSONObject: [s])
        return String(data: data ?? Data("[\"\"]".utf8), encoding: .utf8).map { String($0.dropFirst().dropLast()) } ?? "\"\""
    }

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
        guard let body = message.body as? [String: Any], let value = body["value"] as? String,
              let origin = body["origin"] as? String, let url = body["url"] as? String else { return }
        Task { @MainActor in
            var token = value
            if let strip = self.provider.tokenCapture?.strip {
                token = token.replacingOccurrences(of: strip, with: "", options: [.caseInsensitive, .anchored])
            }
            token = token.trimmingCharacters(in: .whitespaces)
            guard !token.isEmpty, token.count < 8000 else { return }
            self.capturedToken = token
            self.capturedOrigin = origin
            self.capturedURL = url
            self.status = "已捕获登录凭据，可以点「完成连接」。"
        }
    }

    func finish() async -> Bool {
        saving = true
        defer { saving = false }
        var session = ["user_agent": WebProvider.userAgent]
        let cleanLabel = label.trimmingCharacters(in: .whitespacesAndNewlines).prefix(40)
        if !cleanLabel.isEmpty { session["label"] = String(cleanLabel) }
        if let capture = provider.tokenCapture {
            if let token = capturedToken {
                session[capture.field] = token
                // The backend accepts only its own allowlisted hosts / actions for this.
                if let key = capture.urlField { session[key] = key == "origin" ? capturedOrigin : capturedURL }
            } else if capture.required {
                status = "还没有捕获到凭据：登录后打开账户 / 用量页面再试，或在连接窗口手动粘贴。"
                return false
            }
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
    @State private var pastedTokens: [String: String] = [:]
    @State private var manualError: [String: String] = [:]
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
        .themedRoot(store.theme)
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
                // Several fields (an AccessKey pair) are saved together as one session.
                ForEach(p.fields, id: \.field) { f in
                    SecureField(savedKeys.contains(p.id) ? "已保存（输入新值可替换）" : f.placeholder,
                                text: Binding(get: { apiKeys[p.id + "." + f.field] ?? "" }, set: { apiKeys[p.id + "." + f.field] = $0 }))
                        .textFieldStyle(.roundedBorder)
                }
                Button("保存") {
                    var previous = ConnectionManager.shared.session(for: p.id) ?? [:]
                    var session: [String: String] = [:]
                    for f in p.fields {
                        let value = (apiKeys[p.id + "." + f.field] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                        if value.isEmpty {
                            // Optional fields keep their stored value when left blank.
                            if f.optional, let kept = previous[f.field] { session[f.field] = kept; continue }
                            if f.optional { continue }
                            return
                        }
                        guard !value.contains("\n"), value.count < 512 else { return }
                        session[f.field] = value
                    }
                    ConnectionManager.shared.save(p.id, session)
                    for f in p.fields { apiKeys[p.id + "." + f.field] = "" }
                    reload()
                }
                .disabled(p.fields.contains { !$0.optional && (apiKeys[p.id + "." + $0.field] ?? "").trimmingCharacters(in: .whitespaces).isEmpty })
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
        if let manual = p.manual {
            HStack {
                ForEach(manual.fields, id: \.field) { f in
                    SecureField(f.placeholder, text: Binding(get: { pastedTokens[p.id + "." + f.field] ?? "" },
                                                             set: { pastedTokens[p.id + "." + f.field] = $0; manualError[p.id] = nil }))
                        .textFieldStyle(.roundedBorder)
                }
                Button("保存") { saveManual(p, manual, list: list) }
                    .disabled(manual.fields.contains { (pastedTokens[p.id + "." + $0.field] ?? "").trimmingCharacters(in: .whitespaces).isEmpty })
            }
            .controlSize(.small)
            if let error = manualError[p.id] {
                Text(error).font(.system(size: 10.5)).foregroundStyle(.orange).fixedSize(horizontal: false, vertical: true)
            }
        }
        if let help = p.keyHelp {
            Button(help.title) { NSWorkspace.shared.open(help.url) }
                .buttonStyle(.link).font(.system(size: 11))
        }
    }

    /// Typed keys become one more account of this provider.
    private func saveManual(_ p: WebProvider, _ manual: WebProvider.ManualEntry, list: [String]) {
        var session = ["user_agent": WebProvider.userAgent]
        for f in manual.fields {
            var value = pastedTokens[p.id + "." + f.field] ?? ""
            if let strip = manual.strip {
                value = value.replacingOccurrences(of: strip, with: "", options: [.caseInsensitive, .anchored])
            }
            value = value.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !value.isEmpty, !value.contains("\n"), value.count < 8000 else { return }
            if let prefix = f.mustStartWith, !value.uppercased().hasPrefix(prefix) {
                manualError[p.id] = f.wrongPrefixHint
                return
            }
            session[f.field] = value
        }
        let used = Set(list.map(ConnectionManager.order(ofSlot:)))
        guard let n = (1...ConnectionManager.maxAccounts).first(where: { !used.contains($0) }) else { return }
        ConnectionManager.shared.save(n == 1 ? p.id : p.id + "#\(n)", session)
        for f in manual.fields { pastedTokens[p.id + "." + f.field] = "" }
        reload()
    }
}
