// Library: your profile, the guide you were following, then one grid at a time: My guides, Saved or Liked.

import SwiftUI

struct LibraryView: View {
  let reload: Int
  /// Bumped when a draft is opened from a profile: close the guide open on top so the Draft editor can show.
  var home = 0
  /// Opened by tapping your own name: same layout, with a Back bar instead of the "Library" title.
  var pushed = false
  /// Opens a draft in the Draft editor, so the instructor can keep editing and publish it.
  var openDraft: (String) -> Void = { _ in }

  @State private var library: Library?
  @State private var error: String?
  @State private var opened: OpenedGuide?
  /// The shelf in view; the grids page sideways, so a swipe or a tab tap moves it.
  @State private var page: Shelf? = .mine
  private var tab: Shelf { page ?? .mine }
  @Environment(\.dismiss) private var dismiss
  @Environment(\.slideBack) private var slideBack

  enum Shelf: String, CaseIterable {
    case mine = "My guides", saved = "Saved", liked = "Liked"
  }

  var body: some View {
    NavigationStack {
      ScrollView {
        VStack(alignment: .leading, spacing: 16) {
          if !pushed {
            Text("Library").font(.largeTitle.bold()).foregroundStyle(Color.ink)
          }
          if let error {
            StateMessage(symbol: "wifi.exclamationmark", title: "Can't reach the Mac server", message: error,
                         actionTitle: "Try again") { Task { await load() } }
          } else if library == nil {
            ProgressView().frame(maxWidth: .infinity).padding(.top, 60)
          }
          if let library {
            ProfileHeader(name: AppSettings.creatorName, profile: library.profile)
            // One card tall however many guides are under way; swipe sideways for the others.
            ScrollView(.horizontal) {
              LazyHStack(spacing: 10) {
                ForEach(library.continue) { card in
                  ContinueCard(card: card) {
                    withoutAnimation { opened = OpenedGuide(card: card, step: card.step, cards: library.continue) }
                  }
                    .containerRelativeFrame(.horizontal)
                }
              }
              .scrollTargetLayout()
            }
            .scrollTargetBehavior(.viewAligned)
            .scrollIndicators(.hidden)
            tabs(library)
            shelves(library)
          }
        }
        .padding(.horizontal, 16)
        .padding(.top, 8)
        .padding(.bottom, pushed ? 40 : 100)  // no tab bar over a pushed one
      }
      .safeAreaInset(edge: .top, spacing: 0) { if pushed { navBar } }
      .background(Color.canvas)
      .refreshable { await load() }
      .task(id: reload) { await load() }
      // Full screen, so the tab bar doesn't float over the guide.
      .fullScreenCover(item: $opened) { o in
        // Story feed (branch story-feed): Continue lands on the step where you stopped, skipping the summary.
        StoryFeedView(cards: o.cards, start: o.card, startStep: o.step).edgeSwipeBack()
      }
      .onChange(of: opened) { if opened == nil { Task { await load() } } }
      .onChange(of: home) { withoutAnimation { opened = nil } }
    }
  }

  /// Back and your name, like someone else's profile (ProfileView).
  private var navBar: some View {
    ZStack {
      Text(AppSettings.creatorName).font(.headline).foregroundStyle(Color.ink)
      HStack {
        Button { if let slideBack { slideBack() } else { dismiss() } } label: {
          Image(systemName: "chevron.left").font(.system(size: 17, weight: .semibold)).frame(width: 44, height: 44)
        }
        .glassEffect(.regular.interactive(), in: .circle)
        .foregroundStyle(Color.ink)
        .accessibilityLabel("Back")
        Spacer()
      }
    }
    .padding(.horizontal, 16)
    .padding(.vertical, 6)
    .background(Color.canvas)
  }

  /// My guides, Saved and Liked side by side; swipe left or right to move between them.
  private func shelves(_ library: Library) -> some View {
    ScrollView(.horizontal) {
      HStack(alignment: .top, spacing: 0) {
        ForEach(Shelf.allCases, id: \.self) { shelf in
          grid(cards(shelf, library), shelf: shelf)
            .frame(maxWidth: .infinity, alignment: .topLeading)
            .containerRelativeFrame(.horizontal)
            .id(shelf)
        }
      }
      .scrollTargetLayout()
    }
    .scrollTargetBehavior(.paging)
    .scrollPosition(id: $page)
    .scrollIndicators(.hidden)
  }

  private func cards(_ shelf: Shelf, _ library: Library) -> [GuideCard] {
    switch shelf {
    case .mine: library.mine
    case .saved: library.saved
    case .liked: library.liked
    }
  }

  private func emptyMessage(_ shelf: Shelf) -> String {
    switch shelf {
    case .mine: "Guides you record appear here."
    case .saved: "Tap the bookmark on a guide to keep it here."
    case .liked: "Guides you like appear here."
    }
  }

  private func tabs(_ library: Library) -> some View {
    HStack(spacing: 0) {
      ForEach(Shelf.allCases, id: \.self) { shelf in
        let on = shelf == tab
        Button { withAnimation(.snappy) { page = shelf } } label: {
          VStack(spacing: 8) {
            Text("\(shelf.rawValue) \(count(shelf, library))")
              .font(.subheadline.weight(on ? .semibold : .medium))
              .foregroundStyle(on ? Color.ink : Color.inkSecondary)
            Rectangle().fill(on ? Color.ink : Color.track).frame(height: on ? 2 : 1)
          }
          .frame(maxWidth: .infinity)
          .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(on ? .isSelected : [])
      }
    }
    .padding(.top, 4)
  }

  private func count(_ shelf: Shelf, _ library: Library) -> Int {
    switch shelf {
    case .mine: library.mine.count
    case .saved: library.saved.count
    case .liked: library.liked.count
    }
  }

  @ViewBuilder
  private func grid(_ cards: [GuideCard], shelf: Shelf) -> some View {
    if cards.isEmpty {
      Text(emptyMessage(shelf)).font(.callout).foregroundStyle(Color.inkSecondary).padding(.top, 8)
    } else {
      CoverGrid(cards: cards, showsStatus: shelf == .mine) { card in
        if card.visibility == "draft" {
          openDraft(card.guideId)
        } else {
          withoutAnimation { opened = OpenedGuide(card: card, step: nil, cards: cards.filter { $0.visibility != "draft" }) }
        }
      }
    }
  }

  private func load() async {
    do {
      library = try await API.library()
      error = nil
    } catch {
      self.error = "Start the server on your Mac (uv run uvicorn pr.server:app --port 8000), then try again. Looking for it at \(API.base.absoluteString)."
    }
  }
}

private struct OpenedGuide: Hashable, Identifiable {
  var id: String { card.guideId }
  let card: GuideCard
  let step: Int?
  /// The shelf it was opened from: swipe up or down through these.
  let cards: [GuideCard]
}


struct ContinueCard: View {
  let card: GuideCard
  let open: () -> Void

  var body: some View {
    Button(action: open) {
      HStack(spacing: 12) {
        AsyncImage(url: API.url(card.coverUrl)) { $0.resizable().scaledToFill() } placeholder: { Color.track }
          .frame(width: 72, height: 72).clipShape(RoundedRectangle(cornerRadius: 16))
        VStack(alignment: .leading, spacing: 4) {
          Eyebrow(text: "Continue · step \(card.step ?? 1) of \(card.steps)")
          Text(card.title).font(.subheadline.weight(.semibold)).foregroundStyle(Color.ink).lineLimit(1)
          if let next = card.nextStepTitle {
            Text("Next: \(next)").font(.caption).foregroundStyle(Color.inkSecondary).lineLimit(1)
          }
          ProgressView(value: Double((card.step ?? 1) - 1), total: Double(max(card.steps, 1))).tint(Color.ai)
        }
        Image(systemName: "play.fill").font(.system(size: 15)).foregroundStyle(.white)
          .frame(width: 44, height: 44).background(Color.ink, in: .circle)
      }
      .padding(12)
      .background(Color.panel, in: RoundedRectangle(cornerRadius: 24))
    }
    .buttonStyle(.plain)
  }
}

/// A name and what that person's guides have reached: yours on Library, someone else's on their profile.
struct ProfileHeader: View {
  let name: String
  var role = ""
  let profile: Library.Profile

  var body: some View {
    HStack(spacing: 14) {
      Text(name.split(separator: " ").compactMap(\.first).prefix(2).map(String.init).joined().uppercased())
        .font(.title3.weight(.semibold)).foregroundStyle(.white)
        .frame(width: 64, height: 64)
        .background(Color.ai, in: .circle)
      VStack(alignment: .leading, spacing: 6) {
        VStack(alignment: .leading, spacing: 1) {
          Text(name).font(.headline).foregroundStyle(Color.ink)
          if !role.isEmpty { Text(role).font(.caption).foregroundStyle(Color.inkSecondary) }
        }
        HStack(spacing: 18) {
          stat(profile.guides, "guides")
          stat(profile.learners, "learners")
          stat(profile.likes, "likes")
        }
      }
      Spacer(minLength: 0)
    }
  }

  private func stat(_ value: Int, _ label: String) -> some View {
    VStack(alignment: .leading, spacing: 0) {
      Text("\(value)").font(.subheadline.weight(.semibold)).foregroundStyle(Color.ink).monospacedDigit()
      Text(label).font(.caption).foregroundStyle(Color.inkSecondary)
    }
    .accessibilityElement(children: .combine)
  }
}

/// Guide covers three to a row, as on a profile.
struct CoverGrid: View {
  let cards: [GuideCard]
  let showsStatus: Bool
  let open: (GuideCard) -> Void

  var body: some View {
    LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 8), count: 3), spacing: 8) {
      ForEach(cards) { card in
        Button { open(card) } label: { CoverTile(card: card, showsStatus: showsStatus) }
          .buttonStyle(.plain)
      }
    }
  }
}

/// A cover in the Library grid. Your own guides carry who can see them: Draft, Private, or the likes on a public one.
struct CoverTile: View {
  let card: GuideCard
  let showsStatus: Bool

  var body: some View {
    Color.track
      .aspectRatio(115.0 / 150.0, contentMode: .fit)
      .overlay {
        AsyncImage(url: API.url(card.coverUrl)) { $0.resizable().scaledToFill() } placeholder: { Color.track }
      }
      .overlay {
        LinearGradient(stops: [.init(color: .clear, location: 0.45), .init(color: .black.opacity(0.7), location: 1)],
                       startPoint: .top, endPoint: .bottom)
      }
      .overlay(alignment: .bottomLeading) {
        Text(card.title).font(.caption.weight(.semibold)).foregroundStyle(.white).lineLimit(3)
          .multilineTextAlignment(.leading).padding(8)
      }
      .overlay(alignment: .topLeading) {
        if showsStatus, let badge {
          Text(badge.text).font(.caption2.weight(.semibold)).foregroundStyle(Color.ink)
            .padding(.horizontal, 7).padding(.vertical, 3)
            .background(badge.color, in: RoundedRectangle(cornerRadius: 8))
            .padding(8)
        }
      }
      .clipShape(RoundedRectangle(cornerRadius: 14))
      .accessibilityElement(children: .combine)
  }

  private var badge: (text: String, color: Color)? {
    switch card.visibility {
    case "draft": ("Draft", Color(red: 1, green: 0.8, blue: 0.2))
    case "private": ("Private", .white)
    case "public": card.likes > 0 ? ("♥ \(card.likes)", .white) : nil
    default: nil
    }
  }
}
