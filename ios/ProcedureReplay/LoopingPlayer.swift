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
  var loops = true {
    didSet { if !loops { looper?.disableLooping() } else if oldValue == false { restart() } }
  }

  @ObservationIgnored let player = AVQueuePlayer()
  @ObservationIgnored private var looper: AVPlayerLooper?
  @ObservationIgnored private var url: URL?
  @ObservationIgnored private var timeObserver: Any?
  @ObservationIgnored private var statusTask: Task<Void, Never>?

  init() {
    player.isMuted = true  // narration comes with B2; the dataset clips have no speech
    timeObserver = player.addPeriodicTimeObserver(forInterval: CMTime(value: 1, timescale: 10), queue: .main) {
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

  /// Starts the clip from the beginning (the Replay button).
  func restart() {
    guard let url else { return }
    looper?.disableLooping()
    player.removeAllItems()
    let item = AVPlayerItem(url: url)
    looper = loops ? AVPlayerLooper(player: player, templateItem: item) : nil
    if !loops { player.insert(item, after: nil) }
    statusTask?.cancel()
    statusTask = Task { [weak self] in
      // The first request for a clip makes the server cut it, which can take a few seconds.
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

  func stop() {
    player.pause()
    statusTask?.cancel()
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
