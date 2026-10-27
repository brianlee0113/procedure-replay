import SwiftUI

struct GlassesSpikeView: View {
  @State private var spike = GlassesSpike()

  var body: some View {
    VStack(spacing: 16) {
      ZStack {
        Color.black
        if let frame = spike.frame {
          Image(uiImage: frame).resizable().scaledToFit()
        } else {
          Text("No frames yet").foregroundStyle(.secondary)
        }
      }
      .aspectRatio(1, contentMode: .fit)
      .clipShape(RoundedRectangle(cornerRadius: 24))

      Text(spike.status).font(.callout)
      Text("Frames: \(spike.framesReceived)").font(.caption.monospacedDigit())
      if let url = spike.recordingURL {
        Text("Saved \(url.lastPathComponent)").font(.caption)
      }

      HStack {
        Button("Start glasses") { Task { await spike.start() } }
        Button(spike.isRecording ? "Stop recording" : "Record") {
          if spike.isRecording { Task { await spike.stopRecording() } } else { spike.startRecording() }
        }
        .disabled(spike.framesReceived == 0)
      }
      .buttonStyle(.glass)
    }
    .padding()
    .task {
      if ProcessInfo.processInfo.arguments.contains("--spike-autorun") { await spike.autorun() }
    }
  }
}
