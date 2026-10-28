// Step 3 · Step player: the step's clip loops on top, the instruction sits below.

import SwiftUI

struct StepPlayerView: View {
  let guide: Guide
  @State private var index: Int
  @State private var player = LoopingPlayer()
  @State private var lensMode = LensMode()
  @Environment(\.dismiss) private var dismiss

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
    try? await Task.sleep(for: .seconds(4))
    let result: [String: Any] = ["lens_on": lensMode.isOn, "lens_state": "\(lensMode.lens.state)",
                                 "error": lensMode.error ?? "", "step_before": before, "step_after_lens_next": index]
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

  private func show(_ step: GuideStep) {
    if let path = step.clipUrl { player.load(API.url(path)) }
    let i = step.index
    Task { try? await API.setProgress(guideId: guide.guideId, step: i) }
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
          ProgressView("Cutting the clip…").tint(.white).foregroundStyle(.white).padding(.top, 200)
        }
      }
      LinearGradient(colors: [.black.opacity(0.55), .clear], startPoint: .top, endPoint: .center)
        .allowsHitTesting(false)
      VStack(spacing: 10) {
        progress
        topControls
        if lensMode.isOn || lensMode.connecting || lensMode.error != nil { lensStatus }
        Spacer()
        scrubber
      }
      .padding(.horizontal, 16)
      .padding(.top, 58)
      .padding(.bottom, 26)
      .environment(\.colorScheme, .dark)
    }
    .frame(maxWidth: .infinity)
    .frame(height: 470)
    .clipped()
  }

  private var progress: some View {
    HStack(spacing: 4) {
      ForEach(guide.steps) { s in
        Capsule().fill(s.index < index ? .white : s.index == index ? .white.opacity(0.85) : .white.opacity(0.3))
          .frame(height: 3)
      }
    }
    .accessibilityLabel("Step \(index) of \(guide.steps.count)")
  }

  private var topControls: some View {
    HStack {
      Button { dismiss() } label: {
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
        Label(lensMode.connecting ? "Connecting to glasses…" : "On your glasses", systemImage: "eyeglasses")
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

  private var scrubber: some View {
    VStack(spacing: 6) {
      ProgressView(value: min(player.elapsed, max(player.duration, 0.01)), total: max(player.duration, 0.01))
        .tint(.white)
      HStack {
        Text(clock(player.elapsed)).monospacedDigit()
        Spacer()
        Text("Expert clip \(clock(step.clip.startS)) – \(clock(step.clip.endS))".uppercased())
        Spacer()
        Text(clock(player.duration)).monospacedDigit()
      }
      .font(.eyebrow)
      .foregroundStyle(.white.opacity(0.85))
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
      HStack(spacing: 10) {
        Button { index -= 1 } label: {
          Image(systemName: "chevron.left").font(.headline).frame(width: 30, height: 30)
        }
        .buttonStyle(.glass)
        .disabled(index == guide.steps.first?.index)
        .accessibilityLabel("Previous step")
        Button { player.restart() } label: {
          Text("Replay").font(.headline).padding(.horizontal, 6).padding(.vertical, 6)
        }
        .buttonStyle(.glass)
        Button { if isLast { dismiss() } else { index += 1 } } label: {
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
      UnevenRoundedRectangle(topLeadingRadius: 32, topTrailingRadius: 32).fill(Color.panel).ignoresSafeArea(edges: .bottom)
    }
    .offset(y: -28)
    .padding(.bottom, -28)
  }
}

extension String {
  var lowercasedFirst: String { prefix(1).lowercased() + dropFirst() }
}
