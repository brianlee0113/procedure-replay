// Where the Mac server is, and what plays the part of the glasses. Stored on the phone (UserDefaults).

import SwiftUI

enum FeedMode: String, CaseIterable, Identifiable {
  /// The iPhone's rear camera is the glasses camera and its mic records the instructor (iPhone on head or chest).
  case phoneCamera
  /// A licensed first-person video plays as the glasses camera (scripts/make_mock_feed.sh); works in the simulator.
  case demoVideo

  var id: String { rawValue }
  var title: String { self == .phoneCamera ? "iPhone camera + mic" : "Demo video" }
}

enum AppSettings {
  private static let defaults = UserDefaults.standard

  /// Launch environment PR_SERVER wins (simulator runs), then the Settings screen, then localhost.
  static var serverURL: URL {
    if let env = ProcessInfo.processInfo.environment["PR_SERVER"], let url = URL(string: env) { return url }
    if let saved = defaults.string(forKey: "serverURL"), let url = URL(string: saved) { return url }
    return URL(string: "http://localhost:8000")!
  }

  static var feedMode: FeedMode {
    get {
      if let env = ProcessInfo.processInfo.environment["PR_FEED"], let mode = FeedMode(rawValue: env) { return mode }
      #if targetEnvironment(simulator)
        let fallback = FeedMode.demoVideo  // the simulator has no camera
      #else
        let fallback = FeedMode.phoneCamera
      #endif
      return defaults.string(forKey: "feedMode").flatMap(FeedMode.init) ?? fallback
    }
    set { defaults.set(newValue.rawValue, forKey: "feedMode") }
  }

  /// Credited as the creator of recordings made with the iPhone camera (license CC BY 4.0).
  static var creatorName: String {
    get { defaults.string(forKey: "creatorName") ?? API.userName }
    set { defaults.set(newValue, forKey: "creatorName") }
  }
}

struct SettingsView: View {
  @Environment(\.dismiss) private var dismiss
  @State private var server = AppSettings.serverURL.absoluteString
  @State private var mode = AppSettings.feedMode
  @State private var creator = AppSettings.creatorName
  @State private var check: String?

  var body: some View {
    NavigationStack {
      Form {
        Section {
          TextField("http://192.168.1.20:8000", text: $server)
            .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
          Button("Test connection") { Task { await test() } }
          if let check { Text(check).font(.footnote).foregroundStyle(Color.inkSecondary) }
        } header: {
          Text("Mac server")
        } footer: {
          Text("On the Mac: uv run uvicorn pr.server:app --host 0.0.0.0 --port 8000. Use the Mac's IP on the same network.")
        }
        Section {
          Picker("Glasses camera", selection: $mode) {
            ForEach(FeedMode.allCases) { Text($0.title).tag($0) }
          }
          if mode == .phoneCamera {
            TextField("Your name", text: $creator)
          }
        } header: {
          Text("Glasses (simulated)")
        } footer: {
          Text(mode == .phoneCamera
               ? "Wear or hold the iPhone at eye level: its camera is the glasses camera and its mic records you. Your recording is uploaded as yours under CC BY 4.0."
               : "A licensed first-person video plays as the glasses camera.")
        }
      }
      .navigationTitle("Settings")
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .confirmationAction) {
          Button("Done") {
            UserDefaults.standard.set(server.trimmingCharacters(in: .whitespaces), forKey: "serverURL")
            AppSettings.feedMode = mode
            AppSettings.creatorName = creator
            dismiss()
          }
        }
      }
    }
  }

  private func test() async {
    guard let url = URL(string: server.trimmingCharacters(in: .whitespaces))?.appendingPathComponent("categories") else {
      check = "That isn't a valid address."
      return
    }
    do {
      let (_, response) = try await URLSession.shared.data(from: url)
      check = (response as? HTTPURLResponse)?.statusCode == 200 ? "Connected." : "The server answered with an error."
    } catch {
      check = "Can't reach it: \(error.localizedDescription). On campus Wi-Fi, devices often can't see each other; connect the Mac to the iPhone's Personal Hotspot instead."
    }
  }
}
