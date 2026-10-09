import AppKit
import SwiftUI

/// Opens the desktop app behind a source (from the backend's app discovery),
/// or its website when it has no app (即梦 CLI, DeepSeek API).
@MainActor
enum AppLauncher {
    struct Target: Identifiable {
        let id: String
        let name: String
        let path: String?
        let url: URL?
    }

    private static let websites: [String: (String, String)] = [
        "dreamina": ("即梦网页", "https://jimeng.jianying.com/"),
        "deepseek_api": ("DeepSeek 开放平台", "https://platform.deepseek.com/usage"),
    ]

    static func targets(for sourceID: String, in snapshot: Snapshot?) -> [Target] {
        let apps = (snapshot?.apps(for: sourceID) ?? []).map {
            Target(id: $0.path ?? $0.name, name: $0.name, path: $0.path, url: nil)
        }
        if !apps.isEmpty { return apps }
        if let (name, link) = websites[sourceID], let url = URL(string: link) {
            return [Target(id: link, name: name, path: nil, url: url)]
        }
        return []
    }

    static func open(_ target: Target) {
        if let path = target.path {
            let config = NSWorkspace.OpenConfiguration()
            config.activates = true
            NSWorkspace.shared.openApplication(at: URL(fileURLWithPath: path), configuration: config)
        } else if let url = target.url {
            NSWorkspace.shared.open(url)
        }
        StatusBarController.shared.closePanel()
    }

    private static var iconCache: [String: NSImage] = [:]

    /// The real app icon for a source, when one is installed.
    static func icon(for sourceID: String, in snapshot: Snapshot?) -> NSImage? {
        guard let path = snapshot?.apps(for: sourceID).first?.path else { return nil }
        return icon(atPath: path)
    }

    static func icon(atPath path: String) -> NSImage {
        if let cached = iconCache[path] { return cached }
        let image = NSWorkspace.shared.icon(forFile: path)
        iconCache[path] = image
        return image
    }
}

/// "打开" capsule; becomes a menu when a source has several apps.
struct OpenAppButton: View {
    let sourceID: String
    let snapshot: Snapshot?
    var compact = false
    @State private var hovering = false
    @Environment(\.panelTheme) private var theme

    var body: some View {
        let targets = AppLauncher.targets(for: sourceID, in: snapshot)
        if !targets.isEmpty {
            Button {
                if targets.count == 1 { AppLauncher.open(targets[0]) } else { AppMenu.show(targets) }
            } label: { label(web: targets[0].path == nil, multiple: targets.count > 1) }
                .buttonStyle(.plain)
                .help(targets.count == 1 ? "打开 " + targets[0].name : "选择要打开的应用")
        }
    }

    private func label(web: Bool, multiple: Bool) -> some View {
        let tint = theme == .neon ? Neon.cyan : theme.tint(Catalog.brand(sourceID).tint)
        let base = HStack(spacing: 3) {
            Image(systemName: web ? "safari" : "arrow.up.forward.app")
                .font(.system(size: 10, weight: .bold))
            if !compact { Text("打开").font(.system(size: 10.5, weight: .semibold)) }
            if multiple { Image(systemName: "chevron.down").font(.system(size: 7, weight: .heavy)) }
        }
        .padding(.horizontal, compact ? 6 : 8)
        .padding(.vertical, 4)
        .onHover { h in withAnimation(.easeOut(duration: 0.15)) { hovering = h } }
        return Group {
            switch theme {
            case .minimal:
                // Text link: underline on hover instead of a filled capsule.
                base.foregroundStyle(hovering ? AnyShapeStyle(.primary) : AnyShapeStyle(.secondary))
                    .overlay(alignment: .bottom) { Rectangle().fill(Color.primary.opacity(hovering ? 0.6 : 0)).frame(height: 0.5).padding(.horizontal, 6) }
            case .native:
                base.foregroundStyle(hovering ? .white : tint)
                    .background(Capsule().fill(hovering ? tint : tint.opacity(0.12)))
            case .aurora, .neon:
                base.foregroundStyle(hovering ? (theme == .neon ? .black : .white) : tint)
                    .background(Capsule().fill(hovering ? AnyShapeStyle(tint.gradient) : AnyShapeStyle(tint.opacity(0.14))))
                    .overlay(Capsule().strokeBorder(tint.opacity(theme == .neon ? 0.8 : 0.35), lineWidth: theme == .neon ? 1 : 0.6))
                    .themeGlow(tint.opacity(hovering ? 0.5 : (theme == .neon ? 0.3 : 0)), radius: 6, theme: theme)
            }
        }
    }
}


/// Native pop-up menu for sources with several apps (Qoder CN / Qoder CN IDE);
/// a SwiftUI Menu would drop the capsule styling of the label.
@MainActor
private enum AppMenu {
    private final class Item: NSMenuItem {
        var target_: AppLauncher.Target?
        @MainActor @objc func fire() { if let t = target_ { AppLauncher.open(t) } }
    }

    static func show(_ targets: [AppLauncher.Target]) {
        let menu = NSMenu()
        for t in targets {
            let item = Item(title: "打开 " + t.name, action: #selector(Item.fire), keyEquivalent: "")
            item.target = item
            item.target_ = t
            if let path = t.path {
                let icon = AppLauncher.icon(atPath: path).copy() as! NSImage
                icon.size = NSSize(width: 16, height: 16)
                item.image = icon
            }
            menu.addItem(item)
        }
        menu.popUp(positioning: nil, at: NSEvent.mouseLocation, in: nil)
    }
}
