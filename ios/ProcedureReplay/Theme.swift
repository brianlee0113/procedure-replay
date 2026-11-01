// Colors and shapes from the Figma file "Final — App (glass)" (Glass (A) collection, Light mode).
// Floating controls use the system Liquid Glass (`glassEffect`); content panels use regular material.

import SwiftUI

extension Color {
  static let canvas = Color(red: 0.95, green: 0.95, blue: 0.96)
  static let ink = Color(red: 0.04, green: 0.05, blue: 0.06)
  static let inkSecondary = Color(red: 0.04, green: 0.05, blue: 0.06).opacity(0.62)
  static let ai = Color(red: 0.16, green: 0.38, blue: 1.0)
  static let live = Color(red: 0.91, green: 0.10, blue: 0.25)
  static let ok = Color(red: 0.07, green: 0.63, blue: 0.31)
  static let track = Color.black.opacity(0.08)
  /// Content panels (step rows, pipeline rows): solid, so text stays readable over any backdrop.
  static let panel = Color.white.opacity(0.78)
}

extension Font {
  static let eyebrow = Font.system(size: 11, weight: .medium, design: .monospaced)
}

/// Uppercase monospaced label, as used for "STEP 3 · 1:48 – 3:03" and "META AI · MUSE SPARK".
struct Eyebrow: View {
  let text: String
  var color: Color = .ai

  var body: some View {
    Text(text.uppercased()).font(.eyebrow).tracking(0.6).foregroundStyle(color)
  }
}

/// Sparkle + label, shown wherever a value was written or suggested by Meta AI.
struct AIBadge: View {
  let text: String

  var body: some View {
    Label { Eyebrow(text: text) } icon: {
      Image(systemName: "sparkles").font(.system(size: 11, weight: .semibold)).foregroundStyle(Color.ai)
    }
    .labelStyle(.titleAndIcon)
  }
}

/// Small rounded chip with an icon: "9 steps", "8 min", "Screwdriver, cloth".
struct MetaChip: View {
  let systemImage: String
  let text: String

  var body: some View {
    Label(text, systemImage: systemImage)
      .font(.footnote)
      .foregroundStyle(Color.ink)
      .padding(.horizontal, 10).padding(.vertical, 6)
      .glassEffect(.regular, in: .capsule)
  }
}

func clock(_ seconds: Double) -> String {
  let s = max(0, Int(seconds.rounded()))
  return String(format: "%d:%02d", s / 60, s % 60)
}

/// Empty, loading-failed and "nothing here yet" screens: what happened, and the one thing to do next.
struct StateMessage: View {
  let symbol: String
  let title: String
  let message: String
  var actionTitle: String?
  var action: (() -> Void)?

  var body: some View {
    VStack(spacing: 10) {
      Image(systemName: symbol).font(.system(size: 30, weight: .regular)).foregroundStyle(Color.inkSecondary)
      Text(title).font(.headline).foregroundStyle(Color.ink)
      Text(message).font(.callout).foregroundStyle(Color.inkSecondary).multilineTextAlignment(.center)
      if let actionTitle, let action {
        Button(actionTitle, action: action).buttonStyle(.glassProminent).tint(Color.ink).padding(.top, 4)
      }
    }
    .frame(maxWidth: .infinity)
    .padding(.vertical, 40)
    .padding(.horizontal, 24)
  }
}

/// Shown briefly at the top after something finishes elsewhere (e.g. "Published to the Feed").
struct Banner: View {
  let text: String

  var body: some View {
    Label(text, systemImage: "checkmark.circle.fill")
      .font(.subheadline.weight(.semibold))
      .foregroundStyle(Color.ink)
      .padding(.horizontal, 16).padding(.vertical, 10)
      .glassEffect(.regular, in: .capsule)
      .transition(.move(edge: .top).combined(with: .opacity))
  }
}

/// Guides and the step player open as full-screen covers (so the tab bar doesn't float over them), but move like a
/// pushed iPhone screen: they slide in from the right, and go back to the right, by a swipe from the left edge or by
/// their own back button (`slideBack`). Apply it to the cover's root, and present the cover with `withoutAnimation`
/// so the cover's own slide-up doesn't run too. The cover turns clear so the screen behind shows while it slides.
struct EdgeSwipeBack: ViewModifier {
  @Environment(\.dismiss) private var dismiss
  @State private var shown = false
  /// True once the slide-in has finished, until the slide-out starts. An edge swipe only starts while settled: a
  /// finger grabbing the screen mid-slide would yank it from wherever the slide had got to.
  @State private var settled = false
  @State private var closing = false
  @State private var drag: CGFloat = 0
  @State private var width: CGFloat = 400
  /// Set on a drag's first change: nil = not decided yet, else the x translation at which an edge swipe started
  /// (the screen follows the finger from there, so it doesn't jump by the recognition distance), or -1 when the
  /// drag isn't a back swipe (went more up/down than sideways, or the screen was still sliding).
  @State private var swipeStart: CGFloat?
  /// True while any drag is under way; it resets on its own when the system cancels the drag, which skips `onEnded`.
  @GestureState private var dragging = false

  /// The strip along the left edge that the swipe starts in. It sits over the screen and takes those touches itself,
  /// so a swipe that starts on a button (a step row, Back) doesn't also tap it, and a scroll view under it doesn't
  /// scroll. Narrow, like the system's own back-swipe zone, so it covers only the outer few points of a button.
  private let edge: CGFloat = 20

  func body(content: Content) -> some View {
    let shown = shown, drag = drag
    content
      .environment(\.slideBack, close)
      .overlay(alignment: .leading) {
        Color.clear
          .frame(width: edge)
          .frame(maxHeight: .infinity)
          .ignoresSafeArea()
          .contentShape(Rectangle())
          .gesture(swipe)
          .accessibilityHidden(true)
      }
      .visualEffect { effect, proxy in effect.offset(x: shown ? drag : proxy.size.width) }
      .shadow(color: .black.opacity(shown && drag == 0 ? 0 : 0.25), radius: 16)
      // A cancelled drag (another gesture took the touch, an alert, the app went to the background) never reaches
      // `onEnded`: put the screen back instead of leaving it half off, to jump the next time it's touched.
      .onChange(of: dragging) { _, now in
        guard !now, swipeStart != nil else { return }
        swipeStart = nil
        if shown, self.drag != 0 { withAnimation(.spring(duration: 0.25)) { self.drag = 0 } }
      }
      .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { width = $0 }
      .presentationBackground(.clear)
      .onAppear {
        guard !shown else { return }  // onAppear runs again when a cover on top of this one closes
        withAnimation(.easeOut(duration: 0.3)) { self.shown = true } completion: { if !closing { settled = true } }
      }
  }

  private var swipe: some Gesture {
    DragGesture(minimumDistance: 10, coordinateSpace: .global)
      .updating($dragging) { _, state, _ in state = true }
      .onChanged { v in
        if swipeStart == nil {
          let sideways = abs(v.translation.width) > abs(v.translation.height)
          swipeStart = settled && sideways && v.translation.width > 0 ? v.translation.width : -1
        }
        guard let start = swipeStart, start >= 0 else { return }
        self.drag = max(0, v.translation.width - start)
      }
      .onEnded { v in
        defer { swipeStart = nil }
        guard let start = swipeStart, start >= 0 else { return }
        let moved = v.translation.width - start
        if moved > width * 0.35 || v.predictedEndTranslation.width - start > width * 0.6 {
          close()
        } else {
          withAnimation(.spring(duration: 0.25)) { self.drag = 0 }
        }
      }
  }

  private func close() {
    guard !closing else { return }  // a second tap on Back mid-slide would dismiss twice
    closing = true
    settled = false
    withAnimation(.easeOut(duration: 0.25)) {
      shown = false
      drag = 0
    } completion: {
      withoutAnimation { dismiss() }  // already off screen; skip the cover's slide-down
    }
  }
}

extension View {
  func edgeSwipeBack() -> some View { modifier(EdgeSwipeBack()) }
}

extension EnvironmentValues {
  /// Back for a screen under `edgeSwipeBack()`: slides it out to the right, then dismisses it. Nil elsewhere.
  @Entry var slideBack: (() -> Void)?
  /// Opens a guide author's profile, yours included. Set by `authorProfiles()`.
  @Entry var openAuthor: (String) -> Void = { _ in }
  /// Closes whatever is on top, goes to the Library tab and opens the draft in the Draft editor. Set by RootView,
  /// so a draft tapped on your profile opened from a guide reaches the editor too.
  @Entry var editDraft: (String) -> Void = { _ in }
}

/// Lets author names below this view open profiles. Every name slides a profile in over this screen (Back or an edge
/// swipe closes it): someone else's shows their public guides, yours is laid out like the Library tab.
private struct AuthorProfiles: ViewModifier {
  @State private var profile: ProfileLink?
  @Environment(\.editDraft) private var editDraft

  func body(content: Content) -> some View {
    content
      .environment(\.openAuthor) { id in withoutAnimation { profile = ProfileLink(id: id) } }
      .fullScreenCover(item: $profile) { link in
        Group {
          if link.id == API.user {
            LibraryView(reload: 0, pushed: true, openDraft: editDraft)
          } else {
            ProfileView(userId: link.id)
          }
        }
        .edgeSwipeBack()
      }
  }
}

private struct ProfileLink: Identifiable {
  let id: String
}

extension View {
  func authorProfiles() -> some View { modifier(AuthorProfiles()) }
}

/// Presents or dismisses a full-screen cover without its slide-up/down, for covers that slide sideways themselves.
func withoutAnimation(_ body: () -> Void) {
  var t = Transaction()
  t.disablesAnimations = true
  withTransaction(t, body)
}
