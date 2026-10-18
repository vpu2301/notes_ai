import AppKit
import SwiftUI

// MARK: - Markdown-lite → blocks
//
// The same grammar the PDF (`domain/pdf_richtext.py`) and the web app read, plus
// nesting by indentation. The web twin is `web/src/lib/richText.ts` and
// `web/src/components/RichText.tsx`; the three are meant to agree. Pure function of the input.

/// One run of inline text with at most one emphasis on it.
struct RichSpan: Equatable {
    var text: String
    var bold = false
    var italic = false
    var code = false
}

/// One item of a list, flattened: `depth` carries the indent the author typed.
struct RichListItem: Equatable {
    var spans: [RichSpan]
    var depth: Int
    var ordered: Bool
    var number: Int?
    /// Set only on checklist items.
    var done: Bool?
}

enum RichBlockKind: Equatable {
    case heading(level: Int, spans: [RichSpan])
    case paragraph(spans: [RichSpan])
    case item(RichListItem)
    case quote(spans: [RichSpan])
    case rule
    case table(head: [[RichSpan]], rows: [[[RichSpan]]])
}

struct RichBlock: Identifiable, Equatable {
    let id: Int
    let kind: RichBlockKind
    /// The source line of a paragraph or list item, markup and all — what the evidence is keyed by. Nil for other kinds.
    var raw: String? = nil
}

// MARK: - Parser

enum RichText {
    /// The most levels of nesting drawn; deeper indents land on the last one.
    static let maxDepth = 4

    private static let heading = regex(#"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$"#)
    private static let check = regex(#"^(\s*)(?:[-*+•])\s*\[([ xX])\]\s+(.*)$"#)
    private static let bullet = regex(#"^(\s*)(?:[-*+•‣–])\s+(.*)$"#)
    private static let ordered = regex(#"^(\s*)(\d{1,3})[.)]\s+(.*)$"#)
    private static let quote = regex(#"^\s{0,3}>\s?(.*)$"#)
    private static let rule = regex(#"^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$"#)
    private static let tableSep = regex(#"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)+\|?\s*$"#)
    private static let inline = regex([
        #"`([^`\n]+)`"#,                               // code
        #"\*\*(\S(?:[^*]*\S)?)\*\*"#,                  // **bold**
        #"(?<![\w*])\*(\S(?:[^*\n]*\S)?)\*(?![\w*])"#, // *italic*
        #"(?<![\w_])_(\S(?:[^_\n]*\S)?)_(?![\w_])"#,   // _italic_
    ].joined(separator: "|"))

    private static func regex(_ pattern: String) -> NSRegularExpression {
        // The patterns are literals here; one that does not compile is a bug, named as such.
        guard let compiled = try? NSRegularExpression(pattern: pattern) else {
            preconditionFailure("RichText: pattern does not compile: \(pattern)")
        }
        return compiled
    }

    /// Split one line into runs, marking code, bold and italic.
    static func spans(_ text: String) -> [RichSpan] {
        let ns = text as NSString
        var out: [RichSpan] = []
        var cursor = 0
        for match in inline.matches(in: text, range: NSRange(location: 0, length: ns.length)) {
            if match.range.location > cursor {
                out.append(RichSpan(text: ns.substring(with: NSRange(location: cursor, length: match.range.location - cursor))))
            }
            if let code = group(match, 1, ns) {
                out.append(RichSpan(text: code, code: true))
            } else if let bold = group(match, 2, ns) {
                out.append(RichSpan(text: bold, bold: true))
            } else if let italic = group(match, 3, ns) ?? group(match, 4, ns) {
                out.append(RichSpan(text: italic, italic: true))
            }
            cursor = match.range.location + match.range.length
        }
        if cursor < ns.length {
            out.append(RichSpan(text: ns.substring(from: cursor)))
        }
        return out.isEmpty ? [RichSpan(text: text)] : out
    }

    private static func group(_ match: NSTextCheckingResult, _ index: Int, _ ns: NSString) -> String? {
        guard index < match.numberOfRanges else { return nil }
        let range = match.range(at: index)
        return range.location == NSNotFound ? nil : ns.substring(with: range)
    }

    private static func matches(_ expression: NSRegularExpression, _ line: String) -> [String?]? {
        let ns = line as NSString
        guard let match = expression.firstMatch(in: line, range: NSRange(location: 0, length: ns.length)) else {
            return nil
        }
        return (0..<match.numberOfRanges).map { group(match, $0, ns) }
    }

    /// How far a line is indented, tabs counting as four columns.
    private static func indent(of prefix: String) -> Int {
        prefix.replacingOccurrences(of: "\t", with: "    ").count
    }

    private static func cells(_ line: String) -> [String] {
        var body = line.trimmingCharacters(in: .whitespaces)
        if body.hasPrefix("|") { body.removeFirst() }
        if body.hasSuffix("|") { body.removeLast() }
        return body.components(separatedBy: "|").map { $0.trimmingCharacters(in: .whitespaces) }
    }

    private static func isTable(_ lines: ArraySlice<String>) -> Bool {
        guard lines.count >= 2 else { return false }
        let first = lines[lines.startIndex]
        let second = lines[lines.index(after: lines.startIndex)]
        return first.contains("|") && matches(tableSep, second) != nil
    }

    /// Parse one section body into blocks. Single newlines are soft wraps; a blank line starts a new block.
    static func parse(_ text: String) -> [RichBlock] {
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return [] }

        let lines = text.replacingOccurrences(of: "\r\n", with: "\n")
            .replacingOccurrences(of: "\r", with: "\n")
            .components(separatedBy: "\n")
        var kinds: [(kind: RichBlockKind, raw: String?)] = []
        var para: [String] = []
        var items: [(item: RichListItem, raw: String)] = []
        /// Indent columns seen so far in the open list, innermost last.
        var columns: [Int] = []

        func flushPara() {
            let body = para.map { $0.trimmingCharacters(in: .whitespaces) }
                .filter { !$0.isEmpty }
                .joined(separator: " ")
            para = []
            if !body.isEmpty { kinds.append((.paragraph(spans: spans(body)), body)) }
        }

        func flushList() {
            kinds.append(contentsOf: items.map { (RichBlockKind.item($0.item), $0.raw) })
            items = []
            columns = []
        }

        func flush() {
            flushPara()
            flushList()
        }

        /// Where an indent sits in the open list — capped, so one stray space cannot push a bullet three levels deep.
        func depth(for column: Int) -> Int {
            while let top = columns.last, column < top { columns.removeLast() }
            if columns.last.map({ column > $0 }) ?? true { columns.append(column) }
            return min(columns.count - 1, maxDepth)
        }

        func push(_ item: RichListItem, at column: Int, raw: String) {
            flushPara()
            var item = item
            item.depth = depth(for: column)
            items.append((item, raw))
        }

        var i = 0
        while i < lines.count {
            let line = lines[i]

            if line.trimmingCharacters(in: .whitespaces).isEmpty {
                flush()
                i += 1
                continue
            }

            if isTable(lines[i...]) {
                flush()
                var block: [String] = []
                while i < lines.count, lines[i].contains("|"), !lines[i].trimmingCharacters(in: .whitespaces).isEmpty {
                    block.append(lines[i])
                    i += 1
                }
                let body = block.filter { matches(tableSep, $0) == nil }
                if let header = body.first {
                    kinds.append((.table(
                        head: cells(header).map(spans),
                        rows: body.dropFirst().map { cells($0).map(spans) }), nil))
                }
                continue
            }

            if matches(rule, line) != nil {
                flush()
                kinds.append((.rule, nil))
                i += 1
                continue
            }

            if let m = matches(heading, line), let hashes = m[1], let body = m[2] {
                flush()
                // h1/h2 belong to the document chrome, so the body starts at h3.
                kinds.append((.heading(level: min(hashes.count + 2, 4), spans: spans(body)), nil))
                i += 1
                continue
            }

            if let m = matches(check, line), let box = m[2], let body = m[3] {
                push(RichListItem(spans: spans(body), depth: 0, ordered: false, done: box.lowercased() == "x"),
                     at: indent(of: m[1] ?? ""), raw: line)
                i += 1
                continue
            }

            if let m = matches(bullet, line), let body = m[2] {
                push(RichListItem(spans: spans(body), depth: 0, ordered: false), at: indent(of: m[1] ?? ""), raw: line)
                i += 1
                continue
            }

            if let m = matches(ordered, line), let body = m[3] {
                push(RichListItem(spans: spans(body), depth: 0, ordered: true, number: Int(m[2] ?? "")),
                     at: indent(of: m[1] ?? ""), raw: line)
                i += 1
                continue
            }

            if let m = matches(quote, line) {
                var body = [m[1] ?? ""]
                i += 1
                while i < lines.count, let next = matches(quote, lines[i]) {
                    body.append(next[1] ?? "")
                    i += 1
                }
                flush()
                kinds.append((.quote(spans: spans(body.joined(separator: " "))), nil))
                continue
            }

            // A continuation line under an open list belongs to its last item.
            if !items.isEmpty, line.first == " " || line.first == "\t" {
                items[items.count - 1].item.spans.append(
                    RichSpan(text: " " + line.trimmingCharacters(in: .whitespaces)))
                items[items.count - 1].raw += " " + line.trimmingCharacters(in: .whitespaces)
                i += 1
                continue
            }

            flushList()
            para.append(line)
            i += 1
        }

        flush()
        return kinds.enumerated().map { RichBlock(id: $0.offset, kind: $0.element.kind, raw: $0.element.raw) }
    }

    /// A one-line preview of a body: the first line with words in it, markup stripped.
    static func preview(_ text: String, limit: Int = 160) -> String {
        for block in parse(text) {
            let runs: [RichSpan]
            switch block.kind {
            case .heading(_, let spans), .paragraph(let spans), .quote(let spans): runs = spans
            case .item(let item): runs = item.spans
            case .rule, .table: continue
            }
            let flat = runs.map(\.text).joined().trimmingCharacters(in: .whitespaces)
            if !flat.isEmpty {
                return flat.count > limit ? String(flat.prefix(limit - 1)) + "…" : flat
            }
        }
        return ""
    }
}

// MARK: - Rendering

/// A note section, typeset: headings, nested bullets, checklists, quotes and small tables as real structure.
/// Runs of text blocks are one text view each, so a drag selects across lines like a document.
struct RichTextView: View {
    let text: String
    var size: CGFloat = 13.5
    /// Shown in place of an empty body.
    var placeholder: String = "Nothing entered."
    /// Drawn at the end of each paragraph and list item, from its source line — the evidence chip. Nil draws nothing.
    var lineExtra: ((String) -> AnyView?)? = nil

    private var blocks: [RichBlock] { RichText.parse(text) }

    /// Consecutive text blocks share one selectable flow; a rule or table stands alone.
    private enum Segment: Identifiable {
        case flow([RichBlock])
        case single(RichBlock)

        var id: Int {
            switch self {
            case .flow(let blocks): return blocks[0].id
            case .single(let block): return block.id
            }
        }
        var first: RichBlock {
            switch self {
            case .flow(let blocks): return blocks[0]
            case .single(let block): return block
            }
        }
    }

    private var segments: [Segment] {
        var out: [Segment] = []
        var run: [RichBlock] = []
        for block in blocks {
            switch block.kind {
            case .rule, .table:
                if !run.isEmpty { out.append(.flow(run)); run = [] }
                out.append(.single(block))
            default:
                run.append(block)
            }
        }
        if !run.isEmpty { out.append(.flow(run)) }
        return out
    }

    var body: some View {
        if blocks.isEmpty {
            Text(placeholder)
                .font(.ds(size))
                .foregroundStyle(DS.muted)
                .frame(maxWidth: .infinity, alignment: .leading)
        } else {
            let all = blocks
            VStack(alignment: .leading, spacing: 0) {
                ForEach(segments) { segment in
                    let index = segment.first.id
                    Group {
                        switch segment {
                        case .flow(let run):
                            SelectableFlow(blocks: run, size: size, lineExtra: lineExtra, gap: gap)
                        case .single(let block):
                            single(block.kind)
                        }
                    }
                    .padding(.top, gap(before: segment.first.kind, after: index == 0 ? nil : all[index - 1].kind))
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    /// Tight between the items of one list, open around a heading, ordinary between paragraphs.
    private func gap(before kind: RichBlockKind, after previous: RichBlockKind?) -> CGFloat {
        guard let previous else { return 0 }
        switch (previous, kind) {
        case (.item, .item): return 3
        case (_, .heading): return 16
        case (_, .rule): return 12
        case (_, .table): return 10
        case (.heading, _): return 6
        case (_, .item): return 6
        default: return 9
        }
    }

    @ViewBuilder
    private func single(_ kind: RichBlockKind) -> some View {
        switch kind {
        case .table(let head, let rows):
            VStack(alignment: .leading, spacing: 0) {
                tableRow(head, header: true)
                ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                    DSDivider()
                    tableRow(row, header: false)
                }
            }
            .overlay(
                RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                    .strokeBorder(DS.line, lineWidth: DS.hairline))
        default:
            DSDivider()
        }
    }

    private func tableRow(_ cells: [[RichSpan]], header: Bool) -> some View {
        HStack(alignment: .top, spacing: 0) {
            ForEach(Array(cells.enumerated()), id: \.offset) { _, cell in
                Text(attributed(cell, size: size - 1, weight: header ? .semibold : .regular))
                    .font(.ds(size - 1, header ? .semibold : .regular))
                    .foregroundStyle(header ? DS.text2 : DS.text1)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 6)
            }
        }
    }

    /// The run-level attributes. The size is passed in so a heading's bold is heading-sized.
    private func attributed(_ spans: [RichSpan], size: CGFloat, weight: Font.Weight) -> AttributedString {
        var out = AttributedString()
        for span in spans {
            var run = AttributedString(span.text)
            if span.code {
                run.font = .dsMono(size - 1.5)
            } else if span.bold {
                run.font = .ds(size, .semibold)
            } else if span.italic {
                run.font = .ds(size, weight).italic()
            }
            out.append(run)
        }
        return out
    }
}

// MARK: - One selectable flow

/// Headings, paragraphs, list items and quotes as one read-only text view. The
/// evidence chip of a line rides at its end as a live view, never as text, so
/// copying a line never carries it along.
private struct SelectableFlow: NSViewRepresentable {
    let blocks: [RichBlock]
    let size: CGFloat
    let lineExtra: ((String) -> AnyView?)?
    let gap: (RichBlockKind, RichBlockKind?) -> CGFloat

    /// What the text view was last built from; the chips update themselves, so
    /// only a change here rebuilds (and an open evidence popover stays open).
    struct Key: Equatable {
        var blocks: [RichBlock]
        var size: CGFloat
        var extras: [Bool]
    }

    final class Coordinator {
        var key: Key?
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeNSView(context: Context) -> NSTextView {
        let view = FlowTextView(usingTextLayoutManager: true)
        view.isEditable = false
        view.isSelectable = true
        view.drawsBackground = false
        view.isRichText = true
        view.textContainerInset = .zero
        view.textContainer?.lineFragmentPadding = 0
        view.textContainer?.widthTracksTextView = true
        view.isVerticallyResizable = false
        view.isHorizontallyResizable = false
        view.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        return view
    }

    func updateNSView(_ view: NSTextView, context: Context) {
        let extras = blocks.map { block in block.raw.flatMap { lineExtra?($0) } }
        let key = Key(blocks: blocks, size: size, extras: extras.map { $0 != nil })
        guard key != context.coordinator.key else { return }
        context.coordinator.key = key
        view.textStorage?.setAttributedString(build(extras))
    }

    func sizeThatFits(_ proposal: ProposedViewSize, nsView view: NSTextView, context: Context) -> CGSize? {
        let width = proposal.width.flatMap { $0.isFinite ? $0 : nil } ?? 480
        view.textContainer?.size = NSSize(width: width, height: .greatestFiniteMagnitude)
        guard let layout = view.textLayoutManager else { return nil }
        layout.ensureLayout(for: layout.documentRange)
        return CGSize(width: width, height: ceil(layout.usageBoundsForTextContainer.height))
    }

    // MARK: Typesetting

    private static let marker: CGFloat = 21

    private func build(_ extras: [AnyView?]) -> NSAttributedString {
        let out = NSMutableAttributedString()
        for (index, block) in blocks.enumerated() {
            let style = NSMutableParagraphStyle()
            style.paragraphSpacingBefore = index == 0 ? 0 : gap(block.kind, blocks[index - 1].kind)
            let line = NSMutableAttributedString()
            switch block.kind {
            case .heading(let level, let spans):
                let size = level == 3 ? self.size + 1 : self.size
                line.append(runs(spans, size: size, weight: .semibold, color: level == 3 ? DS.text1 : DS.text2))
            case .paragraph(let spans):
                style.lineSpacing = 3
                line.append(runs(spans, size: size, weight: .regular, color: DS.text1))
            case .item(let item):
                let lead = CGFloat(item.depth) * 16
                style.lineSpacing = 3
                style.firstLineHeadIndent = lead
                style.headIndent = lead + Self.marker
                style.tabStops = [NSTextTab(textAlignment: .left, location: lead + Self.marker)]
                line.append(marker(item))
                line.append(runs(item.spans, size: size, weight: .regular, color: DS.text1))
            case .quote(let spans):
                style.lineSpacing = 3
                style.firstLineHeadIndent = 12
                style.headIndent = 12
                line.append(runs(spans, size: size, weight: .regular, color: DS.text2))
            case .rule, .table:
                continue
            }
            if let extra = extras[index] {
                line.append(NSAttributedString(string: " ", attributes: [.font: Self.font(size, .regular)]))
                line.append(NSAttributedString(attachment: HostedAttachment(extra, font: Self.font(size, .regular))))
            }
            if index < blocks.count - 1 { line.append(NSAttributedString(string: "\n")) }
            line.addAttribute(.paragraphStyle, value: style, range: NSRange(location: 0, length: line.length))
            out.append(line)
        }
        return out
    }

    /// Three bullet glyphs, one per level (filled, hollow, dash), a box for a checklist, the number for an ordered item.
    private func marker(_ item: RichListItem) -> NSAttributedString {
        let glyph: String
        var color = DS.muted
        if let done = item.done {
            glyph = done ? "☑" : "☐"
            color = done ? DS.accent : DS.text3
        } else if item.ordered {
            glyph = "\(item.number ?? 1)."
        } else {
            glyph = ["•", "◦", "–"][min(item.depth, 2)]
        }
        return NSAttributedString(string: glyph + "\t", attributes: [
            .font: Self.font(size - 1.5, .regular),
            .foregroundColor: NSColor(color),
        ])
    }

    private func runs(_ spans: [RichSpan], size: CGFloat, weight: Font.Weight, color: Color) -> NSAttributedString {
        let out = NSMutableAttributedString()
        for span in spans {
            var font = Self.font(size, span.bold ? .semibold : weight)
            if span.code {
                font = .monospacedSystemFont(ofSize: size - 1.5, weight: .regular)
            } else if span.italic {
                font = NSFontManager.shared.convert(font, toHaveTrait: .italicFontMask)
            }
            out.append(NSAttributedString(string: span.text, attributes: [
                .font: font,
                .foregroundColor: NSColor(color),
            ]))
        }
        return out
    }

    private static func font(_ size: CGFloat, _ weight: Font.Weight) -> NSFont {
        NSFont(name: DSType.face(weight), size: size) ?? .systemFont(ofSize: size)
    }
}

/// Copies plain words only: the chips are attachments and stay behind.
private final class FlowTextView: NSTextView {
    override func copy(_ sender: Any?) {
        guard let storage = textStorage else { return }
        let words = selectedRanges.map { storage.attributedSubstring(from: $0.rangeValue).string }
            .joined(separator: "\n")
            .replacingOccurrences(of: " \u{FFFC}", with: "")
            .replacingOccurrences(of: "\u{FFFC}", with: "")
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(words, forType: .string)
    }
}

/// A SwiftUI view laid out inline in the text, sized to fit and centred on the line.
private final class HostedAttachment: NSTextAttachment {
    let host: NSHostingView<AnyView>

    init(_ content: AnyView, font: NSFont) {
        host = NSHostingView(rootView: content)
        super.init(data: nil, ofType: nil)
        let fit = host.fittingSize
        host.frame.size = fit
        bounds = CGRect(x: 0, y: (font.capHeight - fit.height) / 2, width: fit.width, height: fit.height)
    }

    required init?(coder: NSCoder) { nil }

    override func viewProvider(
        for parentView: NSView?, location: NSTextLocation, textContainer: NSTextContainer?
    ) -> NSTextAttachmentViewProvider? {
        HostedProvider(textAttachment: self, parentView: parentView,
                       textLayoutManager: textContainer?.textLayoutManager, location: location)
    }
}

private final class HostedProvider: NSTextAttachmentViewProvider {
    override func loadView() {
        view = (textAttachment as? HostedAttachment)?.host
    }
}
