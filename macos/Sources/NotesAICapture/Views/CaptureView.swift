import SwiftUI

struct CaptureView: View {
    @EnvironmentObject private var app: AppState
    @EnvironmentObject private var capture: CaptureViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            TextField("Meeting title", text: $capture.title)
                .textFieldStyle(.roundedBorder)
                .disabled(capture.phase.isBusy)

            HStack(spacing: 10) {
                Picker("Language", selection: $capture.language) {
                    Text("English").tag("en")
                    Text("Українська").tag("uk")
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .disabled(capture.isRecording || capture.phase.isBusy)
            }

            Toggle("Separate speakers", isOn: $capture.diarize)
                .toggleStyle(.switch)
                .controlSize(.small)
                .disabled(capture.isRecording || capture.phase.isBusy)

            recordCard

            statusArea
        }
        .padding(16)
        .animation(.default, value: capture.phase)
    }

    // MARK: - Record card

    private var recordCard: some View {
        VStack(spacing: 12) {
            HStack(spacing: 8) {
                if capture.isRecording {
                    PulsingDot()
                    Text("REC")
                        .font(.caption.weight(.bold))
                        .foregroundStyle(.red)
                }
                Spacer()
                Text(formatElapsed(capture.recorder.elapsed))
                    .font(.title2.weight(.medium).monospacedDigit())
                    .foregroundStyle(capture.isRecording ? .primary : .secondary)
                Spacer()
                // Mirror spacer keeps the timer centered.
                if capture.isRecording {
                    Text("REC").font(.caption.weight(.bold)).hidden()
                    PulsingDot().hidden()
                }
            }

            LevelMeter(level: capture.recorder.level, active: capture.isRecording)

            Button(action: capture.toggleRecording) {
                ZStack {
                    Circle()
                        .fill(capture.isRecording
                              ? Color.red.opacity(0.16)
                              : Color.accentColor.opacity(0.14))
                        .frame(width: 64, height: 64)
                    Image(systemName: capture.isRecording ? "stop.fill" : "mic.fill")
                        .font(.system(size: 24, weight: .semibold))
                        .foregroundStyle(capture.isRecording ? Color.red : Color.accentColor)
                }
                .contentShape(Circle())
            }
            .buttonStyle(.plain)
            .disabled(capture.phase.isBusy)
            .help(capture.isRecording ? "Stop and transcribe" : "Start recording")
        }
        .padding(14)
        .frame(maxWidth: .infinity)
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(.ultraThinMaterial)
        )
    }

    // MARK: - Pipeline status

    @ViewBuilder
    private var statusArea: some View {
        switch capture.phase {
        case .idle:
            Label("Ready to capture", systemImage: "checkmark.circle")
                .font(.caption)
                .foregroundStyle(.secondary)
        case .recording:
            Label("Recording — press stop when the meeting ends", systemImage: "waveform")
                .font(.caption)
                .foregroundStyle(.secondary)
        case .uploading:
            progressRow("Uploading audio…")
        case .transcribing:
            progressRow("Transcribing… you can close this popover")
        case .creatingNote:
            progressRow("Drafting your meeting note…")
        case .done(let noteId):
            HStack(spacing: 8) {
                Image(systemName: "checkmark.seal.fill")
                    .foregroundStyle(.green)
                Text("Note ready")
                    .font(.callout.weight(.medium))
                Spacer()
                Button("Open note") {
                    app.openNote(noteId)
                }
                .controlSize(.small)
                Button("New") { capture.reset() }
                    .controlSize(.small)
                    .buttonStyle(.borderless)
            }
        case .failed(let message):
            VStack(alignment: .leading, spacing: 6) {
                Label(message, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption)
                    .foregroundStyle(.red)
                    .fixedSize(horizontal: false, vertical: true)
                Button("Dismiss") { capture.reset() }
                    .controlSize(.small)
            }
        }
    }

    private func progressRow(_ text: String) -> some View {
        HStack(spacing: 8) {
            ProgressView()
                .controlSize(.small)
            Text(text)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }
}
