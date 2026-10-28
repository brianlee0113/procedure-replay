// Step 4 · Publish: Meta AI's title, category and description are filled in; the instructor picks who can see it.

import SwiftUI

struct PublishView: View {
  let flow: CreateFlow

  @State private var title = ""
  @State private var summary = ""
  @State private var category = ""
  @State private var visibility = "public"
  @State private var categories: [(id: String, label: String)] = []
  @State private var publishing = false
  @State private var error: String?

  private var guide: Guide? { flow.guide?.guide }

  var body: some View {
    if let guide {
      ZStack(alignment: .bottom) {
        ScrollView {
          VStack(alignment: .leading, spacing: 18) {
            cover(guide)
            SuggestedField(label: "Title", text: $title, suggested: guide.title)
            VStack(alignment: .leading, spacing: 8) {
              HStack {
                Text("Category").font(.caption).foregroundStyle(Color.inkSecondary)
                Spacer()
                AIBadge(text: category == guide.category ? "AI suggested" : "Changed")
              }
              FlowLayout(spacing: 8) {
                ForEach(categories, id: \.id) { c in
                  CategoryChip(label: c.label, selected: c.id == category, suggested: c.id == guide.category) {
                    category = c.id
                  }
                }
              }
            }
            SuggestedField(label: "Description", text: $summary, suggested: guide.summary, multiline: true)
            VStack(alignment: .leading, spacing: 8) {
              Text("Who can see this").font(.caption).foregroundStyle(Color.inkSecondary)
              Picker("Who can see this", selection: $visibility) {
                Label("Public", systemImage: "globe").tag("public")
                Label("Private", systemImage: "lock").tag("private")
              }
              .pickerStyle(.segmented)
              Text(visibility == "public"
                   ? "Public guides appear in the Feed, where anyone can watch, like and save them."
                   : "Private guides stay out of the Feed. Only people you share the link with can open them.")
                .font(.caption).foregroundStyle(Color.inkSecondary)
            }
            if let error { Text(error).font(.footnote).foregroundStyle(Color.live) }
          }
          .padding(.horizontal, 16)
          .padding(.top, 8)
          .padding(.bottom, 110)
        }
        Button { Task { await submit() } } label: {
          Text(publishing ? "Publishing…" : "Publish guide").font(.headline).frame(maxWidth: .infinity).padding(.vertical, 6)
        }
        .buttonStyle(.glassProminent)
        .tint(Color.ink)
        .disabled(publishing || title.trimmingCharacters(in: .whitespaces).isEmpty || category.isEmpty)
        .padding(.horizontal, 16)
        .padding(.bottom, 8)
      }
      .background(Color.canvas)
      .navigationTitle("Publish")
      .navigationBarTitleDisplayMode(.inline)
      .task {
        if title.isEmpty {
          title = guide.title
          summary = guide.summary
          category = guide.category
        }
        if categories.isEmpty { categories = (try? await API.categories()) ?? [] }
      }
    }
  }

  private func cover(_ guide: Guide) -> some View {
    let step = guide.steps[guide.steps.count / 2]  // the server's guide cover is the middle step's frame
    return HStack(spacing: 12) {
      AsyncImage(url: API.url("/guides/\(guide.guideId)/cover.jpg")) { $0.resizable().scaledToFill() } placeholder: {
        Color.track
      }
      .frame(width: 84, height: 84)
      .clipShape(RoundedRectangle(cornerRadius: 18))
      VStack(alignment: .leading, spacing: 4) {
        Text("Cover").font(.caption).foregroundStyle(Color.inkSecondary)
        Text("Frame from step \(step.index), \(step.title)").font(.subheadline.weight(.semibold)).foregroundStyle(Color.ink)
      }
    }
  }

  private func submit() async {
    publishing = true
    defer { publishing = false }
    do {
      try await flow.publish(PublishRequest(visibility: visibility, title: title, summary: summary, category: category))
    } catch {
      self.error = "Couldn't publish: \(error.localizedDescription)"
    }
  }
}

/// A text field that shows "AI suggested" until the instructor changes Meta AI's value.
struct SuggestedField: View {
  let label: String
  @Binding var text: String
  let suggested: String
  var multiline = false

  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      HStack {
        Text(label).font(.caption).foregroundStyle(Color.inkSecondary)
        Spacer()
        AIBadge(text: text == suggested ? "AI suggested" : "Edited")
      }
      Group {
        if multiline {
          TextField(label, text: $text, axis: .vertical).lineLimit(3...6)
        } else {
          TextField(label, text: $text)
        }
      }
      .font(.body)
      .padding(.horizontal, 16).padding(.vertical, 14)
      .background(Color.panel, in: RoundedRectangle(cornerRadius: 16))
      .overlay(RoundedRectangle(cornerRadius: 16).strokeBorder(text == suggested ? Color.ai : Color.track, lineWidth: 1))
    }
  }
}

struct CategoryChip: View {
  let label: String
  let selected: Bool
  var suggested = false
  let action: () -> Void

  var body: some View {
    Button(action: action) {
      HStack(spacing: 5) {
        if suggested { Image(systemName: "sparkles").font(.caption2) }
        Text(label).font(.footnote.weight(.medium))
      }
      .foregroundStyle(selected ? Color.white : Color.ink)
      .padding(.horizontal, 12).padding(.vertical, 8)
      .background(selected ? Color.ink : Color.panel, in: .capsule)
      .overlay(Capsule().strokeBorder(suggested && !selected ? Color.ai : Color.track, lineWidth: 1))
    }
    .buttonStyle(.plain)
    .accessibilityAddTraits(selected ? .isSelected : [])
  }
}

/// Lays children left to right and wraps to new rows (category chips).
struct FlowLayout: Layout {
  var spacing: CGFloat = 8

  func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
    let maxWidth = proposal.width ?? .infinity
    var x: CGFloat = 0, y: CGFloat = 0, rowHeight: CGFloat = 0, width: CGFloat = 0
    for s in subviews {
      let size = s.sizeThatFits(.unspecified)
      if x + size.width > maxWidth, x > 0 {
        x = 0
        y += rowHeight + spacing
        rowHeight = 0
      }
      x += size.width + spacing
      rowHeight = max(rowHeight, size.height)
      width = max(width, x - spacing)
    }
    return CGSize(width: proposal.width ?? width, height: y + rowHeight)
  }

  func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
    var x = bounds.minX, y = bounds.minY, rowHeight: CGFloat = 0
    for s in subviews {
      let size = s.sizeThatFits(.unspecified)
      if x + size.width > bounds.maxX, x > bounds.minX {
        x = bounds.minX
        y += rowHeight + spacing
        rowHeight = 0
      }
      s.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
      x += size.width + spacing
      rowHeight = max(rowHeight, size.height)
    }
  }
}
