// The iPhone's microphone while the iPhone stands in for the glasses: it records the instructor to a file
// for the upload, and its on-device speech recognition feeds the simulated glasses' speech recognizer, so the
// live caption on Record shows what was actually said.

import AVFoundation
import Speech

@MainActor
final class PhoneMic {
  /// Partial and final text from on-device recognition.
  var onText: ((String, Bool) -> Void)?

  private let engine = AVAudioEngine()
  private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
  private var request: SFSpeechAudioBufferRecognitionRequest?
  private var task: SFSpeechRecognitionTask?
  private let writer = MicFile()

  /// Asks for microphone and speech permission, then starts listening (captions only, no file yet).
  func start() async -> Bool {
    guard await AVAudioApplication.requestRecordPermission() else { return false }
    let speechOK = await withCheckedContinuation { c in
      SFSpeechRecognizer.requestAuthorization { c.resume(returning: $0 == .authorized) }
    }
    do {
      let session = AVAudioSession.sharedInstance()
      try session.setCategory(.playAndRecord, mode: .measurement, options: [.defaultToSpeaker, .allowBluetoothHFP])
      try session.setActive(true)
    } catch {
      return false
    }
    let input = engine.inputNode
    let format = input.outputFormat(forBus: 0)
    let writer = self.writer
    input.installTap(onBus: 0, bufferSize: 2048, format: format) { [weak self] buffer, _ in
      writer.write(buffer)
      self?.request?.append(buffer)
    }
    do { try engine.start() } catch { return false }
    if speechOK { startRecognition() }
    return true
  }

  /// One recognition request lasts about a minute; start a new one whenever the last one ends.
  private func startRecognition() {
    guard let recognizer, recognizer.isAvailable else { return }
    let request = SFSpeechAudioBufferRecognitionRequest()
    request.shouldReportPartialResults = true
    request.requiresOnDeviceRecognition = recognizer.supportsOnDeviceRecognition
    self.request = request
    task = recognizer.recognitionTask(with: request) { [weak self] result, error in
      Task { @MainActor in
        guard let self else { return }
        if let result {
          self.onText?(result.bestTranscription.formattedString, result.isFinal)
        }
        if error != nil || result?.isFinal == true {
          self.request = nil
          self.task = nil
          if self.engine.isRunning { self.startRecognition() }
        }
      }
    }
  }

  /// Starts writing the mic to a file; the recording starts at the same moment, so the server can line them up.
  func startFile() {
    writer.start(url: FileManager.default.temporaryDirectory.appendingPathComponent("mic-\(UUID().uuidString).caf"),
                 format: engine.inputNode.outputFormat(forBus: 0))
  }

  func stopFile() -> URL? { writer.stop() }

  func stop() {
    task?.cancel()
    request?.endAudio()
    engine.inputNode.removeTap(onBus: 0)
    engine.stop()
    _ = writer.stop()
    try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
  }
}

/// Writes audio buffers from the engine's tap (an audio thread) to a CAF file.
final class MicFile: @unchecked Sendable {
  private let lock = NSLock()
  private var file: AVAudioFile?
  private var url: URL?

  func start(url: URL, format: AVAudioFormat) {
    lock.withLock {
      file = try? AVAudioFile(forWriting: url, settings: format.settings)
      self.url = url
    }
  }

  func write(_ buffer: AVAudioPCMBuffer) {
    lock.withLock { try? file?.write(from: buffer) }
  }

  func stop() -> URL? {
    lock.withLock {
      defer { file = nil; url = nil }
      return file == nil ? nil : url
    }
  }
}
