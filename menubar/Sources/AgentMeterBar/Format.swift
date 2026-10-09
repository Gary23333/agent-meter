import Foundation

/// All times are shown in Beijing time, matching the backend's display_timezone.
enum Fmt {
    static let zone = TimeZone(identifier: "Asia/Shanghai")!

    static var calendar: Calendar = {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = zone
        return c
    }()

    private static func formatter(_ pattern: String) -> DateFormatter {
        let f = DateFormatter()
        f.locale = Locale(identifier: "zh_CN")
        f.timeZone = zone
        f.dateFormat = pattern
        return f
    }

    private static let clock = formatter("HH:mm")
    private static let clockSeconds = formatter("HH:mm:ss")
    private static let monthDayTime = formatter("M月d日 HH:mm")
    private static let monthDay = formatter("M月d日")
    private static let fullDay = formatter("yyyy年M月d日")
    private static let isoDay: DateFormatter = formatter("yyyy-MM-dd")

    static func time(_ d: Date) -> String { clock.string(from: d) }
    static func timeSeconds(_ d: Date) -> String { clockSeconds.string(from: d) }

    /// "10月15日 11:21", with the year only when it differs from now.
    static func moment(_ d: Date, now: Date = Date()) -> String {
        let sameYear = calendar.component(.year, from: d) == calendar.component(.year, from: now)
        return sameYear ? monthDayTime.string(from: d) : fullDay.string(from: d) + " " + clock.string(from: d)
    }

    static func day(_ d: Date, now: Date = Date()) -> String {
        let sameYear = calendar.component(.year, from: d) == calendar.component(.year, from: now)
        return sameYear ? monthDay.string(from: d) : fullDay.string(from: d)
    }

    /// Parses a backend date-only value ("2026-10-20") as a Beijing calendar day.
    static func parseDay(_ s: String?) -> Date? { s.flatMap { isoDay.date(from: $0) } }

    /// Whole calendar days from today to a date-only target, in Beijing time.
    static func daysUntil(_ day: Date, now: Date) -> Int {
        calendar.dateComponents([.day], from: calendar.startOfDay(for: now), to: calendar.startOfDay(for: day)).day ?? 0
    }

    static func dayCountdown(_ day: Date, now: Date) -> String {
        let d = daysUntil(day, now: now)
        if d > 0 { return "\(d) 天后" }
        if d == 0 { return "今天" }
        return "已过 \(-d) 天"
    }

    /// "6天8小时后" style countdown for instants.
    static func countdown(to d: Date, now: Date) -> String {
        let s = Int(d.timeIntervalSince(now))
        if s <= 0 { return "已过时间" }
        let days = s / 86400, hours = (s % 86400) / 3600, minutes = (s % 3600) / 60
        if days > 0 { return hours > 0 ? "\(days)天\(hours)小时后" : "\(days)天后" }
        if hours > 0 { return minutes > 0 ? "\(hours)小时\(minutes)分后" : "\(hours)小时后" }
        return minutes > 0 ? "\(minutes)分钟后" : "不到1分钟"
    }

    /// Compact ticker countdown: "6天", "2天5时", "4时54分", "37分".
    static func shortCountdown(to d: Date, now: Date, past: String) -> String {
        let s = Int(d.timeIntervalSince(now))
        if s <= 0 { return past }
        let days = s / 86400, hours = (s % 86400) / 3600, minutes = (s % 3600) / 60
        if days >= 3 { return "\(days)天" }
        if days >= 1 { return hours > 0 ? "\(days)天\(hours)时" : "\(days)天" }
        if hours >= 1 { return "\(hours)时\(minutes)分" }
        return "\(max(minutes, 1))分"
    }

    static func shortDayCountdown(_ day: Date, now: Date) -> String {
        let d = daysUntil(day, now: now)
        return d > 0 ? "\(d)天" : d == 0 ? "今天" : "已过"
    }

    /// Compact balances for the ticker: 21.1万, 6,086.
    static func compact(_ n: Double) -> String {
        if n >= 1e8 { return String(format: "%.1f亿", n / 1e8) }
        if n >= 1e4 { return String(format: "%.1f万", n / 1e4) }
        return grouped(n)
    }

    static func ago(_ d: Date, now: Date) -> String {
        let s = Int(now.timeIntervalSince(d))
        if s < 60 { return "刚刚" }
        if s < 3600 { return "\(s / 60) 分钟前" }
        if s < 86400 { return "\(s / 3600) 小时前" }
        return "\(s / 86400) 天前"
    }

    static func window(minutes m: Double) -> String {
        let n = Int(m)
        if n % 1440 == 0 { return "\(n / 1440) 天" }
        if n % 60 == 0 { return "\(n / 60) 小时" }
        return "\(n) 分钟"
    }

    static func trim(_ d: Double) -> String {
        d == d.rounded() ? String(Int(d)) : String(format: "%.1f", d)
    }

    static func percent(_ v: Double) -> String {
        v == v.rounded() ? "\(Int(v))%" : String(format: "%.1f%%", v)
    }

    /// Chinese magnitude units: 9008万, 39.33亿.
    static func tokens(_ n: Double) -> String {
        if n >= 1e8 { return String(format: n >= 1e10 ? "%.0f亿" : "%.2f亿", n / 1e8) }
        if n >= 1e4 { return String(format: n >= 1e6 ? "%.0f万" : "%.1f万", n / 1e4) }
        return grouped(n)
    }

    static func grouped(_ n: Double, fraction: Int = 0) -> String {
        let f = NumberFormatter()
        f.numberStyle = .decimal
        f.maximumFractionDigits = fraction
        f.minimumFractionDigits = 0
        return f.string(from: NSNumber(value: n)) ?? String(n)
    }

    static func usd(_ n: Double) -> String {
        let f = NumberFormatter()
        f.numberStyle = .decimal
        f.minimumFractionDigits = n >= 1000 ? 0 : 2
        f.maximumFractionDigits = n >= 1000 ? 0 : 2
        return "$" + (f.string(from: NSNumber(value: n)) ?? String(n))
    }

    static func amount(_ n: Double, unit: String?) -> String {
        switch unit {
        case "USD": return "$" + grouped(n, fraction: 2)
        case "CNY": return "¥" + grouped(n, fraction: 2)
        default: return grouped(n, fraction: 2)
        }
    }
}
