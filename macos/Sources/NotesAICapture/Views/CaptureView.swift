import SwiftUI

/// The single live card: title, timer and Stop while recording; the pipeline steps while working; "Note ready" when done.
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
                // "Starting…" until audio reaches the file; then the counter, with one quiet line when the audio began late.
                VStack(alignment: .leading, spacing: 1) {
                    if let offset = capture.recorder.firstFrameOffsetMs {
                        Text(formatElapsed(capture.recorder.elapsed))
                            .font(.dsMono(compact ? 15 : 17, .medium))
                            .foregroundStyle(DS.text1)
                            .monospacedDigit()
                        if let notice = CaptureTiming.latencyNotice(offsetMs: offset) {
                            Text(notice)
                                .font(.dsMeta)
                                .foregroundStyle(DS.muted)
                        }
                    } else {
                        Text("Starting…")
                            .font(.dsMono(compact ? 15 : 17, .medium))
                            .foregroundStyle(DS.muted)
                    }
                }
                if capture.recorder.captureMode.recordsSystemAudio {
                    // One meter per channel.
                    VStack(alignment: .leading, spacing: 3) {
                        labelledMeter("You", level: capture.recorder.level)
                        labelledMeter("Call audio", level: capture.recorder.systemLevel)
                    }
                } else {
                    LevelMeter(level: capture.recorder.level, active: true,
                               segments: compact ? 14 : 20, height: 10)
                }
                Spacer(minLength: 8)
                Button {
                    capture.toggleRecording()
                } label: {
                    // The popover is too narrow for the word beside two meters.
                    if compact {
                        Image(systemName: "stop.fill")
                            .accessibilityLabel("Stop")
                    } else {
                        Label("Stop", systemImage: "stop.fill")
                    }
                }
                .buttonStyle(DSButtonStyle(kind: .rec, height: 28))
                .keyboardShortcut(".", modifiers: .command)
                .help("Stop and create the note (⌘.)")
            }
            TextField("Untitled meeting", text: $capture.title)
                .textFieldStyle(.plain)
                .font(.dsDisplay(compact ? 17 : 20, .medium))
                .foregroundStyle(DS.text1)
            if let invited = capture.context.inviteLine {
                // A capture from a calendar event says what the invitation will be used for.
                Text(invited)
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
            }
            HStack(spacing: compact ? 8 : 10) {
                Text("People")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                PeoplePicker(height: compact ? 24 : 26, segmentPadding: compact ? 7 : 12)
                    .frame(maxWidth: compact ? .infinity : 300, alignment: .leading)
            }
            MyNotesEditor(compact: compact)
            if let warning = capture.limitWarning {
                DSNotice(tone: .warn, symbol: "clock.badge.exclamationmark", text: warning)
            } else {
                captureStateLine
            }
        }
    }

    private func labelledMeter(_ title: String, level: Double) -> some View {
        HStack(spacing: 6) {
            // Compact has no room for the words; the name is kept for hover and VoiceOver.
            if compact {
                Image(systemName: title == "You" ? "mic.fill" : "speaker.wave.2.fill")
                    .font(.system(size: 9, weight: .semibold))
                    .foregroundStyle(DS.muted)
                    .frame(width: 14, alignment: .leading)
                    .help(title)
            } else {
                Text(title)
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                    .frame(width: 58, alignment: .leading)
            }
            LevelMeter(level: level, active: true, segments: compact ? 12 : 18, height: 7)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(title) level")
    }

    /// What this recording captures, and a way to fix it when call audio could not be recorded.
    @ViewBuilder
    private var captureStateLine: some View {
        let recorder = capture.recorder
        switch CaptureStateLine(mode: recorder.captureMode, systemAudioLost: recorder.systemAudioLost) {
        case .micAndCall:
            Text("Recording your microphone and call audio")
                .font(.dsMeta)
                .foregroundStyle(DS.muted)
        case .callAudioLost:
            DSNotice(tone: .warn, symbol: "speaker.slash.fill",
                     text: "Call audio stopped — the rest is recorded from your microphone only.")
        case .micOnlyPermissionOff:
            HStack(spacing: 6) {
                Text("Recording your microphone only — call audio permission is off")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                    .fixedSize(horizontal: false, vertical: true)
                Button("Fix") { NSWorkspace.shared.open(CallAudioConsent.privacySettingsURL) }
                    .buttonStyle(.plain)
                    .font(.dsMeta)
                    .foregroundStyle(DS.accentText)
                    .help("Open Privacy & Security → Screen & System Audio Recording")
                    .accessibilityLabel("Fix call audio permission")
                    .accessibilityHint("Opens Privacy & Security, Screen & System Audio Recording")
            }
        case .micOnlyConsentNeeded:
            HStack(spacing: 6) {
                Text("Recording your microphone only — the call audio notice changed")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                    .fixedSize(horizontal: false, vertical: true)
                Button("Review") { capture.callAudioConsentPresented = true }
                    .accessibilityLabel("Review the call audio notice")
                    .buttonStyle(.plain)
                    .font(.dsMeta)
                    .foregroundStyle(DS.accentText)
            }
        case .micOnly:
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
            // The typing does not disappear the moment the meeting ends.
            MyNotesEditor(compact: compact)
            if capture.stoppedAtLimit {
                DSNotice(tone: .warn, symbol: "clock.badge.exclamationmark",
                         text: "Stopped at the \(formatLimit(capture.recorder.limitSeconds)) limit. The note is being drafted — start a new meeting to keep recording.")
            }
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

/// "People": how many speakers the meeting has, sent with the upload. Auto and 6+ leave the count to the diarizer. Off with "Separate speakers".
struct PeoplePicker: View {
    @EnvironmentObject private var capture: CaptureViewModel
    var height: CGFloat = 30
    var segmentPadding: CGFloat = 12

    var body: some View {
        DSSegmentedPill(
            options: PeopleCount.allCases.map {
                .init($0, label: $0.label,
                      help: $0.speakersExpected == nil ? "Let the recording decide" : nil)
            },
            selection: $capture.people,
            height: height,
            segmentPadding: segmentPadding)
            .disabled(!capture.diarize)
            .opacity(capture.diarize ? 1 : 0.45)
            .help(capture.diarize ? "How many people are in the meeting"
                                  : "Turn on Separate speakers in Settings to use this")
            .accessibilityElement(children: .contain)
            .accessibilityLabel("People in the meeting")
            .accessibilityHint(capture.diarize ? "" : "Turn on Separate speakers in Settings to use this")
    }
}

/// "My notes": the note's `user_notes` section, autosaved as typed, on disk within half a second, on every device. Nothing downstream rewrites it.
struct MyNotesEditor: View {
    @EnvironmentObject private var capture: CaptureViewModel
    var compact = false

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            ZStack(alignment: .topLeading) {
                if capture.myNotes.isEmpty {
                    Text("Type what matters. We'll fill in the rest.")
                        .font(.ds(13))
                        .foregroundStyle(DS.muted)
                        .padding(.top, 7)
                        .padding(.leading, 6)
                        .allowsHitTesting(false)
                }
                TextEditor(text: $capture.myNotes)
                    .font(.ds(13))
                    .foregroundStyle(DS.text1)
                    .scrollContentBackground(.hidden)
                    .frame(minHeight: compact ? 84 : 150, maxHeight: compact ? 140 : 320)
            }
            .padding(.horizontal, 4)
            .padding(.vertical, 2)
            .background(
                RoundedRectangle(cornerRadius: DS.radiusLg, style: .continuous)
                    .fill(DS.surface2)
            )
            .accessibilityLabel("My notes")
            .accessibilityHint("Type what matters while the meeting runs")
            Text(capture.notesUnsaved ? "Saving…" : "Saved — open on any device")
                .font(.dsMeta)
                .foregroundStyle(DS.muted)
        }
    }
}

/// What kind of meeting the next one is; picks the template family. "Auto" is the default.
struct MeetingTypePicker: View {
    @EnvironmentObject private var capture: CaptureViewModel
    var height: CGFloat = 26

    var body: some View {
        DSSegmentedPill(
            options: MeetingType.allCases.map { .init($0, label: $0.label) },
            selection: $capture.meetingType,
            height: height)
            .disabled(capture.isRecording || capture.phase.isBusy)
            .accessibilityElement(children: .contain)
            .accessibilityLabel("Kind of meeting")
    }
}

/// The kind of meeting as a compact menu ("Auto ▾"), for the menu-bar popover.
struct MeetingTypeMenu: View {
    @EnvironmentObject private var capture: CaptureViewModel

    var body: some View {
        DSMenu(width: 170, items: {
            MeetingType.allCases.map { kind in
                .item(kind.label, checked: kind == capture.meetingType) { capture.meetingType = kind }
            }
        }) {
            HStack(spacing: 5) {
                Text(capture.meetingType.label)
                    .font(.ds(12.5, .medium))
                    .lineLimit(1)
                Image(systemName: "chevron.down")
                    .font(.dsIcon(9, .semibold))
                    .foregroundStyle(DS.muted)
            }
            .fixedSize()
            .foregroundStyle(DS.text1)
            .padding(.horizontal, 10)
            .frame(height: 32)
            .background(
                RoundedRectangle(cornerRadius: DS.radiusSm, style: .continuous)
                    .fill(DS.surface)
                    .overlay(
                        RoundedRectangle(cornerRadius: DS.radiusSm, style: .continuous)
                            .strokeBorder(DS.line, lineWidth: DS.hairline)
                    )
            )
            .contentShape(Rectangle())
        }
        .disabled(capture.isRecording || capture.phase.isBusy)
        .help("Kind of meeting")
        .accessibilityLabel("Kind of meeting: \(capture.meetingType.label)")
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
