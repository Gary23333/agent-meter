import Foundation
import UserNotifications

/// Low-quota and expiry alerts. Each alert has a stable key (source, bucket,
/// event time, level) so it fires once per event rather than on every poll.
@MainActor
final class Notifier: NSObject, UNUserNotificationCenterDelegate {
    static let shared = Notifier()

    struct Alert {
        let key: String
        let title: String
        let body: String
    }

    /// Only available inside an app bundle; nil for `swift run` / previews.
    private var center: UNUserNotificationCenter? {
        Bundle.main.bundleIdentifier == nil ? nil : UNUserNotificationCenter.current()
    }
    private let firedKey = "firedAlerts"
    private var fired: [String: Double] = UserDefaults.standard.dictionary(forKey: "firedAlerts") as? [String: Double] ?? [:]

    func setup() {
        guard let center else { return }
        center.delegate = self
        center.requestAuthorization(options: [.alert, .sound]) { granted, error in
            if !granted { NSLog("AgentMeterBar notifications not granted: %@", String(describing: error)) }
        }
    }

    func evaluate(_ snapshot: Snapshot, store: UsageStore, now: Date) {
        guard store.notificationsEnabled else { return }
        for alert in alerts(snapshot, threshold: store.lowQuotaThreshold, now: now) where fired[alert.key] == nil {
            post(alert)
            fired[alert.key] = now.timeIntervalSince1970
        }
        // Keys embed their event time, so old entries can never match again.
        fired = fired.filter { now.timeIntervalSince1970 - $0.value < 90 * 86400 }
        UserDefaults.standard.set(fired, forKey: firedKey)
    }

    func sendTest() {
        post(Alert(key: "test-\(Date().timeIntervalSince1970)", title: "Agent 用量 · 测试通知",
                   body: "额度不足和到期提醒会以这种方式出现。"))
    }

    private func post(_ alert: Alert) {
        let content = UNMutableNotificationContent()
        content.title = alert.title
        content.body = alert.body
        content.sound = .default
        content.threadIdentifier = "agent-meter"
        center?.add(UNNotificationRequest(identifier: alert.key, content: content, trigger: nil)) { error in
            if let error { NSLog("AgentMeterBar notification failed: %@", String(describing: error)) }
        }
    }

    // MARK: Rules

    func alerts(_ snapshot: Snapshot, threshold: Double, now: Date) -> [Alert] {
        var out: [Alert] = []
        for s in snapshot.accountSources {
            let name = s.displayName

            // 1. Low quota: user threshold, then 5%, then exhausted.
            for q in s.metric("quota")?.value.rows ?? [] {
                guard let r = q["remaining_percent"].double else { continue }
                let reset = q["resets_at"].date
                let level = r <= 0 ? "0" : r <= min(5, threshold) ? "5" : r <= threshold ? "\(Int(threshold))" : nil
                guard let level else { continue }
                let bucket = q["bucket"].string ?? "quota"
                let resetText = reset.map { "，\(Fmt.countdown(to: $0, now: now))（\(Fmt.moment($0, now: now))）重置" } ?? ""
                out.append(Alert(
                    key: "low|\(s.id)|\(bucket)|\(Int(reset?.timeIntervalSince1970 ?? 0))|\(level)",
                    title: r <= 0 ? "\(name) 额度已用完" : "\(name) 额度不足",
                    body: "\(Catalog.bucketLabel(q)) 窗口剩余 \(Fmt.percent(r.rounded()))\(resetText)。"))
            }

            // 2. Reset cards close to expiry.
            if let cards = s.metric("reset_cards")?.value {
                let total = Int(cards["available_count"].double ?? 0)
                var expiries = cards["cards"].array.compactMap { $0["expires_at"].date }
                if expiries.isEmpty, let next = cards["next_known_expiry"].date { expiries = [next] }
                for (exp, count) in Dictionary(grouping: expiries, by: { $0 }).mapValues(\.count) {
                    guard let level = expiryLevel(exp, now: now) else { continue }
                    out.append(Alert(
                        key: "card|\(s.id)|\(Int(exp.timeIntervalSince1970))|\(level)",
                        title: "\(name) 重置卡即将到期",
                        body: "\(count) 张重置卡将于 \(Fmt.moment(exp, now: now)) 到期（还剩 \(Fmt.countdown(to: exp, now: now).replacingOccurrences(of: "后", with: ""))），当前共 \(total) 张，记得使用。"))
                }
            }

            // 3. Credit packs with a balance and an expiry.
            for c in s.metric("credits")?.value.rows ?? [] {
                for b in c["buckets"].array {
                    guard let amount = b["balance"].double, amount > 0, let exp = b["expires_at"].date,
                          let level = expiryLevel(exp, now: now) else { continue }
                    out.append(Alert(
                        key: "credit|\(s.id)|\(Int(exp.timeIntervalSince1970))|\(level)",
                        title: "\(name) 积分即将失效",
                        body: "\(Fmt.grouped(amount)) \(Catalog.unitLabel(c["unit"].string)) 将于 \(Fmt.moment(exp, now: now)) 失效（还剩 \(Fmt.countdown(to: exp, now: now).replacingOccurrences(of: "后", with: ""))）。"))
                }
            }

            // 4. Subscription renewal (charge) and non-renewing membership end.
            if let v = s.metric("renewal_time")?.value, let day = Fmt.parseDay(v["date"].string) {
                let days = Fmt.daysUntil(day, now: now)
                if days >= 0 && days <= 3 {
                    var body = "订阅将于 \(Fmt.day(day, now: now)) 自动续费（\(Fmt.dayCountdown(day, now: now))）"
                    if let a = s.metric("renewal_amount")?.value, let amount = a["amount"].double {
                        body += "，金额 \(Fmt.amount(amount, unit: a["currency"].string))"
                    }
                    out.append(Alert(key: "renew|\(s.id)|\(v["date"].string ?? "")|\(days == 0 ? "0" : "3")",
                                     title: "\(name) 即将续费", body: body + "。"))
                }
            } else if s.subscription["auto_renew"].bool == false, let end = Fmt.parseDay(s.subscription["ends_on"].string) {
                let days = Fmt.daysUntil(end, now: now)
                if days >= 0 && days <= 7 {
                    out.append(Alert(key: "member|\(s.id)|\(s.subscription["ends_on"].string ?? "")|\(days <= 1 ? "1" : "7")",
                                     title: "\(name) 会员即将到期",
                                     body: "会员将于 \(Fmt.day(end, now: now)) 到期（\(Fmt.dayCountdown(end, now: now))），未开启自动续费。"))
                }
            }
        }
        return out
    }

    /// "1" within 24 hours, "3" within 3 days, nil otherwise or when past.
    private func expiryLevel(_ date: Date, now: Date) -> String? {
        let left = date.timeIntervalSince(now)
        if left <= 0 { return nil }
        if left <= 86400 { return "1" }
        if left <= 3 * 86400 { return "3" }
        return nil
    }

    // MARK: UNUserNotificationCenterDelegate

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification)
        async -> UNNotificationPresentationOptions {
        [.banner, .sound, .list]
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse) async {
        await MainActor.run { StatusBarController.shared.showPanel() }
    }
}
