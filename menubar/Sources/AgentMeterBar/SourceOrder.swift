import AppKit
import SwiftUI

/// Window for reordering account cards (also used by the ticker and gauges).
@MainActor
enum SourceOrderWindow {
    private static var window: NSWindow?

    static func show() {
        if window == nil {
            let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 380, height: 520),
                             styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
            w.title = "调整卡片顺序"
            w.isReleasedWhenClosed = false
            w.contentView = NSHostingView(rootView: SourceOrderView().environment(UsageStore.shared))
            w.center()
            window = w
        }
        StatusBarController.shared.closePanel()
        NSApp.activate(ignoringOtherApps: true)
        window?.makeKeyAndOrderFront(nil)
    }
}

struct SourceOrderView: View {
    @Environment(UsageStore.self) private var store
    @State private var ids: [String] = []

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("拖动或用箭头调整顺序。账户卡片、顶部仪表、菜单栏行情和提醒都按这个顺序排列。")
                .font(.system(size: 11.5)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            List {
                ForEach(Array(ids.enumerated()), id: \.element) { index, id in
                    row(id, index: index)
                }
                .onMove { from, to in
                    ids.move(fromOffsets: from, toOffset: to)
                    store.setSourceOrder(ids)
                }
            }
            .listStyle(.inset(alternatesRowBackgrounds: true))
            HStack {
                Button("恢复默认") {
                    store.setSourceOrder(nil)
                    reload()
                }
                Spacer()
                Text("共 \(ids.count) 项").font(.system(size: 11)).foregroundStyle(.tertiary)
            }
        }
        .padding(14)
        .frame(minWidth: 340, minHeight: 420)
        .onAppear(perform: reload)
        .onChange(of: store.snapshot?.collectedAt) { _, _ in reload() }
    }

    /// Every source except CC Switch (local history has its own tab), in the current order.
    private func reload() {
        guard let snapshot = store.snapshot else { return }
        ids = snapshot.sources.filter { !$0.isLocalHistory }
            .sorted { Catalog.rank($0.id) < Catalog.rank($1.id) }
            .map(\.id)
    }

    private func row(_ id: String, index: Int) -> some View {
        let source = store.snapshot?.sources.first { $0.id == id }
        return HStack(spacing: 10) {
            Image(systemName: "line.3.horizontal").foregroundStyle(.tertiary)
            BrandBadge(brand: Catalog.brand(id), size: 20,
                       icon: AppLauncher.icon(for: ConnectionManager.provider(ofSlot: id), in: store.snapshot))
            VStack(alignment: .leading, spacing: 1) {
                Text(source?.displayName ?? Catalog.brand(id).name).font(.system(size: 12.5, weight: .medium))
                if let s = source, !s.hasAccountData {
                    Text("未接入 · " + Catalog.reason(s.reason)).font(.system(size: 10)).foregroundStyle(.tertiary).lineLimit(1)
                }
            }
            Spacer()
            Button { move(index, by: -1) } label: { Image(systemName: "chevron.up") }
                .buttonStyle(.borderless).disabled(index == 0)
            Button { move(index, by: 1) } label: { Image(systemName: "chevron.down") }
                .buttonStyle(.borderless).disabled(index == ids.count - 1)
        }
        .padding(.vertical, 3)
    }

    private func move(_ index: Int, by delta: Int) {
        let target = index + delta
        guard ids.indices.contains(target) else { return }
        ids.swapAt(index, target)
        store.setSourceOrder(ids)
    }
}
