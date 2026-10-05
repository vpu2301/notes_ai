import AppKit
import Combine
import SwiftUI

/// The desktop recording indicator: a small pill that floats above every
/// window and Space while a meeting is being recorded — a pulsing red dot,
/// a live waveform that flows with the voice, and the elapsed time.
///
/// Click opens the app's window; drag moves it (the spot is remembered).
/// Hovering slides out Mark moment, Open and Stop; right-click offers the
/// same. It goes away the moment the recording ends.
@MainActor
final class RecordingBubble {
    static let shared = RecordingBubble()

    private var panel: NSPanel?
    private var container: BubbleContainer?
    private static let originKey = "recordingBubble.origin"

    func show(capture: CaptureViewModel) {
        guard panel == nil, let screen = NSScreen.main else { return }
        let size = NSSize(width: BubbleMetrics.collapsedWidth, height: BubbleMetrics.height)

        let panel = NSPanel(contentRect: NSRect(origin: .zero, size: size),
                            styleMask: [.borderless, .nonactivatingPanel],
                            backing: .buffered, defer: false)
        panel.level = .floating
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.hidesOnDeactivate = false
        panel.isReleasedWhenClosed = false

        let state = BubbleState()
        let open = { NotificationCenter.default.post(name: .openMainWindow, object: nil) }
        let stop = { [weak capture] in
            guard let capture, capture.isRecording else { return }
            capture.toggleRecording()
        }
        let mark = { [weak capture, weak state] in
            guard let capture, capture.isRecording else { return }
            capture.appendQuickNote("★ Marked \(formatElapsed(capture.recorder.elapsed))")
            state?.flashMarked()
        }

        let container = BubbleContainer(frame: NSRect(origin: .zero, size: size), state: state)
        container.onClick = open
        container.onStop = stop
        container.onMark = mark
        container.onMoved = { origin in
            UserDefaults.standard.set(NSStringFromPoint(origin), forKey: Self.originKey)
        }
        let view = RecordingBubbleView(recorder: capture.recorder, state: state,
                                       onMark: mark, onOpen: open, onStop: stop)
        let host = FirstMouseHostingView(rootView: view)
        host.frame = container.bounds
        host.autoresizingMask = [.width, .height]
        container.addSubview(host)
        container.host = host
        panel.contentView = container

        panel.setFrameOrigin(Self.origin(size: size, screen: screen))
        panel.orderFrontRegardless()
        self.panel = panel
        self.container = container
    }

    func hide() {
        panel?.orderOut(nil)
        panel = nil
        container = nil
    }

    /// The remembered spot if it is still on a screen; otherwise the top
    /// right of the main screen, clear of the menu bar.
    private static func origin(size: NSSize, screen: NSScreen) -> NSPoint {
        if let saved = UserDefaults.standard.string(forKey: originKey) {
            let point = NSPointFromString(saved)
            let rect = NSRect(origin: point, size: size)
            if NSScreen.screens.contains(where: { $0.visibleFrame.intersects(rect) }) { return point }
        }
        let visible = screen.visibleFrame
        return NSPoint(x: visible.maxX - BubbleMetrics.expandedWidth - 16,
                       y: visible.maxY - size.height - 16)
    }
}

/// Fixed geometry, so the container knows where the pill's own body ends
/// and the hover buttons begin without asking SwiftUI.
private enum BubbleMetrics {
    static let height: CGFloat = 30
    static let collapsedWidth: CGFloat = 126
    static let buttonWidth: CGFloat = 26
    static let buttonCount: CGFloat = 3
    static let expandedWidth: CGFloat = collapsedWidth + 7 + buttonWidth * buttonCount + 4
    static let bars = 16
}

@MainActor
private final class BubbleState: ObservableObject {
    @Published var expanded = false
    @Published var marked = false
    private var markTask: Task<Void, Never>?

    func flashMarked() {
        markTask?.cancel()
        withAnimation(.snappy(duration: 0.2)) { marked = true }
        markTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(1.2))
            guard !Task.isCancelled else { return }
            withAnimation(.snappy(duration: 0.25)) { self?.marked = false }
        }
    }
}

/// SwiftUI buttons in a non-activating panel must take the first click.
private final class FirstMouseHostingView<Content: View>: NSHostingView<Content> {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
}

/// Owns the pill's body (click vs. drag, hover, right-click); the hover
/// buttons on the right are left to SwiftUI.
private final class BubbleContainer: NSView {
    var onClick: () -> Void = {}
    var onStop: () -> Void = {}
    var onMark: () -> Void = {}
    var onMoved: (NSPoint) -> Void = { _ in }
    weak var host: NSView?

    private let state: BubbleState
    private var pressAt: NSPoint?
    private var dragged = false
    private var collapseTask: Task<Void, Never>?
    /// Where the pill rests collapsed; expanding may nudge it left when it
    /// sits against the right edge of the screen.
    private var restingX: CGFloat?

    init(frame: NSRect, state: BubbleState) {
        self.state = state
        super.init(frame: frame)
        addTrackingArea(NSTrackingArea(rect: .zero,
                                       options: [.mouseEnteredAndExited, .activeAlways, .inVisibleRect],
                                       owner: self, userInfo: nil))
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) is not used") }

    override func hitTest(_ point: NSPoint) -> NSView? {
        guard frame.contains(point) else { return nil }
        let local = convert(point, from: superview)
        if state.expanded, local.x > BubbleMetrics.collapsedWidth,
           let hit = host?.hitTest(local) {
            return hit
        }
        return self
    }

    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    // MARK: Hover

    override func mouseEntered(with event: NSEvent) {
        collapseTask?.cancel()
        expand()
    }

    override func mouseExited(with event: NSEvent) {
        guard pressAt == nil else { return }
        collapseTask?.cancel()
        collapseTask = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .milliseconds(350))
            guard !Task.isCancelled else { return }
            self?.collapse()
        }
    }

    private func expand() {
        guard !state.expanded, let window else { return }
        var frame = window.frame
        restingX = frame.origin.x
        frame.size.width = BubbleMetrics.expandedWidth
        if let visible = window.screen?.visibleFrame, frame.maxX > visible.maxX {
            frame.origin.x = visible.maxX - frame.width
        }
        window.setFrame(frame, display: true)
        withAnimation(.snappy(duration: 0.22)) { state.expanded = true }
        window.invalidateShadow()
    }

    private func collapse() {
        guard state.expanded else { return }
        withAnimation(.snappy(duration: 0.18)) { state.expanded = false }
        Task { @MainActor [weak self] in
            try? await Task.sleep(for: .milliseconds(180))
            guard let self, !self.state.expanded, let window = self.window else { return }
            var frame = window.frame
            frame.size.width = BubbleMetrics.collapsedWidth
            if let x = self.restingX { frame.origin.x = x }
            window.setFrame(frame, display: true)
            window.invalidateShadow()
        }
    }

    // MARK: Click and drag

    override func mouseDown(with event: NSEvent) {
        pressAt = NSEvent.mouseLocation
        dragged = false
    }

    override func mouseDragged(with event: NSEvent) {
        guard let window, let start = pressAt else { return }
        let now = NSEvent.mouseLocation
        let dx = now.x - start.x, dy = now.y - start.y
        if !dragged, abs(dx) < 3, abs(dy) < 3 { return }
        dragged = true
        window.setFrameOrigin(NSPoint(x: window.frame.origin.x + dx, y: window.frame.origin.y + dy))
        pressAt = now
    }

    override func mouseUp(with event: NSEvent) {
        if dragged, let window {
            restingX = window.frame.origin.x
            onMoved(window.frame.origin)
        } else {
            onClick()
        }
        pressAt = nil
        dragged = false
        if let window, !window.frame.contains(NSEvent.mouseLocation) { mouseExited(with: event) }
    }

    override func rightMouseDown(with event: NSEvent) {
        let menu = NSMenu()
        menu.addItem(withTitle: "Open Notes AI", action: #selector(open), keyEquivalent: "").target = self
        menu.addItem(withTitle: "Mark this moment", action: #selector(mark), keyEquivalent: "").target = self
        menu.addItem(.separator())
        menu.addItem(withTitle: "Stop recording", action: #selector(stop), keyEquivalent: "").target = self
        NSMenu.popUpContextMenu(menu, with: event, for: self)
    }

    @objc private func open() { onClick() }
    @objc private func mark() { onMark() }
    @objc private func stop() { onStop() }
}

/// The pill: ink ground, a pulsing red dot, a waveform that scrolls right
/// to left with the voice, the elapsed time — and, on hover, the actions.
private struct RecordingBubbleView: View {
    @ObservedObject var recorder: AudioRecorder
    @ObservedObject var state: BubbleState
    let onMark: () -> Void
    let onOpen: () -> Void
    let onStop: () -> Void

    @State private var history = Array(repeating: 0.0, count: BubbleMetrics.bars)
    @State private var pulse = false

    private static let ground = Color(red: 0.10, green: 0.094, blue: 0.086)

    var body: some View {
        HStack(spacing: 0) {
            core
                .frame(width: BubbleMetrics.collapsedWidth, height: BubbleMetrics.height)
            if state.expanded {
                Rectangle()
                    .fill(.white.opacity(0.14))
                    .frame(width: 1, height: 16)
                    .padding(.horizontal, 3)
                actions
                    .padding(.trailing, 4)
                    .transition(.opacity.combined(with: .move(edge: .leading)))
            }
        }
        .background(Capsule().fill(Self.ground))
        .overlay(Capsule().strokeBorder(.white.opacity(0.12), lineWidth: 0.5))
        .clipShape(Capsule())
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        .onReceive(recorder.$level) { level in
            // A sqrt lifts quiet speech so the wave never looks dead.
            let value = min(max(level, recorder.systemLevel, 0), 1).squareRoot()
            history.removeFirst()
            history.append(value)
        }
        .onAppear { pulse = true }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Recording, \(formatElapsed(recorder.elapsed))")
    }

    private var core: some View {
        HStack(spacing: 8) {
            ZStack {
                Circle()
                    .fill(DS.rec.opacity(0.35))
                    .frame(width: 13, height: 13)
                    .scaleEffect(pulse ? 1 : 0.55)
                    .opacity(pulse ? 0 : 1)
                    .animation(.easeOut(duration: 1.4).repeatForever(autoreverses: false), value: pulse)
                Circle()
                    .fill(state.marked ? DS.accent : DS.rec)
                    .frame(width: 7, height: 7)
            }
            .frame(width: 13, height: 13)

            waveform
                .frame(width: 40, height: 18)

            Text(formatElapsed(recorder.elapsed))
                .font(.system(size: 11, weight: .medium, design: .monospaced))
                .monospacedDigit()
                .foregroundStyle(.white.opacity(0.92))
                .lineLimit(1)
                .minimumScaleFactor(0.75)
        }
        .padding(.horizontal, 11)
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(Rectangle())
    }

    /// Mirrored bars, newest on the right; the older ones fade out to the
    /// left so the sound reads as flowing past.
    private var waveform: some View {
        HStack(alignment: .center, spacing: 1.5) {
            ForEach(history.indices, id: \.self) { index in
                Capsule()
                    .fill(.white)
                    .frame(width: 1.5, height: 2 + history[index] * 16)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .mask(LinearGradient(colors: [.white.opacity(0.15), .white],
                             startPoint: .leading, endPoint: .trailing))
        .animation(.linear(duration: 0.05), value: history)
    }

    private var actions: some View {
        HStack(spacing: 0) {
            BubbleButton(symbol: state.marked ? "checkmark" : "bookmark.fill",
                         tint: state.marked ? DS.accent : .white,
                         help: "Mark this moment", action: onMark)
            BubbleButton(symbol: "arrow.up.forward.app", tint: .white,
                         help: "Open Notes AI", action: onOpen)
            BubbleButton(symbol: "stop.fill", tint: DS.rec,
                         help: "Stop recording", action: onStop)
        }
    }
}

private struct BubbleButton: View {
    let symbol: String
    let tint: Color
    let help: String
    let action: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(tint)
                .contentTransition(.symbolEffect(.replace))
                .frame(width: BubbleMetrics.buttonWidth - 4, height: 22)
                .background(Circle().fill(.white.opacity(hovering ? 0.14 : 0)))
                .frame(width: BubbleMetrics.buttonWidth, height: BubbleMetrics.height)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hovering = $0 }
        .help(help)
        .accessibilityLabel(help)
    }
}
