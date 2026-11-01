// Step 3 · Guide: what a trainee sees when they open a guide (from the Feed, a shared link, or Library).

import SwiftUI

@Observable
@MainActor
final class GuideModel {
  let guideId: String
  var response: GuideResponse?
  var error: String?

  init(guideId: String) { self.guideId = guideId }

  func load() async {
    do {
      let fresh = try await API.guide(guideId)
      guard let shown = response else { response = fresh; return }
      // A reload (after the step player closes) only brings back where the trainee stopped. Swapping the whole
      // response would rebuild the page under them a beat after it slid back in; change just that, and ease it.
      if fresh.progress != shown.progress { withAnimation(.snappy) { response?.progress = fresh.progress } }
    } catch {
      self.error = "Couldn't open this guide: \(error.localizedDescription)"
    }
  }

  func toggle(_ kind: Reaction) async {
    guard let r = response?.reactions else { return }
    let on = kind == .like ? !r.liked : !r.saved
    if let updated = try? await API.react(guideId: guideId, kind, on: on) {
      response?.reactions = updated
    }
  }
}

struct GuideView: View {
  @State var model: GuideModel
  @State var playing: Int?
  @Environment(\.dismiss) private var dismiss
  @Environment(\.slideBack) private var slideBack

  var body: some View {
    Group {
      if let response = model.response {
        content(response)
      } else if let error = model.error {
        Text(error).foregroundStyle(Color.inkSecondary).padding()
      } else {
        ProgressView()
      }
    }
    .frame(maxWidth: .infinity, maxHeight: .infinity)
    .background(Color.canvas)
    .task { if model.response == nil { await model.load() } }
    // Reload on close so "Continue step n" follows where the trainee stopped.
    .fullScreenCover(item: Binding(get: { playing.map(StartStep.init) }, set: { playing = $0?.index }),
                     onDismiss: { Task { await model.load() } }) { start in
      if let response = model.response {
        StepPlayerView(guide: response.guide, startIndex: start.index).edgeSwipeBack()
      }
    }
    .authorProfiles()
  }

  private func content(_ response: GuideResponse) -> some View {
    let guide = response.guide
    return ScrollView {
      VStack(alignment: .leading, spacing: 0) {
        hero(guide)
        VStack(alignment: .leading, spacing: 12) {
          Text(response.categoryLabel).font(.footnote.weight(.medium))
            .padding(.horizontal, 12).padding(.vertical, 6)
            .glassEffect(.regular, in: .capsule)
          Text(guide.title).font(.title.bold()).foregroundStyle(Color.ink)
          author(response.meta)
          Text(guide.summary).font(.callout).foregroundStyle(Color.inkSecondary)
          HStack(spacing: 6) {
            MetaChip(systemImage: "list.bullet", text: "\(guide.steps.count) steps")
            MetaChip(systemImage: "clock", text: clock(guide.durationS))
          }
          if !guide.tools.isEmpty {
            // One chip per tool, wrapping, so a long tool list doesn't stretch the steps/time row.
            VStack(alignment: .leading, spacing: 8) {
              Eyebrow(text: "Tools", color: Color.inkSecondary)
              FlowLayout(spacing: 6) {
                ForEach(guide.tools, id: \.self) { tool in
                  MetaChip(systemImage: "wrench.and.screwdriver", text: tool.capitalizedFirst)
                }
              }
            }
            .padding(.top, 4)
          }
          actions(response)
          HStack {
            Text("Steps").font(.headline)
            Spacer()
            // Partway through, the other way in is starting over; it sits here, quietly, above step 1.
            if (response.progress ?? 1) > 1 {
              Button { withoutAnimation { playing = 1 } } label: {
                Label("Start over", systemImage: "arrow.counterclockwise").font(.subheadline.weight(.medium))
              }
              .foregroundStyle(Color.ai)
            } else {
              Text("Each step has its own clip").font(.caption).foregroundStyle(Color.inkSecondary)
            }
          }
          .padding(.top, 8)
          ForEach(guide.steps) { step in
            Button { withoutAnimation { playing = step.index } } label: {
              StepRow(step: step, eyebrow: "Step \(step.index) · \(clock(step.clip.endS - step.clip.startS)) clip",
                      trailing: "play.fill")
            }
            .buttonStyle(.plain)
          }
        }
        .padding(.horizontal, 16)
        .padding(.top, -40)
        .padding(.bottom, 40)
      }
    }
    .ignoresSafeArea(edges: .top)
    .toolbar(.hidden, for: .navigationBar)
  }

  private func hero(_ guide: Guide) -> some View {
    ZStack(alignment: .top) {
      // The cover fills a fixed frame as an overlay, so a wide image can't widen the page.
      Color.track
        .frame(maxWidth: .infinity)
        .frame(height: 340)
        .overlay {
          AsyncImage(url: API.url("/guides/\(guide.guideId)/cover.jpg")) { image in
            image.resizable().scaledToFill()
          } placeholder: {
            Color.track
          }
        }
        .clipped()
      .overlay {
        LinearGradient(stops: [.init(color: .black.opacity(0.35), location: 0), .init(color: .clear, location: 0.3),
                               .init(color: Color.canvas.opacity(0.6), location: 0.7), .init(color: Color.canvas, location: 1)],
                       startPoint: .top, endPoint: .bottom)
      }
      HStack {
        Button { if let slideBack { slideBack() } else { dismiss() } } label: {
          Image(systemName: "chevron.left").font(.system(size: 17, weight: .semibold)).frame(width: 44, height: 44)
        }
        .glassEffect(.regular.interactive(), in: .circle)
        .accessibilityLabel("Back")
        Spacer()
        ShareLink(item: API.url("/guides/\(guide.guideId)")) {
          Image(systemName: "square.and.arrow.up").font(.system(size: 17, weight: .semibold)).frame(width: 44, height: 44)
        }
        .glassEffect(.regular.interactive(), in: .circle)
      }
      .foregroundStyle(.white)
      .padding(.horizontal, 16)
      .padding(.top, 60)
    }
  }

  private func author(_ meta: GuideMeta) -> some View { AuthorRow(meta: meta) }

  private func actions(_ response: GuideResponse) -> some View {
    let r = response.reactions
    let start = response.progress ?? 1
    return HStack(spacing: 8) {
      Button { withoutAnimation { playing = start } } label: {
        Text(start > 1 ? "Continue step \(start)" : "Start step 1")
          .font(.headline).frame(maxWidth: .infinity).padding(.vertical, 6)
      }
      .buttonStyle(.glassProminent)
      .tint(Color.ink)
      reactions(r)
    }
    .padding(.top, 4)
  }

  @ViewBuilder
  private func reactions(_ r: Reactions) -> some View {
    reaction(r.liked ? "heart.fill" : "heart", "\(r.likes)", r.liked ? Color.live : Color.ink) {
      Task { await model.toggle(.like) }
    }
    .accessibilityLabel(r.liked ? "Unlike" : "Like")
    reaction(r.saved ? "bookmark.fill" : "bookmark", "\(r.saves)", Color.ink) {
      Task { await model.toggle(.save) }
    }
    .accessibilityLabel(r.saved ? "Remove from saved" : "Save")
  }

  private func reaction(_ symbol: String, _ count: String, _ tint: Color, action: @escaping () -> Void) -> some View {
    Button(action: action) {
      Label(count, systemImage: symbol).font(.footnote.weight(.medium)).foregroundStyle(tint)
        .padding(.horizontal, 12).padding(.vertical, 10)
    }
    .glassEffect(.regular.interactive(), in: .capsule)
  }
}

private struct StartStep: Identifiable {
  let index: Int
  var id: Int { index }
}

/// The guide's author under its title; tapping it opens their profile. A view of its own so it reads the
/// `openAuthor` that GuideView's `authorProfiles()` sets, not the one of the screen the guide was opened from.
private struct AuthorRow: View {
  let meta: GuideMeta
  @Environment(\.openAuthor) private var openAuthor

  var body: some View {
    Button { openAuthor(meta.author) } label: {
      HStack(spacing: 8) {
        Text(meta.authorName.split(separator: " ").compactMap(\.first).prefix(2).map(String.init).joined())
          .font(.eyebrow).foregroundStyle(.white)
          .frame(width: 32, height: 32)
          .background(Color.ai, in: .circle)
        VStack(alignment: .leading, spacing: 1) {
          Text(meta.authorName).font(.subheadline.weight(.semibold)).foregroundStyle(Color.ink)
          Text([meta.authorRole, "recorded on Meta glasses"].filter { !$0.isEmpty }.joined(separator: " · "))
            .font(.caption).foregroundStyle(Color.inkSecondary)
        }
        Spacer(minLength: 0)
      }
      .contentShape(Rectangle())
    }
    .buttonStyle(.plain)
    .accessibilityLabel("\(meta.authorName)'s profile")
  }
}
