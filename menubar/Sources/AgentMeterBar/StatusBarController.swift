import AppKit
import Observation
import SwiftUI

/// The label must not swallow clicks meant for the status item button.
private final class PassthroughHostingView<Content: View>: NSHostingView<Content> {
    override func hitTest(_ point: NSPoint) -> NSView? { nil }
}

/// Stock-board scroll driven by Core Animation: the strip is rendered to an
/// image only when its content changes, and the GPU slides it, so the
/// ticker costs almost no CPU (a per-frame SwiftUI timeline cost ~50%).
private final class MarqueeView: NSView {
    private let strip = CALayer()
    private let fade = CAGradientLayer()
    private var cycle: CGFloat = 0
    private let gap: CGFloat = 18
    private let speed: CGFloat = 24 // points per second

    override init(frame: NSRect) {
        super.init(frame: frame)
        wantsLayer = true
        layer?.masksToBounds = true
        layer?.addSublayer(strip)
        fade.startPoint = CGPoint(x: 0, y: 0.5)
        fade.endPoint = CGPoint(x: 1, y: 0.5)
        layer?.mask = fade
    }

    required init?(coder: NSCoder) { fatalError() }

    override func hitTest(_ point: NSPoint) -> NSView? { nil }

    func show(_ image: NSImage) {
        let w = image.size.width, h = image.size.height
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        fade.frame = bounds
        let y = (bounds.height - h) / 2
        if w <= bounds.width {
            strip.removeAllAnimations()
            cycle = 0
            strip.contents = image
            strip.frame = CGRect(x: 0, y: y, width: w, height: h)
            fade.colors = [NSColor.black.cgColor, NSColor.black.cgColor]
            CATransaction.commit()
            return
        }
        // Two copies side by side; sliding by one copy + gap loops seamlessly.
        let doubled = NSImage(size: NSSize(width: w * 2 + gap, height: h), flipped: false) { _ in
            image.draw(at: .zero, from: .zero, operation: .sourceOver, fraction: 1)
            image.draw(at: NSPoint(x: w + self.gap, y: 0), from: .zero, operation: .sourceOver, fraction: 1)
            return true
        }
        strip.contents = doubled
        strip.anchorPoint = .zero
        strip.bounds = CGRect(x: 0, y: 0, width: doubled.size.width, height: h)
        strip.position = CGPoint(x: 0, y: y)
        let edge = 8 / max(bounds.width, 1)
        fade.colors = [NSColor.clear.cgColor, NSColor.black.cgColor, NSColor.black.cgColor, NSColor.clear.cgColor]
        fade.locations = [0, NSNumber(value: Double(edge)), NSNumber(value: Double(1 - edge)), 1]
        CATransaction.commit()

        // Keep the running animation when only the text changed, to avoid a jump.
        let newCycle = w + gap
        guard newCycle != cycle || strip.animation(forKey: "scroll") == nil else { return }
        cycle = newCycle
        let anim = CABasicAnimation(keyPath: "position.x")
        anim.fromValue = 0
        anim.toValue = -newCycle
        anim.duration = Double(newCycle / speed)
        anim.repeatCount = .infinity
        anim.timingFunction = CAMediaTimingFunction(name: .linear)
        strip.add(anim, forKey: "scroll")
    }
}

/// AppKit status item so the label can animate (MenuBarExtra labels are
/// static snapshots), with the SwiftUI panel in a popover.
@MainActor
final class StatusBarController: NSObject {
    static let shared = StatusBarController()

    private var item: NSStatusItem?
    private var label: NSView?
    private var marquee: MarqueeView?
    private var marqueeActive = false
    private var lastRender: [TickerItem] = []
    private var lastDark: Bool?
    private let popover = NSPopover()
    private let store = UsageStore.shared

    func install(store: UsageStore) {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        self.item = item
        guard let button = item.button else { return }
        button.target = self
        button.action = #selector(toggle(_:))

        let label = PassthroughHostingView(rootView: StatusLabel(store: store) { [weak self] width in
            guard let self, !self.marqueeActive else { return }
            self.item?.length = ceil(width)
        })
        // Pinned only at the leading edge: item.length alone sets the width,
        // otherwise the hidden label's intrinsic size squeezes the marquee.
        label.translatesAutoresizingMaskIntoConstraints = false
        button.addSubview(label)
        NSLayoutConstraint.activate([
            label.leadingAnchor.constraint(equalTo: button.leadingAnchor),
            label.centerYAnchor.constraint(equalTo: button.centerYAnchor),
        ])
        self.label = label

        let marquee = MarqueeView(frame: .zero)
        marquee.isHidden = true
        button.addSubview(marquee)
        self.marquee = marquee

        let controller = NSHostingController(rootView: PanelView().environment(store))
        controller.sizingOptions = .preferredContentSize
        popover.contentViewController = controller
        popover.behavior = .transient
        popover.animates = true

        observe()
    }

    /// Re-renders whenever the store values read in `render()` change.
    private func observe() {
        withObservationTracking { render() } onChange: {
            DispatchQueue.main.async { [weak self] in self?.observe() }
        }
    }

    private func render() {
        let items = store.tickerItems()
        let width = store.tickerWidth.points
        let useMarquee = store.menuBarMode == .ticker && !items.isEmpty
        marqueeActive = useMarquee
        label?.isHidden = useMarquee
        marquee?.isHidden = !useMarquee
        guard useMarquee, let item, let button = item.button, let marquee else {
            lastRender = []
            return
        }
        item.length = width + 12
        marquee.frame = NSRect(x: 6, y: 0, width: width, height: button.bounds.height > 0 ? button.bounds.height : 22)
        let dark = button.effectiveAppearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
        guard items != lastRender || dark != lastDark else { return }
        lastRender = items
        lastDark = dark
        let strip = HStack(spacing: 18) { ForEach(items) { TickerCell(item: $0) } }
            .environment(\.colorScheme, dark ? .dark : .light)
        let renderer = ImageRenderer(content: strip)
        renderer.scale = button.window?.backingScaleFactor ?? 2
        if let image = renderer.nsImage { marquee.show(image) }
    }

    @objc private func toggle(_ sender: Any?) {
        if popover.isShown { popover.performClose(sender) } else { showPanel() }
    }

    func closePanel() {
        if popover.isShown { popover.performClose(nil) }
    }

    func showPanel() {
        guard let button = item?.button, !popover.isShown else { return }
        UsageStore.shared.panelOpened()
        NSApp.activate(ignoringOtherApps: true)
        popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
        popover.contentViewController?.view.window?.makeKey()
    }
}
