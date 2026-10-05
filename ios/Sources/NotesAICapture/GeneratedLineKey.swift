import CryptoKit
import Foundation

/// A generated line's key — note-service's `lines.key_of(lines.strip_marker(line))`
/// ported: marker, "Owner:" prefix and "— due" tail off, normalised, sha256[:16].
/// Web twin `web/src/lib/itemKey.ts`; both checked against `web/tests/fixtures/item-keys.json`.
enum GeneratedLineKey {
    // lines.py _MARKER
    private static let marker = regex(#"^([\s>]*(?:[-–—•*·▪◦●○]+|\(?(?:\d{1,2}|[a-zA-Z])[.)])\s*)"#)
    // action_items.py _BULLET, _OWNER, _DUE_DASH, _DUE_WORD
    private static let bullet = regex(#"^[\s\-•*·▪◦]*(?:\d{1,2}[.)]\s*)?[\s\-•*·]*"#)
    private static let owner = regex(#"^([^:—–-]{1,60}?):(?!//)\s*(\S.*)$"#)
    private static let dueDash = regex(#"^(.+?)\s+[—–-]\s*(?:(?:by|due|until|до|bis)\s+)?(.+?)\s*$"#, caseInsensitive: true)
    private static let dueWord = regex(#"^(.+?)\s+(?:by|due|until|до|bis)\s+(.+?)\s*$"#, caseInsensitive: true)
    private static let whitespace = regex(#"\s+"#)
    private static let trailingPunctuation = regex(#"[.;,]+$"#)
    private static let maxText = 500

    // CorrectionsPanel.tsx MARKED — "Emil (?)", a name the engine doubted.
    private static let doubted = regex(#"([A-ZÄÖÜА-ЯІЇЄҐ][\w'’-]+(?:\s[A-ZÄÖÜА-ЯІЇЄҐ][\w'’-]+)?) \(\?\)"#)

    /// The names a line marks as doubtful — "Emil (?)".
    static func doubtedNames(in text: String) -> [String] {
        let ns = text as NSString
        return doubted.matches(in: text, range: NSRange(location: 0, length: ns.length)).compactMap { m in
            group(m, 1, text)
        }
    }

    /// The key of a line as it is displayed, marker and all.
    static func lineKey(_ line: String) -> String {
        keyOf(stripMarker(line))
    }

    /// lines.strip_marker → the content without its list marker.
    static func stripMarker(_ line: String) -> String {
        let ns = line as NSString
        if let m = marker.firstMatch(in: line, range: NSRange(location: 0, length: ns.length)) {
            return ns.substring(from: m.range.length).trimmingCharacters(in: .whitespacesAndNewlines)
        }
        return line.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// action_items.normalise_text
    static func normaliseText(_ text: String) -> String {
        var out = replacing(whitespace, in: text, with: " ").trimmingCharacters(in: .whitespacesAndNewlines)
        out = replacing(trailingPunctuation, in: out, with: "").trimmingCharacters(in: .whitespacesAndNewlines)
        return out.lowercased()
    }

    /// lines.key_of(content) — content with the marker already off.
    static func keyOf(_ content: String) -> String {
        var line = replacing(bullet, in: content, with: "", firstOnly: true)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        if line.isEmpty { return String(sha256Hex(normaliseText(content)).prefix(16)) }
        if let m = owner.firstMatch(in: line, range: NSRange(location: 0, length: (line as NSString).length)),
           let name = group(m, 1, line), let rest = group(m, 2, line),
           name.trimmingCharacters(in: .whitespaces).split(whereSeparator: \.isWhitespace).count <= 4 {
            line = rest
        }
        let body = String(splitDue(line).prefix(maxText))
        return String(sha256Hex(normaliseText(body)).prefix(16))
    }

    private static func splitDue(_ rest: String) -> String {
        let ns = rest as NSString
        for pattern in [dueDash, dueWord] {
            if let m = pattern.firstMatch(in: rest, range: NSRange(location: 0, length: ns.length)),
               let due = group(m, 2, rest), !due.trimmingCharacters(in: .whitespaces).isEmpty,
               let head = group(m, 1, rest) {
                return head.trimmingCharacters(in: .whitespaces)
            }
        }
        return rest.trimmingCharacters(in: .whitespaces)
    }

    private static func sha256Hex(_ text: String) -> String {
        SHA256.hash(data: Data(text.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    private static func group(_ match: NSTextCheckingResult, _ index: Int, _ text: String) -> String? {
        guard index < match.numberOfRanges else { return nil }
        let range = match.range(at: index)
        return range.location == NSNotFound ? nil : (text as NSString).substring(with: range)
    }

    private static func replacing(_ expression: NSRegularExpression, in text: String, with replacement: String,
                                  firstOnly: Bool = false) -> String {
        let ns = text as NSString
        let full = NSRange(location: 0, length: ns.length)
        if firstOnly {
            guard let m = expression.firstMatch(in: text, range: full) else { return text }
            return ns.replacingCharacters(in: m.range, with: replacement)
        }
        return expression.stringByReplacingMatches(in: text, range: full, withTemplate: replacement)
    }

    private static func regex(_ pattern: String, caseInsensitive: Bool = false) -> NSRegularExpression {
        do {
            return try NSRegularExpression(pattern: pattern, options: caseInsensitive ? [.caseInsensitive] : [])
        } catch {
            // Literal patterns; a non-compiling one is a bug here.
            preconditionFailure("invalid pattern in GeneratedLineKey: \(pattern)")
        }
    }
}
