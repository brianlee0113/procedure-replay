// Step 5 · Feed: public guides, newest first, filtered by category. Likes and saves only.

import SwiftUI

struct FeedView: View {
  let reload: Int
  var startRecording: () -> Void = {}

  @State private var cards: [GuideCard] = []
  @State private var categories: [(id: String, label: String)] = []
  @State private var selected: String?
  @State private var error: String?
  @State private var loaded = false
  @State private var opened: GuideCard?
  @State private var showSettings = false

  var body: some View {
    NavigationStack {
      ScrollView {
        VStack(alignment: .leading, spacing: 14) {
          HStack {
            Text("Feed").font(.largeTitle.bold()).foregroundStyle(Color.ink)
            Spacer()
            Button { showSettings = true } label: {
              Image(systemName: "gearshape").font(.system(size: 17, weight: .semibold)).frame(width: 40, height: 40)
            }
            .glassEffect(.regular.interactive(), in: .circle)
            .foregroundStyle(Color.ink)
            .accessibilityLabel("Settings")
          }
          ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
              CategoryChip(label: "All", selected: selected == nil) { selected = nil }
              ForEach(categories, id: \.id) { c in
                CategoryChip(label: c.label, selected: selected == c.id) { selected = c.id }
              }
            }
          }
          if let error {
            StateMessage(symbol: "wifi.exclamationmark", title: "Can't reach the Mac server", message: error,
                         actionTitle: "Try again") { Task { await load() } }
          } else if !loaded {
            ProgressView().frame(maxWidth: .infinity).padding(.top, 60)
          } else if cards.isEmpty && selected != nil {
            StateMessage(symbol: "square.grid.2x2", title: "Nothing here yet",
                         message: "No public guides in this category yet.", actionTitle: "Show all") { selected = nil }
          } else if cards.isEmpty {
            StateMessage(symbol: "video.badge.plus", title: "No public guides yet",
                         message: "Record a job with your glasses and publish it as Public. It will show up here.",
                         actionTitle: "Record a guide", action: startRecording)
          }
          ForEach($cards) { $card in
            FeedCard(card: $card) { opened = card }
          }
        }
        .padding(.horizontal, 16)
        .padding(.top, 8)
        .padding(.bottom, 100)
      }
      .background(Color.canvas)
      .refreshable { await load() }
      .task(id: "\(reload)-\(selected ?? "all")") { await load() }
      .sheet(isPresented: $showSettings, onDismiss: { Task { await load() } }) { SettingsView() }
      // Full screen, so the tab bar doesn't float over the guide.
      .fullScreenCover(item: $opened) { card in
        NavigationStack { GuideView(model: GuideModel(guideId: card.guideId)) }.edgeSwipeBack()
      }
      .onChange(of: opened) { if opened == nil { Task { await load() } } }  // likes may have changed
    }
  }

  private func load() async {
    do {
      cards = try await API.feed(category: selected)
      error = nil
      loaded = true
      if categories.isEmpty { categories = (try? await API.categories()) ?? [] }
    } catch {
      self.error = "Start the server on your Mac (uv run uvicorn pr.server:app --port 8000), then try again. Looking for it at \(API.base.absoluteString)."
    }
  }
}

struct FeedCard: View {
  @Binding var card: GuideCard
  let open: () -> Void

  var body: some View {
    ZStack {
      // A fill-scaled image proposes its own width; keep it inside a fixed frame so the card stays screen-wide.
      Color.track
        .frame(height: 440)
        .overlay { AsyncImage(url: API.url(card.coverUrl)) { $0.resizable().scaledToFill() } placeholder: { Color.track } }
        .clipped()
      LinearGradient(stops: [.init(color: .black.opacity(0.35), location: 0), .init(color: .clear, location: 0.3),
                             .init(color: .black.opacity(0.05), location: 0.5), .init(color: .black.opacity(0.85), location: 1)],
                     startPoint: .top, endPoint: .bottom)
      VStack(alignment: .leading) {
        HStack {
          Text(card.categoryLabel).font(.footnote.weight(.medium))
            .padding(.horizontal, 12).padding(.vertical, 7).glassEffect(.regular, in: .capsule)
          Spacer()
          Text("\(card.steps) steps · \(clock(card.durationS))".uppercased()).font(.eyebrow)
            .padding(.horizontal, 12).padding(.vertical, 8).glassEffect(.regular, in: .capsule)
        }
        Spacer()
        Text(card.title).font(.title2.bold()).multilineTextAlignment(.leading)
        HStack(spacing: 8) {
          Avatar(name: card.authorName, size: 28)
          Text([card.authorName, card.authorRole].filter { !$0.isEmpty }.joined(separator: " · "))
            .font(.caption).lineLimit(1)
          Spacer()
          ReactionButton(symbol: card.liked ? "heart.fill" : "heart", count: card.likes,
                         tint: card.liked ? Color.live : .white, label: card.liked ? "Unlike" : "Like") {
            await toggle(.like)
          }
          ReactionButton(symbol: card.saved ? "bookmark.fill" : "bookmark", count: card.saves, tint: .white,
                         label: card.saved ? "Remove from saved" : "Save") {
            await toggle(.save)
          }
        }
      }
      .foregroundStyle(.white)
      .padding(16)
      .environment(\.colorScheme, .dark)
    }
    .frame(height: 440)
    .clipShape(RoundedRectangle(cornerRadius: 28))
    .contentShape(RoundedRectangle(cornerRadius: 28))
    .onTapGesture(perform: open)
    .accessibilityElement(children: .contain)
    .accessibilityAction(named: "Open guide", open)
  }

  private func toggle(_ kind: Reaction) async {
    let on = kind == .like ? !card.liked : !card.saved
    if let r = try? await API.react(guideId: card.guideId, kind, on: on) {
      card.likes = r.likes
      card.saves = r.saves
      card.liked = r.liked
      card.saved = r.saved
    }
  }
}

struct ReactionButton: View {
  let symbol: String
  let count: Int
  let tint: Color
  let label: String
  let action: () async -> Void

  var body: some View {
    Button { Task { await action() } } label: {
      Label("\(count)", systemImage: symbol).font(.footnote.weight(.medium)).foregroundStyle(tint)
        .padding(.horizontal, 12).padding(.vertical, 8)
    }
    .glassEffect(.regular.interactive(), in: .capsule)
    .accessibilityLabel(label)
  }
}

struct Avatar: View {
  let name: String
  var size: CGFloat = 32

  var body: some View {
    Text(name.split(separator: " ").compactMap(\.first).prefix(2).map(String.init).joined())
      .font(.system(size: size * 0.36, weight: .medium, design: .monospaced)).foregroundStyle(.white)
      .frame(width: size, height: size)
      .background(Color.ai, in: .circle)
  }
}
