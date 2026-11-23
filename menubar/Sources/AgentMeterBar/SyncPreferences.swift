import Foundation

/// Last-writer-wins for the preferences a sync space shares.
///
/// Each device stamps a preference with the moment it noticed its own value
/// change. A remote value is applied only when its stamp is later than the
/// local one, so two devices that changed the same preference while apart
/// settle on the later change and never trade values back and forth.
///
/// The first round is special. A device that paired on this build adopts the
/// space's preferences (`adopt`); one that paired earlier keeps its own,
/// because its theme and thresholds were chosen on purpose and had never
/// been shared before.
enum SyncPreferenceSync {
    /// Device-local: whether to follow the other devices at all.
    static let enabledKey = "syncPreferencesEnabled"
    /// Set when a pairing is made on this build: adopt on the first round.
    static let adoptKey = "syncSettingsAdopt"
    private static let stateKey = "syncPreferencesState"

    struct State: Equatable, Codable {
        /// This device's values at its last round, every key present.
        var local: [String: JSON] = [:]
        /// When each key last changed here; a key that never did is absent.
        var changedAt: [String: Double] = [:]
        /// False until the first round has run.
        var started = false
    }

    static func enabled(in defaults: UserDefaults = .standard) -> Bool {
        defaults.object(forKey: enabledKey) == nil ? true : defaults.bool(forKey: enabledKey)
    }

    static func load(from defaults: UserDefaults = .standard) -> State {
        guard let data = defaults.data(forKey: stateKey) else { return State() }
        return (try? JSONDecoder().decode(State.self, from: data)) ?? State()
    }

    static func save(_ state: State, to defaults: UserDefaults = .standard) {
        if let data = try? JSONEncoder().encode(state) {
            defaults.set(data, forKey: stateKey)
        }
    }

    /// Forgets the shared preferences' history (the device left the space).
    static func reset(from defaults: UserDefaults = .standard) {
        defaults.removeObject(forKey: stateKey)
        defaults.removeObject(forKey: adoptKey)
    }

    /// Before an upload: every value that differs from the last round gets
    /// this moment as its stamp. Nothing is stamped on the first round.
    static func noting(_ values: [String: JSON], at now: TimeInterval, state: inout State) -> [String: Double] {
        if state.started {
            for (key, value) in values where state.local[key] != value {
                state.changedAt[key] = now
            }
        }
        state.local = values
        state.started = true
        return state.changedAt
    }

    /// The remote values that may replace the local ones, or nil when none may.
    ///
    /// A key the sender never stamped counts as "never changed there".
    /// `adopt` also takes a value that is merely not older, so a new device
    /// picks up what the space already has.
    static func accepted(_ remote: SyncSettings, local: SyncSettings, state: State,
                         adopt: Bool) -> SyncSettings? {
        var patch = SyncSettings()
        var stamps: [String: Double] = [:]
        let mine = local.values, theirs = remote.values
        for key in SyncSettings.keys {
            let stamp = remote.changedAt[key] ?? 0
            let own = state.changedAt[key] ?? 0
            guard let value = theirs[key], !value.isNull, value != mine[key],
                  stamp > own || (adopt && stamp >= own) else { continue }
            switch key {
            case "theme": patch.theme = value.string
            case "low_quota_threshold": patch.lowQuotaThreshold = value.double
            case "alerts_enabled": patch.alertsEnabled = value.bool
            case "menu_bar_mode": patch.menuBarMode = value.string
            case "source_order": patch.sourceOrder = value.array.compactMap(\.string)
            default: patch.budget = value.object.compactMapValues { $0.double }
            }
            stamps[key] = stamp
        }
        guard !stamps.isEmpty else { return nil }
        patch.changedAt = stamps
        return patch
    }

    /// After applying: the applied values count as this device's own, so the
    /// next round does not mistake them for a local change.
    static func applied(_ patch: SyncSettings, to state: inout State) {
        let values = patch.values
        for key in patch.changedAt.keys {
            state.changedAt[key] = patch.changedAt[key]
            state.local[key] = values[key]
        }
    }
}
