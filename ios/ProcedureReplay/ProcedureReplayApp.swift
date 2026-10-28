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
      RootView()
        .preferredColorScheme(.light)
        .onOpenURL { url in
          Task { _ = try? await Wearables.shared.handleUrl(url) }
        }
    }
  }
}
