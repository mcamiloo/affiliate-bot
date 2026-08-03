import WidgetKit

struct DashboardEntry: TimelineEntry {
    let date: Date
    let snapshot: DashboardSnapshot
}

struct Provider: TimelineProvider {
    func placeholder(in context: Context) -> DashboardEntry {
        DashboardEntry(date: Date(), snapshot: .placeholder)
    }

    func getSnapshot(in context: Context, completion: @escaping (DashboardEntry) -> Void) {
        completion(DashboardEntry(date: Date(), snapshot: DataStore.loadSnapshot()))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<DashboardEntry>) -> Void) {
        let entry = DashboardEntry(date: Date(), snapshot: DataStore.loadSnapshot())
        // O sistema controla o orçamento real de refresh — isso é só o
        // pedido; pode ser espaçado mais pelo macOS. O botão "Rodar ciclo
        // agora" força um reload imediato à parte (ver RunCycleIntent).
        let nextUpdate = Calendar.current.date(byAdding: .minute, value: 10, to: Date()) ?? Date().addingTimeInterval(600)
        completion(Timeline(entries: [entry], policy: .after(nextUpdate)))
    }
}
