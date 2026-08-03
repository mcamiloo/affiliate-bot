// Botão "Rodar ciclo agora" do widget grande. Em App Sandbox a extensão
// não pode Process()-spawnar o python direto (bloqueado pelo sandbox),
// então em vez disso escreve nesse arquivo já existente — um launchd
// agent com WatchPaths (com.miguelcamilo.affiliatebot.widgettrigger)
// reage a isso fora do sandbox e roda scripts/run_cycle_now.py de
// verdade. Escreve com FileHandle (mesmo inode, sem unlink/rename) porque
// WatchPaths do launchd é baseado em kqueue e pode perder o evento se o
// arquivo for substituído em vez de modificado in-place.
import AppIntents
import WidgetKit
import Foundation

struct RunCycleNowIntent: AppIntent {
    static var title: LocalizedStringResource = "Rodar ciclo agora"
    static var description = IntentDescription("Dispara manualmente um ciclo do bot de ofertas.")

    func perform() async throws -> some IntentResult {
        if let handle = try? FileHandle(forWritingTo: DataStore.triggerPath) {
            let payload = Data(ISO8601DateFormatter().string(from: Date()).utf8)
            handle.seek(toFileOffset: 0)
            handle.write(payload)
            try? handle.truncate(atOffset: UInt64(payload.count))
            try? handle.close()
        }
        WidgetCenter.shared.reloadAllTimelines()
        return .result()
    }
}
