// App host — não faz nada sozinho, só existe pra hospedar a extensão de
// widget (WidgetKit exige um app container). LSUIElement=true no Info.plist
// mantém fora do Dock; ainda assim precisa ser aberto uma vez (`open`) pra
// o macOS registrar a extensão e o widget aparecer no catálogo.
import SwiftUI

@main
struct OmbroPanelApp: App {
    var body: some Scene {
        WindowGroup {
            VStack(spacing: 12) {
                Text("OmbroPanel").font(.title2).bold()
                Text("Este app só existe pra hospedar o widget da área de trabalho.")
                    .multilineTextAlignment(.center)
                    .foregroundStyle(.secondary)
                Text("Clique direito na área de trabalho → Editar Widgets → OmbroPanel.")
                    .font(.caption)
                    .multilineTextAlignment(.center)
            }
            .padding(40)
            .frame(width: 360, height: 220)
        }
        .windowResizability(.contentSize)
    }
}
