import SwiftUI

struct SmallView: View {
    let snapshot: DashboardSnapshot

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("OmbroPanel").font(.caption2).fontWeight(.bold).foregroundStyle(.secondary)
            HStack(spacing: 6) {
                StatusDot(running: snapshot.mainBotRunning)
                StatusDot(running: snapshot.newsletterRunning)
                StatusDot(running: !snapshot.whatsappEnabled || snapshot.whatsappAppRunning)
            }
            Spacer()
            Text("\(snapshot.offersToday)")
                .font(.system(size: 30, weight: .heavy))
            Text("ofertas hoje")
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .padding()
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    }
}
