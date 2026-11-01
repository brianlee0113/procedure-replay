// Plays one step's clip (cut by the server) on repeat, so a trainee can watch the move as often as needed.

import AVFoundation
import Observation
import SwiftUI

@Observable
@MainActor
final class LoopingPlayer {
  var isReady = false
  var failed: String?
  var elapsed = 0.0
  var duration = 0.0
  var isPaused = false
  /// Only mutes the player. The audio session is set once (`activateAudio`): changing it on every toggle
  /// made iOS stop the clip for a moment, so the sound button seemed to pause the video too.
  var isMuted = true {
    didSet { player.isMuted = isMuted }
  }
  var loops = true {
    didSet { if !loops { looper?.disableLooping() } else if oldValue == false { restart() } }
  }

  @ObservationIgnored let player = AVQueuePlayer()
  @ObservationIgnored private var looper: AVPlayerLooper?
  @ObservationIgnored private var url: URL?
  @ObservationIgnored private var timeObserver: Any?
  @ObservationIgnored private var statusTask: Task<Void, Never>?
  @ObservationIgnored private var playAfterScrub = false

  init() {
    player.isMuted = true  // StepPlayerView turns sound on for guides built with a transcript; the trainee can toggle it
    // 30 Hz so the story bar at the top fills smoothly.
    timeObserver = player.addPeriodicTimeObserver(forInterval: CMTime(value: 1, timescale: 30), queue: .main) {
      [weak self] t in
      MainActor.assumeIsolated {
        guard let self else { return }
        self.elapsed = t.seconds.isFinite ? t.seconds : 0
      }
    }
  }

  func load(_ url: URL) {
    guard url != self.url else { return }
    self.url = url
    isReady = false
    failed = nil
    elapsed = 0
    restart()
  }

  /// Nothing on screen until the next clip is ready (so the last step's video doesn't keep playing under the new title).
  func clear() {
    url = nil
    isReady = false
    failed = nil
    elapsed = 0
    statusTask?.cancel()
    looper?.disableLooping()
    looper = nil
    player.removeAllItems()
  }

  /// Starts the clip from the beginning (a new step, Loop turned back on, or Replay on the lens).
  func restart() {
    guard let url else { return }
    isPaused = false
    looper?.disableLooping()
    player.removeAllItems()
    let item = AVPlayerItem(url: url)
    looper = loops ? AVPlayerLooper(player: player, templateItem: item) : nil
    if !loops { player.insert(item, after: nil) }
    statusTask?.cancel()
    statusTask = Task { [weak self] in
      // Clips are usually on the phone already (ClipCache); a streamed fallback can take a moment.
      for _ in 0..<300 {
        guard let self, !Task.isCancelled else { return }
        if let current = self.player.currentItem {
          if current.status == .readyToPlay {
            self.duration = (try? await current.asset.load(.duration).seconds) ?? 0
            self.isReady = true
            return
          }
          if current.status == .failed {
            self.failed = current.error?.localizedDescription ?? "The clip couldn't be played"
            return
          }
        }
        try? await Task.sleep(for: .milliseconds(100))
      }
    }
    player.play()
  }

  /// Sound plays even with the ring switch on silent, like a video app, and mixes with music the trainee has on.
  func activateAudio() {
    let session = AVAudioSession.sharedInstance()
    try? session.setCategory(.playback, mode: .moviePlayback, options: [.mixWithOthers])
    try? session.setActive(true)
  }

  /// A tap on the middle of the video. A clip that played to its end (Loop off) starts over.
  func togglePause() {
    if isPaused {
      isPaused = false
      if player.currentItem == nil { restart() } else { player.play() }
    } else {
      isPaused = true
      player.pause()
    }
  }

  /// Dragging along the bottom of the video: hold the clip still, follow the finger, then carry on as before.
  func beginScrub() {
    playAfterScrub = !isPaused
    player.pause()
  }

  func scrub(to fraction: Double) {
    guard duration > 0 else { return }
    let seconds = min(max(fraction, 0), 1) * duration
    elapsed = seconds
    player.seek(to: CMTime(seconds: seconds, preferredTimescale: 600), toleranceBefore: .zero, toleranceAfter: .zero)
  }

  func endScrub() {
    if playAfterScrub { player.play() }
  }

  func stop() {
    player.pause()
    statusTask?.cancel()
    try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
  }
}

/// Step clips saved on the phone. The player plays the local file, and the steps either side are fetched ahead,
/// so moving between steps doesn't wait on the network. Keyed by the clip's bounds: a re-cut in the Draft is a new file.
actor ClipCache {
  static let shared = ClipCache()

  private let dir = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
    .appendingPathComponent("clips", isDirectory: true)
  private var inFlight: [String: Task<URL, Error>] = [:]

  static func key(guideId: String, step: GuideStep) -> String {
    String(format: "%@_%02d_%.2f_%.2f", guideId, step.index, step.clip.startS, step.clip.endS)
  }

  func file(for remote: URL, key: String) async throws -> URL {
    let local = dir.appendingPathComponent(key + ".mp4")
    if FileManager.default.fileExists(atPath: local.path) { return local }
    if let running = inFlight[key] { return try await running.value }
    let task = Task<URL, Error> { [dir] in
      try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
      let (tmp, response) = try await URLSession.shared.download(from: remote)
      guard (response as? HTTPURLResponse)?.statusCode == 200 else { throw URLError(.badServerResponse) }
      try? FileManager.default.removeItem(at: local)
      try FileManager.default.moveItem(at: tmp, to: local)
      return local
    }
    inFlight[key] = task
    defer { inFlight[key] = nil }
    return try await task.value
  }
}

/// AVPlayerLayer without system controls; the step player draws its own.
struct PlayerSurface: UIViewRepresentable {
  let player: AVPlayer

  func makeUIView(context: Context) -> PlayerUIView {
    let v = PlayerUIView()
    v.playerLayer.player = player
    v.playerLayer.videoGravity = .resizeAspectFill
    return v
  }

  func updateUIView(_ view: PlayerUIView, context: Context) {}

  final class PlayerUIView: UIView {
    override class var layerClass: AnyClass { AVPlayerLayer.self }
    var playerLayer: AVPlayerLayer { layer as! AVPlayerLayer }
  }
}
