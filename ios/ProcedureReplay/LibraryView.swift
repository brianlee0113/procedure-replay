// Library: pick up where you stopped, guides you saved, and guides you recorded (with who can see them).

import SwiftUI

struct LibraryView: View {
  let reload: Int
  /// Opens a draft in the Draft editor, so the instructor can keep editing and publish it.
  var openDraft: (String) -> Void = { _ in }

  @State private var library: Library?
  @State private var error: String?
  @State private var opened: OpenedGuide?

  var body: some View {
    NavigationStack {
      ScrollView {
        VStack(alignment: .leading, spacing: 14) {
          Text("Library").font(.largeTitle.bold()).foregroundStyle(Color.ink)
          if let error {
            StateMessage(symbol: "wifi.exclamationmark", title: "Can't reach the Mac server", message: error,
                         actionTitle: "Try again") { Task { await load() } }
          } else if library == nil {
            ProgressView().frame(maxWidth: .infinity).padding(.top, 60)
          }
          if let library {
            ForEach(library.continue) { card in
              ContinueCard(card: card) { opened = OpenedGuide(card: card, step: card.step) }
            }
            section("Saved", count: library.saved.count)
            if library.saved.isEmpty {
              Text("Tap the bookmark on a guide in the Feed to keep it here.").font(.callout).foregroundStyle(Color.inkSecondary)
            } else {
              LazyVGrid(columns: [GridItem(.flexible(), spacing: 16), GridItem(.flexible(), spacing: 16)],
                        alignment: .leading, spacing: 18) {
                ForEach(library.saved) { card in
                  Button { opened = OpenedGuide(card: card, step: nil) } label: { GuideTile(card: card) }
                    .buttonStyle(.plain)
                }
              }
            }
            section("My guides", count: library.mine.count, note: "Recorded on your glasses")
            if library.mine.isEmpty {
              Text("Guides you record appear here.").font(.callout).foregroundStyle(Color.inkSecondary)
            }
            ForEach(library.mine) { card in
              Button {
                if card.visibility == "draft" { openDraft(card.guideId) } else { opened = OpenedGuide(card: card, step: nil) }
              } label: { MineRow(card: card) }.buttonStyle(.plain)
            }
          }
        }
        .padding(.horizontal, 16)
        .padding(.top, 8)
        .padding(.bottom, 100)
      }
      .background(Color.canvas)
      .refreshable { await load() }
      .task(id: reload) { await load() }
      // Full screen, so the tab bar doesn't float over the guide.
      .fullScreenCover(item: $opened) { o in
        NavigationStack { GuideView(model: GuideModel(guideId: o.card.guideId), playing: o.step) }
      }
      .onChange(of: opened) { if opened == nil { Task { await load() } } }
    }
  }

  private func section(_ title: String, count: Int, note: String? = nil) -> some View {
    HStack(alignment: .firstTextBaseline) {
      Text("\(title) · \(count)").font(.headline).foregroundStyle(Color.ink)
      Spacer()
      if let note { Text(note).font(.caption).foregroundStyle(Color.inkSecondary) }
    }
    .padding(.top, 8)
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

struct GuideTile: View {
  let card: GuideCard

  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      Color.track
        .aspectRatio(0.86, contentMode: .fit)
        .overlay {
          AsyncImage(url: API.url(card.coverUrl)) { $0.resizable().scaledToFill() } placeholder: { Color.track }
        }
        .overlay(alignment: .topLeading) {
          Text("\(card.steps) steps".uppercased()).font(.eyebrow).foregroundStyle(.white)
            .padding(.horizontal, 10).padding(.vertical, 6)
            .glassEffect(.regular, in: .capsule)
            .environment(\.colorScheme, .dark)
            .padding(10)
        }
        .clipShape(RoundedRectangle(cornerRadius: 22))
      Text(card.title).font(.subheadline.weight(.semibold)).foregroundStyle(Color.ink).lineLimit(2)
        .multilineTextAlignment(.leading)
      Text("\(card.authorName) · \(clock(card.durationS))").font(.caption).foregroundStyle(Color.inkSecondary)
    }
  }
}

struct MineRow: View {
  let card: GuideCard

  private var status: String {
    switch card.visibility {
    case "public": return "Public · \(card.likes) likes · \(card.saves) saves"
    case "private": return "Private · only people with the link"
    default: return "Draft · not published"
    }
  }

  var body: some View {
    HStack(spacing: 12) {
      AsyncImage(url: API.url(card.coverUrl)) { $0.resizable().scaledToFill() } placeholder: { Color.track }
        .frame(width: 76, height: 64).clipShape(RoundedRectangle(cornerRadius: 14))
      VStack(alignment: .leading, spacing: 3) {
        Eyebrow(text: status, color: card.visibility == "draft" ? Color.inkSecondary : Color.ai)
        Text(card.title).font(.subheadline.weight(.semibold)).foregroundStyle(Color.ink).lineLimit(2)
        Text("\(card.steps) steps · \(clock(card.durationS))").font(.caption).foregroundStyle(Color.inkSecondary)
      }
      Spacer(minLength: 0)
      Image(systemName: "chevron.right").font(.caption.weight(.semibold)).foregroundStyle(Color.inkSecondary)
    }
    .padding(10)
    .background(Color.panel, in: RoundedRectangle(cornerRadius: 20))
  }
}
