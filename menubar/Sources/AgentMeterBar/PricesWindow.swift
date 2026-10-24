import AppKit
import SwiftUI

/// Model catalogue, local price overrides and preview-model price bindings.
/// Every result remains an API-equivalent estimate, never a subscription bill.
@MainActor
enum PricesWindow {
    private static var window: NSWindow?

    static func show() {
        if window == nil {
            let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 760, height: 650),
                             styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
            w.title = "模型与计费"
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
    var id: String
    var input: String
    var cacheRead: String
    var cacheWrite: String
    var output: String
    var converted: Bool
    var synced = false
}

struct ModelBindingRow: Identifiable {
    var id: String
    var target: String
}

struct PricesView: View {
    @Environment(UsageStore.self) private var store
    @State private var currency = "USD"
    @State private var rows: [PriceRow] = []
    @State private var bindings: [ModelBindingRow] = []
    @State private var message: String?
    @State private var syncMessage: String?
    @State private var loading = true
    @State private var syncing = false
    @State private var section = 0

    private var pricedTargets: [String] { rows.map(\.id).filter { !$0.isEmpty }.sorted() }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            header
            Picker("", selection: $section) {
                Text("模型价格").tag(0)
                Text("体验期绑定 \(bindings.isEmpty ? "" : "· \(bindings.count)")").tag(1)
            }
            .pickerStyle(.segmented)
            if loading {
                Spacer(); HStack { Spacer(); ProgressView(); Spacer() }; Spacer()
            } else if section == 0 {
                prices
            } else {
                bindingEditor
            }
            footer
        }
        .padding(16)
        .frame(minWidth: 720, minHeight: 560)
        .task { await load() }
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text("模型目录与 API 等价估算")
                    .font(.system(size: 17, weight: .semibold, design: .rounded))
                Text("自动更新公开模型名称和刊例价；个人修改与绑定独立保存。体验期模型没有价格时保持未计价，不按免费处理。")
                    .font(.system(size: 11)).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer()
            Button {
                Task { await sync() }
            } label: {
                Label(syncing ? "同步中…" : "立即同步", systemImage: "arrow.triangle.2.circlepath")
            }
            .disabled(syncing)
        }
    }

    private var prices: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Picker("币种", selection: $currency) {
                    Text("美元 USD").tag("USD"); Text("人民币 CNY").tag("CNY")
                }
                .pickerStyle(.segmented).frame(width: 210)
                .onChange(of: currency) { _, _ in Task { await load() } }
                Spacer()
                Button("添加自定义价格") {
                    rows.insert(PriceRow(id: "", input: "", cacheRead: "", cacheWrite: "", output: "", converted: false), at: 0)
                }
                Button("保存修改") { Task { await save() } }.buttonStyle(.borderedProminent)
            }
            .controlSize(.small)
            tableHeader
            List {
                ForEach($rows) { $row in
                    HStack(spacing: 7) {
                        VStack(alignment: .leading, spacing: 2) {
                            TextField("模型 ID 或匹配片段", text: $row.id).textFieldStyle(.roundedBorder)
                            HStack(spacing: 4) {
                                if row.synced { Label("目录", systemImage: "icloud") }
                                if row.converted { Text("折算") }
                            }
                            .font(.system(size: 8.5)).foregroundStyle(.secondary)
                        }
                        .frame(width: 205, alignment: .leading)
                        numField("输入", $row.input)
                        numField("缓存读", $row.cacheRead)
                        numField("缓存写", $row.cacheWrite)
                        numField("输出", $row.output)
                        Button { rows.removeAll { $0.id == row.id } } label: { Image(systemName: "minus.circle") }
                            .buttonStyle(.borderless).foregroundStyle(.red)
                            .help("从个人价格表移除；内置或目录条目会在下次同步后恢复")
                    }
                }
            }
            .listStyle(.plain)
        }
    }

    private var bindingEditor: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 10) {
                Label("把超前体验期或内部代号绑定到现有模型，沿用其四项 token 单价。绑定关系会标记在估算结果中，方便之后替换为正式价格。", systemImage: "link")
                    .font(.system(size: 11)).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer()
                Button("从当前统计补未定价模型") { addMissingFromSnapshot() }
                Button("添加绑定") { bindings.append(ModelBindingRow(id: "", target: "")) }
            }
            .controlSize(.small)
            HStack {
                Text("未定价模型 / 内部代号").frame(maxWidth: .infinity, alignment: .leading)
                Text("按此模型计费").frame(width: 260, alignment: .leading)
                Color.clear.frame(width: 20)
            }
            .font(.system(size: 10, weight: .semibold)).foregroundStyle(.secondary)
            List {
                if bindings.isEmpty {
                    ContentUnavailableView("没有绑定", systemImage: "link.circle",
                                           description: Text("可从当前统计一键补入未定价模型。"))
                }
                ForEach($bindings) { $binding in
                    HStack(spacing: 12) {
                        TextField("例如 kimi-k3.1-pro-preview", text: $binding.id)
                            .textFieldStyle(.roundedBorder)
                        Image(systemName: "arrow.right").foregroundStyle(.tertiary)
                        Picker("计费模型", selection: $binding.target) {
                            Text("请选择").tag("")
                            ForEach(pricedTargets, id: \.self) { Text($0).tag($0) }
                        }
                        .labelsHidden().frame(width: 260)
                        Button { bindings.removeAll { $0.id == binding.id } } label: { Image(systemName: "minus.circle") }
                            .buttonStyle(.borderless).foregroundStyle(.red)
                    }
                }
            }
            .listStyle(.plain)
            Button("保存绑定") { Task { await save() } }.buttonStyle(.borderedProminent)
        }
    }

    private var footer: some View {
        HStack(spacing: 8) {
            if let syncMessage { Text(syncMessage).foregroundStyle(.secondary) }
            if let message { Text(message).foregroundStyle(.blue) }
            Spacer()
            Text("每百万 tokens · 不是订阅账单").font(.system(size: 10)).foregroundStyle(.tertiary)
        }
        .font(.system(size: 10.5))
        .frame(minHeight: 18)
    }

    private var tableHeader: some View {
        HStack(spacing: 7) {
            Text("模型 ID / 匹配片段").frame(width: 205, alignment: .leading)
            Text("输入").frame(width: 72, alignment: .leading)
            Text("缓存读").frame(width: 72, alignment: .leading)
            Text("缓存写").frame(width: 72, alignment: .leading)
            Text("输出").frame(width: 72, alignment: .leading)
            Color.clear.frame(width: 20)
        }
        .font(.system(size: 10, weight: .semibold)).foregroundStyle(.secondary)
        .padding(.horizontal, 6)
    }

    private func numField(_ hint: String, _ binding: Binding<String>) -> some View {
        TextField(hint, text: binding).textFieldStyle(.roundedBorder).frame(width: 72)
    }

    private func load() async {
        loading = true
        defer { loading = false }
        guard let client = store.backendClient else { message = "后端未连接"; return }
        do {
            let json = try await client.getPrices()
            currency = json["currency"].string ?? "USD"
            let converted = Set(json["converted_patterns"].array.compactMap(\.string))
            let catalog = json["catalog"].object
            rows = json["models"].object.keys.sorted().map { pattern in
                let p = json["models"][pattern]
                return PriceRow(id: pattern,
                                input: p["input"].double.map { Fmt.trim($0) } ?? "0",
                                cacheRead: p["cache_read"].double.map { Fmt.trim($0) } ?? "0",
                                cacheWrite: p["cache_write"].double.map { Fmt.trim($0) } ?? "0",
                                output: p["output"].double.map { Fmt.trim($0) } ?? "0",
                                converted: converted.contains(pattern), synced: catalog[pattern] != nil)
            }
            bindings = json["aliases"].object.map { ModelBindingRow(id: $0.key, target: $0.value.string ?? "") }
                .sorted { $0.id < $1.id }
            let sync = json["sync"]
            syncMessage = sync["synced_at"].double.map { "目录 \(Fmt.moment(Date(timeIntervalSince1970: $0), now: Date())) · \(Int(sync["model_count"].double ?? 0)) 个模型" }
                ?? "目录尚未同步"
            message = nil
        } catch { message = "读取失败：\(error.localizedDescription)" }
    }

    private func sync() async {
        guard let client = store.backendClient else { return }
        syncing = true
        defer { syncing = false }
        do {
            let result = try await client.syncPrices()
            syncMessage = "已同步：新增 \(Int(result["added"].double ?? 0)) · 更新 \(Int(result["updated"].double ?? 0))"
            await load()
            await store.fetch(force: true)
        } catch { syncMessage = "同步失败，保留上次目录：\(error.localizedDescription)" }
    }

    private func addMissingFromSnapshot() {
        guard let snapshot = store.snapshot else { return }
        let countBefore = bindings.count
        var names = Set(bindings.map { Catalog.modelKey($0.id) })
        for source in snapshot.sources {
            guard let value = source.metric("tokens")?.value else { continue }
            for group in value["periods"]["all"]["groups"].array {
                guard let full = group["model"].string else { continue }
                let short = Catalog.modelLabel(full)
                let key = Catalog.modelKey(short)
                guard !short.isEmpty, short != "unknown", !names.contains(key) else { continue }
                let priced = rows.contains { !Catalog.modelKey($0.id).isEmpty && key.contains(Catalog.modelKey($0.id)) }
                if !priced {
                    bindings.append(ModelBindingRow(id: short, target: ""))
                    names.insert(key)
                }
            }
        }
        message = bindings.count == countBefore ? "没有发现新的未定价模型" : "已补入，请选择计费模型后保存"
    }

    private func save() async {
        guard let client = store.backendClient else { message = "后端未连接"; return }
        let catalogKeys = Set(rows.filter(\.synced).map(\.id))
        var models: [String: [String: Double]] = [:]
        for row in rows where !catalogKeys.contains(row.id) {
            let pattern = row.id.trimmingCharacters(in: .whitespaces)
            guard !pattern.isEmpty else { continue }
            func num(_ s: String) -> Double { Double(s.replacingOccurrences(of: ",", with: ".")) ?? 0 }
            models[pattern] = ["input": num(row.input), "cache_read": num(row.cacheRead),
                               "cache_write": num(row.cacheWrite), "output": num(row.output)]
        }
        var aliases: [String: String] = [:]
        for row in bindings {
            let id = row.id.trimmingCharacters(in: .whitespaces)
            let target = row.target.trimmingCharacters(in: .whitespaces)
            if !id.isEmpty, !target.isEmpty { aliases[Catalog.modelKey(id)] = target }
        }
        do {
            _ = try await client.putPrices(currency: currency, models: models, aliases: aliases)
            message = "已保存，正在重新估算"
            await store.fetch(force: true)
            await load()
        } catch { message = "保存失败：\(error.localizedDescription)" }
    }
}
