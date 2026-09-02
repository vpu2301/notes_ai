import SwiftUI

// MARK: - Status chip

struct StatusChip: View {
    let status: JobStatus?

    var body: some View {
        Text(status?.label ?? "Unknown")
            .font(.caption2.weight(.semibold))
            .padding(.horizontal, 7)
            .padding(.vertical, 2)
            .background(Capsule().fill(color.opacity(0.16)))
            .foregroundStyle(color)
    }

    private var color: Color {
        switch status {
        case .queued: return .gray
        case .running: return .blue
        case .complete: return .green
        case .failed: return .red
        case .cancelled: return .orange
        case nil: return .gray
        }
    }
}

// MARK: - Pulsing recording dot

struct PulsingDot: View {
    @State private var dimmed = false

    var body: some View {
        Circle()
            .fill(.red)
            .frame(width: 8, height: 8)
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

    private let segments = 24

    var body: some View {
        HStack(spacing: 3) {
            ForEach(0..<segments, id: \.self) { index in
                let threshold = Double(index) / Double(segments)
                Capsule()
                    .fill(color(for: threshold))
                    .frame(width: 4, height: 14)
                    .opacity(active && level > threshold ? 1 : 0.18)
            }
        }
        .animation(.linear(duration: 0.08), value: level)
        .accessibilityLabel("Input level")
    }

    private func color(for threshold: Double) -> Color {
        if threshold > 0.85 { return .red }
        if threshold > 0.65 { return .orange }
        return .green
    }
}

// MARK: - Helpers

func formatElapsed(_ interval: TimeInterval) -> String {
    let seconds = Int(interval)
    return String(format: "%02d:%02d", seconds / 60, seconds % 60)
}
