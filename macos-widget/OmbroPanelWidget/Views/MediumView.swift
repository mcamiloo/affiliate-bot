import SwiftUI

struct MediumView: View {
    let snapshot: DashboardSnapshot

    var body: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 6) {
                Text("OmbroPanel").font(.caption2).fontWeight(.bold).foregroundStyle(.secondary)
                ServiceRow(label: "Bot principal", running: snapshot.mainBotRunning)
                ServiceRow(label: "Newsletter", running: snapshot.newsletterRunning)
                ServiceRow(label: "WhatsApp", running: !snapshot.whatsappEnabled || snapshot.whatsappAppRunning)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 2) {
                Text("\(snapshot.offersToday)").font(.system(size: 24, weight: .heavy))
                Text("hoje").font(.caption2).foregroundStyle(.secondary)
                Text("\(snapshot.offersWeek)").font(.system(size: 17, weight: .bold)).padding(.top, 4)
                Text("semana").font(.caption2).foregroundStyle(.secondary)
            }
        }
        .padding()
    }
}
