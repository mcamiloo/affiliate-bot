import SwiftUI

struct LargeView: View {
    let snapshot: DashboardSnapshot

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("OmbroPanel").font(.headline)

            VStack(alignment: .leading, spacing: 3) {
                ServiceRow(label: "Bot principal", running: snapshot.mainBotRunning)
                ServiceRow(label: "Newsletter", running: snapshot.newsletterRunning)
                ServiceRow(label: "WhatsApp", running: !snapshot.whatsappEnabled || snapshot.whatsappAppRunning)
            }

            HStack(spacing: 4) {
                Text("\(snapshot.offersToday) hoje").font(.caption)
                Text("·").foregroundStyle(.secondary)
                Text("\(snapshot.offersWeek) essa semana").font(.caption)
            }
            .foregroundStyle(.secondary)

            Divider()

            VStack(alignment: .leading, spacing: 5) {
                Text("Últimas ofertas").font(.caption).fontWeight(.bold)
                if snapshot.latestOffers.isEmpty {
                    Text("Nenhuma ainda.").font(.caption2).foregroundStyle(.secondary)
                }
                ForEach(snapshot.latestOffers, id: \.itemId) { offer in
                    VStack(alignment: .leading, spacing: 1) {
                        Text(offer.title)
                            .font(.caption2)
                            .lineLimit(1)
                        HStack(spacing: 4) {
                            Text("£\(offer.price, specifier: "%.2f")")
                                .font(.caption2)
                                .fontWeight(.bold)
                            if let discount = offer.discountPercent {
                                Text("· \(Int(discount))% OFF")
                                    .font(.caption2)
                            }
                        }
                        .foregroundStyle(.secondary)
                    }
                }
            }

            Spacer(minLength: 4)

            Button(intent: RunCycleNowIntent()) {
                Text("▶ Rodar ciclo agora")
                    .font(.caption)
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
        }
        .padding()
    }
}
