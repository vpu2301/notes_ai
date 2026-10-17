import AppKit
import SwiftUI

/// Shown right after a public link is made: the link itself, what kind it is (permanent or
/// limited), and the two things people do next — copy it or send it.
struct PublicLinkSheet: View {
    let noteTitle: String
    let link: PublicLink?
    let url: URL?
    let busy: Bool
    let error: String?
    /// Mints a new link with this lifetime (nil = permanent); the old one stops working.
    let renew: (Int?) async -> Void
    /// True when the link is gone.
    let turnOff: () async -> Bool
    let onClose: () -> Void

    /// The link's lifetime in days; 0 = permanent. Same choices as the web.
    @State private var days = 0
    @State private var copied = false

    private static let dayOptions = [0, 7, 30, 90, 180]

    private var title: String {
        let title = noteTitle.trimmingCharacters(in: .whitespaces)
        return title.isEmpty ? "A note" : title
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            DSDivider()
            VStack(alignment: .leading, spacing: 18) {
                linkRow
                linkType
                if let error = error {
                    DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: error)
                }
            }
            .padding(20)
            DSDivider()
            footer
        }
        .frame(width: 460)
        .background(DS.bg)
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: "globe")
                .font(.dsIcon(15, .medium))
                .foregroundStyle(DS.accentText)
                .frame(width: 36, height: 36)
                .background(Circle().fill(DS.accentSoft))
            VStack(alignment: .leading, spacing: 3) {
                Text("Public link")
                    .font(.dsDisplay(17, .medium))
                    .foregroundStyle(DS.text1)
                Text("Anyone with the link can read and download “\(title)” — no sign-in, no replies.")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 16)
    }

    private var linkRow: some View {
        HStack(spacing: 8) {
            Text(url?.absoluteString ?? "—")
                .font(.system(size: 12.5, design: .monospaced))
                .foregroundStyle(DS.text1)
                .lineLimit(1)
                .truncationMode(.middle)
                .textSelection(.enabled)
                .padding(.horizontal, 10)
                .frame(maxWidth: .infinity, minHeight: 32, alignment: .leading)
                .background(
                    RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                        .fill(DS.surface)
                )
                .overlay(
                    RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                        .strokeBorder(DS.line, lineWidth: DS.hairline)
                )
            Button { copy() } label: {
                Label(copied ? "Copied" : "Copy", systemImage: copied ? "checkmark" : "doc.on.doc")
            }
            .buttonStyle(DSButtonStyle(kind: .primary, height: 32))
            .disabled(url == nil || busy)
        }
    }

    private var linkType: some View {
        VStack(alignment: .leading, spacing: 6) {
            DSLabel("Link type")
            DSSelect(
                options: Self.dayOptions.map {
                    .init(value: $0, label: $0 == 0 ? "Permanent — never expires" : "Limited — \($0) days",
                          symbol: $0 == 0 ? "infinity" : "clock")
                },
                selection: Binding(get: { days }, set: { renew($0) }),
                width: 240, height: 30)
            .disabled(busy)
            Text(status)
                .font(.dsMeta)
                .foregroundStyle(DS.muted)
            Text("Changing the type creates a new link; the previous one stops working.")
                .font(.dsMeta)
                .foregroundStyle(DS.muted)
        }
    }

    private var status: String {
        guard let link else { return "" }
        let kind = link.expiresAt.map {
            "Limited · expires \($0.formatted(.dateTime.day().month(.abbreviated).year()))"
        } ?? "Permanent · never expires"
        let opened = link.viewCount == 0
            ? "not opened yet"
            : "opened \(link.viewCount) time\(link.viewCount == 1 ? "" : "s")"
        return "\(kind) · \(opened)"
    }

    private var footer: some View {
        HStack(spacing: 8) {
            Button("Turn off link") {
                Task { if await turnOff() { onClose() } }
            }
            .buttonStyle(DSButtonStyle(kind: .ghost, height: 28))
            .foregroundStyle(DS.danger)
            .disabled(busy)
            Spacer()
            // Mail, Messages, AirDrop… — whatever the system offers.
            if let url {
                ShareLink(item: url, subject: Text(title), message: Text(title)) {
                    Label("Send…", systemImage: "square.and.arrow.up")
                }
                .buttonStyle(DSButtonStyle(kind: .secondary, height: 28))
                .disabled(busy)
            }
            Button("Done", action: onClose)
                .buttonStyle(DSButtonStyle(kind: .primary, height: 28))
                .keyboardShortcut(.defaultAction)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 12)
    }

    private func copy() {
        guard let url else { return }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(url.absoluteString, forType: .string)
        copied = true
        Task {
            try? await Task.sleep(for: .seconds(1.5))
            copied = false
        }
    }

    private func renew(_ next: Int) {
        guard next != days else { return }
        days = next
        copied = false
        Task { await renew(next == 0 ? nil : next) }
    }
}
