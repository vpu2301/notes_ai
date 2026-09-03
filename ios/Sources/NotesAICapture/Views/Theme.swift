import SwiftUI
import UIKit

// MARK: - Design tokens
//
// Paper, ink, and a moss accent — the same palette as the Mac app and the
// web: a warm off-white ground, hairline (½ pt) borders instead of shadows,
// generous radii, Avenir Next for everything you read. Every colour is a
// dynamic UIColor so the same token resolves for light and dark; the dark
// side is the same warm palette turned over.

enum DS {
    // Ground & surfaces
    static let bg           = Color.ds("fbfaf7", "171512")
    static let surface      = Color.ds("ffffff", "1e1b18")
    static let surface2     = Color.ds("f3f1ec", "27231f")
    static let surfaceHover = Color.ds("f6f4f0", "231f1c")
    static let sidebar      = Color.ds("f6f4ef", "131110")
    static let sidebarOn    = Color.ds("ffffff", "1e1b18")

    // Ink (text) scale — warm, never pure black
    static let text1        = Color.ds("1a1816", "ece8e1")
    static let text2        = Color.ds("3d3936", "cfc9c0")
    static let text3        = Color.ds("5f5a55", "a49d94")
    static let muted        = Color.ds("8a847c", "7d766e")

    // Hairlines
    static let line         = Color.ds("e6e2db", "2c2824")
    static let line2        = Color.ds("efece6", "241f1c")
    /// Border weight for every hairline: half a point on Retina.
    static let hairline: CGFloat = 0.5

    // Ink fill — the primary button (Granola's black pill) and the toggle.
    static let ink          = Color.ds("1a1816", "ece8e1")
    static let inkText      = Color.ds("ffffff", "171512")

    // Accent family (moss)
    static let accent       = Color.ds("4f7a5e", "8fbf9c")
    static let accent2      = Color.ds("3f6650", "a9d3b4")
    static let accentSoft   = Color.ds("4f7a5e", "8fbf9c", lightAlpha: 0.11, darkAlpha: 0.14)
    static let accentText   = Color.ds("3f6650", "a9d3b4")
    static let accentFill   = Color.ds("4f7a5e", "8fbf9c")
    static let accentInk    = Color.ds("ffffff", "171512")

    // Second hue ("amended") — a dusty plum
    static let indigo       = Color.ds("6b5b95", "b3a4d6")
    static let indigoSoft   = Color.ds("6b5b95", "b3a4d6", lightAlpha: 0.10, darkAlpha: 0.12)

    // Semantic
    static let warn         = Color.ds("a8651a", "e2a24d")
    static let warnSoft     = Color.ds("a8651a", "e2a24d", lightAlpha: 0.10, darkAlpha: 0.12)
    static let rec          = Color.ds("d9483b", "f0796d")
    static let recSoft      = Color.ds("d9483b", "f0796d", lightAlpha: 0.10, darkAlpha: 0.14)
    static let danger       = Color.ds("b4483e", "c7574c")
    static let dangerSoft   = Color.ds("b4483e", "c7574c", lightAlpha: 0.09, darkAlpha: 0.16)
    static let dangerText   = Color.ds("9a3a31", "e29a92")
    static let ok           = Color.ds("3f7d55", "7fc394")
    static let okSoft       = Color.ds("3f7d55", "7fc394", lightAlpha: 0.11, darkAlpha: 0.12)
    static let info         = Color.ds("4b6f9e", "8fb0dd")
    static let infoSoft     = Color.ds("4b6f9e", "8fb0dd", lightAlpha: 0.10, darkAlpha: 0.12)

    // Radii — rounder than the web's, the organic half of the look
    static let radius: CGFloat = 12
    static let radiusLg: CGFloat = 16
    static let radiusXl: CGFloat = 22

    // Layout
    /// Page gutter on an iPhone.
    static let gutter: CGFloat = 18
    /// Touch-sized control height.
    static let control: CGFloat = 44
}

// MARK: - Type scale
//
// Avenir Next — ships with iOS — for everything you read; SF Mono for
// codes and timers. Display sizes use the DemiBold cut. Sizes are a notch
// above the Mac's for a phone held at arm's length.

enum DSType {
    static let family = "AvenirNext"

    static func face(_ weight: Font.Weight) -> String {
        switch weight {
        case .ultraLight, .thin, .light: return "\(family)-UltraLight"
        case .regular: return "\(family)-Regular"
        case .medium: return "\(family)-Medium"
        case .semibold: return "\(family)-DemiBold"
        case .bold: return "\(family)-Bold"
        default: return "\(family)-Heavy"
        }
    }
}

extension Font {
    static func ds(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
        .custom(DSType.face(weight), size: size)
    }
    /// Display text: titles, greetings, the wordmark.
    static func dsDisplay(_ size: CGFloat, _ weight: Font.Weight = .semibold) -> Font {
        .custom(DSType.face(weight), size: size)
    }
    static func dsMono(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .monospaced)
    }

    static let dsTitle   = Font.dsDisplay(26)
    static let dsDoc     = Font.dsDisplay(27)
    static let dsH2      = Font.dsDisplay(19)
    static let dsBody    = Font.ds(16)
    static let dsUI      = Font.ds(15, .medium)
    static let dsMeta    = Font.ds(13)
    static let dsLabel   = Font.ds(11, .semibold)
}

// MARK: - Dynamic colours

extension Color {
    /// A light/dark pair as one dynamic colour. Hex without `#`.
    static func ds(_ light: String, _ dark: String,
                   lightAlpha: CGFloat = 1, darkAlpha: CGFloat = 1) -> Color {
        Color(uiColor: UIColor { traits in
            traits.userInterfaceStyle == .dark
                ? UIColor(hex: dark, alpha: darkAlpha)
                : UIColor(hex: light, alpha: lightAlpha)
        })
    }
}

extension UIColor {
    convenience init(hex: String, alpha: CGFloat = 1) {
        var value: UInt64 = 0
        Scanner(string: hex).scanHexInt64(&value)
        self.init(red: CGFloat((value >> 16) & 0xff) / 255,
                  green: CGFloat((value >> 8) & 0xff) / 255,
                  blue: CGFloat(value & 0xff) / 255,
                  alpha: alpha)
    }
}

// MARK: - Theme preference

enum ThemePref: String, CaseIterable, Identifiable {
    case light, system, dark

    var id: String { rawValue }

    var colorScheme: ColorScheme? {
        switch self {
        case .light: return .light
        case .dark: return .dark
        case .system: return nil
        }
    }

    var symbol: String {
        switch self {
        case .light: return "sun.max"
        case .system: return "iphone"
        case .dark: return "moon"
        }
    }

    var title: String {
        switch self {
        case .light: return "Light"
        case .system: return "Follow system"
        case .dark: return "Dark"
        }
    }
}

// MARK: - Surfaces

struct DSCard: ViewModifier {
    var padding: CGFloat
    var radius: CGFloat

    func body(content: Content) -> some View {
        content
            .padding(padding)
            .background(
                RoundedRectangle(cornerRadius: radius, style: .continuous)
                    .fill(DS.surface)
            )
            .overlay(
                RoundedRectangle(cornerRadius: radius, style: .continuous)
                    .strokeBorder(DS.line, lineWidth: DS.hairline)
            )
    }
}

extension View {
    func dsCard(padding: CGFloat = 16, radius: CGFloat = DS.radiusLg) -> some View {
        modifier(DSCard(padding: padding, radius: radius))
    }
}

/// The ground behind sign-in and loading: flat paper with the faintest
/// warm glow at the top — no colour washes.
struct DSWash: View {
    var body: some View {
        ZStack {
            DS.bg
            LinearGradient(colors: [DS.text1.opacity(0.025), .clear],
                           startPoint: .top, endPoint: .center)
        }
        .ignoresSafeArea()
    }
}

/// A print of small dots over the ground, fading out from the top — the
/// texture behind the home page, sign-in, and empty states.
struct DSDots: View {
    var spacing: CGFloat = 20
    var dot: CGFloat = 1.1
    var opacity: Double = 0.16
    var fade: CGFloat = 700

    var body: some View {
        Canvas(rendersAsynchronously: true) { context, size in
            var path = Path()
            var y = spacing / 2
            while y < size.height {
                var x = spacing / 2
                while x < size.width {
                    path.addEllipse(in: CGRect(x: x - dot, y: y - dot, width: dot * 2, height: dot * 2))
                    x += spacing
                }
                y += spacing
            }
            context.fill(path, with: .color(DS.text1.opacity(opacity)))
        }
        .mask(
            RadialGradient(colors: [.black, .black.opacity(0.35), .clear],
                           center: .init(x: 0.5, y: 0.0),
                           startRadius: 0, endRadius: fade)
        )
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}

// MARK: - Buttons

enum DSButtonKind {
    case primary, secondary, ghost, dark, danger, rec
}

struct DSButtonStyle: ButtonStyle {
    var kind: DSButtonKind = .secondary
    var size: CGFloat = 15
    var height: CGFloat = 40
    var fill = false

    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.ds(size, .medium))
            .foregroundStyle(foreground)
            .padding(.horizontal, 14)
            .frame(height: height)
            .frame(maxWidth: fill ? .infinity : nil)
            .background(
                RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                    .fill(background(pressed: configuration.isPressed))
            )
            .overlay(
                RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                    .strokeBorder(border, lineWidth: DS.hairline)
            )
            .opacity(isEnabled ? 1 : 0.45)
            .contentShape(RoundedRectangle(cornerRadius: DS.radius, style: .continuous))
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
    }

    // `.primary` and `.dark` are both the ink pill — Granola has one filled
    // button and it is black; the accent is for tints and text.
    private var foreground: Color {
        switch kind {
        case .primary, .dark: return DS.inkText
        case .secondary, .ghost: return DS.text1
        case .danger: return .white
        case .rec: return .white
        }
    }

    private func background(pressed: Bool) -> Color {
        switch kind {
        case .primary, .dark: return DS.ink.opacity(pressed ? 0.85 : 1)
        case .secondary: return pressed ? DS.surface2 : DS.surface
        case .ghost: return pressed ? DS.surface2 : .clear
        case .danger: return DS.danger.opacity(pressed ? 0.88 : 1)
        case .rec: return DS.rec.opacity(pressed ? 0.88 : 1)
        }
    }

    private var border: Color {
        switch kind {
        case .secondary: return DS.line
        default: return .clear
        }
    }
}

/// Square icon-only button (36 pt) with a pressed tint.
struct DSIconButtonStyle: ButtonStyle {
    var on = false
    var size: CGFloat = 36

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.ds(15, .medium))
            .foregroundStyle(on ? DS.accentText : DS.text3)
            .frame(width: size, height: size)
            .background(
                RoundedRectangle(cornerRadius: 9, style: .continuous)
                    .fill(on ? DS.accentSoft : (configuration.isPressed ? DS.surface2 : .clear))
            )
            .contentShape(Rectangle())
    }
}

// MARK: - Fields

/// Text field in the web's `.input` clothing: surface, hairline, ink ring
/// on focus.
struct DSTextField: View {
    var placeholder: String
    @Binding var text: String
    var secure = false
    var mono = false

    @FocusState private var focused: Bool

    var body: some View {
        Group {
            if secure {
                SecureField(placeholder, text: $text)
            } else {
                TextField(placeholder, text: $text)
                    .autocorrectionDisabled(mono)
                    .textInputAutocapitalization(mono ? .never : .sentences)
            }
        }
        .textFieldStyle(.plain)
        .font(mono ? .dsMono(14.5) : .ds(16))
        .foregroundStyle(DS.text1)
        .focused($focused)
        .padding(.horizontal, 12)
        .frame(height: DS.control)
        .background(
            RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                .fill(DS.surface)
        )
        .overlay(
            RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                .strokeBorder(focused ? DS.text3 : DS.line, lineWidth: focused ? 1 : DS.hairline)
        )
        .animation(.easeOut(duration: 0.12), value: focused)
    }
}

/// Toggle drawn as the web's switch: a pill with a sliding knob.
struct DSToggleStyle: ToggleStyle {
    func makeBody(configuration: Configuration) -> some View {
        Button {
            configuration.isOn.toggle()
        } label: {
            HStack(spacing: 10) {
                configuration.label
                    .font(.ds(15))
                    .foregroundStyle(DS.text1)
                Spacer(minLength: 0)
                ZStack(alignment: configuration.isOn ? .trailing : .leading) {
                    Capsule()
                        .fill(configuration.isOn ? DS.ink : DS.surface2)
                        .overlay(Capsule().strokeBorder(DS.line, lineWidth: configuration.isOn ? 0 : DS.hairline))
                        .frame(width: 44, height: 26)
                    Circle()
                        .fill(configuration.isOn ? DS.inkText : DS.surface)
                        .overlay(Circle().strokeBorder(DS.line, lineWidth: configuration.isOn ? 0 : DS.hairline))
                        .frame(width: 22, height: 22)
                        .padding(2)
                }
                .animation(.easeOut(duration: 0.15), value: configuration.isOn)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

/// Segmented pill (`.seg-pill`): a grey track with a white raised segment.
struct DSSegmentedPill<T: Hashable>: View {
    struct Option {
        let value: T
        let label: String?
        let symbol: String?
        let help: String?

        init(_ value: T, label: String? = nil, symbol: String? = nil, help: String? = nil) {
            self.value = value
            self.label = label
            self.symbol = symbol
            self.help = help
        }
    }

    let options: [Option]
    @Binding var selection: T
    var height: CGFloat = 34

    var body: some View {
        HStack(spacing: 2) {
            ForEach(Array(options.enumerated()), id: \.offset) { _, option in
                let on = option.value == selection
                Button {
                    withAnimation(.easeOut(duration: 0.15)) { selection = option.value }
                } label: {
                    HStack(spacing: 5) {
                        if let symbol = option.symbol {
                            Image(systemName: symbol).font(.ds(12, .medium))
                        }
                        if let label = option.label {
                            Text(label).font(.ds(13.5, .medium))
                        }
                    }
                    .foregroundStyle(on ? DS.text1 : DS.muted)
                    .padding(.horizontal, option.label == nil ? 9 : 12)
                    .frame(height: height - 6)
                    .frame(maxWidth: .infinity)
                    .background(
                        RoundedRectangle(cornerRadius: 8, style: .continuous)
                            .fill(on ? DS.surface : .clear)
                            .overlay(
                                RoundedRectangle(cornerRadius: 8, style: .continuous)
                                    .strokeBorder(DS.line, lineWidth: on ? DS.hairline : 0)
                            )
                    )
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(option.help ?? option.label ?? "")
            }
        }
        .padding(3)
        .background(
            RoundedRectangle(cornerRadius: 11, style: .continuous)
                .fill(DS.surface2)
        )
    }
}

// MARK: - Small pieces

/// Uppercase tracked section label (`.sb-section-h`, `.field-label`).
struct DSLabel: View {
    let text: String

    init(_ text: String) { self.text = text }

    var body: some View {
        Text(text.uppercased())
            .font(.dsLabel)
            .tracking(0.8)
            .foregroundStyle(DS.muted)
    }
}

/// Soft-tinted status pill (`.chip`).
struct DSChip: View {
    let text: String
    let tint: Color
    let soft: Color
    var dot = false

    var body: some View {
        HStack(spacing: 5) {
            if dot {
                Circle().fill(tint).frame(width: 6, height: 6)
            }
            Text(text)
                .font(.ds(12, .semibold))
        }
        .foregroundStyle(tint)
        .padding(.horizontal, 9)
        .padding(.vertical, 4)
        .background(Capsule().fill(soft))
    }
}

/// Initials avatar (`.avatar`): a tinted circle with two letters.
struct DSAvatar: View {
    let name: String
    var size: CGFloat = 32

    var body: some View {
        Text(initials)
            .font(.dsDisplay(size * 0.42, .medium))
            .foregroundStyle(DS.accentText)
            .frame(width: size, height: size)
            .background(Circle().fill(DS.accentSoft))
            .overlay(Circle().strokeBorder(DS.accent.opacity(0.25), lineWidth: DS.hairline))
    }

    private var initials: String {
        let parts = name.split(whereSeparator: { " @.".contains($0) }).filter { !$0.isEmpty }
        let first = parts.first?.first.map(String.init) ?? "?"
        let second = parts.count > 1 ? parts[1].first.map(String.init) ?? "" : ""
        return (first + second).uppercased()
    }
}

/// The brand mark: ink tile with the product initial.
struct DSBrandMark: View {
    var size: CGFloat = 28

    var body: some View {
        Text("N")
            .font(.dsDisplay(size * 0.58, .medium))
            .foregroundStyle(DS.inkText)
            .frame(width: size, height: size)
            .background(
                RoundedRectangle(cornerRadius: size * 0.3, style: .continuous)
                    .fill(DS.ink)
            )
    }
}

/// "Notes AI" with the AI in accent, as the web wordmark does.
struct DSWordmark: View {
    var size: CGFloat = 16

    var body: some View {
        HStack(spacing: 0) {
            Text("Notes ")
                .foregroundStyle(DS.text1)
            Text("AI")
                .foregroundStyle(DS.accentText)
        }
        .font(.dsDisplay(size + 1))
        .tracking(-0.3)
    }
}

/// Hairline divider in the token colour.
struct DSDivider: View {
    var body: some View {
        Rectangle().fill(DS.line).frame(height: DS.hairline)
    }
}

extension NoteStatus {
    var tint: Color {
        switch self {
        case .draft: return DS.muted
        case .finalized: return DS.ok
        case .amended: return DS.indigo
        case .cancelled: return DS.warn
        }
    }

    var soft: Color {
        switch self {
        case .draft: return DS.surface2
        case .finalized: return DS.okSoft
        case .amended: return DS.indigoSoft
        case .cancelled: return DS.warnSoft
        }
    }
}

extension JobStatus {
    var tint: Color {
        switch self {
        case .queued: return DS.muted
        case .running: return DS.info
        case .complete: return DS.ok
        case .failed: return DS.rec
        case .cancelled: return DS.warn
        }
    }

    var soft: Color {
        switch self {
        case .queued: return DS.surface2
        case .running: return DS.infoSoft
        case .complete: return DS.okSoft
        case .failed: return DS.recSoft
        case .cancelled: return DS.warnSoft
        }
    }
}
