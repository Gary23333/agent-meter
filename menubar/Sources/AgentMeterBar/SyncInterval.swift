import Foundation

/// How often a paired device pushes and pulls usage + quota in the background.
/// The interval is device-local: one Mac can sync every five minutes while a
/// laptop that is usually asleep syncs once a day.
enum SyncInterval: String, CaseIterable, Identifiable, Sendable {
    case off
    case fiveMinutes = "5m"
    case thirtyMinutes = "30m"
    case oneHour = "1h"
    case oneDay = "1d"

    var id: String { rawValue }

    /// Picker label, with the leading "每" so the setting reads as a cadence.
    var label: String {
        switch self {
        case .off: return "关闭自动同步"
        case .fiveMinutes: return "每 5 分钟"
        case .thirtyMinutes: return "每 30 分钟"
        case .oneHour: return "每 1 小时"
        case .oneDay: return "每 1 天"
        }
    }

    var shortLabel: String {
        switch self {
        case .off: return "关闭"
        case .fiveMinutes: return "5 分钟"
        case .thirtyMinutes: return "30 分钟"
        case .oneHour: return "1 小时"
        case .oneDay: return "1 天"
        }
    }

    /// nil means no timer at all; manual sync still works.
    var seconds: TimeInterval? {
        switch self {
        case .off: return nil
        case .fiveMinutes: return 5 * 60
        case .thirtyMinutes: return 30 * 60
        case .oneHour: return 60 * 60
        case .oneDay: return 24 * 60 * 60
        }
    }

    private static let key = "syncAutoInterval"

    static func stored(in defaults: UserDefaults = .standard) -> SyncInterval {
        guard let raw = defaults.string(forKey: key),
              let value = SyncInterval(rawValue: raw) else { return .off }
        return value
    }

    func store(in defaults: UserDefaults = .standard) {
        defaults.set(rawValue, forKey: Self.key)
    }
}
