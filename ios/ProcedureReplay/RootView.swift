// App shell: Feed and Library tabs with the record button in the middle (Figma B/TabBar).
// Feed and Library get their content in A5; the record button opens the instructor flow.

import SwiftUI

struct RootView: View {
  enum Tab { case feed, library }

  @State private var tab = Tab.feed
  @State private var flow: CreateFlow?
  @State private var openGuide: GuideLink?

  var body: some View {
    ZStack(alignment: .bottom) {
      Group {
        switch tab {
        case .feed: Placeholder(title: "Feed", message: "Public guides will appear here.")
        case .library: Placeholder(title: "Library", message: "Guides you saved and guides you recorded will appear here.")
        }
      }
      tabBar
    }
    .background(Color.canvas)
    .fullScreenCover(item: Binding(get: { flow.map(FlowBox.init) }, set: { flow = $0?.flow })) { box in
      CreateFlowView(flow: box.flow) { flow = nil }
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
      if args.contains("--autorun-a3") {
        let f = CreateFlow()
        flow = f
        await f.autorun()
      }
    }
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

private struct Placeholder: View {
  let title: String
  let message: String

  var body: some View {
    VStack(alignment: .leading, spacing: 12) {
      Text(title).font(.largeTitle.bold()).foregroundStyle(Color.ink)
      Text(message).font(.callout).foregroundStyle(Color.inkSecondary)
      Spacer()
    }
    .frame(maxWidth: .infinity, alignment: .leading)
    .padding(16)
  }
}

/// Record → Building → Draft in one full-screen flow.
struct CreateFlowView: View {
  let flow: CreateFlow
  let close: () -> Void

  var body: some View {
    NavigationStack {
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
}
