// A1 spike: simulated Ray-Ban Meta glasses (MockDeviceKit) stream a licensed video as the camera feed;
// the app previews the frames and records them to an mp4.
//
// Launch with `--spike-autorun` to run the whole path unattended (start, record 5 s, stop) and write
// Documents/spike_result.json, so it can be checked from the command line.

import AVFoundation
import MWDATCamera
import MWDATCore
import MWDATMockDevice
import Observation
import UIKit

@Observable
@MainActor
final class GlassesSpike {
  var status = "Idle"
  var frame: UIImage?
  var framesReceived = 0
  var isRecording = false
  var recordingURL: URL?

  @ObservationIgnored private var glasses: MockGlasses?
  @ObservationIgnored private var session: DeviceSession?
  @ObservationIgnored private var camera: Camera?
  @ObservationIgnored private let tokens = ListenerTokenBag()
  @ObservationIgnored private let recorder = FrameRecorder()
  // Created before pairing so it sees the mock device appear; createSession throws noEligibleDevice
  // if no device is active yet (DAT skills/display-access).
  @ObservationIgnored private let selector = AutoDeviceSelector(wearables: Wearables.shared)

  func start() async {
    do {
      MockDeviceKit.shared.enable()  // starts registered, with permissions granted
      let glasses = try MockDeviceKit.shared.pairGlasses(model: .rayBanMeta)
      glasses.powerOn()
      glasses.unfold()
      glasses.don()
      // `--feed=<name>` picks another bundled mp4 (spike diagnostics).
      let feedName = ProcessInfo.processInfo.arguments.first { $0.hasPrefix("--feed=") }?
        .replacingOccurrences(of: "--feed=", with: "") ?? "glasses_feed"
      guard let feed = Bundle.main.url(forResource: feedName, withExtension: "mp4") else {
        status = "glasses_feed.mp4 missing: run scripts/make_mock_feed.sh"
        return
      }
      glasses.services.camera.setCameraFeed(fileURL: feed)
      self.glasses = glasses

      status = "Waiting for glasses"
      for await device in selector.activeDeviceStream() where device != nil { break }
      let session = try Wearables.shared.createSession(deviceSelector: selector)
      self.session = session
      session.statePublisher.listen { [weak self] state in
        Task { @MainActor in self?.sessionChanged(state) }
      }.store(in: tokens)
      session.errorPublisher.listen { [weak self] error in
        Task { @MainActor in self?.status = "Session error: \(error.localizedDescription)" }
      }.store(in: tokens)
      status = "Starting session"
      try session.start()
    } catch {
      status = "Start failed: \(error)"
    }
  }

  @ObservationIgnored private var events: [String] = []

  private func log(_ event: String) {
    events.append(event)
    status = event
  }

  private func sessionChanged(_ state: DeviceSessionState) {
    log("session \(state)")
    guard state == .started, camera == nil, let session else { return }
    do {
      let config = StreamConfiguration(videoCodec: .raw, resolution: .medium, frameRate: 15)
      guard let camera = try session.addCamera(config: config) else {
        status = "addCamera returned nil"
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
          if let image { self.frame = image }
        }
      }.store(in: tokens)
      camera.stream.errorPublisher.listen { [weak self] error in
        Task { @MainActor in self?.log("stream error: \(error)") }
      }.store(in: tokens)
      camera.stream.statePublisher.listen { [weak self] state in
        Task { @MainActor in self?.log("stream \(state)") }
      }.store(in: tokens)
      camera.stream.start()
      status = "Streaming"
    } catch {
      status = "addCamera failed: \(error)"
    }
  }

  func startRecording() {
    let url = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
      .appendingPathComponent("spike_recording.mp4")
    try? FileManager.default.removeItem(at: url)
    recorder.start(url: url)
    isRecording = true
  }

  func stopRecording() async {
    recordingURL = await recorder.stop()
    isRecording = false
  }

  func stop() {
    camera?.stop()
    session?.stop()
    camera = nil
    session = nil
    status = "Stopped"
  }

  /// Unattended run for command-line verification.
  func autorun() async {
    await start()
    for _ in 0..<40 where framesReceived == 0 { try? await Task.sleep(for: .milliseconds(250)) }
    let firstFrameSeen = framesReceived > 0
    startRecording()
    try? await Task.sleep(for: .seconds(5))
    await stopRecording()
    var duration = 0.0
    if let url = recordingURL {
      duration = (try? await AVURLAsset(url: url).load(.duration).seconds) ?? 0
    }
    let result: [String: Any] = [
      "status": status,
      "events": events,
      "arguments": Array(ProcessInfo.processInfo.arguments.dropFirst()),
      "first_frame_seen": firstFrameSeen,
      "frames_received": framesReceived,
      "frame_size": frame.map { "\(Int($0.size.width))x\(Int($0.size.height))" } ?? "none",
      "recording": recordingURL?.lastPathComponent ?? "none",
      "recording_duration_s": duration,
    ]
    let out = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
      .appendingPathComponent("spike_result.json")
    try? JSONSerialization.data(withJSONObject: result, options: .prettyPrinted).write(to: out)
    stop()
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
