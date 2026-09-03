import SwiftUI

// MARK: - Dropdown menus
//
// The Mac app draws its own dropdown panels; on the phone the native
// context menu is the right thing — it is what every ⋯ button on iOS
// opens, it handles small screens, and it takes symbols, subtitles,
// sections and a destructive tint. These wrappers keep the Mac app's
// `DSMenuItem` shape so the screens describe menus the same way.

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

/// The rows of a menu, from the item list. Separators become sections.
struct DSMenuContent: View {
    let items: [DSMenuItem]

    var body: some View {
        ForEach(Array(sections.enumerated()), id: \.offset) { _, section in
            Section {
                ForEach(section) { item in
                    row(item)
                }
            }
        }
    }

    private var sections: [[DSMenuItem]] {
        var out: [[DSMenuItem]] = [[]]
        for item in items {
            if item.kind == .separator {
                if !(out.last?.isEmpty ?? true) { out.append([]) }
            } else {
                out[out.count - 1].append(item)
            }
        }
        return out.filter { !$0.isEmpty }
    }

    @ViewBuilder
    private func row(_ item: DSMenuItem) -> some View {
        switch item.kind {
        case .header:
            Button {} label: {
                Text(item.title)
                if let hint = item.hint { Text(hint) }
            }
            .disabled(true)
        case .action:
            if item.checked {
                Toggle(isOn: Binding(get: { true }, set: { _ in item.action() })) {
                    label(item)
                }
                .disabled(item.disabled)
            } else {
                Button(role: item.danger ? .destructive : nil, action: item.action) {
                    label(item)
                }
                .disabled(item.disabled)
            }
        case .separator:
            EmptyView()
        }
    }

    @ViewBuilder
    private func label(_ item: DSMenuItem) -> some View {
        if let symbol = item.symbol {
            Label {
                Text(item.title)
                if let hint = item.hint { Text(hint) }
            } icon: {
                Image(systemName: symbol)
            }
        } else {
            Text(item.title)
            if let hint = item.hint { Text(hint) }
        }
    }
}

/// An overflow menu behind any label — by default the ⋯ icon button.
struct DSMenu<Label: View>: View {
    let items: () -> [DSMenuItem]
    @ViewBuilder let label: () -> Label

    init(items: @escaping () -> [DSMenuItem], @ViewBuilder label: @escaping () -> Label) {
        self.items = items
        self.label = label
    }

    var body: some View {
        Menu {
            DSMenuContent(items: items())
        } label: {
            label()
        }
        .menuIndicator(.hidden)
    }
}

extension DSMenu where Label == DSMoreLabel {
    /// The standard ⋯ trigger.
    init(dim: Bool = false, items: @escaping () -> [DSMenuItem]) {
        self.init(items: items) { DSMoreLabel(dim: dim) }
    }
}

struct DSMoreLabel: View {
    var dim = false

    var body: some View {
        Image(systemName: "ellipsis")
            .font(.ds(15, .semibold))
            .foregroundStyle(dim ? DS.muted : DS.text3)
            .frame(width: 34, height: 34)
            .contentShape(Rectangle())
            .accessibilityLabel("More actions")
    }
}

/// A select field: the current value in an input-shaped button, the
/// options in a menu with a check on the chosen one.
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
    var height: CGFloat = 38

    var body: some View {
        Menu {
            ForEach(Array(options.enumerated()), id: \.offset) { _, option in
                Button {
                    selection = option.value
                } label: {
                    if option.value == selection {
                        Label(option.label, systemImage: "checkmark")
                    } else if let symbol = option.symbol {
                        Label(option.label, systemImage: symbol)
                    } else {
                        Text(option.label)
                    }
                    if let hint = option.hint { Text(hint) }
                }
            }
        } label: {
            HStack(spacing: 7) {
                if let symbol = current?.symbol {
                    Image(systemName: symbol)
                        .font(.system(size: 12.5, weight: .medium))
                        .foregroundStyle(DS.text3)
                }
                Text(current?.label ?? "—")
                    .font(.ds(14, .medium))
                    .foregroundStyle(DS.text1)
                    .lineLimit(1)
                Spacer(minLength: 6)
                Image(systemName: "chevron.up.chevron.down")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(DS.muted)
            }
            .padding(.leading, 12)
            .padding(.trailing, 10)
            .frame(height: height)
            .frame(width: width)
            .background(
                RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                    .fill(DS.surface)
            )
            .overlay(
                RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                    .strokeBorder(DS.line, lineWidth: DS.hairline)
            )
            .contentShape(RoundedRectangle(cornerRadius: DS.radius, style: .continuous))
        }
        .menuIndicator(.hidden)
    }

    private var current: Option? {
        options.first { $0.value == selection }
    }
}
