import SwiftUI

/// 报告与分享卡的唯一数据源：口径与「本机消耗」页一致，直接复用 LocalUsage.merged。
struct ReportData {
    struct CostPart: Identifiable {
        let id: String
        let label: String
        let text: String
    }

    struct AppRow: Identifiable {
        let id: String
        let name: String
        let tint: Color
        let tokens: Double
        let requests: Double
        let cost: String
        /// 占 Token 总量的比例。
        let fraction: Double
    }

    struct ModelRow: Identifiable {
        let id: String
        let name: String
        let app: String
        let appLabel: String
        let tint: Color
        let tokens: Double
        let cost: String
    }

    let period: Period
    let generatedAt: Date
    let totalTokens: Double
    let requests: Double
    let freshInput: Double
    let output: Double
    let cacheRead: Double
    let cacheWrite: Double
    let cacheHitRate: Double?
    /// 估算费用，可能是 USD 或 CNY；未知价时为 nil（显示「—」，不是 0）。
    let costAmount: Double?
    let costUnit: String?
    let costText: String
    let costParts: [CostPart]
    let unpricedModels: [String]
    let totalIsLowerBound: Bool
    let apps: [AppRow]
    let models: [ModelRow]
    let includesLocal: [String]
    let sourceNote: String
    let appCount: Int
    let periodStatus: String?

    var cacheHitText: String {
        guard let rate = cacheHitRate else { return "—" }
        return Fmt.percent((rate * 1000).rounded() / 10)
    }

    var costNote: String {
        guard !unpricedModels.isEmpty else { return "API 等价估算" }
        let names = unpricedModels.prefix(2).joined(separator: "、")
        let more = unpricedModels.count > 2 ? " 等 \(unpricedModels.count) 个" : ""
        return "未计价：" + names + more + "，费用为下界"
    }

    static func build(snapshot: Snapshot, period: Period, now: Date) -> ReportData? {
        guard let data = LocalUsage.merged(snapshot: snapshot, period: period) else { return nil }
        let totals = data["totals"]
        let costIndex = data["cost_index"]

        // 单个分组费用：CC Switch 自带 estimated_cost_usd 优先，其余按价格表逐模型估算。
        func groupCost(_ g: JSON) -> [String: Double] {
            if let usd = g["estimated_cost_usd"].double, usd > 0 { return ["USD": usd] }
            let entry = costIndex[g["source"].string ?? ""]
            guard let unit = entry["unit"].string,
                  let amount = entry["models"][g["model"].string ?? ""].double, amount > 0 else { return [:] }
            return [unit: amount]
        }

        func costLabel(_ costs: [String: Double]) -> String {
            guard !costs.isEmpty else { return "—" }
            return costs.sorted { $0.key < $1.key }
                .map { Fmt.amount($0.value, unit: $0.key) }
                .joined(separator: " + ")
        }

        let total = totals["total_tokens"].double ?? 0

        // 按应用聚合
        var appMap: [String: (tokens: Double, requests: Double, costs: [String: Double])] = [:]
        for g in data["groups"].array {
            let app = g["app"].string ?? "其他"
            var row = appMap[app] ?? (0, 0, [:])
            row.tokens += g["total_tokens"].double ?? 0
            row.requests += g["requests"].double ?? 0
            for (unit, amount) in groupCost(g) { row.costs[unit, default: 0] += amount }
            appMap[app] = row
        }
        let apps = appMap.sorted { $0.value.tokens > $1.value.tokens }.prefix(5).map { key, value in
            AppRow(id: key, name: Catalog.appLabel(key), tint: Catalog.appTint(key),
                   tokens: value.tokens, requests: value.requests, cost: costLabel(value.costs),
                   fraction: total > 0 ? value.tokens / total : 0)
        }

        // 按模型聚合：同应用内同一模型的不同写法合并，与「本机消耗」页一致。
        struct Bucket {
            var name: String
            var app: String
            var tokens: Double
            var costs: [String: Double]
        }
        var modelMap: [String: Bucket] = [:]
        for g in data["groups"].array {
            let raw = g["model"].string ?? "未知模型"
            let app = g["app"].string ?? ""
            let key = app + "\u{1}" + Catalog.modelKey(raw)
            var bucket = modelMap[key] ?? Bucket(name: Catalog.modelLabel(raw), app: app, tokens: 0, costs: [:])
            bucket.tokens += g["total_tokens"].double ?? 0
            for (unit, amount) in groupCost(g) { bucket.costs[unit, default: 0] += amount }
            modelMap[key] = bucket
        }
        let models = modelMap.sorted { $0.value.tokens > $1.value.tokens }.prefix(5).map { key, value in
            ModelRow(id: key, name: value.name, app: value.app, appLabel: Catalog.appLabel(value.app),
                     tint: Catalog.appTint(value.app), tokens: value.tokens, cost: costLabel(value.costs))
        }

        // 费用口径：CC Switch 的 USD 估算 + 价格表 USD 可相加；CNY 单独成数，绝不跨币种相加。
        let local = data["local_cost"].object
        let cc = totals["estimated_cost_usd"].double ?? 0
        let localUSD = local["USD"]?.double ?? 0
        var costAmount: Double?
        var costUnit: String?
        if cc > 0 || localUSD > 0 {
            costAmount = cc + localUSD
            costUnit = "USD"
        } else if let cny = local["CNY"]?.double, cny > 0 {
            costAmount = cny
            costUnit = "CNY"
        }
        let costText = costAmount.map { Fmt.amount($0, unit: costUnit) } ?? "—"

        var costParts: [CostPart] = []
        if cc > 0 { costParts.append(CostPart(id: "ccswitch", label: "CC Switch", text: Fmt.usd(cc))) }
        for (unit, value) in local.sorted(by: { $0.key < $1.key }) {
            guard let amount = value.double, amount > 0 else { continue }
            costParts.append(CostPart(id: "local-\(unit)", label: "价格表 \(unit)", text: Fmt.amount(amount, unit: unit)))
        }
        if let n = totals["unpriced_detail_requests"].double, n > 0 {
            costParts.append(CostPart(id: "unpriced", label: "无定价请求", text: "\(Int(n)) 次"))
        }

        let includesLocal = data["includes_local"].array.compactMap { $0.string }
        let sourceNote = includesLocal.isEmpty
            ? "数据来自 CC Switch 本机记录"
            : "数据来自 CC Switch 与 " + includesLocal.map { Catalog.brand($0).name }.joined(separator: "、") + " 本机记录"

        return ReportData(period: period, generatedAt: now,
                          totalTokens: total,
                          requests: totals["requests"].double ?? 0,
                          freshInput: totals["fresh_input"].double ?? 0,
                          output: totals["output"].double ?? 0,
                          cacheRead: totals["cache_read"].double ?? 0,
                          cacheWrite: totals["cache_write"].double ?? 0,
                          cacheHitRate: totals["cache_hit_rate"].double,
                          costAmount: costAmount, costUnit: costUnit, costText: costText,
                          costParts: costParts,
                          unpricedModels: data["unpriced_models"].array.compactMap { $0.string },
                          totalIsLowerBound: data["total_is_lower_bound"].bool == true,
                          apps: apps, models: models,
                          includesLocal: includesLocal, sourceNote: sourceNote,
                          appCount: appMap.count,
                          periodStatus: data["period_status"].string)
    }
}
