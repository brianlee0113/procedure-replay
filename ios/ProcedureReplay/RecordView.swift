// Step 1 · Record: what the glasses see, full screen. Dark like a camera viewfinder.

import SwiftUI

struct RecordView: View {
  let flow: CreateFlow
  let close: () -> Void

  private var camera: GlassesCamera { flow.camera }

  var body: some View {
    ZStack {
      Color.black.ignoresSafeArea()
      if let frame = camera.frame {
        Image(uiImage: frame).resizable().scaledToFit().ignoresSafeArea()
      } else {
        ProgressView().tint(.white)
      }
      VStack(spacing: 12) {
        topBar
        inputs
        Spacer()
        if case .failed(let message) = camera.state {
          Text(message).font(.callout).foregroundStyle(.white).multilineTextAlignment(.center)
            .padding(14).glassEffect(.regular, in: .rect(cornerRadius: 18))
        }
        Text("Talk as you work. Meta AI uses your words to write each step.")
          .font(.footnote).foregroundStyle(.white.opacity(0.75)).multilineTextAlignment(.center)
        controls
      }
      .padding(.horizontal, 16)
      .padding(.bottom, 8)
    }
    .environment(\.colorScheme, .dark)
    .task { await camera.connect() }
  }

  private var topBar: some View {
    HStack {
      Label {
        Text(camera.state == .streaming ? "Glasses connected" : "Connecting to glasses…")
      } icon: {
        Circle().fill(camera.state == .streaming ? Color.ok : Color.orange).frame(width: 8, height: 8)
      }
      .font(.subheadline).padding(.horizontal, 12).padding(.vertical, 7)
      .glassEffect(.regular, in: .capsule)
      Spacer()
      if let started = camera.recordingStarted {
        TimelineView(.periodic(from: started, by: 1)) { context in
          Label {
            Text("REC \(clock(context.date.timeIntervalSince(started)))").font(.eyebrow)
          } icon: {
            Circle().fill(Color.live).frame(width: 8, height: 8)
          }
          .padding(.horizontal, 12).padding(.vertical, 8)
          .glassEffect(.regular, in: .capsule)
        }
      }
    }
  }

  private var inputs: some View {
    HStack(spacing: 6) {
      inputBadge("video", "Video")
      inputBadge("mic", "Narration")
      inputBadge("text.viewfinder", "On-screen text")
      Spacer()
    }
  }

  private func inputBadge(_ symbol: String, _ text: String) -> some View {
    Label(text, systemImage: symbol)
      .font(.footnote).padding(.horizontal, 10).padding(.vertical, 6)
      .glassEffect(.regular, in: .capsule)
  }

  private var controls: some View {
    HStack(alignment: .top) {
      sideButton("flag", flow.marks.isEmpty ? "Mark step" : "Marked \(flow.marks.count)") { flow.markStep() }
        .disabled(!camera.isRecording)
      Spacer()
      VStack(spacing: 6) {
        Button { Task { await flow.toggleRecording() } } label: {
          ZStack {
            Circle().strokeBorder(.white, lineWidth: 4).frame(width: 76, height: 76)
            RoundedRectangle(cornerRadius: camera.isRecording ? 8 : 30)
              .fill(Color.live)
              .frame(width: camera.isRecording ? 30 : 60, height: camera.isRecording ? 30 : 60)
          }
        }
        .disabled(camera.state != .streaming)
        .accessibilityLabel(camera.isRecording ? "Stop and build guide" : "Start recording")
        Text(camera.isRecording ? "Stop & build guide" : "Record").font(.footnote).foregroundStyle(.white)
      }
      Spacer()
      sideButton("xmark", "Close") {
        camera.disconnect()
        close()
      }
      .disabled(camera.isRecording)
    }
  }

  private func sideButton(_ symbol: String, _ text: String, action: @escaping () -> Void) -> some View {
    Button(action: action) {
      VStack(spacing: 6) {
        Image(systemName: symbol).font(.system(size: 18, weight: .medium)).frame(width: 52, height: 52)
          .glassEffect(.regular.interactive(), in: .circle)
        Text(text).font(.footnote)
      }
      .foregroundStyle(.white)
      .frame(width: 90)
    }
  }
}
