import Foundation

struct Metric {
    let status: String
    let value: JSON
    let reason: String?

    init(_ json: JSON) {
        status = json["status"].string ?? "not_provided"
        value = json["value"]
        reason = json["reason"].string
    }

    var hasValue: Bool { !value.isNull }
}

struct Source: Identifiable {
    let id: String
    let scope: String
    let status: String
    let observedAt: Date?
    let reason: String?
    let lastError: String?
    let lastImport: Date?
    /// Label of an extra web-login account ("qoder#2" → "小号").
    let accountLabel: String?
    /// Provider part of the id ("qoder#2" → "qoder").
    var baseID: String { ConnectionManager.provider(ofSlot: id) }
    /// Brand name plus account label, for cards, ticker and alerts.
    var displayName: String { Catalog.brand(id).name + (accountLabel.map { " · " + $0 } ?? "") }
    var shortName: String { Catalog.shortName(id) + (accountLabel.map { "·" + $0 } ?? "") }
    let subscription: JSON
    let metrics: [String: Metric]

    init(_ json: JSON) {
        id = json["id"].string ?? "unknown"
        scope = json["scope"].string ?? ""
        status = json["status"].string ?? "error"
        observedAt = json["observed_at"].date
        reason = json["diagnostics"]["reason"].string
        lastError = json["diagnostics"]["last_error"].string
        lastImport = json["diagnostics"]["last_import_at"].date
        accountLabel = json["account_label"].string
        subscription = json["subscription"]
        metrics = json["metrics"].object.mapValues(Metric.init)
    }

    func metric(_ name: String) -> Metric? {
        guard let m = metrics[name], m.hasValue else { return nil }
        return m
    }

    var isLocalHistory: Bool { scope == "local_imported_history" || scope == "local_session_history" }
    var hasAccountData: Bool {
        ["quota", "reset_cards", "credits", "renewal_time", "credit_refresh_time"].contains { metric($0) != nil }
    }
}

struct CoverageRow: Identifiable {
    let id: String
    let name: String
    let version: String?
    let installed: Bool
    let provider: String
    let path: String?
    let bundleID: String?
    let fields: [(name: String, status: String)]

    init(_ json: JSON, index: Int) {
        let app = json["application"]
        name = app["name"].string ?? "未知应用"
        version = app["version"].string
        installed = app["installed"].bool ?? false
        provider = app["provider"].string ?? ""
        path = app["path"].string
        bundleID = app["bundle_id"].string
        id = "\(index)-\(name)"
        fields = Catalog.metricOrder.compactMap { key in
            json["fields"][key]["status"].string.map { (key, $0) }
        }
    }

    var collected: Int { fields.filter { ["available", "partial", "stale"].contains($0.status) }.count }
}

struct Snapshot {
    let schemaVersion: Int
    let collectedAt: Date?
    let servedFromCache: Bool
    let sources: [Source]
    let coverage: [CoverageRow]
    let summary: JSON

    init(_ json: JSON) {
        schemaVersion = Int(json["schema_version"].double ?? 0)
        collectedAt = json["collected_at"].date
        servedFromCache = json["served_from_cache"].bool ?? false
        sources = json["sources"].array.map(Source.init)
        coverage = json["coverage"].array.enumerated().map { CoverageRow($1, index: $0) }
        summary = json["coverage_summary"]
    }

    var history: Source? { sources.first { $0.isLocalHistory } }

    /// Installed .app bundles for a source (Qoder has both CN and CN IDE).
    func apps(for sourceID: String) -> [CoverageRow] {
        coverage.filter { $0.provider == sourceID && $0.installed && ($0.path?.hasSuffix(".app") ?? false) }
    }

    /// Accounts with something to show, in the catalog's preferred order.
    var accountSources: [Source] {
        sources.filter { !$0.isLocalHistory && $0.hasAccountData }
            .sorted { Catalog.rank($0.id) < Catalog.rank($1.id) }
    }

    var inactiveSources: [Source] {
        sources.filter { !$0.isLocalHistory && !$0.hasAccountData }
            .sorted { Catalog.rank($0.id) < Catalog.rank($1.id) }
    }

    /// The quota bucket closest to running out, for the menu bar label.
    var tightestQuota: (source: Source, remaining: Double)? {
        var best: (source: Source, remaining: Double)?
        for s in sources {
            for q in s.metric("quota")?.value.rows ?? [] {
                guard let r = q["remaining_percent"].double else { continue }
                if best == nil || r < best!.remaining { best = (s, r) }
            }
        }
        return best
    }
}
