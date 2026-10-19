import SwiftUI

/// Where each navigable place (a headed section, a transcript mark) starts in the note's
/// scroll view, by navigator key.
struct SectionTopsKey: PreferenceKey {
    static let defaultValue: [String: CGFloat] = [:]
    static func reduce(value: inout [String: CGFloat], nextValue: () -> [String: CGFloat]) {
        value.merge(nextValue(), uniquingKeysWith: { $1 })
    }
}

/// The note's sections — or, on the transcript, marks along its time — as short marks on
/// the right edge (the current one darker), as on the web. Hovering opens the list;
/// hovering an entry tints its place, clicking scrolls to it. Fewer than two: nothing.
struct SectionNavView: View {
    struct Item: Identifiable, Equatable {
        let key: String
        let title: String
        var id: String { key }
    }

    let items: [Item]
    let active: String?
    @Binding var hovered: String?
    let onSelect: (String) -> Void
    @State private var open = false

    var body: some View {
        if items.count >= 2 {
            HStack(alignment: .top, spacing: 8) {
                if open { card.transition(.opacity.combined(with: .move(edge: .trailing))) }
                rail
            }
            .padding(.trailing, 12)
            .contentShape(Rectangle())
            .onHover { inside in
                withAnimation(.easeOut(duration: 0.12)) { open = inside }
                if !inside { hovered = nil }
            }
            .accessibilityElement(children: .contain)
            .accessibilityLabel("Sections of this note")
        }
    }

    private var rail: some View {
        VStack(spacing: 10) {
            ForEach(items) { item in
                Capsule()
                    .fill(item.key == active ? DS.text1 : DS.line)
                    .frame(width: 16, height: 2)
            }
        }
        .padding(.vertical, 6)
        .padding(.horizontal, 4)
        .accessibilityHidden(true)
    }

    private var card: some View {
        VStack(alignment: .leading, spacing: 2) {
            ForEach(items) { item in
                Button { onSelect(item.key) } label: {
                    Text(item.title)
                        .font(.ds(13))
                        .foregroundStyle(item.key == active ? DS.accentText : (hovered == item.key ? DS.text1 : DS.text3))
                        .multilineTextAlignment(.leading)
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, 10)
                        .padding(.vertical, 5)
                        .background(
                            RoundedRectangle(cornerRadius: DS.radiusSm, style: .continuous)
                                .fill(hovered == item.key ? DS.surface2 : .clear)
                        )
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .onHover { inside in hovered = inside ? item.key : (hovered == item.key ? nil : hovered) }
                .accessibilityAddTraits(item.key == active ? .isSelected : [])
            }
        }
        .padding(10)
        .frame(width: 240, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: DS.radiusLg, style: .continuous)
                .fill(DS.surface)
                .shadow(color: .black.opacity(0.12), radius: 14, y: 4)
        )
        .overlay(
            RoundedRectangle(cornerRadius: DS.radiusLg, style: .continuous)
                .strokeBorder(DS.line, lineWidth: 0.5)
        )
    }

    /// The transcript's marks: the first turn at or after each round interval (1, 2, 5, 10,
    /// 15, 20 or 30 minutes — the smallest giving at most `most` marks), labelled
    /// "12:30 · Anna — first words…". Keys are `t<startMs>`, the turn's scroll id.
    static func transcriptItems(_ turns: [TranscriptTurn], most: Int = 12,
                                speaker: (TranscriptTurn) -> String?) -> [Item] {
        guard let first = turns.first, let last = turns.last else { return [] }
        let minute = 60_000
        let span = max(1, last.startMs - first.startMs)
        let step = ([1, 2, 5, 10, 15, 20, 30].first { span / ($0 * minute) < most } ?? 60) * minute
        var out: [Item] = []
        var next = 0
        for turn in turns where turn.startMs >= next {
            let words = turn.paragraphs.joined(separator: " ").split(separator: " ").prefix(6)
            var title = elapsed(turn.startMs)
            if let name = speaker(turn) { title += " · \(name)" }
            if !words.isEmpty { title += " — " + words.joined(separator: " ") + "…" }
            out.append(Item(key: "t\(turn.startMs)", title: title))
            next = (turn.startMs / step + 1) * step
        }
        return out
    }

    /// `m:ss`, or `h:mm:ss` past an hour.
    static func elapsed(_ ms: Int) -> String {
        let s = max(0, ms) / 1000
        return s >= 3600
            ? String(format: "%d:%02d:%02d", s / 3600, s / 60 % 60, s % 60)
            : String(format: "%d:%02d", s / 60, s % 60)
    }

    /// The current section: the last whose top has passed `offset` below the top of the
    /// view. The last section rarely reaches the top: it is current once it starts in the
    /// upper half.
    static func current(_ items: [Item], tops: [String: CGFloat], viewHeight: CGFloat,
                        offset: CGFloat = 120) -> String? {
        var current = items.first?.key
        for item in items where (tops[item.key] ?? .infinity) <= offset { current = item.key }
        if let last = items.last, let top = tops[last.key], top < viewHeight / 2 {
            current = last.key
        }
        return current
    }
}
