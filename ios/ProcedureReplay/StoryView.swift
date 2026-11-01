// Story feed (experiment, branch story-feed; Figma "Ideation — story feed (11-01)"): a guide opens as a story.
// Page 0 sums the guide up (title, summary, tools, every step name), then one step per page, then a done page.
// Tap the left third for the previous page, the middle to pause or resume, the right third for the next; hold to pause. Swipe up or down
// for the next or previous guide, which always starts at its summary. No tab bar; × or a left-edge swipe goes back.

import AVFoundation
import SwiftUI

struct StoryFeedView: View {
  let cards: [GuideCard]
  /// The guide that was tapped; with `startStep`, the story opens at that step (Library's Continue).
  let first: String
  let startStep: Int?

  @State private var current: String?
  /// Nil until the trainee touches the sound button; until then each guide follows its own default
  /// (on for guides built with narration).
  @State private var soundOn: Bool?
  @Environment(\.dismiss) private var dismiss
  @Environment(\.slideBack) private var slideBack

  init(cards: [GuideCard], start: GuideCard, startStep: Int? = nil) {
    self.cards = cards.contains { $0.guideId == start.guideId } ? cards : [start]
    first = start.guideId
    self.startStep = startStep
    _current = State(initialValue: start.guideId)
  }

  var body: some View {
    ScrollView(.vertical) {
      LazyVStack(spacing: 0) {
        ForEach(cards) { card in
          StoryPage(guideId: card.guideId,
                    startPage: card.guideId == first ? (startStep ?? 0) : 0,
                    isActive: current == card.guideId,
                    hasNext: card.guideId != cards.last?.guideId,
                    soundOn: $soundOn,
                    close: close)
            .containerRelativeFrame([.horizontal, .vertical])
            .id(card.guideId)
        }
      }
      .scrollTargetLayout()
    }
    .scrollTargetBehavior(.paging)
    .scrollPosition(id: $current)
    .scrollIndicators(.hidden)
    .ignoresSafeArea()
    .background(Color.black)
    .statusBarHidden()  // the story bar takes its place, as in Instagram
    .onDisappear { try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation) }
    .authorProfiles()
  }

  private func close() {
    if let slideBack { slideBack() } else { dismiss() }
  }
}

/// One guide: summary, its steps, done.
private struct StoryPage: View {
  let guideId: String
  let isActive: Bool
  let hasNext: Bool
  @Binding var soundOn: Bool?
  let close: () -> Void

  @State private var model: GuideModel
  /// 0 = summary, 1…n = steps, n + 1 = done.
  @State private var page: Int
  @State private var player = LoopingPlayer()
  @State private var loadTask: Task<Void, Never>?
  @State private var held = false
  @State private var showSteps = false
  @State private var lensMode = LensMode()
  @Environment(\.openAuthor) private var openAuthor

  init(guideId: String, startPage: Int, isActive: Bool, hasNext: Bool, soundOn: Binding<Bool?>, close: @escaping () -> Void) {
    self.guideId = guideId
    self.isActive = isActive
    self.hasNext = hasNext
    _soundOn = soundOn
    self.close = close
    _model = State(initialValue: GuideModel(guideId: guideId))
    _page = State(initialValue: startPage)
  }

  private var steps: [GuideStep] { model.response?.guide.steps ?? [] }
  private var stepCount: Int { steps.count }
  private var step: GuideStep? { page >= 1 && page <= stepCount ? steps[page - 1] : nil }
  private var isDone: Bool { stepCount > 0 && page > stepCount }

  var body: some View {
    GeometryReader { g in
      ZStack {
        Color.black
        if let response = model.response {
          content(response, width: g.size.width)
        } else if let error = model.error {
          Text(error).font(.callout).foregroundStyle(.white.opacity(0.8)).padding(40)
        } else {
          ProgressView().tint(.white)
        }
      }
    }
    .task {
      if model.response == nil { await model.load() }
      page = min(page, stepCount + 1)
      sync()
    }
    .onChange(of: isActive) { sync() }
    .onChange(of: page) {
      sync()
      if let step, lensMode.isOn, let guide = model.response?.guide { Task { await lensMode.show(guide: guide, step: step) } }
    }
    .onChange(of: soundOn) { applySound() }
    .onChange(of: lensMode.requestedStep) {
      guard let requested = lensMode.requestedStep else { return }
      lensMode.requestedStep = nil
      page = min(max(requested, 1), stepCount + 1)
    }
    .onChange(of: lensMode.replayRequests) { player.restart() }
    .onDisappear {
      loadTask?.cancel()
      player.clear()
      lensMode.turnOff()
    }
    .fullScreenCover(isPresented: $showSteps) {
      NavigationStack { GuideView(model: GuideModel(guideId: guideId)) }.edgeSwipeBack()
    }
  }

  // MARK: playback

  /// Only the guide on screen plays, and only on a step page.
  private func sync() {
    loadTask?.cancel()
    held = false
    guard isActive, let response = model.response else {
      player.clear()
      if !isActive { lensMode.turnOff() }
      return
    }
    player.activateAudio()
    applySound()
    UIApplication.shared.isIdleTimerDisabled = true  // hands are on the job, not the screen
    if let step {
      let i = step.index
      Task { try? await API.setProgress(guideId: guideId, step: i) }
      play(step)
    } else {
      player.clear()
      // From the summary, step 1 is next: have its clip on the phone before the tap.
      if page == 0, let first = response.guide.steps.first { prefetch(first) }
    }
  }

  private func applySound() {
    player.isMuted = !(soundOn ?? model.response?.guide.hasNarration ?? false)
  }

  private func play(_ step: GuideStep) {
    guard let path = step.clipUrl else { player.clear(); return }
    player.clear()
    loadTask = Task {
      do {
        let local = try await ClipCache.shared.file(for: API.url(path), key: ClipCache.key(guideId: guideId, step: step))
        guard !Task.isCancelled else { return }
        player.load(local)
      } catch {
        guard !Task.isCancelled else { return }
        player.load(API.url(path))
      }
      for neighbour in steps where abs(neighbour.index - step.index) == 1 { prefetch(neighbour) }
    }
  }

  private func prefetch(_ step: GuideStep) {
    guard let path = step.clipUrl else { return }
    let key = ClipCache.key(guideId: guideId, step: step)
    Task.detached { _ = try? await ClipCache.shared.file(for: API.url(path), key: key) }
  }

  private func next() { if page <= stepCount { page += 1 } }
  private func previous() { if page > 0 { page -= 1 } }

  // MARK: layout

  private func content(_ response: GuideResponse, width: CGFloat) -> some View {
    ZStack {
      background(response)
      if step != nil, player.isPaused {
        Image(systemName: "play.fill").font(.system(size: 30, weight: .semibold))
          .frame(width: 76, height: 76)
          .glassEffect(.regular, in: .circle)
          .allowsHitTesting(false)
      }
      LinearGradient(stops: [.init(color: .black.opacity(0.55), location: 0), .init(color: .clear, location: 0.22),
                             .init(color: .clear, location: 0.42), .init(color: .black.opacity(0.6), location: 0.68),
                             .init(color: .black.opacity(0.88), location: 1)],
                     startPoint: .top, endPoint: .bottom)
        .allowsHitTesting(false)
      VStack(alignment: .leading, spacing: 12) {
        storyBar
        header(response)
        if lensMode.isOn || lensMode.connecting || lensMode.error != nil { lensStatus }
        Spacer(minLength: 0)
        if isDone {
          done(response)
        } else {
          HStack(alignment: .bottom, spacing: 12) {
            Group {
              if let step { stepText(step) } else { summary(response) }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            rail(response)
          }
        }
      }
      .padding(.horizontal, 16)
      .padding(.top, 54)  // under the Dynamic Island
      .padding(.bottom, 34)
    }
    .foregroundStyle(.white)
    .environment(\.colorScheme, .dark)
    // Like the step player: left third back, middle pause/resume, right third forward. Buttons keep their own taps.
    // Off a step (summary, done) there is no clip, so the middle goes forward too.
    .contentShape(Rectangle())
    .onTapGesture(coordinateSpace: .local) { location in
      if location.x < width / 3 {
        previous()
      } else if location.x < width * 2 / 3, step != nil {
        player.togglePause()
      } else {
        next()
      }
    }
    .onLongPressGesture(minimumDuration: 0.25, maximumDistance: 12) {
      guard step != nil else { return }
      held = true
      player.player.pause()
    } onPressingChanged: { pressing in
      if !pressing, held {
        held = false
        player.player.play()
      }
    }
    .accessibilityAction(named: "Next page") { next() }
    .accessibilityAction(named: "Previous page") { previous() }
    .accessibilityAction(named: player.isPaused ? "Play" : "Pause") { player.togglePause() }
  }

  @ViewBuilder
  private func background(_ response: GuideResponse) -> some View {
    if step != nil {
      PlayerSurface(player: player.player)
    } else {
      Color.clear.overlay {
        AsyncImage(url: API.url("/guides/\(guideId)/cover.jpg")) { $0.resizable().scaledToFill() } placeholder: { Color.black }
      }
      .clipped()
      .overlay { if isDone { Color.black.opacity(0.45) } }
    }
  }

  /// One segment for the summary and one per step; the current step fills as its clip plays.
  private var storyBar: some View {
    HStack(spacing: 4) {
      ForEach(0...stepCount, id: \.self) { i in
        // The summary is a different kind of page from the steps, so its segment is AI blue, not white.
        let tint = i == 0 ? Color(red: 0.45, green: 0.62, blue: 1) : .white
        Capsule().fill(tint.opacity(0.35))
          .overlay(alignment: .leading) {
            GeometryReader { g in Capsule().fill(tint).frame(width: g.size.width * fill(i)) }
          }
          .frame(height: 3)
      }
    }
    .accessibilityHidden(true)
  }

  private func fill(_ i: Int) -> CGFloat {
    if isDone || i < page { return 1 }
    if i > page { return 0 }
    if page == 0 { return 1 }
    guard player.isReady, player.duration > 0 else { return 0 }
    return CGFloat(min(max(player.elapsed / player.duration, 0), 1))
  }

  private func header(_ response: GuideResponse) -> some View {
    let meta = response.meta
    return HStack(spacing: 8) {
      Button { openAuthor(meta.author) } label: {
        HStack(spacing: 8) {
          Text(meta.authorName.split(separator: " ").compactMap(\.first).prefix(2).map(String.init).joined())
            .font(.eyebrow).foregroundStyle(.white)
            .frame(width: 32, height: 32)
            .background(Color.ai, in: .circle)
          VStack(alignment: .leading, spacing: 0) {
            Text(meta.authorName).font(.subheadline.weight(.semibold))
            Text(page == 0 ? meta.authorRole : response.guide.title).font(.caption).opacity(0.75).lineLimit(1)
          }
        }
        .contentShape(Rectangle())
      }
      .buttonStyle(.plain)
      .accessibilityLabel("\(meta.authorName)'s profile")
      Spacer(minLength: 8)
      circleButton(lensMode.isOn ? "eyeglasses.slash" : "eyeglasses", lensMode.isOn ? "Stop following on glasses" : "Follow on Display glasses") {
        if lensMode.isOn {
          lensMode.turnOff()
        } else if let first = step ?? steps.first {
          if step == nil { page = first.index }
          Task { await lensMode.turnOn(guide: response.guide, step: first) }
        }
      }
      circleButton(player.isMuted ? "speaker.slash.fill" : "speaker.wave.2.fill", player.isMuted ? "Sound on" : "Sound off") {
        soundOn = player.isMuted
      }
      circleButton("xmark", "Close") { close() }
    }
  }

  private func circleButton(_ symbol: String, _ label: String, action: @escaping () -> Void) -> some View {
    Button(action: action) {
      Image(systemName: symbol).font(.system(size: 13, weight: .semibold))
        .contentTransition(.symbolEffect(.replace))
        .frame(width: 36, height: 36)
    }
    .glassEffect(.regular.interactive(), in: .circle)
    .accessibilityLabel(label)
  }

  private var lensStatus: some View {
    Label(lensMode.error ?? (lensMode.connecting ? "Connecting to glasses…"
            : lensMode.heardCommand.map { "Heard “\($0)”" } ?? "Glasses · say “next”"),
          systemImage: lensMode.heardCommand == nil ? "eyeglasses" : "waveform")
      .font(.footnote.weight(.semibold))
      .padding(.horizontal, 12).padding(.vertical, 7)
      .background(Color.ai, in: .capsule)
  }

  /// Page 0 (Figma C1): what the job is, who made it, the tools, and every step name.
  private func summary(_ response: GuideResponse) -> some View {
    let guide = response.guide
    return VStack(alignment: .leading, spacing: 12) {
      pill(response.categoryLabel)
      Text(guide.title).font(.title.bold()).lineLimit(3).fixedSize(horizontal: false, vertical: true)
      Text(guide.summary).font(.subheadline).opacity(0.85).lineLimit(2)
      HStack(spacing: 6) {
        pill("\(stepCount) steps")
        pill(clock(guide.durationS))
        if let tool = guide.tools.first { pill(guide.tools.count > 1 ? "\(tool) +\(guide.tools.count - 1)" : tool) }
      }
      VStack(alignment: .leading, spacing: 5) {
        Text("WHAT YOU'LL DO").font(.eyebrow).opacity(0.7)
        ForEach(guide.steps.prefix(6)) { s in
          HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text("\(s.index)").font(.eyebrow).opacity(0.6).frame(width: 16, alignment: .leading)
            Text(s.title).font(.subheadline.weight(.medium)).lineLimit(1)
          }
        }
        if stepCount > 6 { Text("+ \(stepCount - 6) more").font(.caption).opacity(0.7).padding(.leading, 26) }
      }
      Label("Tap right to start step 1", systemImage: "chevron.right")
        .font(.caption.weight(.semibold))
        .padding(.horizontal, 12).padding(.vertical, 7)
        .background(.black.opacity(0.38), in: .capsule)
    }
  }

  private func stepText(_ step: GuideStep) -> some View {
    VStack(alignment: .leading, spacing: 10) {
      Text("STEP \(step.index) / \(stepCount)").font(.eyebrow).foregroundStyle(Color(red: 0.62, green: 0.74, blue: 1))
      Text(step.title).font(.title2.bold()).lineLimit(3).fixedSize(horizontal: false, vertical: true)
      Text(step.instruction).font(.callout).opacity(0.92).lineLimit(6)
      Label {
        Text("Done when \(step.doneWhen.lowercasedFirst).").opacity(0.9)
      } icon: {
        Image(systemName: "checkmark.circle.fill").foregroundStyle(Color.ok)
      }
      .font(.footnote)
      if let quote = step.quote {
        Label("“\(quote.text)”", systemImage: "mic.fill")
          .font(.caption).lineLimit(2)
          .padding(.horizontal, 12).padding(.vertical, 8)
          .background(.black.opacity(0.38), in: RoundedRectangle(cornerRadius: 14))
      }
    }
  }

  private func done(_ response: GuideResponse) -> some View {
    let r = response.reactions
    return VStack(spacing: 14) {
      Image(systemName: "checkmark.circle.fill").font(.system(size: 52)).foregroundStyle(.white, Color.ok)
      Text("You did all \(stepCount) steps").font(.title2.bold())
      Text(response.guide.title).font(.subheadline).opacity(0.75).multilineTextAlignment(.center)
      HStack(spacing: 8) {
        Button { page = 1 } label: {
          Label("Watch again", systemImage: "arrow.counterclockwise").font(.subheadline.weight(.semibold))
            .padding(.horizontal, 14).padding(.vertical, 10)
        }
        .glassEffect(.regular.interactive(), in: .capsule)
        Button { Task { await model.toggle(.save) } } label: {
          Label(r.saved ? "Saved" : "Save", systemImage: r.saved ? "bookmark.fill" : "bookmark")
            .font(.subheadline.weight(.semibold))
            .padding(.horizontal, 14).padding(.vertical, 10)
        }
        .glassEffect(.regular.interactive(), in: .capsule)
      }
      Spacer().frame(height: 120)
      if hasNext {
        Label("Swipe up for the next guide", systemImage: "chevron.up").font(.caption.weight(.semibold)).opacity(0.85)
      }
    }
    .frame(maxWidth: .infinity)
  }

  /// Like, save, share, and Steps (the full step list, today's Guide page).
  private func rail(_ response: GuideResponse) -> some View {
    let r = response.reactions
    return VStack(spacing: 18) {
      railButton(r.liked ? "heart.fill" : "heart", "\(r.likes)", tint: r.liked ? Color.live : .white,
                 label: r.liked ? "Unlike" : "Like") { Task { await model.toggle(.like) } }
      railButton(r.saved ? "bookmark.fill" : "bookmark", "\(r.saves)", label: r.saved ? "Remove from saved" : "Save") {
        Task { await model.toggle(.save) }
      }
      ShareLink(item: API.url("/guides/\(guideId)"),
                subject: Text("Learn it firsthand: \(response.guide.title)"),
                message: Text("Learn it firsthand: \(response.guide.title)"),
                preview: SharePreview("Learn it firsthand: \(response.guide.title)")) {
        railLabel("paperplane", "Share", tint: .white)
      }
      railButton("list.bullet", "Steps", label: "All steps") {
        player.player.pause()
        withoutAnimation { showSteps = true }
      }
    }
    .shadow(color: .black.opacity(0.35), radius: 6, y: 1)
  }

  private func railButton(_ symbol: String, _ text: String, tint: Color = .white, label: String,
                          action: @escaping () -> Void) -> some View {
    Button(action: action) { railLabel(symbol, text, tint: tint) }
      .buttonStyle(.plain)
      .accessibilityLabel(label)
  }

  private func railLabel(_ symbol: String, _ text: String, tint: Color) -> some View {
    VStack(spacing: 4) {
      Image(systemName: symbol).font(.system(size: 24, weight: .semibold)).foregroundStyle(tint)
      Text(text).font(.caption2.weight(.medium))
    }
    .frame(width: 48)
    .contentShape(Rectangle())
  }

  private func pill(_ text: String) -> some View {
    Text(text).font(.caption.weight(.medium)).lineLimit(1)
      .padding(.horizontal, 10).padding(.vertical, 6)
      .background(.black.opacity(0.38), in: .capsule)
  }
}
