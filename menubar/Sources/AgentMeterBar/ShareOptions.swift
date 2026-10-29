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

    static let compact = ShareOptions()
    static let review = ShareOptions(mode: .review, peak: true)
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
