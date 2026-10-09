import Foundation

/// Schema-tolerant JSON tree. The backend adds fields between schema versions,
/// so the UI reads what it understands and ignores the rest.
enum JSON: Decodable, Equatable {
    case null
    case bool(Bool)
    case number(Double)
    case string(String)
    case array([JSON])
    case object([String: JSON])

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let n = try? c.decode(Double.self) { self = .number(n) }
        else if let b = try? c.decode(Bool.self) { self = .bool(b) }
        else if let s = try? c.decode(String.self) { self = .string(s) }
        else if let a = try? c.decode([JSON].self) { self = .array(a) }
        else { self = .object(try c.decode([String: JSON].self)) }
    }

    subscript(key: String) -> JSON {
        if case .object(let o) = self { return o[key] ?? .null }
        return .null
    }

    var isNull: Bool { self == .null }
    var string: String? { if case .string(let s) = self { return s }; return nil }
    var bool: Bool? { if case .bool(let b) = self { return b }; return nil }
    var array: [JSON] { if case .array(let a) = self { return a }; return [] }
    var object: [String: JSON] { if case .object(let o) = self { return o }; return [:] }

    /// Numbers may arrive as JSON numbers or as Decimal strings ("6086", "34.09").
    var double: Double? {
        switch self {
        case .number(let n): return n
        case .string(let s): return Double(s)
        default: return nil
        }
    }

    /// Backend timestamps are `{epoch_seconds, utc, display}` objects.
    var date: Date? { self["epoch_seconds"].double.map { Date(timeIntervalSince1970: $0) } }

    /// A list metric, or a single object metric treated as one row.
    var rows: [JSON] {
        switch self {
        case .array(let a): return a
        case .object: return [self]
        default: return []
        }
    }
}
