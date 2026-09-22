import CryptoKit
import Foundation

/// The identity of a line the author typed.
///
/// The same rule the server keys by — `sha256(normalise(line)).hex[:16]`
/// over `action_items.normalise_text` of the line without its bullet — so a
/// line keeps its timing across a whitespace edit, and the same thought
/// typed on the Mac and on the phone is one line, not two.
///
/// It is a hash, which is what makes it safe to put in a sidecar table, in
/// a metric's payload and in a generation's stats: no content travels with
/// it. It is NOT a secret, and nothing here treats it as one.
enum MeetingLineKey {
    static func of(_ line: String) -> String {
        let normalised = PendingMeetingNotes.normalise(line)
        guard !normalised.isEmpty else { return "" }
        let digest = SHA256.hash(data: Data(normalised.utf8))
        return digest.map { String(format: "%02x", $0) }.joined().prefix(16).description
    }
}
