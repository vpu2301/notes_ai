import SwiftUI

// MARK: - Status chip

struct StatusChip: View {
    let status: JobStatus?

    var body: some View {
        DSChip(text: status?.label ?? "Unknown",
               tint: status?.tint ?? DS.muted,
               soft: status?.soft ?? DS.surface2,
               dot: status == .running)
    }
}

// MARK: - Pulsing recording dot

struct PulsingDot: View {
    var size: CGFloat = 8
    @State private var dimmed = false

    var body: some View {
        Circle()
            .fill(DS.rec)
            .frame(width: size, height: size)
            .opacity(dimmed ? 0.3 : 1)
            .onAppear {
                withAnimation(.easeInOut(duration: 0.8).repeatForever(autoreverses: true)) {
                    dimmed = true
                }
            }
    }
}

// MARK: - Input level meter

struct LevelMeter: View {
    var level: Double
    var active: Bool
    var segments = 28
    var height: CGFloat = 14

    var body: some View {
        HStack(spacing: 3) {
            ForEach(0..<segments, id: \.self) { index in
                let threshold = Double(index) / Double(segments)
                Capsule()
                    .fill(color(for: threshold))
                    .frame(width: 3, height: height)
                    .opacity(active && level > threshold ? 1 : 0.16)
            }
        }
        .animation(.linear(duration: 0.08), value: level)
        .accessibilityLabel("Input level")
    }

    private func color(for threshold: Double) -> Color {
        if threshold > 0.85 { return DS.rec }
        if threshold > 0.65 { return DS.warn }
        return DS.accent
    }
}

// MARK: - Pipeline stepper

/// Upload → Transcribe → Draft, drawn as the web's step list.
struct PipelineSteps: View {
    let phase: CaptureViewModel.Phase

    private let steps: [(String, String)] = [
        ("Upload", "arrow.up.circle"),
        ("Transcribe", "waveform"),
        ("Draft note", "doc.text"),
    ]

    private var activeIndex: Int? {
        switch phase {
        case .uploading: return 0
        case .transcribing: return 1
        case .creatingNote: return 2
        case .done: return 3
        default: return nil
        }
    }

    var body: some View {
        HStack(spacing: 0) {
            ForEach(Array(steps.enumerated()), id: \.offset) { index, step in
                let state = state(for: index)
                HStack(spacing: 7) {
                    ZStack {
                        Circle()
                            .fill(state == .done ? DS.okSoft : (state == .active ? DS.accentSoft : DS.surface2))
                            .frame(width: 22, height: 22)
                        if state == .done {
                            Image(systemName: "checkmark")
                                .font(.system(size: 10, weight: .bold))
                                .foregroundStyle(DS.ok)
                        } else if state == .active {
                            ProgressView().controlSize(.mini)
                        } else {
                            Image(systemName: step.1)
                                .font(.system(size: 10, weight: .medium))
                                .foregroundStyle(DS.muted)
                        }
                    }
                    Text(step.0)
                        .font(.ds(12, state == .pending ? .regular : .medium))
                        .foregroundStyle(state == .pending ? DS.muted : DS.text1)
                }
                if index < steps.count - 1 {
                    Rectangle()
                        .fill(state == .done ? DS.ok.opacity(0.5) : DS.line)
                        .frame(height: 1)
                        .frame(maxWidth: .infinity)
                        .padding(.horizontal, 8)
                }
            }
        }
    }

    private enum StepState { case pending, active, done }

    private func state(for index: Int) -> StepState {
        guard let activeIndex else { return .pending }
        if index < activeIndex { return .done }
        if index == activeIndex { return .active }
        return .pending
    }
}

// MARK: - Inline notice

struct DSNotice: View {
    enum Tone { case ok, warn, danger, info }

    let tone: Tone
    let symbol: String
    let text: String

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: symbol)
                .font(.ds(12, .semibold))
                .foregroundStyle(tint)
                .padding(.top, 1)
            Text(text)
                .font(.ds(12.5))
                .foregroundStyle(DS.text1)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
            Spacer(minLength: 0)
        }
        .padding(10)
        .background(
            RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                .fill(soft)
        )
    }

    private var tint: Color {
        switch tone {
        case .ok: return DS.ok
        case .warn: return DS.warn
        case .danger: return DS.danger
        case .info: return DS.info
        }
    }

    private var soft: Color {
        switch tone {
        case .ok: return DS.okSoft
        case .warn: return DS.warnSoft
        case .danger: return DS.dangerSoft
        case .info: return DS.infoSoft
        }
    }
}

// MARK: - Skeleton

/// Loading placeholder bar (`.skeleton`).
struct DSSkeleton: View {
    var height: CGFloat = 16
    var width: CGFloat? = nil
    @State private var shimmer = false

    var body: some View {
        RoundedRectangle(cornerRadius: 6, style: .continuous)
            .fill(DS.surface2)
            .frame(width: width, height: height)
            .frame(maxWidth: width == nil ? .infinity : nil, alignment: .leading)
            .opacity(shimmer ? 0.55 : 1)
            .onAppear {
                withAnimation(.easeInOut(duration: 0.9).repeatForever(autoreverses: true)) {
                    shimmer = true
                }
            }
    }
}

// MARK: - Helpers

func formatElapsed(_ interval: TimeInterval) -> String {
    let seconds = Int(interval)
    return String(format: "%02d:%02d", seconds / 60, seconds % 60)
}

func formatElapsed(ms: Int) -> String {
    formatElapsed(TimeInterval(ms) / 1000)
}

func formatDateTime(_ date: Date) -> String {
    date.formatted(.dateTime.day().month(.abbreviated).year().hour().minute())
}

func relativeTime(_ date: Date) -> String {
    let formatter = RelativeDateTimeFormatter()
    formatter.unitsStyle = .short
    if abs(date.timeIntervalSinceNow) < 45 { return "just now" }
    return formatter.localizedString(for: date, relativeTo: Date())
}


// MARK: - One-time code

/// Six boxes for a six-digit code.
///
/// Drawn over a single hidden field rather than as six real ones: the
/// code arrives from the mail app by paste far more often than it is
/// typed, and six separate fields turn one ⌘V into six keystrokes in the
/// wrong boxes. Typing still works — the boxes fill left to right — and
/// the field auto-submits on the sixth digit, because asking someone to
/// press Return after entering a code they were just told to enter is a
/// step with no content.
struct DSCodeField: View {
    @Binding var code: String
    var length = 6
    var onComplete: (String) -> Void

    @FocusState private var focused: Bool

    var body: some View {
        ZStack {
            // The real field: invisible, but it holds the caret, the paste
            // and the keyboard.
            TextField("", text: $code)
                .textFieldStyle(.plain)
                .textContentType(.oneTimeCode)
                .focused($focused)
                .opacity(0.02)
                .onChange(of: code) { _, new in
                    let digits = String(new.filter(\.isNumber).prefix(length))
                    if digits != new { code = digits }
                    if digits.count == length { onComplete(digits) }
                }
            HStack(spacing: 8) {
                ForEach(0..<length, id: \.self) { index in
                    box(at: index)
                }
            }
            .allowsHitTesting(false)
        }
        .contentShape(Rectangle())
        .onTapGesture { focused = true }
        .onAppear { focused = true }
        .accessibilityLabel("One-time code")
    }

    private func box(at index: Int) -> some View {
        let characters = Array(code)
        let filled = index < characters.count
        let isNext = index == characters.count && focused
        return Text(filled ? String(characters[index]) : " ")
            .font(.dsMono(17))
            .foregroundStyle(DS.text1)
            .frame(width: 38, height: 44)
            .background(
                RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                    .fill(DS.surface)
            )
            .overlay(
                RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                    .strokeBorder(isNext ? DS.text3 : DS.line,
                                  lineWidth: isNext ? 1 : DS.hairline)
            )
            .animation(.easeOut(duration: 0.12), value: isNext)
    }
}
