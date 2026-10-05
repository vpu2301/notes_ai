import CryptoKit
import Foundation

/// A generated line's key — the server's rule, ported (Summary Engine v2, Q5).
///
/// The note shows lines; the evidence behind each lives in a row keyed by
/// `lines.key_of(lines.strip_marker(line))` in note-service: the marker off,
/// an "Owner:" prefix and a "— due" tail stripped (so fixing an owner or a
/// date keeps the line's evidence), the rest normalised and hashed —
/// sha256, first 16 hex characters. The client hashes the line it displays
/// the same way to find its row: no positional mapping, nothing to drift.
/// The web twin is `web/src/lib/itemKey.ts`; both read the same fixtures.
enum GeneratedLineKey {
    // lines.py _MARKER
    private static let marker = regex(#"^([\s>]*(?:[-–—•*·▪◦●○]+|\(?(?:\d{1,2}|[a-zA-Z])[.)])\s*)"#)
    // action_items.py _BULLET, _OWNER, _DUE_DASH, _DUE_WORD
    private static let bullet = regex(#"^[\s\-•*·▪◦]*(?:\d{1,2}[.)]\s*)?[\s\-•*·]*"#)
    private static let owner = regex(#"^([^:—–-]{1,60}?):(?!//)\s*(\S.*)$"#)
    private static let dueDash = regex(#"^(.+?)\s+[—–-]\s*(?:(?:by|due|until|до|bis)\s+)?(.+?)\s*$"#, caseInsensitive: true)
    private static let dueWord = regex(#"^(.+?)\s+(?:by|due|until|до|bis)\s+(.+?)\s*$"#, caseInsensitive: true)
    private static let maxText = 500

    private static func regex(_ pattern: String, caseInsensitive: Bool = false) -> NSRegularExpression {
        guard let re = try? NSRegularExpression(pattern: pattern, options: caseInsensitive ? [.caseInsensitive] : [])
        else { preconditionFailure("GeneratedLineKey: pattern does not compile: \(pattern)") }
        return re
    }

    private static func match(_ re: NSRegularExpression, _ text: String) -> [String?]? {
        let ns = text as NSString
        guard let m = re.firstMatch(in: text, range: NSRange(location: 0, length: ns.length)) else { return nil }
        return (0..<m.numberOfRanges).map { i in
            let r = m.range(at: i)
            return r.location == NSNotFound ? nil : ns.substring(with: r)
        }
    }

    /// lines.strip_marker → the content without its list marker.
    static func stripMarker(_ line: String) -> String {
        if let m = match(marker, line), let whole = m[0] {
            return String(line.dropFirst(whole.count)).trimmingCharacters(in: .whitespaces)
        }
        return line.trimmingCharacters(in: .whitespaces)
    }

    /// action_items.normalise_text
    static func normalise(_ text: String) -> String {
        text.replacingOccurrences(of: "\\s+", with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespaces)
            .replacingOccurrences(of: "[.;,]+$", with: "", options: .regularExpression)
            .trimmingCharacters(in: .whitespaces)
            .lowercased()
    }

    private static func splitDue(_ rest: String) -> String {
        for pattern in [dueDash, dueWord] {
            if let m = match(pattern, rest), let due = m[2], !due.trimmingCharacters(in: .whitespaces).isEmpty {
                return (m[1] ?? "").trimmingCharacters(in: .whitespaces)
            }
        }
        return rest.trimmingCharacters(in: .whitespaces)
    }

    /// lines.key_of(content) — content with the marker already off.
    static func keyOf(_ content: String) -> String {
        var line = content
        if let m = match(bullet, content), let whole = m[0] {
            line = String(content.dropFirst(whole.count))
        }
        line = line.trimmingCharacters(in: .whitespaces)
        if line.isEmpty { return hash(normalise(content)) }
        if let m = match(owner, line), let who = m[1],
           who.trimmingCharacters(in: .whitespaces).split(whereSeparator: \.isWhitespace).count <= 4 {
            line = m[2] ?? ""
        }
        let body = String(splitDue(line).prefix(maxText))
        return hash(normalise(body))
    }

    /// The key of a line as it is displayed, marker and all.
    static func of(_ line: String) -> String {
        keyOf(stripMarker(line))
    }

    private static func hash(_ text: String) -> String {
        let digest = SHA256.hash(data: Data(text.utf8))
        return String(digest.map { String(format: "%02x", $0) }.joined().prefix(16))
    }
}
