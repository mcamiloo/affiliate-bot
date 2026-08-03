// Lê o snapshot que scripts/write_widget_snapshot.py materializa a partir
// dos mesmos dados que a Home do painel Flask mostra. A extensão roda em
// App Sandbox (exigência do WidgetKit no macOS) e não pode abrir o
// SQLite, ler logs/.env, nem chamar launchctl/pgrep diretamente — a
// única leitura liberada (via temporary-exception entitlement) é este
// único arquivo JSON.
import Foundation

struct OfferSummary: Decodable {
    let itemId: String
    let title: String
    let price: Double
    let originalPrice: Double?
    let discountPercent: Double?
    let category: String?
    let headline: String

    enum CodingKeys: String, CodingKey {
        case itemId = "item_id"
        case title, price
        case originalPrice = "original_price"
        case discountPercent = "discount_percent"
        case category, headline
    }
}

struct DashboardSnapshot: Decodable {
    let mainBotRunning: Bool
    let lastCycleAt: Date?
    let lastCycleCount: Int?
    let newsletterRunning: Bool
    let whatsappEnabled: Bool
    let whatsappAppRunning: Bool
    let offersToday: Int
    let offersWeek: Int
    let latestOffers: [OfferSummary]

    enum CodingKeys: String, CodingKey {
        case mainBotRunning = "main_bot_running"
        case lastCycleAt = "last_cycle_at"
        case lastCycleCount = "last_cycle_count"
        case newsletterRunning = "newsletter_running"
        case whatsappEnabled = "whatsapp_enabled"
        case whatsappAppRunning = "whatsapp_app_running"
        case offersToday = "offers_today"
        case offersWeek = "offers_week"
        case latestOffers = "latest_offers"
    }

    static let placeholder = DashboardSnapshot(
        mainBotRunning: true, lastCycleAt: Date(), lastCycleCount: 1,
        newsletterRunning: true, whatsappEnabled: false, whatsappAppRunning: false,
        offersToday: 3, offersWeek: 21, latestOffers: []
    )
}

enum DataStore {
    // Único lugar com o caminho hardcoded — o widget só roda nesse Mac.
    // Precisam bater exatamente com config.WIDGET_SNAPSHOT_PATH e
    // config.WIDGET_RUN_TRIGGER_PATH (Python) e com os caminhos liberados
    // em OmbroPanelWidget.entitlements — os três lados têm que concordar.
    static let repoRoot = URL(fileURLWithPath: "/Users/miguelcamilo/affiliate-bot")
    static let snapshotPath = repoRoot.appendingPathComponent("state/widget_snapshot.json")
    static let triggerPath = repoRoot.appendingPathComponent("state/widget_run_trigger")

    static func loadSnapshot() -> DashboardSnapshot {
        guard let data = try? Data(contentsOf: snapshotPath) else { return .placeholder }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return (try? decoder.decode(DashboardSnapshot.self, from: data)) ?? .placeholder
    }
}
