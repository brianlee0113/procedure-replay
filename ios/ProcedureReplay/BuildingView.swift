// Step 2 · Meta AI builds the guide: the server's job stages, live.

import SwiftUI

struct BuildingView: View {
  let flow: CreateFlow

  private var stages: [String: String] { flow.job?.stages ?? ["upload": flow.phase == .uploading ? "running" : "queued"] }
  private var doneCount: Int { stages.values.filter { $0 == "done" }.count }

  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 14) {
        recording
        Eyebrow(text: "Meta AI · Muse Spark")
        Text("Building your guide").font(.largeTitle.bold()).foregroundStyle(Color.ink)
        Text("Watching the video, listening to your narration and reading the text on screen, all with one multimodal model.")
          .font(.callout).foregroundStyle(Color.inkSecondary)
        VStack(spacing: 8) {
          ForEach(CreateFlow.stages, id: \.id) { stage in
            PipelineRow(title: stage.title, detail: stage.detail, state: stages[stage.id] ?? "queued")
          }
        }
        ProgressView(value: Double(doneCount), total: Double(CreateFlow.stages.count)).tint(Color.ai)
        Label("You can close the app. We'll let you know when the guide is ready.", systemImage: "bell")
          .font(.footnote).foregroundStyle(Color.inkSecondary)
      }
      .padding(.horizontal, 16)
      .padding(.vertical, 12)
    }
    .background(Color.canvas)
  }

  private var recording: some View {
    ZStack(alignment: .bottomLeading) {
      Rectangle().fill(Color.black)
        .overlay {
          if let image = flow.thumbnail { Image(uiImage: image).resizable().scaledToFill() }
        }
        .frame(height: 170)
        .clipShape(RoundedRectangle(cornerRadius: 24))
      Text("\(clock(flow.recordedSeconds)) · from your glasses".uppercased())
        .font(.eyebrow).foregroundStyle(.white)
        .padding(.horizontal, 10).padding(.vertical, 6)
        .glassEffect(.regular, in: .capsule)
        .padding(12)
        .environment(\.colorScheme, .dark)
    }
  }
}

struct PipelineRow: View {
  let title: String
  let detail: String
  let state: String  // queued | running | done

  var body: some View {
    HStack(spacing: 12) {
      Group {
        switch state {
        case "done":
          Image(systemName: "checkmark.circle.fill").font(.system(size: 26)).foregroundStyle(Color.ok)
        case "running":
          ProgressView().tint(Color.ai)
        default:
          Circle().strokeBorder(Color.track, lineWidth: 2)
        }
      }
      .frame(width: 26, height: 26)
      VStack(alignment: .leading, spacing: 2) {
        Text(title).font(.subheadline.weight(.semibold))
          .foregroundStyle(state == "queued" ? Color.inkSecondary : Color.ink)
        Text(detail).font(.caption).foregroundStyle(Color.inkSecondary)
      }
      Spacer()
    }
    .padding(.horizontal, 16).padding(.vertical, 14)
    .background(Color.panel, in: RoundedRectangle(cornerRadius: 18))
    .accessibilityElement(children: .combine)
    .accessibilityValue(state)
  }
}
