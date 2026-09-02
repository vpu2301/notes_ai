import SwiftUI

struct RootView: View {
    enum Tab: CaseIterable {
        case capture, recents, settings

        var symbol: String {
            switch self {
            case .capture: return "mic"
            case .recents: return "clock"
            case .settings: return "gearshape"
            }
        }

        var help: String {
            switch self {
            case .capture: return "Capture"
            case .recents: return "Recent captures"
            case .settings: return "Settings"
            }
        }
    }

    @EnvironmentObject private var app: AppState
    @State private var tab: Tab = .capture

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            content
        }
        .frame(width: 340)
    }

    private var header: some View {
        HStack(spacing: 8) {
            Image(systemName: "waveform.circle.fill")
                .font(.title3)
                .foregroundStyle(Color.accentColor)
            Text("Notes AI Capture")
                .font(.headline)
            Spacer()
            if app.authState == .signedIn {
                ForEach(Tab.allCases, id: \.self) { item in
                    Button {
                        tab = item
                    } label: {
                        Image(systemName: item.symbol)
                            .font(.system(size: 13, weight: .medium))
                            .frame(width: 24, height: 22)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(tab == item ? Color.accentColor : Color.secondary)
                    .help(item.help)
                }
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
    }

    @ViewBuilder
    private var content: some View {
        switch app.authState {
        case .restoring:
            VStack(spacing: 10) {
                ProgressView()
                Text("Connecting…")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 44)
        case .signedOut:
            SignInView()
        case .signedIn:
            switch tab {
            case .capture: CaptureView()
            case .recents: RecentsView()
            case .settings: SettingsView()
            }
        }
    }
}
