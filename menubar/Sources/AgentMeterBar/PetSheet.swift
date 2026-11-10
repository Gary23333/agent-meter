import AppKit
import WebKit

/// `AgentMeterBar --pet-sheet <pack-id> <out.png>`: renders a pack's contact sheet (every state, expression and
/// theme) with the real WebKit engine and the real `agentpet://` loader, then exits. The same page opens in any
/// browser through `pets/tools/serve.py`; this route needs neither a server nor a browser.
@MainActor
enum PetSheetRunner {
    private static var window: NSWindow?
    private static var web: WKWebView?
    private static var output = ""

    private static func outPath(for view: WKWebView) -> String { output }

    static func run(pack: String, outPath: String, arguments: String = "") {
        guard PetResources.validID(pack) || pack.split(separator: ",").allSatisfy({ PetResources.validID(String($0)) }) else {
            fail("无效的形象 id：\(pack)", code: 64)
        }
        let config = WKWebViewConfiguration()
        config.setURLSchemeHandler(PetSchemeHandler(), forURLScheme: PetResources.scheme)
        config.websiteDataStore = .nonPersistent()
        let size = NSSize(width: 1500, height: 900)
        let view = WKWebView(frame: NSRect(origin: .zero, size: size), configuration: config)
        let window = NSWindow(contentRect: NSRect(x: -10000, y: -10000, width: size.width, height: size.height),
                              styleMask: [.borderless], backing: .buffered, defer: false)
        window.contentView = view
        window.orderFrontRegardless()
        Self.window = window
        Self.web = view
        Self.output = outPath
        var components = URLComponents(string: "\(PetResources.scheme)://\(PetResources.host)/runtime/sheet.html")!
        components.queryItems = [URLQueryItem(name: "pack", value: pack),
                                 URLQueryItem(name: "packRoot", value: "\(PetResources.scheme)://\(PetResources.host)/pack/")]
        for pair in arguments.split(separator: "&") {
            let kv = pair.split(separator: "=", maxSplits: 1).map(String.init)
            if kv.count == 2 { components.queryItems?.append(URLQueryItem(name: kv[0], value: kv[1])) }
        }
        guard let url = components.url else { fail("无法构造联系表地址", code: 70) }
        view.load(URLRequest(url: url))

        poll(view, waited: 0)
    }

    /// Checks twice a second whether the page finished drawing (or failed), for at most 40 seconds.
    private static func poll(_ view: WKWebView, waited: Double) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            MainActor.assumeIsolated {
                view.evaluateJavaScript("document.body.dataset.error ? 'ERR:' + document.body.dataset.error : (document.body.dataset.ready === '1' ? 'READY' : '')") { result, _ in
                    MainActor.assumeIsolated {
                        let state = result as? String ?? ""
                        if state.hasPrefix("ERR:") {
                            fail("联系表出错：\(state.dropFirst(4))", code: 1)
                        } else if state == "READY" {
                            save(from: view, to: outPath(for: view))
                        } else if waited >= 40 {
                            fail("联系表超时（WebGL 不可用或资源缺失）", code: 2)
                        } else {
                            poll(view, waited: waited + 0.5)
                        }
                    }
                }
            }
        }
    }

    private static func save(from view: WKWebView, to path: String) {
        view.evaluateJavaScript("window.__sheetPNG(0)") { result, error in
            MainActor.assumeIsolated {
                guard let dataURL = result as? String, let comma = dataURL.firstIndex(of: ","),
                      let png = Data(base64Encoded: String(dataURL[dataURL.index(after: comma)...])) else {
                    fail("无法读取联系表图像：\(error.map(String.init(describing:)) ?? "empty")", code: 3)
                }
                do {
                    try FileManager.default.createDirectory(at: URL(fileURLWithPath: path).deletingLastPathComponent(), withIntermediateDirectories: true)
                    try png.write(to: URL(fileURLWithPath: path))
                } catch {
                    fail("写入失败：\(error.localizedDescription)", code: 73)
                }
                print(path)
                exit(0)
            }
        }
    }

    private static func fail(_ message: String, code: Int32) -> Never {
        FileHandle.standardError.write(Data((message + "\n").utf8))
        exit(code)
    }
}
