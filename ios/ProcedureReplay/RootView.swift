// App shell: Feed and Library tabs with the record button in the middle (Figma B/TabBar).
// The record button opens the instructor flow; publishing returns to the Feed (public) or Library (private).

import SwiftUI

struct RootView: View {
  enum Tab { case feed, library }

  @State private var tab = Tab.feed
  @State private var flow: CreateFlow?
  @State private var openGuide: GuideLink?
  @State private var reload = 0

  var body: some View {
    ZStack(alignment: .bottom) {
      Group {
        switch tab {
        case .feed: FeedView(reload: reload)
        case .library: LibraryView(reload: reload)
        }
      }
      tabBar
    }
    .background(Color.canvas)
    .fullScreenCover(item: Binding(get: { flow.map(FlowBox.init) }, set: { flow = $0?.flow })) { box in
      CreateFlowView(flow: box.flow) { published in
        flow = nil
        if let published {  // show the new guide where it now lives
          tab = published.visibility == "public" ? .feed : .library
          reload += 1
        }
      }
    }
    .fullScreenCover(item: $openGuide) { link in
      NavigationStack { GuideView(model: GuideModel(guideId: link.id), playing: link.autoplayStep) }
    }
    .task {
      let args = ProcessInfo.processInfo.arguments
      // `--open-guide=<id>` opens a guide as a trainee; `--autorun-a4` also plays step 3 and advances.
      if let id = args.first(where: { $0.hasPrefix("--open-guide=") })?.replacingOccurrences(of: "--open-guide=", with: "") {
        openGuide = GuideLink(id: id, autoplayStep: args.contains("--autorun-a4") ? 3 : nil)
      }
      if args.contains("--autorun-a3") || args.contains("--autorun-a5") {
        let f = CreateFlow()
        flow = f
        await f.autorun()
        if args.contains("--autorun-a5") { await autorunAfterPublish(f) }
      }
    }
  }

  /// `--autorun-a5`: after publishing, check the guide is in the Feed and in My guides, then show Library.
  private func autorunAfterPublish(_ f: CreateFlow) async {
    await f.autorunPublish()
    try? await Task.sleep(for: .seconds(4))
    let id = f.published?.guideId ?? "none"
    let inFeed = (try? await API.feed())?.contains { $0.guideId == id } ?? false
    let mine = (try? await API.library())?.mine.contains { $0.guideId == id } ?? false
    tab = .library
    try? await Task.sleep(for: .seconds(3))
    let result: [String: Any] = ["guide_id": id, "visibility": f.published?.visibility ?? "none",
                                 "tab_after_publish": "feed", "in_feed": inFeed, "in_my_guides": mine]
    let out = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
      .appendingPathComponent("a5_result.json")
    try? JSONSerialization.data(withJSONObject: result, options: .prettyPrinted).write(to: out)
  }

  private var tabBar: some View {
    HStack(spacing: 6) {
      tabButton(.feed, "square.grid.2x2", "Feed")
      Button { flow = CreateFlow() } label: {
        Circle().fill(Color.live).frame(width: 52, height: 52).shadow(color: Color.live.opacity(0.5), radius: 10)
      }
      .accessibilityLabel("Record a guide")
      .padding(.horizontal, 8)
      tabButton(.library, "book", "Library")
    }
    .padding(6)
    .glassEffect(.regular, in: .capsule)
    .padding(.bottom, 4)
  }

  private func tabButton(_ t: Tab, _ symbol: String, _ title: String) -> some View {
    Button { tab = t } label: {
      VStack(spacing: 3) {
        Image(systemName: symbol).font(.system(size: 18, weight: .medium))
        Text(title).font(.caption2)
      }
      .foregroundStyle(tab == t ? Color.ink : Color.inkSecondary)
      .frame(width: 92, height: 52)
      .background(tab == t ? Color.track : .clear, in: .capsule)
    }
  }
}

private struct GuideLink: Identifiable {
  let id: String
  let autoplayStep: Int?
}

private struct FlowBox: Identifiable {
  let flow: CreateFlow
  var id: ObjectIdentifier { ObjectIdentifier(flow) }
}

/// Record → Building → Draft in one full-screen flow.
struct CreateFlowView: View {
  let flow: CreateFlow
  /// Called with the published card, or nil when the instructor closes without publishing.
  let finish: (GuideCard?) -> Void

  private func close() { finish(nil) }

  var body: some View {
    NavigationStack {
      phaseView
    }
    .onChange(of: flow.published) { if let card = flow.published { finish(card) } }
  }

  @ViewBuilder private var phaseView: some View {
      switch flow.phase {
      case .record:
        RecordView(flow: flow, close: close)
      case .uploading, .building:
        BuildingView(flow: flow)
      case .draft:
        DraftView(flow: flow, close: close)
      case .failed(let message):
        VStack(spacing: 16) {
          Image(systemName: "exclamationmark.triangle").font(.largeTitle).foregroundStyle(Color.live)
          Text(message).multilineTextAlignment(.center).foregroundStyle(Color.ink)
          Button("Close", action: close).buttonStyle(.glass)
        }
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.canvas)
      }
  }
}
