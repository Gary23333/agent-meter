import Foundation
import Observation

enum PetSize: String, CaseIterable, Identifiable {
    case small, medium, large
    var id: String { rawValue }
    var label: String {
        switch self {
        case .small: return "小"
        case .medium: return "中"
        case .large: return "大"
        }
    }
    var scale: Double {
        switch self {
        case .small: return 0.75
        case .medium: return 1.0
        case .large: return 1.3
        }
    }
}

enum PetHUD: String, CaseIterable, Identifiable {
    case off, pill, full
    var id: String { rawValue }
    var label: String {
        switch self {
        case .off: return "关闭"
        case .pill: return "额度胶囊"
        case .full: return "胶囊 + 会话标签"
        }
    }
}

/// Everything the user can change about the pet, persisted in UserDefaults like the other panel settings.
@MainActor @Observable
final class PetPrefs {
    static let shared = PetPrefs()

    @ObservationIgnored private let defaults: UserDefaults

    var enabled: Bool { didSet { defaults.set(enabled, forKey: "petEnabled") } }
    var packID: String { didSet { defaults.set(packID, forKey: "petPack") } }
    var size: PetSize { didSet { defaults.set(size.rawValue, forKey: "petSize") } }
    var hud: PetHUD { didSet { defaults.set(hud.rawValue, forKey: "petHUD") } }
    var followCursor: Bool { didSet { defaults.set(followCursor, forKey: "petFollowCursor") } }
    /// Quiet mode: no idle antics, no chatter, only real news.
    var calm: Bool { didSet { defaults.set(calm, forKey: "petCalm") } }
    /// Show reminders as pet bubbles instead of system notifications.
    var takeoverAlerts: Bool { didSet { defaults.set(takeoverAlerts, forKey: "petTakeoverAlerts") } }
    /// Minutes of uninterrupted agent activity before a break reminder; 0 turns it off.
    var breakMinutes: Int { didSet { defaults.set(breakMinutes, forKey: "petBreakMinutes") } }
    /// "23:00-08:00" in local time, or nil.
    var quietHours: String? { didSet { defaults.set(quietHours, forKey: "petQuietHours") } }
    /// "auto" follows the sources in use; otherwise a source id such as "codex".
    var energySource: String { didSet { defaults.set(energySource, forKey: "petEnergySource") } }
    /// Wander slowly around the screen; pauses for drag, interaction and quiet hours.
    var roam: Bool { didSet { defaults.set(roam, forKey: "petRoam") } }

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        enabled = defaults.object(forKey: "petEnabled") as? Bool ?? false
        packID = defaults.string(forKey: "petPack") ?? "gauge"
        size = PetSize(rawValue: defaults.string(forKey: "petSize") ?? "") ?? .medium
        hud = PetHUD(rawValue: defaults.string(forKey: "petHUD") ?? "") ?? .pill
        followCursor = defaults.object(forKey: "petFollowCursor") as? Bool ?? true
        calm = defaults.object(forKey: "petCalm") as? Bool ?? false
        takeoverAlerts = defaults.object(forKey: "petTakeoverAlerts") as? Bool ?? false
        breakMinutes = defaults.object(forKey: "petBreakMinutes") as? Int ?? 120
        quietHours = defaults.string(forKey: "petQuietHours")
        energySource = defaults.string(forKey: "petEnergySource") ?? "auto"
        roam = defaults.object(forKey: "petRoam") as? Bool ?? false
    }

    /// Saved window position (bottom-left in screen coordinates), if any.
    var origin: CGPoint? {
        get {
            guard let x = defaults.object(forKey: "petOriginX") as? Double, let y = defaults.object(forKey: "petOriginY") as? Double else { return nil }
            return CGPoint(x: x, y: y)
        }
        set {
            if let p = newValue {
                defaults.set(Double(p.x), forKey: "petOriginX")
                defaults.set(Double(p.y), forKey: "petOriginY")
            } else {
                defaults.removeObject(forKey: "petOriginX")
                defaults.removeObject(forKey: "petOriginY")
            }
        }
    }

    /// What the backend brain needs, as the body of PUT /v1/pet/preferences.
    func brainPreferences(lowQuotaThreshold: Double) -> [String: Any] {
        [
            "low_quota_threshold": lowQuotaThreshold,
            "energy_source": energySource,
            "quiet_hours": quietHours as Any? ?? NSNull(),
            "break_after_minutes": breakMinutes,
        ]
    }
}
