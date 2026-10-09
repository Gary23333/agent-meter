import Foundation

/// Finds which of 即梦's own page requests carry membership, renewal and
/// credit-refresh data. The page's responses are reduced to their *shape*
/// (field names, types, timestamp-like flags) in memory; values, cookies and
/// query strings are never written. Nothing is replayed or signed here.
@MainActor
final class DreaminaDiscovery {
    nonisolated static let handlerName = "agentMeterDiscovery"

    /// Observes (never alters) the page's billing-related JSON responses.
    nonisolated static let script = """
    (function(){
      const want = u => { try {
        const x = new URL(u, location.href);
        return /(^|\\.)jianying\\.com$/.test(x.hostname) &&
               /commerce|benefit|credit|vip|subscri|member|pay|order|account|user_info|privilege/i.test(x.pathname);
      } catch (e) { return false; } };
      const send = (u, text) => { try {
        if (!text || text.length > 524288) return;
        window.webkit.messageHandlers.agentMeterDiscovery.postMessage({url: String(u), json: text});
      } catch (e) {} };
      const f = window.fetch;
      window.fetch = function() {
        return f.apply(this, arguments).then(r => {
          try { if (want(r.url)) r.clone().text().then(t => send(r.url, t)).catch(() => {}); } catch (e) {}
          return r;
        });
      };
      const open = XMLHttpRequest.prototype.open;
      XMLHttpRequest.prototype.open = function() {
        this.addEventListener('load', function() {
          try { if (want(this.responseURL) && typeof this.responseText === 'string') send(this.responseURL, this.responseText); } catch (e) {}
        });
        return open.apply(this, arguments);
      };
    })();
    """

    private var endpoints: [String: Any] = [:]
    var count: Int { endpoints.count }

    /// Returns true when a new endpoint shape was recorded.
    @discardableResult
    func record(url: String, json: String) -> Bool {
        guard let parsed = URL(string: url), let host = parsed.host,
              let data = json.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data) else { return false }
        let key = host + parsed.path   // query strings dropped: they can carry tokens
        let isNew = endpoints[key] == nil
        endpoints[key] = Self.shape(object, depth: 0)
        return isNew && endpoints.count <= 200
    }

    func write(to file: URL) {
        let report: [String: Any] = [
            "generated_at": ISO8601DateFormatter().string(from: Date()),
            "note": "Structure only: field names and value types from 即梦 page responses. No values, cookies or query strings.",
            "endpoints": endpoints,
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]) else { return }
        FileManager.default.createFile(atPath: file.path, contents: data, attributes: [.posixPermissions: 0o600])
    }

    /// Type-only description of a JSON value.
    nonisolated static func shape(_ value: Any, depth: Int) -> Any {
        if depth > 8 { return "…" }
        switch value {
        case let dict as [String: Any]:
            return dict.mapValues { shape($0, depth: depth + 1) }
        case let array as [Any]:
            return ["array(\(array.count))", array.first.map { shape($0, depth: depth + 1) } ?? "empty"]
        case let number as NSNumber:
            if CFGetTypeID(number) == CFBooleanGetTypeID() { return "bool" }
            let v = number.doubleValue
            if (1.0e9...4.0e9).contains(v) { return "number:epoch_seconds?" }
            if (1.0e12...4.0e12).contains(v) { return "number:epoch_ms?" }
            return v == v.rounded() ? "integer" : "decimal"
        case let string as String:
            if string.range(of: #"^\d{4}[-/]\d{2}[-/]\d{2}"#, options: .regularExpression) != nil { return "string:date-like" }
            if string.range(of: #"^\d{10}(\d{3})?$"#, options: .regularExpression) != nil { return "string:epoch?" }
            if string.range(of: #"^-?\d+(\.\d+)?$"#, options: .regularExpression) != nil { return "string:number" }
            return "string"
        case is NSNull:
            return "null"
        default:
            return "unknown"
        }
    }
}
