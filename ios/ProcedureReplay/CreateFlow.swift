// Instructor flow, Steps 1–2 of the app: record with the glasses → upload → Meta AI builds the guide → Draft.

import Foundation
import Observation
import UIKit

@Observable
@MainActor
final class CreateFlow {
  enum Phase: Equatable { case record, uploading, building, draft, failed(String) }

  var phase = Phase.record
  let camera = GlassesCamera()
  var marks: [Double] = []
  var thumbnail: UIImage?
  var recordedSeconds = 0.0
  var job: Job?
  var guide: GuideResponse?
  var showPublish = false
  /// Set once the guide is published; the flow closes and the app shows it in the Feed or Library.
  var published: GuideCard?

  /// Server stages in order, with what each one means for the instructor (Figma "Building" screen).
  static let stages: [(id: String, title: String, detail: String)] = [
    ("upload", "Uploaded from your glasses", "Video from your glasses"),
    ("transcribe", "Transcribed your narration", "What you said, matched to the video"),
    ("read_text", "Read text on screen", "Labels and screens in view"),
    ("split", "Splitting into steps", "Where each step starts and ends"),
    ("write", "Writing the instructions", "A title, a summary and one instruction per step"),
  ]

  func toggleRecording() async {
    if camera.isRecording {
      await finishRecording()
    } else {
      marks = []
      camera.startRecording()
    }
  }

  func markStep() {
    guard let started = camera.recordingStarted else { return }
    marks.append(Date().timeIntervalSince(started))
  }

  func finishRecording() async {
    recordedSeconds = camera.recordingStarted.map { Date().timeIntervalSince($0) } ?? 0
    thumbnail = camera.frame
    guard let file = await camera.stopRecording() else {
      phase = .failed("Nothing was recorded. Record for at least a second, then stop.")
      return
    }
    camera.disconnect()
    guard let source = FeedSource.bundled else {
      phase = .failed("glasses_feed.json is missing: run scripts/make_mock_feed.sh")
      return
    }
    phase = .uploading
    do {
      job = try await API.uploadRecording(file: file, task: source.task, sourceVideoId: source.videoId, marks: marks)
      phase = .building
      await followJob()
    } catch {
      phase = .failed("Upload failed. Is the Mac server running at \(API.base.absoluteString)? (\(error.localizedDescription))")
    }
  }

  private func followJob() async {
    while let current = job, current.status == "queued" || current.status == "running" {
      try? await Task.sleep(for: .milliseconds(400))
      if let next = try? await API.job(current.id) { job = next }
    }
    guard let job else { return }
    if job.status == "error" {
      phase = .failed("Meta AI couldn't build the guide: \(job.error ?? "unknown error")")
      return
    }
    do {
      guide = try await API.guide(job.guideId)
      phase = .draft
    } catch {
      phase = .failed("The guide is ready but couldn't be opened: \(error.localizedDescription)")
    }
  }

  func save(_ edit: StepEdit, step index: Int) async throws {
    guard let id = guide?.guide.guideId else { return }
    let updated = try await API.editStep(guideId: id, index: index, edit)
    if let i = guide?.guide.steps.firstIndex(where: { $0.index == index }) {
      guide?.guide.steps[i] = updated
    }
  }

  func publish(_ body: PublishRequest) async throws {
    guard let id = guide?.guide.guideId else { return }
    published = try await API.publish(guideId: id, body)
  }

  /// `--autorun-a5`, after `autorun()`: open Publish, keep Meta AI's suggestions, publish as Public.
  func autorunPublish() async {
    guard phase == .draft, let g = guide?.guide else { return }
    try? await Task.sleep(for: .seconds(1.5))
    showPublish = true
    try? await Task.sleep(for: .seconds(3))
    try? await publish(PublishRequest(visibility: "public", title: g.title, summary: g.summary, category: g.category))
  }

  /// `--autorun-a3`: record 4 s with one Mark step, upload, follow the job, open the Draft, edit step 1,
  /// and write Documents/a3_result.json for command-line checks.
  func autorun() async {
    await camera.connect()
    for _ in 0..<60 where camera.framesReceived == 0 { try? await Task.sleep(for: .milliseconds(250)) }
    await toggleRecording()
    try? await Task.sleep(for: .seconds(2))
    markStep()
    try? await Task.sleep(for: .seconds(2))
    var stagesSeen: [String] = []
    let watcher = Task { @MainActor in
      while !Task.isCancelled {
        if let running = job?.stages.first(where: { $0.value == "running" })?.key, stagesSeen.last != running {
          stagesSeen.append(running)
        }
        try? await Task.sleep(for: .milliseconds(100))
      }
    }
    await toggleRecording()
    watcher.cancel()
    var edited = ""
    if phase == .draft {
      try? await save(StepEdit(title: "Take the battery pack off the drill"), step: 1)
      edited = guide?.guide.steps.first?.title ?? ""
    }
    let result: [String: Any] = [
      "phase": "\(phase)",
      "frames_received": camera.framesReceived,
      "recorded_s": recordedSeconds,
      "marks": marks,
      "job_status": job?.status ?? "none",
      "stages_seen_running": stagesSeen,
      "guide_id": guide?.guide.guideId ?? "none",
      "steps": guide?.guide.steps.count ?? 0,
      "edited_step_1_title": edited,
    ]
    let out = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
      .appendingPathComponent("a3_result.json")
    try? JSONSerialization.data(withJSONObject: result, options: .prettyPrinted).write(to: out)
  }
}
