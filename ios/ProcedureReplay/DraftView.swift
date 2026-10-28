// Step 2 · Draft: the instructor checks what Meta AI made and fixes a step's words or where it starts and ends.

import SwiftUI

struct DraftView: View {
  let flow: CreateFlow
  let close: () -> Void
  @State private var editing: GuideStep?
  @State private var previewing = false

  var body: some View {
    if let response = flow.guide {
      let guide = response.guide
      ZStack(alignment: .bottom) {
        ScrollView {
          VStack(alignment: .leading, spacing: 12) {
            AIBadge(text: "Made by Meta AI from \(clock(guide.durationS)) of video")
            Text(guide.title).font(.title.bold()).foregroundStyle(Color.ink)
            Text(guide.summary).font(.callout).foregroundStyle(Color.inkSecondary)
            HStack(spacing: 6) {
              MetaChip(systemImage: "list.bullet", text: "\(guide.steps.count) steps")
              MetaChip(systemImage: "clock", text: clock(guide.durationS))
              if !guide.tools.isEmpty {
                MetaChip(systemImage: "wrench.and.screwdriver", text: guide.tools.joined(separator: ", ").capitalizedFirst)
              }
            }
            HStack {
              Text("Steps").font(.headline)
              Spacer()
              Text("Tap to edit or re-cut").font(.caption).foregroundStyle(Color.inkSecondary)
            }
            .padding(.top, 6)
            ForEach(guide.steps) { step in
              Button { editing = step } label: { StepRow(step: step) }.buttonStyle(.plain)
            }
          }
          .padding(.horizontal, 16)
          .padding(.top, 8)
          .padding(.bottom, 110)
        }
        Button { flow.showPublish = true } label: {
          Text("Next: publish settings").font(.headline).frame(maxWidth: .infinity).padding(.vertical, 6)
        }
        .buttonStyle(.glassProminent)
        .tint(Color.ink)
        .padding(.horizontal, 16)
        .padding(.bottom, 8)
      }
      .navigationDestination(isPresented: Binding(get: { flow.showPublish }, set: { flow.showPublish = $0 })) {
        PublishView(flow: flow)
      }
      .background(Color.canvas)
      .toolbar {
        ToolbarItem(placement: .topBarLeading) {
          Button { close() } label: { Image(systemName: "xmark") }.accessibilityLabel("Close")
        }
        ToolbarItem(placement: .principal) { Text("Draft").font(.headline) }
        ToolbarItem(placement: .topBarTrailing) {
          Button("Preview") { previewing = true }.accessibilityHint("See the guide as a trainee will")
        }
      }
      .navigationBarTitleDisplayMode(.inline)
      .fullScreenCover(isPresented: $previewing) {
        NavigationStack { GuideView(model: GuideModel(guideId: guide.guideId)) }
      }
      .sheet(item: $editing) { step in
        StepEditSheet(step: step, duration: guide.durationS) { edit in
          try await flow.save(edit, step: step.index)
        }
      }
    }
  }
}

struct StepRow: View {
  let step: GuideStep
  var eyebrow: String?
  var trailing = "chevron.right"

  var body: some View {
    HStack(spacing: 12) {
      AsyncImage(url: step.coverUrl.map(API.url)) { image in
        image.resizable().scaledToFill()
      } placeholder: {
        Color.track
      }
      .frame(width: 76, height: 64)
      .clipShape(RoundedRectangle(cornerRadius: 14))
      VStack(alignment: .leading, spacing: 3) {
        Eyebrow(text: eyebrow ?? "Step \(step.index) · \(clock(step.startS)) – \(clock(step.endS))")
        Text(step.title).font(.subheadline.weight(.semibold)).foregroundStyle(Color.ink)
        Text(step.instruction).font(.caption).foregroundStyle(Color.inkSecondary).lineLimit(2)
      }
      Spacer(minLength: 0)
      Image(systemName: trailing).font(.caption.weight(.semibold)).foregroundStyle(Color.inkSecondary)
    }
    .padding(10)
    .background(Color.panel, in: RoundedRectangle(cornerRadius: 20))
    .contentShape(Rectangle())
  }
}

struct StepEditSheet: View {
  let step: GuideStep
  let duration: Double
  let save: (StepEdit) async throws -> Void

  @Environment(\.dismiss) private var dismiss
  @State private var title = ""
  @State private var instruction = ""
  @State private var doneWhen = ""
  @State private var start = 0.0
  @State private var end = 0.0
  @State private var saving = false
  @State private var error: String?

  var body: some View {
    NavigationStack {
      Form {
        Section("Step \(step.index)") {
          TextField("Title", text: $title)
          TextField("Instruction", text: $instruction, axis: .vertical).lineLimit(2...5)
        }
        Section("Done when") {
          TextField("Done when", text: $doneWhen, axis: .vertical).lineLimit(1...3)
        }
        Section {
          Stepper("Starts at \(clockTenths(start))", value: $start, in: 0...max(0, end - 0.5), step: 0.5)
          Stepper("Ends at \(clockTenths(end))", value: $end, in: (start + 0.5)...duration, step: 0.5)
        } header: {
          Text("Re-cut the clip")
        } footer: {
          Text("The looping clip follows these times, plus one second on each side.")
        }
        if let error {
          Section { Text(error).foregroundStyle(Color.live) }
        }
      }
      .navigationTitle("Edit step")
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
        ToolbarItem(placement: .confirmationAction) {
          Button("Save") { Task { await submit() } }.disabled(saving || title.isEmpty)
        }
      }
    }
    .onAppear {
      title = step.title
      instruction = step.instruction
      doneWhen = step.doneWhen
      start = step.startS
      end = step.endS
    }
  }

  private func submit() async {
    saving = true
    defer { saving = false }
    var edit = StepEdit()
    if title != step.title { edit.title = title }
    if instruction != step.instruction { edit.instruction = instruction }
    if doneWhen != step.doneWhen { edit.doneWhen = doneWhen }
    if start != step.startS || end != step.endS {
      edit.startS = start
      edit.endS = end
    }
    do {
      try await save(edit)
      dismiss()
    } catch {
      // The server refuses a re-cut that overlaps a neighbouring step.
      self.error = "Couldn't save: \(error.localizedDescription)"
    }
  }

  private func clockTenths(_ s: Double) -> String {
    String(format: "%d:%04.1f", Int(s) / 60, s.truncatingRemainder(dividingBy: 60))
  }
}

extension String {
  var capitalizedFirst: String { prefix(1).uppercased() + dropFirst() }
}
