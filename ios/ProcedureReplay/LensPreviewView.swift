// The simulated lens of Meta Ray-Ban Display glasses, drawn by MockDeviceKit, inside the app.

import SwiftUI

struct LensPreview: UIViewRepresentable {
  let lens: LensController

  func makeUIView(context: Context) -> UIView {
    let host = UIView()
    host.backgroundColor = .black
    if let preview = lens.previewView() {
      preview.translatesAutoresizingMaskIntoConstraints = false
      host.addSubview(preview)
      NSLayoutConstraint.activate([
        preview.leadingAnchor.constraint(equalTo: host.leadingAnchor),
        preview.trailingAnchor.constraint(equalTo: host.trailingAnchor),
        preview.topAnchor.constraint(equalTo: host.topAnchor),
        preview.bottomAnchor.constraint(equalTo: host.bottomAnchor),
      ])
    }
    return host
  }

  func updateUIView(_ view: UIView, context: Context) {}
}

/// The trainee's Display glasses during a guide: shows the phone's current step in the lens, and turns the lens
/// buttons (Back, Next, Replay clip) into requests the step player applies.
@Observable
@MainActor
final class LensMode {
  let lens = LensController()
  var isOn = false
  var connecting = false
  var error: String?
  /// Set by a lens button; the step player moves there (total + 1 means "finished").
  var requestedStep: Int?
  var replayRequests = 0
  /// The last voice command the glasses understood, shown briefly on the phone.
  var heardCommand: String?
  private var currentIndex = 1

  func turnOn(guide: Guide, step: GuideStep) async {
    isOn = true
    connecting = true
    error = nil
    lens.onHeard = { [weak self] text in self?.handleVoice(text) }
    await lens.connect()
    connecting = false
    if case .failed(let message) = lens.state {
      error = message
      isOn = false
      return
    }
    await show(guide: guide, step: step)
  }

  func show(guide: Guide, step: GuideStep) async {
    guard isOn, !connecting else { return }
    let index = step.index
    currentIndex = index
    let total = guide.steps.count
    await lens.show(
      LensStep(index: index, total: total, title: step.title, instruction: step.instruction,
               doneWhen: step.doneWhen.lowercasedFirst, cover: nil),
      onPrevious: { [weak self] in Task { @MainActor in self?.requestedStep = max(1, index - 1) } },
      onNext: { [weak self] in Task { @MainActor in self?.requestedStep = index + 1 } },
      onReplay: { [weak self] in Task { @MainActor in self?.replayRequests += 1 } })
  }

  /// "Next step", "go back", "replay that": hands-free control while the trainee's hands are busy.
  private func handleVoice(_ text: String) {
    let said = text.lowercased()
    if said.contains("next") {
      requestedStep = currentIndex + 1
      heardCommand = "Next"
    } else if said.contains("back") || said.contains("previous") {
      requestedStep = max(1, currentIndex - 1)
      heardCommand = "Back"
    } else if said.contains("replay") || said.contains("again") {
      replayRequests += 1
      heardCommand = "Replay"
    } else {
      return
    }
    Task {
      try? await Task.sleep(for: .seconds(2))
      heardCommand = nil
    }
  }

  func finish(title: String) async {
    guard isOn else { return }
    await lens.showFinished(title: title)
  }

  func turnOff() {
    guard isOn || connecting else { return }
    lens.disconnect()
    isOn = false
    connecting = false
  }
}
