import SwiftUI
import WidgetKit

struct OmbroPanelWidget: Widget {
    let kind: String = "OmbroPanelWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: Provider()) { entry in
            OmbroPanelWidgetView(snapshot: entry.snapshot)
        }
        .configurationDisplayName("OmbroPanel")
        .description("Status do bot de afiliados e últimas ofertas publicadas.")
        .supportedFamilies([.systemSmall, .systemMedium, .systemLarge])
    }
}

struct OmbroPanelWidgetView: View {
    @Environment(\.widgetFamily) private var family
    let snapshot: DashboardSnapshot

    var body: some View {
        Group {
            switch family {
            case .systemSmall:
                SmallView(snapshot: snapshot)
            case .systemMedium:
                MediumView(snapshot: snapshot)
            default:
                LargeView(snapshot: snapshot)
            }
        }
        // Obrigatório desde macOS 14 (deploymentTarget deste projeto) — sem
        // isso o WidgetKit recusa desenhar o conteúdo e mostra só o aviso
        // "Please adopt containerBackground API" no lugar do widget.
        .containerBackground(for: .widget) {
            Color(nsColor: .windowBackgroundColor)
        }
    }
}

@main
struct OmbroPanelWidgetBundle: WidgetBundle {
    var body: some Widget {
        OmbroPanelWidget()
    }
}
