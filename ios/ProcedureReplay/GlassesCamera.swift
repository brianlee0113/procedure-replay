// Glasses camera through the Meta Wearables Device Access Toolkit.
// Without glasses, MockDeviceKit plays the bundled licensed video (glasses_feed.mp4, made by
// scripts/make_mock_feed.sh) as the camera feed. It must be HEVC, portrait 540x960, 30 fps:
// a square 10 fps file started the stream but delivered no frames.

import AVFoundation
import MWDATCamera
import MWDATCore
import MWDATMockDevice
import Observation
import UIKit

/// The licensed video behind the mock feed: the upload inherits its license (server.store_upload).
struct FeedSource: Decodable {
  let videoId: String
  let task: String
  let durationS: Double?

  static let bundled: FeedSource? = {
    guard let url = Bundle.main.url(forResource: "glasses_feed", withExtension: "json"),
      let data = try? Data(contentsOf: url)
    else { return nil }
    let d = JSONDecoder()
    d.keyDecodingStrategy = .convertFromSnakeCase
    return try? d.decode(FeedSource.self, from: data)
  }()
}

@Observable
@MainActor
final class GlassesCamera {
  enum State: Equatable { case idle, connecting, streaming, failed(String) }

  var state = State.idle
  var frame: UIImage?
  var framesReceived = 0
  var recordingStarted: Date?
  /// When the first frame arrived: the mock feed starts playing the source video from 0:00 then.
  var firstFrameAt: Date?

  @ObservationIgnored private var glasses: (any MockGlasses)?
  @ObservationIgnored private var session: DeviceSession?
  @ObservationIgnored private var camera: Camera?
  @ObservationIgnored private let tokens = ListenerTokenBag()
  @ObservationIgnored private let recorder = FrameRecorder()
  // Created before pairing so it sees the mock device appear; createSession throws noEligibleDevice
  // if no device is active yet (DAT skills/display-access).
  // Camera glasses only: the trainee's Display glasses (LensController) may be paired at the same time.
  @ObservationIgnored private let selector = AutoDeviceSelector(wearables: Wearables.shared, filter: { !$0.supportsDisplay() })

  var isRecording: Bool { recordingStarted != nil }

  func connect() async {
    guard state == .idle else { return }
    state = .connecting
    do {
      MockDeviceKit.shared.enable()  // starts registered, with permissions granted
      let glasses = try MockDeviceKit.shared.pairGlasses(model: .rayBanMeta)
      glasses.powerOn()
      glasses.unfold()
      glasses.don()
      guard let feed = Bundle.main.url(forResource: "glasses_feed", withExtension: "mp4") else {
        state = .failed("glasses_feed.mp4 is missing: run scripts/make_mock_feed.sh")
        return
      }
      glasses.services.camera.setCameraFeed(fileURL: feed)
      self.glasses = glasses
      for await device in selector.activeDeviceStream() where device != nil { break }
      let session = try Wearables.shared.createSession(deviceSelector: selector)
      self.session = session
      session.statePublisher.listen { [weak self] s in
        Task { @MainActor in self?.sessionChanged(s) }
      }.store(in: tokens)
      try session.start()
    } catch {
      state = .failed("Couldn't connect to the glasses: \(error)")
    }
  }

  private func sessionChanged(_ s: DeviceSessionState) {
    guard s == .started, camera == nil, let session else { return }
    do {
      let config = StreamConfiguration(videoCodec: .raw, resolution: .medium, frameRate: 15)
      guard let camera = try session.addCamera(config: config) else {
        state = .failed("The glasses camera didn't start")
        return
      }
      self.camera = camera
      let recorder = self.recorder
      camera.stream.videoFramePublisher.listen { [weak self] frame in
        recorder.append(frame.sampleBuffer)
        let image = frame.makeUIImage()
        Task { @MainActor in
          guard let self else { return }
          self.framesReceived += 1
          if self.firstFrameAt == nil { self.firstFrameAt = Date() }
          if let image { self.frame = image }
          if self.state != .streaming { self.state = .streaming }
        }
      }.store(in: tokens)
      camera.stream.start()
    } catch {
      state = .failed("The glasses camera didn't start: \(error)")
    }
  }

  func startRecording() {
    let url = FileManager.default.temporaryDirectory.appendingPathComponent("recording-\(UUID().uuidString).mp4")
    recorder.start(url: url)
    recordingStarted = Date()
  }

  /// Finishes the file; nil if nothing was written.
  func stopRecording() async -> URL? {
    recordingStarted = nil
    return await recorder.stop()
  }

  func disconnect() {
    camera?.stop()
    session?.stop()
    camera = nil
    session = nil
    tokens.clear()
    // Unpair, or every new recording adds a mock device and pairing fails after three.
    if let glasses { MockDeviceKit.shared.unpairDevice(glasses) }
    glasses = nil
    frame = nil
    framesReceived = 0
    firstFrameAt = nil
    state = .idle
  }
}

/// Writes raw (uncompressed) glasses frames to an H.264 mp4. Frames are stamped with wall-clock time
/// since recording started, because the stream's own timestamps are not documented.
final class FrameRecorder: @unchecked Sendable {
  private let lock = NSLock()
  private var writer: AVAssetWriter?
  private var input: AVAssetWriterInput?
  private var adaptor: AVAssetWriterInputPixelBufferAdaptor?
  private var url: URL?
  private var startTime: CFTimeInterval?
  private var pending: URL?

  func start(url: URL) {
    lock.withLock { pending = url }
  }

  func append(_ sampleBuffer: CMSampleBuffer) {
    lock.withLock {
      guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
      if let url = pending {
        pending = nil
        open(url: url, width: CVPixelBufferGetWidth(pixelBuffer), height: CVPixelBufferGetHeight(pixelBuffer))
      }
      guard let input, let adaptor, let startTime, input.isReadyForMoreMediaData else { return }
      let t = CMTime(seconds: CACurrentMediaTime() - startTime, preferredTimescale: 600)
      adaptor.append(pixelBuffer, withPresentationTime: t)
    }
  }

  private func open(url: URL, width: Int, height: Int) {
    guard let writer = try? AVAssetWriter(outputURL: url, fileType: .mp4) else { return }
    let input = AVAssetWriterInput(mediaType: .video, outputSettings: [
      AVVideoCodecKey: AVVideoCodecType.h264, AVVideoWidthKey: width, AVVideoHeightKey: height,
    ])
    input.expectsMediaDataInRealTime = true
    writer.add(input)
    let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: nil)
    guard writer.startWriting() else { return }
    writer.startSession(atSourceTime: .zero)
    self.writer = writer
    self.input = input
    self.adaptor = adaptor
    self.url = url
    startTime = CACurrentMediaTime()
  }

  func stop() async -> URL? {
    let (writer, input, url) = lock.withLock { () -> (AVAssetWriter?, AVAssetWriterInput?, URL?) in
      defer { self.writer = nil; self.input = nil; self.adaptor = nil; self.url = nil; self.startTime = nil; pending = nil }
      return (self.writer, self.input, self.url)
    }
    guard let writer, let input else { return nil }
    input.markAsFinished()
    await writer.finishWriting()
    return writer.status == .completed ? url : nil
  }
}
