import SwiftUI

struct StatusDot: View {
    let running: Bool
    var body: some View {
        Circle()
            .fill(running ? Color.green : Color.red)
            .frame(width: 9, height: 9)
    }
}

struct ServiceRow: View {
    let label: String
    let running: Bool

    var body: some View {
        HStack(spacing: 6) {
            StatusDot(running: running)
            Text(label).font(.caption)
            Spacer()
            Text(running ? "rodando" : "parado")
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
    }
}
