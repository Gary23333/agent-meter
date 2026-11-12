import AppKit
import Observation
import WebKit

/// Pictures for the gallery in the 桌宠 tab, drawn by the pet's own runtime: each pack is loaded (one at a time) in
/// an off-screen web view in `still` mode, which draws the pet content and healthy in a single pass and leaves the
/// picture in `window.__petStill`. (A window that is not on screen gets no animation frames, so nothing here waits
/// for one.) Because the runtime draws them, they always match the pack on disk (self-made ones included) and the
/// current panel style, and no preview image has to be stored or kept in sync by hand.
@MainActor @Observable
final class PetThumbnails: NSObject {
    static let shared = PetThumbnails()

    private(set) var images: [String: NSImage] = [:]
    private(set) var failed: Set<String> = []
    private(set) var busy = false

    @ObservationIgnored private var theme = ""
    @ObservationIgnored private var scheme = ""
    @ObservationIgnored private var queue: [PetResources.Pack] = []
    /// Bumped when the look changes: work that started under an older look is thrown away.
    @ObservationIgnored private var generation = 0
    @ObservationIgnored private var window: NSWindow?
    @ObservationIgnored private var web: WKWebView?

    /// Asks for thumbnails of `packs` in the given panel style. Cheap to call repeatedly.
    func ensure(_ packs: [PetResources.Pack], theme: String, scheme: String) {
        if theme != self.theme || scheme != self.scheme {
            self.theme = theme
            self.scheme = scheme
            images = [:]
            failed = []
            queue = []
            generation += 1
        }
        for pack in packs where images[pack.id] == nil && !failed.contains(pack.id) && !queue.contains(where: { $0.id == pack.id }) {
            queue.append(pack)
        }
        if !busy { next() }
    }

    /// True once every pack has a thumbnail (or a recorded failure) in this panel style.
    func isComplete(for packs: [PetResources.Pack], theme: String, scheme: String) -> Bool {
        self.theme == theme && self.scheme == scheme && !busy && queue.isEmpty
            && packs.allSatisfy { images[$0.id] != nil || failed.contains($0.id) }
    }

    private func next() {
        guard !queue.isEmpty else { finish(); return }
        busy = true
        let pack = queue.removeFirst()
        let generation = generation
        guard let url = PetPage.url(pack: pack.id, theme: theme, scheme: scheme, hud: "off", mode: .still) else {
            failed.insert(pack.id)
            next()
            return
        }
        loadedWeb(size: pack.stage).load(URLRequest(url: url))
        poll(pack, generation: generation, waited: 0)
    }

    /// Twice a second: has the page settled (or failed)? Gives up after ten seconds.
    private func poll(_ pack: PetResources.Pack, generation: Int, waited: Double) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) { [weak self] in
            MainActor.assumeIsolated {
                guard let self else { return }
                guard generation == self.generation, let web = self.web else { self.next(); return }
                web.evaluateJavaScript("document.body.dataset.error ? 'E' : (document.body.dataset.settled === '1' ? 'R' : '')") { result, _ in
                    MainActor.assumeIsolated {
                        guard generation == self.generation else { self.next(); return }
                        switch result as? String ?? "" {
                        case "R": self.collect(pack, generation: generation)
                        case "E": self.fail(pack)
                        default:
                            if waited >= 10 { self.fail(pack) } else { self.poll(pack, generation: generation, waited: waited + 0.25) }
                        }
                    }
                }
            }
        }
    }

    private func collect(_ pack: PetResources.Pack, generation: Int) {
        web?.evaluateJavaScript("window.__petStill || ''") { [weak self] result, _ in
            MainActor.assumeIsolated {
                guard let self else { return }
                if generation == self.generation {
                    if let image = Self.image(fromDataURL: result as? String ?? "") { self.images[pack.id] = image } else { self.failed.insert(pack.id) }
                }
                self.next()
            }
        }
    }

    /// The PNG the page draws, which arrives as a `data:` URL.
    static func image(fromDataURL url: String) -> NSImage? {
        let prefix = "data:image/png;base64,"
        guard url.hasPrefix(prefix), url.count < 8_000_000, let data = Data(base64Encoded: String(url.dropFirst(prefix.count))) else { return nil }
        return NSImage(data: data)
    }

    /// Cuts the transparent margins off a stage capture so the pet itself fills the picture (share card).
    static func trimmed(_ image: NSImage) -> NSImage? {
        guard let tiff = image.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff),
              rep.pixelsWide > 0, rep.pixelsHigh > 0, let samples = rep.bitmapData else { return nil }
        let w = rep.pixelsWide, h = rep.pixelsHigh, row = rep.bytesPerRow, spp = rep.samplesPerPixel
        guard spp >= 4, rep.bitsPerPixel == 8 * spp, !rep.isPlanar else { return nil }
        let alpha = rep.bitmapFormat.contains(.alphaFirst) ? 0 : 3
        var minX = w, minY = h, maxX = -1, maxY = -1
        for y in 0..<h {
            for x in 0..<w where samples[y * row + x * spp + alpha] > 8 {
                if x < minX { minX = x }
                if x > maxX { maxX = x }
                if y < minY { minY = y }
                if y > maxY { maxY = y }
            }
        }
        guard maxX >= minX, maxY >= minY else { return nil }
        let crop = CGRect(x: minX, y: minY, width: maxX - minX + 1, height: maxY - minY + 1)
        guard let cg = rep.cgImage?.cropping(to: crop) else { return nil }
        let out = NSImage(cgImage: cg, size: NSSize(width: crop.width, height: crop.height))
        return out
    }

    private func fail(_ pack: PetResources.Pack) {
        failed.insert(pack.id)
        next()
    }

    // MARK: The off-screen page

    private func loadedWeb(size: CGSize) -> WKWebView {
        if let web, let window {
            window.setContentSize(size)
            web.frame = NSRect(origin: .zero, size: size)
            return web
        }
        let config = WKWebViewConfiguration()
        config.setURLSchemeHandler(PetSchemeHandler(), forURLScheme: PetResources.scheme)
        config.websiteDataStore = .nonPersistent()
        let view = WKWebView(frame: NSRect(origin: .zero, size: size), configuration: config)
        view.setValue(false, forKey: "drawsBackground")
        view.underPageBackgroundColor = .clear
        let window = NSWindow(contentRect: NSRect(x: -10000, y: -10000, width: size.width, height: size.height),
                              styleMask: [.borderless], backing: .buffered, defer: false)
        window.isOpaque = false
        window.backgroundColor = .clear
        window.hasShadow = false
        window.isReleasedWhenClosed = false
        window.contentView = view
        window.orderFrontRegardless()
        self.window = window
        web = view
        return view
    }

    /// Nothing left to draw: release the web view and its GPU memory until the next time.
    private func finish() {
        busy = false
        web?.stopLoading()
        window?.orderOut(nil)
        window?.contentView = nil
        web = nil
        window = nil
    }
}
