import MWDATCore
import SwiftUI

@main
struct ProcedureReplayApp: App {
  init() {
    do {
      try Wearables.configure()
    } catch {
      NSLog("[ProcedureReplay] Wearables.configure failed: \(error)")
    }
  }

  var body: some Scene {
    WindowGroup {
      GlassesSpikeView()
        .onOpenURL { url in
          Task { _ = try? await Wearables.shared.handleUrl(url) }
        }
    }
  }
}
