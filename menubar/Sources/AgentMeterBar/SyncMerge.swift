import Foundation

/// Folds what other devices synced into the snapshot, so every view reads one
/// set of accounts as if a single Mac had collected them.
///
/// The backend already matched accounts across devices (keyless ones by their
/// quota), so rows here are keyed by account. A local account takes a synced
/// window only when it is newer and any fact it cannot read itself; an account
/// only another device reads becomes an ordinary source.
enum SyncMerge {
    /// A synced reading older than this shows as "采样于 …", like a stale local one.
    static let staleAfter: TimeInterval = 3600
    private static let aliases = ["mcode": "minimax_code", "minimax": "minimax_code"]

    static func merged(_ snapshot: Snapshot, history: JSON?, now: Date = Date()) -> Snapshot {
        let quota = latestQuota(history?["remote_quota"].array ?? [])
        var accounts: [String: JSON] = [:]
        for row in history?["accounts"].array ?? [] {
            guard let key = row["account"].string else { continue }
            if (row["observed_at"].double ?? 0) >= (accounts[key]?["observed_at"].double ?? 0) { accounts[key] = row }
        }
        guard !quota.isEmpty || !accounts.isEmpty else { return snapshot }

        var sources = snapshot.raw["sources"].array
        var used = Set<String>()
        for index in sources.indices {
            let key = Source(sources[index]).syncAccountKey
            guard quota[key] != nil || accounts[key] != nil else { continue }
            sources[index] = overlay(sources[index], quota: quota[key] ?? [], account: accounts[key], now: now)
            used.insert(key)
        }
        for key in Set(quota.keys).union(accounts.keys).subtracting(used).sorted() {
            let rows = quota[key] ?? []
            guard let provider = provider(key: key, rows: rows, account: accounts[key]) else { continue }
            // An account the local Mac is not signed in to takes over its "未接入" row.
            if let index = sources.firstIndex(where: { json in
                let source = Source(json)
                return source.baseID == provider && !source.isLocalHistory && !source.isForecastFeature && !source.hasAccountData
            }) {
                sources[index] = overlay(sources[index], quota: rows, account: accounts[key], now: now)
                continue
            }
            let ids = Set(sources.compactMap { $0["id"].string })
            var id = provider
            var slot = 2
            while ids.contains(id) { id = "\(provider)#\(slot)"; slot += 1 }
            var shell: [String: JSON] = ["id": .string(id), "scope": .string("account"), "status": .string("available"),
                                         "metrics": .object([:]), "subscription": .object([:])]
            if AccountsView.syncProvider(accountKey: key) == nil { shell["account_key"] = .string(key) }
            sources.append(overlay(.object(shell), quota: rows, account: accounts[key], now: now))
        }
        var raw = snapshot.raw.object
        raw["sources"] = .array(sources)
        return Snapshot(.object(raw))
    }

    /// Newest synced row per account and window.
    private static func latestQuota(_ rows: [JSON]) -> [String: [JSON]] {
        var latest: [String: JSON] = [:]
        for row in rows where row["remaining_percent"].double != nil {
            guard let account = row["account"].string, let bucket = row["bucket"].string else { continue }
            let key = account + "|" + bucket + "|" + AccountsView.syncWindowID(row)
            if (row["observed_at"].double ?? 0) >= (latest[key]?["observed_at"].double ?? 0) { latest[key] = row }
        }
        var out: [String: [JSON]] = [:]
        for row in latest.values { out[row["account"].string ?? "", default: []].append(row) }
        return out
    }

    private static func provider(key: String, rows: [JSON], account: JSON?) -> String? {
        let name = account?["provider"].string ?? rows.compactMap { $0["provider"].string }.first
            ?? AccountsView.syncProvider(accountKey: key)
        return name.map { aliases[$0] ?? $0 }
    }

    private static func overlay(_ source: JSON, quota remote: [JSON], account: JSON?, now: Date) -> JSON {
        var object = source.object
        var metrics = source["metrics"].object
        let adopting = !Source(source).hasAccountData
        let localObserved = source["observed_at"].date?.timeIntervalSince1970 ?? 0
        var newest = 0.0

        var rows = source["metrics"]["quota"]["value"].rows.filter { $0["remaining_percent"].double != nil }
        for row in remote {
            let observed = row["observed_at"].double ?? 0
            let synced = AccountsView.syncedDisplayRow(row)
            if let index = rows.firstIndex(where: { sameWindow($0, row) }) {
                guard observed > localObserved else { continue }
                var merged = rows[index].object
                for key in ["used_percent", "remaining_percent", "resets_at"] where !synced[key].isNull {
                    merged[key] = synced[key]
                }
                rows[index] = .object(merged)
            } else {
                rows.append(synced)
            }
            newest = max(newest, observed)
        }
        if !rows.isEmpty, rows != source["metrics"]["quota"]["value"].rows {
            metrics["quota"] = .object(["status": .string("available"), "value": .array(Catalog.sortedQuotas(rows))])
        }

        if let account {
            newest = max(newest, account["observed_at"].double ?? 0)
            let credits = account["credits"].array.map(normalizedCredit)
            if metrics["credits"].map({ Metric($0).hasValue }) != true, !credits.isEmpty {
                metrics["credits"] = fact(.array(credits))
            }
            if metrics["reset_cards"].map({ Metric($0).hasValue }) != true, let count = account["reset_cards"]["count"].double {
                let cards = account["reset_cards"]["expiries"].array.compactMap(\.double).map {
                    JSON.object(["expires_at": .object(["epoch_seconds": .number($0)]), "status": .string("available")])
                }
                metrics["reset_cards"] = fact(.object(["available_count": .number(count), "cards": .array(cards)]))
            }
            for (metric, key) in [("renewal_time", "renewal_date"), ("credit_refresh_time", "credit_refresh_date")]
            where metrics[metric].map({ Metric($0).hasValue }) != true {
                if let day = account[key].string { metrics[metric] = fact(.object(["date": .string(day)])) }
            }
            if metrics["renewal_amount"].map({ Metric($0).hasValue }) != true, let amount = account["renewal_amount"].double {
                var value: [String: JSON] = ["amount": .number(amount)]
                if let currency = account["renewal_currency"].string { value["currency"] = .string(currency) }
                metrics["renewal_amount"] = fact(.object(value))
            }
            var subscription = source["subscription"].object
            for key in ["plan", "ends_on", "auto_renew"] where subscription[key] == nil || subscription[key] == .null {
                if !account[key].isNull { subscription[key] = account[key] }
            }
            object["subscription"] = .object(subscription)
        }
        object["metrics"] = .object(metrics)

        // A source this Mac cannot read takes the other device's reading time and freshness.
        if adopting, newest > 0 {
            object["observed_at"] = .object(["epoch_seconds": .number(newest)])
            object["status"] = .string(now.timeIntervalSince1970 - newest > staleAfter ? "stale" : "available")
            object["diagnostics"] = .object([:])
        }
        return .object(object)
    }

    private static func fact(_ value: JSON) -> JSON {
        .object(["status": .string("available"), "value": value])
    }

    private static func sameWindow(_ lhs: JSON, _ rhs: JSON) -> Bool {
        lhs["bucket"].string == rhs["bucket"].string && AccountsView.syncWindowID(lhs) == AccountsView.syncWindowID(rhs)
    }

    /// Synced balance buckets carry bare epochs; the credit rows read timestamps.
    private static func normalizedCredit(_ remote: JSON) -> JSON {
        var object = remote.object
        if !remote["buckets"].isNull {
            object["buckets"] = .array(remote["buckets"].array.map { bucket in
                var entry = bucket.object
                if let expiry = bucket["expires_at"].double {
                    entry["expires_at"] = .object(["epoch_seconds": .number(expiry)])
                }
                return .object(entry)
            })
        }
        return .object(object)
    }
}
