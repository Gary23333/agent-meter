import AppKit
import SwiftUI

/// Local price-table editor: per-1M-token prices for API-equivalent cost
/// estimates of the local token history. Prices are estimates, never bills.
@MainActor
enum PricesWindow {
    private static var window: NSWindow?

    static func show() {
        if window == nil {
            let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 520, height: 560),
                             styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
            w.title = "API 价格表（本机估算）"
            w.isReleasedWhenClosed = false
            w.contentView = NSHostingView(rootView: PricesView().environment(UsageStore.shared))
            w.center()
            window = w
        }
        StatusBarController.shared.closePanel()
        NSApp.activate(ignoringOtherApps: true)
        window?.makeKeyAndOrderFront(nil)
    }
}

struct PriceRow: Identifiable {
    var id: String          // pattern
    var input: String
    var cacheRead: String
    var cacheWrite: String
    var output: String
    var converted: Bool
}

struct PricesView: View {
    @Environment(UsageStore.self) private var store
    @State private var currency = "USD"
    @State private var rows: [PriceRow] = []
    @State private var message: String?
    @State private var loading = true

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("按每百万 tokens 计价，用于估算本机各来源的 API 等价费用（不是订阅账单）。内置默认价来自 2026-10-09 摸排，可修改；CNY 中标注「折算」的默认值按 7.25 汇率换算。")
                .font(.system(size: 11)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            HStack {
                Picker("币种", selection: $currency) {
                    Text("美元 USD").tag("USD"); Text("人民币 CNY").tag("CNY")
                }
                .pickerStyle(.segmented).frame(width: 200)
                .onChange(of: currency) { _, _ in Task { await load() } }
                Spacer()
                Button("从当前统计补模型") { addMissingFromSnapshot() }
                Button("保存") { Task { await save() } }.buttonStyle(.borderedProminent)
            }
            .controlSize(.small)
            if loading {
                Spacer(); HStack { Spacer(); ProgressView(); Spacer() }; Spacer()
            } else {
                tableHeader
                List {
                    ForEach($rows) { $row in
                        HStack(spacing: 6) {
                            TextField("模型名或片段", text: $row.id).textFieldStyle(.roundedBorder)
                                .frame(width: 168)
                            if row.converted { Text("折算").font(.system(size: 9)).foregroundStyle(.orange) }
                            numField("输入", $row.input)
                            numField("缓存读", $row.cacheRead)
                            numField("缓存写", $row.cacheWrite)
                            numField("输出", $row.output)
                            Button { rows.removeAll { $0.id == row.id } } label: { Image(systemName: "minus.circle") }
                                .buttonStyle(.borderless).foregroundStyle(.red)
                        }
                    }
                }
                .listStyle(.plain)
                HStack {
                    Button("添加一行") { rows.append(PriceRow(id: "", input: "", cacheRead: "", cacheWrite: "", output: "", converted: false)) }
                    Spacer()
                    Text("共 \(rows.count) 条").font(.system(size: 10)).foregroundStyle(.tertiary)
                    if let message { Text(message).font(.system(size: 10.5)).foregroundStyle(.blue) }
                }
                .controlSize(.small)
            }
        }
        .padding(14)
        .frame(minWidth: 560, minHeight: 420)
        .task { await load() }
    }

    private var tableHeader: some View {
        HStack(spacing: 6) {
            Text("模型匹配片段").frame(width: 172, alignment: .leading)
            Text("输入").frame(width: 58, alignment: .leading)
            Text("缓存读").frame(width: 58, alignment: .leading)
            Text("缓存写").frame(width: 58, alignment: .leading)
            Text("输出").frame(width: 58, alignment: .leading)
        }
        .font(.system(size: 10, weight: .semibold)).foregroundStyle(.secondary)
        .padding(.horizontal, 6)
    }

    private func numField(_ hint: String, _ binding: Binding<String>) -> some View {
        TextField(hint, text: binding).textFieldStyle(.roundedBorder).frame(width: 62)
    }

    private func load() async {
        loading = true
        defer { loading = false }
        guard let client = store.backendClient else { message = "后端未连接"; return }
        do {
            let json = try await client.getPrices()
            currency = json["currency"].string ?? "USD"
            let converted = Set(json["converted_patterns"].array.compactMap(\.string))
            rows = json["models"].object.keys.sorted().map { pattern in
                let p = json["models"][pattern]
                return PriceRow(id: pattern,
                                input: p["input"].double.map { Fmt.trim($0) } ?? "0",
                                cacheRead: p["cache_read"].double.map { Fmt.trim($0) } ?? "0",
                                cacheWrite: p["cache_write"].double.map { Fmt.trim($0) } ?? "0",
                                output: p["output"].double.map { Fmt.trim($0) } ?? "0",
                                converted: converted.contains(pattern))
            }
            message = nil
        } catch { message = "读取失败：\(error.localizedDescription)" }
    }

    /// Short names of models seen in the snapshot that match no existing row.
    private func addMissingFromSnapshot() {
        guard let snapshot = store.snapshot else { return }
        var seen = Set(rows.map(\.id))
        var names = Set<String>()
        for source in snapshot.sources {
            guard let value = source.metric("tokens")?.value else { continue }
            for group in value["periods"]["all"]["groups"].array {
                guard let full = group["model"].string else { continue }
                let short = full.split(separator: "/").last.map(String.init) ?? full
                if short.isEmpty || short == "unknown" || names.contains(short) { continue }
                names.insert(short)
                if !rows.contains(where: { row in short.lowercased().contains(row.id.lowercased()) && !row.id.isEmpty }) {
                    if !seen.contains(short) {
                        rows.append(PriceRow(id: short, input: "", cacheRead: "", cacheWrite: "", output: "", converted: false))
                        seen.insert(short)
                    }
                }
            }
        }
    }

    private func save() async {
        guard let client = store.backendClient else { message = "后端未连接"; return }
        var models: [String: [String: Double]] = [:]
        for row in rows {
            let pattern = row.id.trimmingCharacters(in: .whitespaces)
            guard !pattern.isEmpty else { continue }
            func num(_ s: String) -> Double { Double(s.replacingOccurrences(of: ",", with: ".")) ?? 0 }
            models[pattern] = ["input": num(row.input), "cache_read": num(row.cacheRead),
                               "cache_write": num(row.cacheWrite), "output": num(row.output)]
        }
        do {
            _ = try await client.putPrices(currency: currency, models: models)
            message = "已保存，正在重新估算"
            await store.fetch(force: true)
        } catch { message = "保存失败：\(error.localizedDescription)" }
    }
}
