import Foundation

enum ShareMode: String, CaseIterable, Identifiable, Codable {
    case compact, review
    var id: String { rawValue }
    var label: String { self == .compact ? "简洁晒用量" : "完整复盘" }
}

struct ShareOptions: Codable, Equatable {
    var mode: ShareMode = .compact
    var costs = true
    var efficiency = true
    var apps = true
    var models = true
    var peak = false
    var images = true
    /// Project QR code in the footer.
    var qrCode = true

    static let compact = ShareOptions()
    static let review = ShareOptions(mode: .review, peak: true)
    init(mode: ShareMode = .compact, costs: Bool = true, efficiency: Bool = true, apps: Bool = true,
         models: Bool = true, peak: Bool = false, images: Bool = true, qrCode: Bool = true) {
        self.mode = mode; self.costs = costs; self.efficiency = efficiency; self.apps = apps
        self.models = models; self.peak = peak; self.images = images; self.qrCode = qrCode
    }

    /// Older saved options have no qrCode key; keep their choices and default it on.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        mode = try c.decodeIfPresent(ShareMode.self, forKey: .mode) ?? .compact
        costs = try c.decodeIfPresent(Bool.self, forKey: .costs) ?? true
        efficiency = try c.decodeIfPresent(Bool.self, forKey: .efficiency) ?? true
        apps = try c.decodeIfPresent(Bool.self, forKey: .apps) ?? true
        models = try c.decodeIfPresent(Bool.self, forKey: .models) ?? true
        peak = try c.decodeIfPresent(Bool.self, forKey: .peak) ?? false
        images = try c.decodeIfPresent(Bool.self, forKey: .images) ?? true
        qrCode = try c.decodeIfPresent(Bool.self, forKey: .qrCode) ?? true
    }

    var appLimit: Int { mode == .compact ? 3 : 5 }
    var modelLimit: Int { mode == .compact ? 3 : 5 }

    static func restored() -> ShareOptions {
        guard let data = UserDefaults.standard.data(forKey: "shareOptions"),
              let options = try? JSONDecoder().decode(ShareOptions.self, from: data) else { return .compact }
        return options
    }

    func save() {
        if let data = try? JSONEncoder().encode(self) { UserDefaults.standard.set(data, forKey: "shareOptions") }
    }
}
