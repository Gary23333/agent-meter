import Foundation
import Observation

/// The one poller for the pet's brain (`GET /v1/pet`), shared by everything that shows the pet: the floating desktop
/// window and the stage in the panel's 桌宠 tab. It only runs while somebody is subscribed, asks every 2 seconds
/// while a subscriber is on screen (10 seconds otherwise), and never triggers a collection: the endpoint just
/// interprets what the backend already has.
@MainActor @Observable
final class PetFeed {
    static let shared = PetFeed()

    /// The latest frame exactly as the backend produced it (or the offline frame after three failed requests).
    private(set) var frame: [String: Any]?
    /// What the panel shows in words, parsed from `frame`.
    private(set) var status: PetStatus?
    private(set) var updatedAt: Date?

    private struct Consumer {
        let onFrame: ([String: Any]) -> Void
        let isVisible: () -> Bool
    }

    @ObservationIgnored private let prefs = PetPrefs.shared
    @ObservationIgnored private let store = UsageStore.shared
    @ObservationIgnored private var consumers: [String: Consumer] = [:]
    @ObservationIgnored private var polling: Task<Void, Never>?
    @ObservationIgnored private var failures = 0
    @ObservationIgnored private var lastBrainPrefs = ""
    @ObservationIgnored private var lastLoggedError = ""
    @ObservationIgnored private var observing = false

    var subscriberCount: Int { consumers.count }
    var isPolling: Bool { polling != nil }

    /// Starts feeding `onFrame`. The latest frame is replayed at once so a newly opened view is never empty.
    /// Subscribing again under the same id only replaces the callbacks.
    func subscribe(_ id: String, isVisible: @escaping () -> Bool = { true }, onFrame: @escaping ([String: Any]) -> Void) {
        let isNew = consumers[id] == nil
        consumers[id] = Consumer(onFrame: onFrame, isVisible: isVisible)
        observeBrainPreferences()
        if isNew, let frame { onFrame(frame) }
        startPolling()
    }

    func unsubscribe(_ id: String) {
        consumers[id] = nil
        if consumers.isEmpty { stopPolling() }
    }

    /// An immediate fetch, e.g. right after a view finished loading.
    func refreshNow() {
        Task { await tick() }
    }

    /// Hook-style events for the brain (focus timer ...). The next frame shows their effect.
    func emit(_ payload: [String: Any]) {
        guard let client = store.backendClient else { return }
        Task {
            try? await client.petEvent(payload)
            await tick()
        }
    }

    /// Offline previews: publishes a frame without any backend.
    func inject(_ frame: [String: Any]) {
        publish(frame)
    }

    // MARK: Polling

    private func startPolling() {
        guard polling == nil else { return }
        polling = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                await self.tick()
                let fast = self.consumers.values.contains { $0.isVisible() }
                try? await Task.sleep(for: .seconds(fast ? 2 : 10))
            }
        }
    }

    private func stopPolling() {
        polling?.cancel()
        polling = nil
        failures = 0
    }

    private func tick() async {
        guard !consumers.isEmpty, let client = store.backendClient else { return }
        await pushBrainPreferences(client)
        do {
            let data = try await client.petFrame()
            failures = 0
            guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
            publish(object)
        } catch {
            // While the backend is still starting (no token file yet, nothing listening) that is not a failure.
            guard store.phase != .starting else { return }
            failures += 1
            if failures == 3 { publish(PetController.offlineFrame()) }
        }
    }

    private func publish(_ new: [String: Any]) {
        frame = new
        status = PetStatus.parse(new)
        updatedAt = Date()
        for consumer in Array(consumers.values) { consumer.onFrame(new) }
    }

    // MARK: What the brain needs to know

    /// Pushes the preferences the brain interprets (energy source, quiet hours, break reminder, threshold) whenever
    /// they changed since the last successful push.
    private func pushBrainPreferences(_ client: BackendClient) async {
        let body = prefs.brainPreferences(lowQuotaThreshold: store.lowQuotaThreshold)
        guard let data = try? JSONSerialization.data(withJSONObject: body, options: [.sortedKeys]),
              let json = String(data: data, encoding: .utf8), json != lastBrainPrefs else { return }
        do {
            try await client.putPetPreferences(body)
            lastBrainPrefs = json
            lastLoggedError = ""
        } catch {
            // Expected while the backend starts; log a given problem once, not on every tick.
            let text = String(describing: error)
            if store.phase != .starting, text != lastLoggedError { NSLog("AgentMeterBar pet preferences push: %@", text) }
            lastLoggedError = text
        }
    }

    private func observeBrainPreferences() {
        guard !observing else { return }
        observing = true
        track()
    }

    private func track() {
        withObservationTracking {
            _ = (prefs.energySource, prefs.quietHours, prefs.breakMinutes, store.lowQuotaThreshold)
        } onChange: { [weak self] in
            DispatchQueue.main.async {
                MainActor.assumeIsolated {
                    guard let self else { return }
                    self.track()
                    if !self.consumers.isEmpty { self.refreshNow() }
                }
            }
        }
    }
}
