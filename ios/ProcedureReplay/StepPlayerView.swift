// Step 3 · Step player: the step's clip loops on top, the instruction sits below.

import SwiftUI

struct StepPlayerView: View {
  let guide: Guide
  @State private var index: Int
  @State private var player = LoopingPlayer()
  @State private var lensMode = LensMode()
  @State private var loadTask: Task<Void, Never>?
  @State private var scrubbing = false
  @State private var scrubFraction = 0.0
  @Environment(\.dismiss) private var dismiss
  @Environment(\.slideBack) private var slideBack

  private let autorun: Bool
  private let autorunLens: Bool

  init(guide: Guide, startIndex: Int) {
    self.guide = guide
    _index = State(initialValue: startIndex)
    let args = ProcessInfo.processInfo.arguments
    autorun = args.contains("--autorun-a4") || args.contains("--autorun-e2e")
    autorunLens = args.contains("--autorun-lens")
  }

  private var step: GuideStep { guide.steps.first { $0.index == index } ?? guide.steps[0] }
  private var isLast: Bool { index == guide.steps.last?.index }

  var body: some View {
    VStack(spacing: 0) {
      video
      sheet
    }
    .background(Color.white)
    .ignoresSafeArea(edges: .top)
    .onAppear {
      player.player.isMuted = !guide.hasNarration
      show(step)
      UIApplication.shared.isIdleTimerDisabled = true  // the trainee's hands are on the job, not the screen
    }
    .onChange(of: index) {
      show(step)
      Task { await lensMode.show(guide: guide, step: step) }
    }
    .onChange(of: lensMode.requestedStep) {
      guard let requested = lensMode.requestedStep else { return }
      lensMode.requestedStep = nil
      if requested > guide.steps.count {
        Task { await lensMode.finish(title: guide.title) }
      } else {
        index = requested
      }
    }
    .onChange(of: lensMode.replayRequests) { player.restart() }
    .onDisappear {
      UIApplication.shared.isIdleTimerDisabled = false
      loadTask?.cancel()
      player.stop()
      lensMode.turnOff()
    }
    .task {
      if autorun { await runAutorun() }
      if autorunLens { await runLensAutorun() }
    }
  }

  /// `--autorun-lens`: turn on the Display glasses, then press Next on the lens; the phone must follow.
  private func runLensAutorun() async {
    for _ in 0..<200 where !player.isReady { try? await Task.sleep(for: .milliseconds(100)) }
    await lensMode.turnOn(guide: guide, step: step)
    try? await Task.sleep(for: .seconds(3))
    let before = index
    lensMode.requestedStep = index + 1  // what the lens Next button does
    try? await Task.sleep(for: .seconds(3))
    let afterButton = index
    lensMode.lens.simulateSpeech("okay, next step")  // what the trainee says to the glasses
    try? await Task.sleep(for: .seconds(4))
    let result: [String: Any] = ["lens_on": lensMode.isOn, "lens_state": "\(lensMode.lens.state)",
                                 "error": lensMode.error ?? "", "step_before": before, "step_after_lens_next": afterButton,
                                 "step_after_voice_next": index]
    let out = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
      .appendingPathComponent("lens_result.json")
    try? JSONSerialization.data(withJSONObject: result, options: .prettyPrinted).write(to: out)
  }

  /// `--autorun-a4`: wait for the clip, advance one step, wait again, write Documents/a4_result.json.
  private func runAutorun() async {
    func waitReady() async { for _ in 0..<200 where !player.isReady { try? await Task.sleep(for: .milliseconds(100)) } }
    await waitReady()
    let first = (index, player.isReady, player.duration)
    try? await Task.sleep(for: .seconds(3))
    let elapsedAfter3s = player.elapsed
    index += 1
    try? await Task.sleep(for: .milliseconds(300))
    await waitReady()
    try? await Task.sleep(for: .seconds(2))
    let result: [String: Any] = [
      "first_step": first.0, "first_ready": first.1, "first_clip_s": first.2, "elapsed_after_3s": elapsedAfter3s,
      "second_step": index, "second_ready": player.isReady, "second_clip_s": player.duration,
      "failed": player.failed ?? "",
    ]
    let out = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
      .appendingPathComponent("a4_result.json")
    try? JSONSerialization.data(withJSONObject: result, options: .prettyPrinted).write(to: out)
  }

  /// Plays the step's clip from the phone (downloading it first if needed), then fetches the steps either side.
  private func show(_ step: GuideStep) {
    let i = step.index
    Task { try? await API.setProgress(guideId: guide.guideId, step: i) }
    guard let path = step.clipUrl else { return }
    player.clear()
    loadTask?.cancel()
    loadTask = Task {
      do {
        let local = try await ClipCache.shared.file(for: API.url(path), key: ClipCache.key(guideId: guide.guideId, step: step))
        guard !Task.isCancelled, index == i else { return }
        player.load(local)
      } catch {
        guard !Task.isCancelled, index == i else { return }
        player.load(API.url(path))  // stream it as before if the download fails
      }
      for neighbour in guide.steps where abs(neighbour.index - i) == 1 {
        guard let p = neighbour.clipUrl else { continue }
        let key = ClipCache.key(guideId: guide.guideId, step: neighbour)
        Task.detached { _ = try? await ClipCache.shared.file(for: API.url(p), key: key) }
      }
    }
  }

  // MARK: video

  private var video: some View {
    ZStack(alignment: .top) {
      Color.black
      PlayerSurface(player: player.player)
      if !player.isReady {
        if let failed = player.failed {
          Text(failed).font(.footnote).foregroundStyle(.white).padding(40)
        } else {
          ProgressView("Loading clip…").tint(.white).foregroundStyle(.white).padding(.top, 200)
        }
      }
      LinearGradient(colors: [.black.opacity(0.55), .clear], startPoint: .top, endPoint: .center)
        .allowsHitTesting(false)
      tapZones
      if player.isPaused {
        Image(systemName: "play.fill").font(.system(size: 30, weight: .semibold)).foregroundStyle(.white)
          .frame(width: 72, height: 72)
          .glassEffect(.regular, in: .circle)
          .frame(maxHeight: .infinity)
          .allowsHitTesting(false)
      }
      VStack(spacing: 10) {
        progress
        topControls
        if lensMode.isOn || lensMode.connecting || lensMode.error != nil { lensStatus }
        Spacer()
        seekBar.padding(.horizontal, -16)  // edge to edge, outside the controls' side margins
      }
      .padding(.horizontal, 16)
      .padding(.top, 58)
      .padding(.bottom, sheetOverlap)  // keep the seek bar above the sheet's rounded top
      .environment(\.colorScheme, .dark)
    }
    .frame(maxWidth: .infinity)
    .frame(height: 470)
    .clipped()
  }

  /// Like a story: tap the left third for the previous step, the middle to pause or resume, the right third for the next.
  /// The buttons drawn on top keep their own taps.
  private var tapZones: some View {
    HStack(spacing: 0) {
      Color.clear.contentShape(Rectangle()).onTapGesture { previous() }
        .accessibilityHidden(true)
      Color.clear.contentShape(Rectangle()).onTapGesture { player.togglePause() }
        .accessibilityLabel(player.isPaused ? "Play" : "Pause")
        .accessibilityAddTraits(.isButton)
      Color.clear.contentShape(Rectangle()).onTapGesture { next() }
        .accessibilityHidden(true)
    }
  }

  private var isFirst: Bool { index == guide.steps.first?.index }

  private func previous() {
    if !isFirst { index -= 1 }
  }

  private func close() {
    if let slideBack { slideBack() } else { dismiss() }
  }

  private func next() {
    if isLast { close() } else { index += 1 }
  }

  /// Like a story: one segment per step, done steps full, the current one filling as its clip plays.
  private var progress: some View {
    HStack(spacing: 4) {
      ForEach(guide.steps) { s in
        Capsule().fill(.white.opacity(0.3))
          .overlay(alignment: .leading) {
            GeometryReader { g in
              Capsule().fill(.white).frame(width: g.size.width * fill(for: s))
            }
          }
          .frame(height: 3)
      }
    }
    .accessibilityLabel("Step \(index) of \(guide.steps.count)")
  }

  private var clipFraction: Double {
    if scrubbing { return scrubFraction }
    guard player.isReady, player.duration > 0 else { return 0 }
    return min(max(player.elapsed / player.duration, 0), 1)
  }

  private func fill(for s: GuideStep) -> CGFloat {
    s.index < index ? 1 : s.index > index ? 0 : CGFloat(clipFraction)
  }

  private var topControls: some View {
    HStack {
      Button { close() } label: {
        Image(systemName: "xmark").font(.system(size: 16, weight: .semibold)).frame(width: 40, height: 40)
      }
      .glassEffect(.regular.interactive(), in: .circle)
      .accessibilityLabel("Close")
      Spacer()
      Text("Step \(index) of \(guide.steps.count)").font(.subheadline.weight(.semibold))
        .padding(.horizontal, 14).padding(.vertical, 8)
        .glassEffect(.regular, in: .capsule)
      Spacer()
      Button {
        if lensMode.isOn { lensMode.turnOff() } else { Task { await lensMode.turnOn(guide: guide, step: step) } }
      } label: {
        Image(systemName: lensMode.isOn ? "eyeglasses.slash" : "eyeglasses").font(.system(size: 16, weight: .semibold))
          .frame(width: 40, height: 40)
          .foregroundStyle(lensMode.isOn ? Color.ink : .white)
      }
      .glassEffect(lensMode.isOn ? .regular.tint(.white) : .regular, in: .circle)
      .accessibilityLabel(lensMode.isOn ? "Stop following on glasses" : "Follow on Display glasses")
      Button { player.loops.toggle() } label: {
        Label("Loop", systemImage: "repeat").font(.subheadline.weight(.semibold))
          .padding(.horizontal, 12).padding(.vertical, 8)
          .foregroundStyle(player.loops ? Color.ink : .white)
      }
      .glassEffect(player.loops ? .regular.tint(.white) : .regular, in: .capsule)
      .accessibilityValue(player.loops ? "On" : "Off")
    }
    .foregroundStyle(.white)
  }

  /// "On your glasses" and, with simulated glasses, the lens itself in the corner.
  private var lensStatus: some View {
    HStack(alignment: .top) {
      if let error = lensMode.error {
        Text(error).font(.caption).padding(8).glassEffect(.regular, in: .rect(cornerRadius: 12))
      } else {
        Label(lensMode.connecting ? "Connecting to glasses…"
                : lensMode.heardCommand.map { "Heard “\($0)”" } ?? "Glasses · say “next”",
              systemImage: lensMode.heardCommand == nil ? "eyeglasses" : "waveform")
          .font(.footnote.weight(.semibold))
          .padding(.horizontal, 12).padding(.vertical, 7)
          .background(Color.ai, in: .capsule)
      }
      Spacer()
      if lensMode.isOn, !lensMode.connecting {
        VStack(spacing: 4) {
          LensPreview(lens: lensMode.lens).frame(width: 150, height: 150).clipShape(RoundedRectangle(cornerRadius: 18))
          Text("SIMULATED LENS").font(.eyebrow).foregroundStyle(.white.opacity(0.8))
        }
      }
    }
    .foregroundStyle(.white)
  }

  /// Like TikTok: drag anywhere along the bottom of the video to move through the clip. The bar itself is drawn on
  /// the sheet's rounded top edge (`SheetTopEdge`), so it follows the corners instead of cutting across them.
  private var seekBar: some View {
    GeometryReader { g in
      VStack(spacing: 10) {
        Spacer(minLength: 0)
        if scrubbing {
          Text("\(clock(scrubFraction * player.duration)) / \(clock(player.duration))")
            .font(.title3.weight(.semibold)).monospacedDigit().foregroundStyle(.white)
            .shadow(color: .black.opacity(0.5), radius: 6)
            .frame(maxWidth: .infinity)
        }
        Color.clear.frame(height: 6)
      }
      .contentShape(Rectangle())
      .gesture(
        DragGesture(minimumDistance: 0)
          .onChanged { v in
            if !scrubbing {
              scrubbing = true
              player.beginScrub()
            }
            scrubFraction = min(max(v.location.x / g.size.width, 0), 1)
            player.scrub(to: scrubFraction)
          }
          .onEnded { _ in
            scrubbing = false
            player.endScrub()
          }
      )
    }
    .frame(height: 64)
    .allowsHitTesting(player.isReady)
    .accessibilityElement()
    .accessibilityLabel("Clip position")
    .accessibilityValue("\(clock(player.elapsed)) of \(clock(player.duration))")
    .accessibilityAdjustableAction { direction in
      let delta = 1 / max(player.duration, 1)
      player.scrub(to: clipFraction + (direction == .increment ? delta : -delta))
    }
  }

  // MARK: instruction sheet

  private var sheet: some View {
    VStack(alignment: .leading, spacing: 12) {
      ScrollView {
        VStack(alignment: .leading, spacing: 12) {
          Eyebrow(text: "Step \(index)" + (step.keyObjects.isEmpty ? "" : " · " + step.keyObjects.joined(separator: ", ")))
          Text(step.title).font(.title2.bold()).foregroundStyle(Color.ink)
          Text(step.instruction).font(.body).foregroundStyle(Color.ink)
          Label {
            Text("Done when \(step.doneWhen.lowercasedFirst).").font(.callout).foregroundStyle(Color.inkSecondary)
          } icon: {
            Image(systemName: "checkmark.circle.fill").foregroundStyle(Color.ok)
          }
          if let quote = step.quote {
            Label {
              Text("“\(quote.text)”  \(clock(quote.startS))").font(.footnote).foregroundStyle(Color.ink)
            } icon: {
              Image(systemName: "mic.fill").foregroundStyle(Color.ai)
            }
            .padding(.horizontal, 12).padding(.vertical, 10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.track, in: RoundedRectangle(cornerRadius: 14))
          }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
      }
      // The clip loops on its own (Loop at the top), so the bottom row only moves between steps.
      HStack(spacing: 10) {
        Button { previous() } label: {
          Text("Previous").font(.headline).frame(maxWidth: .infinity).padding(.vertical, 6)
        }
        .buttonStyle(.glass)
        .disabled(isFirst)
        Button { next() } label: {
          Text(isLast ? "Finish" : "Next step").font(.headline).frame(maxWidth: .infinity).padding(.vertical, 6)
        }
        .buttonStyle(.glassProminent)
        .tint(Color.ink)
      }
    }
    .padding(.horizontal, 20)
    .padding(.top, 20)
    .padding(.bottom, 8)
    .background {
      // Solid: the sheet overlaps the video, and the translucent panel let it show through as a gray band.
      UnevenRoundedRectangle(topLeadingRadius: sheetRadius, topTrailingRadius: sheetRadius).fill(Color.white)
        .ignoresSafeArea(edges: .bottom)
        .overlay(alignment: .top) { clipBar }
    }
    .offset(y: -sheetOverlap)
    .padding(.bottom, -sheetOverlap)
  }

  /// How far the instruction sheet rises over the bottom of the video.
  private let sheetOverlap: CGFloat = 28
  private let sheetRadius: CGFloat = 32

  /// Where the clip is, drawn along the sheet's top edge: a faint track, filled in blue up to the playhead.
  private var clipBar: some View {
    GeometryReader { g in
      let edge = SheetTopEdge(radius: sheetRadius)
      let width: CGFloat = scrubbing ? 5 : 2.25
      ZStack {
        edge.stroke(.white.opacity(scrubbing ? 0.5 : 0.3), style: StrokeStyle(lineWidth: width, lineCap: .round))
        edge.trim(from: 0, to: SheetTopEdge.trim(forX: clipFraction, width: g.size.width, radius: sheetRadius))
          .stroke(Color.ai, style: StrokeStyle(lineWidth: width, lineCap: .round))
      }
      .animation(.easeOut(duration: 0.15), value: scrubbing)
    }
    .frame(height: sheetRadius)
    .allowsHitTesting(false)
  }
}

extension String {
  var lowercasedFirst: String { prefix(1).lowercased() + dropFirst() }
}

/// The sheet's top outline: up the left corner, along the top, down the right corner.
struct SheetTopEdge: Shape {
  let radius: CGFloat

  func path(in rect: CGRect) -> Path {
    var p = Path()
    p.move(to: CGPoint(x: rect.minX, y: rect.minY + radius))
    p.addArc(center: CGPoint(x: rect.minX + radius, y: rect.minY + radius), radius: radius,
             startAngle: .degrees(180), endAngle: .degrees(270), clockwise: false)
    p.addLine(to: CGPoint(x: rect.maxX - radius, y: rect.minY))
    p.addArc(center: CGPoint(x: rect.maxX - radius, y: rect.minY + radius), radius: radius,
             startAngle: .degrees(270), endAngle: .degrees(360), clockwise: false)
    return p
  }

  /// The trim end whose point sits at `fraction` of the width, so the fill ends under the finger even on the corners.
  static func trim(forX fraction: Double, width: CGFloat, radius r: CGFloat) -> CGFloat {
    guard width > 2 * r else { return CGFloat(fraction) }
    let x = CGFloat(min(max(fraction, 0), 1)) * width
    let arc = r * .pi / 2
    let total = 2 * arc + (width - 2 * r)
    let length: CGFloat
    if x < r {
      length = r * acos(1 - x / r)
    } else if x > width - r {
      length = total - r * acos(1 - (width - x) / r)
    } else {
      length = arc + (x - r)
    }
    return length / total
  }
}
