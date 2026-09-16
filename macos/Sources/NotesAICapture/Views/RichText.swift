import SwiftUI

// MARK: - Markdown-lite → blocks
//
// A generated note is not flat prose: it arrives as headings, nested
// bullets, numbered decisions, checkbox action items and bold run-in
// leads. The PDF has always typeset that (note-service's
// `domain/pdf_richtext.py`); on screen it was shown as one plain string,
// so the reader saw the raw `- ` and `**…**` instead of a document.
//
// This is the same grammar the PDF and the web app read, plus nesting:
// indentation puts a bullet at a depth, and the renderer draws a
// different glyph per level. The web twin is `web/src/lib/richText.ts`
// and `web/src/components/RichText.tsx` — the three are meant to agree,
// so a change to one belongs in all of them.
//
// Parsing is a pure function of the input string: no time, no locale.

/// One run of inline text with at most one emphasis on it.
struct RichSpan: Equatable {
    var text: String
    var bold = false
    var italic = false
    var code = false
}

/// One item of a list, flattened: `depth` carries the indent the author
/// typed, so the renderer can lay the whole list out in one column.
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
}

// MARK: - Parser

enum RichText {
    /// The most levels of nesting the renderer draws; deeper indents all
    /// land on the last one rather than marching off the page.
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
        // The patterns are literals in this file; one that does not compile
        // is a bug to fix here, not a condition to handle at run time.
        // swiftlint:disable:next force_try
        try! NSRegularExpression(pattern: pattern)
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

    /// Parse one section body into blocks. Single newlines are soft wraps
    /// inside a paragraph; a blank line starts a new block — which is how
    /// the note editor's plain-text fields behave.
    static func parse(_ text: String) -> [RichBlock] {
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return [] }

        let lines = text.replacingOccurrences(of: "\r\n", with: "\n")
            .replacingOccurrences(of: "\r", with: "\n")
            .components(separatedBy: "\n")
        var kinds: [RichBlockKind] = []
        var para: [String] = []
        var items: [RichListItem] = []
        /// Indent columns seen so far in the open list, innermost last.
        var columns: [Int] = []

        func flushPara() {
            let body = para.map { $0.trimmingCharacters(in: .whitespaces) }
                .filter { !$0.isEmpty }
                .joined(separator: " ")
            para = []
            if !body.isEmpty { kinds.append(.paragraph(spans: spans(body))) }
        }

        func flushList() {
            kinds.append(contentsOf: items.map { RichBlockKind.item($0) })
            items = []
            columns = []
        }

        func flush() {
            flushPara()
            flushList()
        }

        /// Where an indent sits in the open list — capped, so one stray
        /// space cannot push a bullet three levels deep.
        func depth(for column: Int) -> Int {
            while let top = columns.last, column < top { columns.removeLast() }
            if columns.last.map({ column > $0 }) ?? true { columns.append(column) }
            return min(columns.count - 1, maxDepth)
        }

        func push(_ item: RichListItem, at column: Int) {
            flushPara()
            var item = item
            item.depth = depth(for: column)
            items.append(item)
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
                    kinds.append(.table(
                        head: cells(header).map(spans),
                        rows: body.dropFirst().map { cells($0).map(spans) }))
                }
                continue
            }

            if matches(rule, line) != nil {
                flush()
                kinds.append(.rule)
                i += 1
                continue
            }

            if let m = matches(heading, line), let hashes = m[1], let body = m[2] {
                flush()
                // h1/h2 belong to the document chrome, so the body starts at h3.
                kinds.append(.heading(level: min(hashes.count + 2, 4), spans: spans(body)))
                i += 1
                continue
            }

            if let m = matches(check, line), let box = m[2], let body = m[3] {
                push(RichListItem(spans: spans(body), depth: 0, ordered: false, done: box.lowercased() == "x"),
                     at: indent(of: m[1] ?? ""))
                i += 1
                continue
            }

            if let m = matches(bullet, line), let body = m[2] {
                push(RichListItem(spans: spans(body), depth: 0, ordered: false), at: indent(of: m[1] ?? ""))
                i += 1
                continue
            }

            if let m = matches(ordered, line), let body = m[3] {
                push(RichListItem(spans: spans(body), depth: 0, ordered: true, number: Int(m[2] ?? "")),
                     at: indent(of: m[1] ?? ""))
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
                kinds.append(.quote(spans: spans(body.joined(separator: " "))))
                continue
            }

            // A continuation line under an open list belongs to its last item.
            if !items.isEmpty, line.first == " " || line.first == "\t" {
                items[items.count - 1].spans.append(
                    RichSpan(text: " " + line.trimmingCharacters(in: .whitespaces)))
                i += 1
                continue
            }

            flushList()
            para.append(line)
            i += 1
        }

        flush()
        return kinds.enumerated().map { RichBlock(id: $0.offset, kind: $0.element) }
    }

    /// A one-line preview of a body — the first line with words in it,
    /// with the markup stripped.
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

/// A note section, typeset. Headings, nested bullets, checklists, quotes
/// and small tables come out as real structure instead of the raw `- `
/// and `**…**` a plain string used to show.
struct RichTextView: View {
    let text: String
    var size: CGFloat = 13.5
    /// Shown in place of an empty body.
    var placeholder: String = "Nothing entered."

    private var blocks: [RichBlock] { RichText.parse(text) }

    var body: some View {
        if blocks.isEmpty {
            Text(placeholder)
                .font(.ds(size))
                .foregroundStyle(DS.muted)
                .frame(maxWidth: .infinity, alignment: .leading)
        } else {
            VStack(alignment: .leading, spacing: 0) {
                ForEach(Array(blocks.enumerated()), id: \.element.id) { index, block in
                    row(block, after: index == 0 ? nil : blocks[index - 1].kind)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    @ViewBuilder
    private func row(_ block: RichBlock, after previous: RichBlockKind?) -> some View {
        content(block.kind)
            .padding(.top, gap(before: block.kind, after: previous))
    }

    /// The rhythm of the document: tight between the items of one list,
    /// open around a heading, ordinary between paragraphs.
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
    private func content(_ kind: RichBlockKind) -> some View {
        switch kind {
        case .heading(let level, let spans):
            Text(attributed(spans, size: level == 3 ? size + 1 : size, weight: .semibold))
                .font(.dsDisplay(level == 3 ? size + 1 : size, .semibold))
                .foregroundStyle(level == 3 ? DS.text1 : DS.text2)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)

        case .paragraph(let spans):
            body(spans)

        case .item(let item):
            HStack(alignment: .firstTextBaseline, spacing: 7) {
                marker(item)
                body(item.spans)
            }
            .padding(.leading, CGFloat(item.depth) * 16)

        case .quote(let spans):
            HStack(spacing: 10) {
                Rectangle()
                    .fill(DS.line)
                    .frame(width: 2)
                body(spans, color: DS.text2)
            }
            .fixedSize(horizontal: false, vertical: true)

        case .rule:
            DSDivider()

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
        }
    }

    private func tableRow(_ cells: [[RichSpan]], header: Bool) -> some View {
        HStack(alignment: .top, spacing: 0) {
            ForEach(Array(cells.enumerated()), id: \.offset) { _, cell in
                Text(attributed(cell, size: size - 1, weight: header ? .semibold : .regular))
                    .font(.ds(size - 1, header ? .semibold : .regular))
                    .foregroundStyle(header ? DS.text2 : DS.text1)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 6)
            }
        }
    }

    private func body(_ spans: [RichSpan], color: Color = DS.text1) -> some View {
        Text(attributed(spans, size: size, weight: .regular))
            .font(.ds(size))
            .foregroundStyle(color)
            .lineSpacing(3)
            .textSelection(.enabled)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    /// Three bullet glyphs, one per level, the way an outline is drawn on
    /// paper: filled, then hollow, then a dash — and a real box for a
    /// checklist, ticked or not.
    @ViewBuilder
    private func marker(_ item: RichListItem) -> some View {
        if let done = item.done {
            Image(systemName: done ? "checkmark.square.fill" : "square")
                .font(.system(size: size - 1.5, weight: .regular))
                .foregroundStyle(done ? DS.accent : DS.text3)
                .frame(width: 14, alignment: .leading)
        } else if item.ordered {
            Text("\(item.number ?? 1).")
                .font(.ds(size - 1.5))
                .monospacedDigit()
                .foregroundStyle(DS.muted)
                .frame(width: 16, alignment: .trailing)
        } else {
            bulletGlyph(depth: item.depth)
                .frame(width: 14, alignment: .leading)
        }
    }

    @ViewBuilder
    private func bulletGlyph(depth: Int) -> some View {
        switch depth {
        case 0:
            Circle().fill(DS.muted).frame(width: 4, height: 4).offset(y: -1)
        case 1:
            Circle().strokeBorder(DS.muted, lineWidth: 1).frame(width: 5, height: 5).offset(y: -1)
        default:
            Rectangle().fill(DS.muted).frame(width: 6, height: 1.5).offset(y: -3)
        }
    }

    /// Build the run-level attributes. The size is passed in rather than
    /// read off the view so a heading's bold is a heading-sized bold.
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
