import SwiftUI
import UIKit

/// The live card: title, timer and Stop while recording; the three pipeline
/// steps while working; "Note ready" when done. Nothing to fill in before
/// pressing record — the title can be typed while the meeting runs. It sits
/// at the bottom of every screen (`CaptureBar`) so the meeting is one tap
/// away wherever you are.
struct ActiveCaptureCard: View {
    @EnvironmentObject private var app: AppState
    @EnvironmentObject private var capture: CaptureViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            switch capture.phase {
            case .idle:
                EmptyView()
            case .recording:
                recording
            case .uploading, .transcribing, .creatingNote:
                working
            case .done(let noteId):
                done(noteId)
            case .failed(let message):
                failed(message)
            case .microphoneDenied:
                microphoneDenied
            }
        }
        .animation(.easeOut(duration: 0.2), value: capture.phase)
    }

    // MARK: - Recording

    private var recording: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                if capture.recorder.interrupted {
                    Image(systemName: "pause.circle.fill")
                        .font(.ds(15))
                        .foregroundStyle(DS.warn)
                } else {
                    PulsingDot()
                }
                Text(formatElapsed(capture.recorder.elapsed))
                    .font(.dsMono(18, .medium))
                    .foregroundStyle(DS.text1)
                    .monospacedDigit()
                LevelMeter(level: capture.recorder.level, active: !capture.recorder.interrupted,
                           segments: 14, height: 12)
                Spacer(minLength: 8)
                Button {
                    capture.toggleRecording()
                } label: {
                    Label("Stop", systemImage: "stop.fill")
                }
                .buttonStyle(DSButtonStyle(kind: .rec, size: 14, height: 34))
            }
            TextField("Untitled meeting", text: $capture.title)
                .textFieldStyle(.plain)
                .font(.dsDisplay(18, .medium))
                .foregroundStyle(DS.text1)
                .submitLabel(.done)
            Text(capture.recorder.interrupted
                 ? "Paused for a call. Recording resumes when it ends."
                 : "Recording this phone's microphone. Stop when the meeting ends — the note is drafted for you.")
                .font(.dsMeta)
                .foregroundStyle(DS.muted)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    // MARK: - Working

    private var working: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                ProgressView().controlSize(.small)
                Text(capture.title.isEmpty ? "Untitled meeting" : capture.title)
                    .font(.ds(15, .semibold))
                    .foregroundStyle(DS.text1)
                    .lineLimit(1)
            }
            PipelineSteps(phase: capture.phase)
            Text("Keep the app open until the upload finishes; the rest happens on the server.")
                .font(.dsMeta)
                .foregroundStyle(DS.muted)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    // MARK: - Done / failed

    private func done(_ noteId: String) -> some View {
        HStack(spacing: 10) {
            Image(systemName: "checkmark.circle.fill")
                .font(.ds(17))
                .foregroundStyle(DS.ok)
            Text("Note ready")
                .font(.dsDisplay(17, .medium))
                .foregroundStyle(DS.text1)
            Spacer(minLength: 8)
            Button("Dismiss") { capture.reset() }
                .buttonStyle(DSButtonStyle(kind: .ghost, size: 14, height: 34))
            Button {
                app.openNote(noteId)
                capture.reset()
            } label: {
                Label("Open note", systemImage: "arrow.up.right")
            }
            .buttonStyle(DSButtonStyle(kind: .primary, size: 14, height: 34))
        }
    }

    private var microphoneDenied: some View {
        VStack(alignment: .leading, spacing: 10) {
            DSNotice(tone: .warn, symbol: "mic.slash.fill",
                     text: RecorderError.permissionDenied.localizedDescription)
            HStack {
                Spacer()
                Button("Dismiss") { capture.reset() }
                    .buttonStyle(DSButtonStyle(kind: .ghost, size: 14, height: 34))
                Button {
                    UIApplication.shared.open(RecorderError.settingsURL)
                } label: {
                    Label("Open Settings", systemImage: "gearshape")
                }
                .buttonStyle(DSButtonStyle(kind: .primary, size: 14, height: 34))
            }
        }
    }

    private func failed(_ message: String) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: message)
            HStack {
                Spacer()
                Button("Dismiss") { capture.reset() }
                    .buttonStyle(DSButtonStyle(kind: .secondary, size: 14, height: 34))
            }
        }
    }
}

/// The one button. Dark, like the web's create button.
struct NewMeetingButton: View {
    @EnvironmentObject private var capture: CaptureViewModel
    var fill = false
    var height: CGFloat = DS.control

    var body: some View {
        Button {
            capture.startNew()
        } label: {
            HStack(spacing: 8) {
                Image(systemName: "mic.fill")
                    .font(.system(size: 13, weight: .semibold))
                Text("New meeting")
            }
        }
        .buttonStyle(DSButtonStyle(kind: .dark, size: 16, height: height, fill: fill))
        .disabled(capture.isRecording || capture.phase.isBusy)
        .accessibilityHint("Start recording now")
    }
}

/// The strip pinned to the bottom of every screen: the one button when
/// nothing is happening, otherwise the live card — full size, or folded
/// to one line. Swipe up (or tap the chevron) for the whole card, swipe
/// down to fold it away; a new recording or a result unfolds it.
struct CaptureBar: View {
    @EnvironmentObject private var capture: CaptureViewModel
    /// The keyboard is up (a note is being typed): the idle button steps
    /// aside; the live card stays, its title field needs the keyboard too.
    @State private var keyboardShown = false
    @State private var expanded = true

    var body: some View {
        Group {
            if case .idle = capture.phase {
                if !keyboardShown {
                    NewMeetingButton(fill: true, height: 50)
                }
            } else {
                card
            }
        }
        .padding(.horizontal, DS.gutter)
        .padding(.top, 8)
        .padding(.bottom, 6)
        .background(
            LinearGradient(colors: [DS.bg.opacity(0), DS.bg.opacity(0.92), DS.bg],
                           startPoint: .top, endPoint: .bottom)
                .ignoresSafeArea(edges: .bottom)
        )
        .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillShowNotification)) { _ in
            keyboardShown = true
        }
        .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillHideNotification)) { _ in
            keyboardShown = false
        }
        .onChange(of: capture.phase) { old, new in
            if case .idle = old { expanded = true }
            switch new {
            case .done, .failed, .microphoneDenied: expanded = true
            default: break
            }
        }
    }

    private var card: some View {
        VStack(spacing: 8) {
            handle
            if expanded {
                ActiveCaptureCard()
            } else {
                CompactCaptureRow(expand: { setExpanded(true) })
            }
        }
        .padding(.horizontal, 14)
        .padding(.top, 6)
        .padding(.bottom, 12)
        .background(
            RoundedRectangle(cornerRadius: DS.radiusXl, style: .continuous)
                .fill(DS.surface)
        )
        .overlay(
            RoundedRectangle(cornerRadius: DS.radiusXl, style: .continuous)
                .strokeBorder(DS.line, lineWidth: DS.hairline)
        )
        .gesture(
            DragGesture(minimumDistance: 16)
                .onEnded { value in
                    if value.translation.height < -24 {
                        setExpanded(true)
                    } else if value.translation.height > 24 {
                        setExpanded(false)
                    }
                }
        )
    }

    /// The grabber, with a chevron that folds / unfolds the card.
    private var handle: some View {
        Button {
            setExpanded(!expanded)
        } label: {
            HStack {
                Spacer()
                Capsule().fill(DS.line).frame(width: 36, height: 4)
                Spacer()
            }
            .overlay(alignment: .trailing) {
                Image(systemName: expanded ? "chevron.down" : "chevron.up")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(DS.muted)
            }
            .frame(height: 22)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(expanded ? "Fold the meeting card" : "Show the meeting card")
    }

    private func setExpanded(_ on: Bool) {
        withAnimation(.easeOut(duration: 0.22)) { expanded = on }
    }
}

/// The folded card: one line with what matters — the timer and Stop while
/// recording, the step in progress, or the result and its button.
private struct CompactCaptureRow: View {
    @EnvironmentObject private var app: AppState
    @EnvironmentObject private var capture: CaptureViewModel
    let expand: () -> Void

    var body: some View {
        HStack(spacing: 10) {
            switch capture.phase {
            case .recording:
                if capture.recorder.interrupted {
                    Image(systemName: "pause.circle.fill").font(.ds(14)).foregroundStyle(DS.warn)
                } else {
                    PulsingDot(size: 8)
                }
                Text(formatElapsed(capture.recorder.elapsed))
                    .font(.dsMono(15, .medium))
                    .foregroundStyle(DS.text1)
                    .monospacedDigit()
                LevelMeter(level: capture.recorder.level, active: !capture.recorder.interrupted,
                           segments: 10, height: 10)
                tapToExpand(capture.title.isEmpty ? "Recording" : capture.title)
                Button {
                    capture.toggleRecording()
                } label: {
                    Label("Stop", systemImage: "stop.fill")
                }
                .buttonStyle(DSButtonStyle(kind: .rec, size: 13, height: 30))
            case .uploading, .transcribing, .creatingNote:
                ProgressView().controlSize(.small)
                tapToExpand(stepLabel)
            case .done(let noteId):
                Image(systemName: "checkmark.circle.fill").font(.ds(15)).foregroundStyle(DS.ok)
                tapToExpand("Note ready")
                Button("Open") {
                    app.openNote(noteId)
                    capture.reset()
                }
                .buttonStyle(DSButtonStyle(kind: .primary, size: 13, height: 30))
            case .failed:
                Image(systemName: "exclamationmark.triangle.fill").font(.ds(14)).foregroundStyle(DS.danger)
                tapToExpand("Something went wrong")
                Button("Dismiss") { capture.reset() }
                    .buttonStyle(DSButtonStyle(kind: .ghost, size: 13, height: 30))
            case .microphoneDenied:
                Image(systemName: "mic.slash.fill").font(.ds(14)).foregroundStyle(DS.warn)
                tapToExpand("Microphone is off")
                Button("Dismiss") { capture.reset() }
                    .buttonStyle(DSButtonStyle(kind: .ghost, size: 13, height: 30))
            case .idle:
                EmptyView()
            }
        }
        .frame(minHeight: 32)
    }

    private var stepLabel: String {
        switch capture.phase {
        case .uploading: return "Uploading…"
        case .transcribing: return "Transcribing…"
        case .creatingNote: return "Drafting the note…"
        default: return ""
        }
    }

    private func tapToExpand(_ text: String) -> some View {
        Button(action: expand) {
            Text(text)
                .font(.ds(14, .medium))
                .foregroundStyle(DS.text1)
                .lineLimit(1)
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}
