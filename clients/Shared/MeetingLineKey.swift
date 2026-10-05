import CryptoKit
import Foundation

/// The identity of a typed line: `sha256(normalise(line)).hex[:16]`, the server's rule,
/// so a line keeps its timing across a whitespace edit. A hash, not a secret.
enum MeetingLineKey {
    static func of(_ line: String) -> String {
        let normalised = PendingMeetingNotes.normalise(line)
        guard !normalised.isEmpty else { return "" }
        let digest = SHA256.hash(data: Data(normalised.utf8))
        return digest.map { String(format: "%02x", $0) }.joined().prefix(16).description
    }
}
