import AppKit
import SwiftUI

// MARK: - Dropdown menus
//
// SwiftUI's `Menu` draws a native NSMenu that cannot take the design
// tokens. These widgets draw the web app's `.dropdown` instead: a surface
// panel with a hairline, 6 pt inset, 28 pt rows with a leading symbol, an
// optional trailing hint (a shortcut, a value), separators, and a danger
// tint for destructive rows. They open as transient popovers so they can
// hang off anything — a ⋯ button, an avatar, a select field.

struct DSMenuItem: Identifiable {
    enum Kind { case action, separator, header }

    let id = UUID()
    var kind: Kind = .action
    var title = ""
    var symbol: String?
    var hint: String?
    var danger = false
    var disabled = false
    var checked = false
    var action: () -> Void = {}

    static func item(_ title: String, symbol: String? = nil, hint: String? = nil,
                     danger: Bool = false, disabled: Bool = false, checked: Bool = false,
                     action: @escaping () -> Void) -> DSMenuItem {
        DSMenuItem(title: title, symbol: symbol, hint: hint, danger: danger,
                   disabled: disabled, checked: checked, action: action)
    }

    static let separator = DSMenuItem(kind: .separator)

    static func header(_ title: String, hint: String? = nil) -> DSMenuItem {
        DSMenuItem(kind: .header, title: title, hint: hint)
    }
}

/// The panel itself; `DSMenu` / `DSSelect` present it, but it can also sit
/// inside any popover.
struct DSMenuPanel: View {
    let items: [DSMenuItem]
    var width: CGFloat = 220
    let dismiss: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 1) {
            ForEach(items) { item in
                switch item.kind {
                case .separator:
                    DSDivider().padding(.vertical, 4).padding(.horizontal, -6)
                case .header:
                    VStack(alignment: .leading, spacing: 1) {
                        Text(item.title)
                            .font(.ds(12.5, .medium))
                            .foregroundStyle(DS.text1)
                            .lineLimit(1)
                        if let hint = item.hint {
                            Text(hint)
                                .font(.dsMono(10.5))
                                .foregroundStyle(DS.muted)
                                .lineLimit(1)
                        }
                    }
                    .padding(.horizontal, 8)
                    .padding(.vertical, 6)
                case .action:
                    DSMenuRow(item: item) {
                        dismiss()
                        item.action()
                    }
                }
            }
        }
        .padding(6)
        .frame(width: width)
        .background(DS.surface)
        .overlay(
            RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                .strokeBorder(DS.line, lineWidth: DS.hairline)
        )
    }
}

private struct DSMenuRow: View {
    let item: DSMenuItem
    let select: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: select) {
            HStack(spacing: 9) {
                if let symbol = item.symbol {
                    Image(systemName: symbol)
                        .font(.system(size: 12, weight: .medium))
                        .frame(width: 16)
                }
                Text(item.title)
                    .font(.ds(12.5))
                    .lineLimit(1)
                Spacer(minLength: 12)
                if item.checked {
                    Image(systemName: "checkmark")
                        .font(.system(size: 10, weight: .bold))
                        .foregroundStyle(DS.accentText)
                } else if let hint = item.hint {
                    Text(hint)
                        .font(.dsMono(10.5))
                        .foregroundStyle(DS.muted)
                }
            }
            .foregroundStyle(item.danger ? DS.dangerText : DS.text1)
            .padding(.horizontal, 8)
            .frame(height: 28)
            .background(
                RoundedRectangle(cornerRadius: 6, style: .continuous)
                    .fill(hover ? (item.danger ? DS.dangerSoft : DS.surface2) : .clear)
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(item.disabled)
        .opacity(item.disabled ? 0.45 : 1)
        .onHover { hover = $0 }
    }
}

/// An overflow menu behind any label — by default the ⋯ icon button.
struct DSMenu<Label: View>: View {
    let items: () -> [DSMenuItem]
    var width: CGFloat = 220
    var edge: Edge = .bottom
    @ViewBuilder let label: () -> Label

    @State private var open = false

    init(width: CGFloat = 220, edge: Edge = .bottom,
         items: @escaping () -> [DSMenuItem], @ViewBuilder label: @escaping () -> Label) {
        self.items = items
        self.width = width
        self.edge = edge
        self.label = label
    }

    var body: some View {
        Button {
            open.toggle()
        } label: {
            label()
        }
        .buttonStyle(.plain)
        .popover(isPresented: $open, arrowEdge: edge) {
            DSMenuPanel(items: items(), width: width) { open = false }
        }
    }
}

extension DSMenu where Label == DSMoreLabel {
    /// The standard ⋯ trigger.
    init(width: CGFloat = 220, edge: Edge = .bottom, dim: Bool = false,
         items: @escaping () -> [DSMenuItem]) {
        self.init(width: width, edge: edge, items: items) { DSMoreLabel(dim: dim) }
    }
}

struct DSMoreLabel: View {
    var dim = false
    @State private var hover = false

    var body: some View {
        Image(systemName: "ellipsis")
            .font(.ds(13, .semibold))
            .foregroundStyle(hover ? DS.text1 : (dim ? DS.muted : DS.text3))
            .frame(width: 26, height: 26)
            .background(
                RoundedRectangle(cornerRadius: 7, style: .continuous)
                    .fill(hover ? DS.surface2 : .clear)
            )
            .contentShape(Rectangle())
            .onHover { hover = $0 }
            .help("More actions")
    }
}

/// A select field: the current value in an input-shaped button, the
/// options in the same dropdown panel with a check on the chosen one.
struct DSSelect<T: Hashable>: View {
    struct Option {
        let value: T
        let label: String
        var symbol: String? = nil
        var hint: String? = nil
    }

    let options: [Option]
    @Binding var selection: T
    var width: CGFloat? = nil
    var height: CGFloat = 30

    @State private var open = false
    @State private var hover = false

    var body: some View {
        Button {
            open.toggle()
        } label: {
            HStack(spacing: 7) {
                if let symbol = current?.symbol {
                    Image(systemName: symbol)
                        .font(.system(size: 11.5, weight: .medium))
                        .foregroundStyle(DS.text3)
                }
                Text(current?.label ?? "—")
                    .font(.ds(12.5, .medium))
                    .foregroundStyle(DS.text1)
                    .lineLimit(1)
                Spacer(minLength: 6)
                Image(systemName: "chevron.up.chevron.down")
                    .font(.system(size: 9, weight: .semibold))
                    .foregroundStyle(DS.muted)
            }
            .padding(.leading, 10)
            .padding(.trailing, 8)
            .frame(height: height)
            .frame(width: width)
            .background(
                RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                    .fill(hover || open ? DS.surface2 : DS.surface)
            )
            .overlay(
                RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                    .strokeBorder(open ? DS.text3 : DS.line, lineWidth: open ? 1 : DS.hairline)
            )
            .contentShape(RoundedRectangle(cornerRadius: DS.radius, style: .continuous))
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .popover(isPresented: $open, arrowEdge: .bottom) {
            DSMenuPanel(items: options.map { option in
                .item(option.label, symbol: option.symbol, hint: option.hint,
                      checked: option.value == selection) {
                    selection = option.value
                }
            }, width: max(width ?? 0, 180)) { open = false }
        }
    }

    private var current: Option? {
        options.first { $0.value == selection }
    }
}
