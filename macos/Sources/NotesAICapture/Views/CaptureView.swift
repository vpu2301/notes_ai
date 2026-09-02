import SwiftUI

/// The single live card: title, timer and Stop while recording; the three
/// pipeline steps while working; "Note ready" when done. Nothing to fill in
/// before pressing record — the title can be typed while the meeting runs.
struct ActiveCaptureCard: View {
    @EnvironmentObject private var app: AppState
    @EnvironmentObject private var capture: CaptureViewModel
    var compact = false

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
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                PulsingDot()
                Text(formatElapsed(capture.recorder.elapsed))
                    .font(.dsMono(compact ? 15 : 17, .medium))
                    .foregroundStyle(DS.text1)
                    .monospacedDigit()
                LevelMeter(level: capture.recorder.level, active: true,
                           segments: compact ? 14 : 20, height: 10)
                Spacer(minLength: 8)
                Button {
                    capture.toggleRecording()
                } label: {
                    Label("Stop", systemImage: "stop.fill")
                }
                .buttonStyle(DSButtonStyle(kind: .rec, height: 28))
                .keyboardShortcut(".", modifiers: .command)
                .help("Stop and create the note (⌘.)")
            }
            TextField("Untitled meeting", text: $capture.title)
                .textFieldStyle(.plain)
                .font(.dsDisplay(compact ? 17 : 20, .medium))
                .foregroundStyle(DS.text1)
            Text("Recording this Mac's microphone. Stop when the meeting ends — the note is drafted for you.")
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
                    .font(.ds(14, .semibold))
                    .foregroundStyle(DS.text1)
                    .lineLimit(1)
            }
            PipelineSteps(phase: capture.phase)
            if compact {
                Text("You can close this — the note appears in the list when it is ready.")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    // MARK: - Done / failed

    private func done(_ noteId: String) -> some View {
        HStack(spacing: 10) {
            Image(systemName: "checkmark.circle.fill")
                .font(.ds(16))
                .foregroundStyle(DS.ok)
            Text("Note ready")
                .font(.dsDisplay(16, .medium))
                .foregroundStyle(DS.text1)
            Spacer(minLength: 8)
            Button("Dismiss") { capture.reset() }
                .buttonStyle(DSButtonStyle(kind: .ghost, height: 28))
            Button {
                app.openNote(noteId)
            } label: {
                Label("Open note", systemImage: "arrow.up.right")
            }
            .buttonStyle(DSButtonStyle(kind: .primary, height: 28))
        }
    }

    private var microphoneDenied: some View {
        VStack(alignment: .leading, spacing: 10) {
            DSNotice(tone: .warn, symbol: "mic.slash.fill",
                     text: RecorderError.permissionDenied.localizedDescription)
            HStack {
                Spacer()
                Button("Dismiss") { capture.reset() }
                    .buttonStyle(DSButtonStyle(kind: .ghost, height: 28))
                Button {
                    NSWorkspace.shared.open(RecorderError.privacySettingsURL)
                } label: {
                    Label("Open System Settings", systemImage: "gearshape")
                }
                .buttonStyle(DSButtonStyle(kind: .primary, height: 28))
            }
        }
    }

    private func failed(_ message: String) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: message)
            HStack {
                Spacer()
                Button("Dismiss") { capture.reset() }
                    .buttonStyle(DSButtonStyle(kind: .secondary, height: 28))
            }
        }
    }
}

/// The one button. Dark, like the web's create button.
struct NewMeetingButton: View {
    @EnvironmentObject private var capture: CaptureViewModel
    var fill = false
    var height: CGFloat = 32

    var body: some View {
        Button {
            capture.startNew()
        } label: {
            HStack(spacing: 7) {
                Image(systemName: "mic.fill")
                    .font(.system(size: 11, weight: .semibold))
                Text("New meeting")
                if !fill {
                    Text("⌘N")
                        .font(.dsMono(10.5))
                        .opacity(0.55)
                }
            }
        }
        .buttonStyle(DSButtonStyle(kind: .dark, height: height, fill: fill))
        .disabled(capture.isRecording || capture.phase.isBusy)
        .help("Start recording now (⌘N)")
    }
}
