// Colors and shapes from the Figma file "Final — App (glass)" (Glass (A) collection, Light mode).
// Floating controls use the system Liquid Glass (`glassEffect`); content panels use regular material.

import SwiftUI

extension Color {
  static let canvas = Color(red: 0.95, green: 0.95, blue: 0.96)
  static let ink = Color(red: 0.04, green: 0.05, blue: 0.06)
  static let inkSecondary = Color(red: 0.04, green: 0.05, blue: 0.06).opacity(0.62)
  static let ai = Color(red: 0.16, green: 0.38, blue: 1.0)
  static let live = Color(red: 0.91, green: 0.10, blue: 0.25)
  static let ok = Color(red: 0.07, green: 0.63, blue: 0.31)
  static let track = Color.black.opacity(0.08)
  /// Content panels (step rows, pipeline rows): solid, so text stays readable over any backdrop.
  static let panel = Color.white.opacity(0.78)
}

extension Font {
  static let eyebrow = Font.system(size: 11, weight: .medium, design: .monospaced)
}

/// Uppercase monospaced label, as used for "STEP 3 · 1:48 – 3:03" and "META AI · MUSE SPARK".
struct Eyebrow: View {
  let text: String
  var color: Color = .ai

  var body: some View {
    Text(text.uppercased()).font(.eyebrow).tracking(0.6).foregroundStyle(color)
  }
}

/// Sparkle + label, shown wherever a value was written or suggested by Meta AI.
struct AIBadge: View {
  let text: String

  var body: some View {
    Label { Eyebrow(text: text) } icon: {
      Image(systemName: "sparkles").font(.system(size: 11, weight: .semibold)).foregroundStyle(Color.ai)
    }
    .labelStyle(.titleAndIcon)
  }
}

/// Small rounded chip with an icon: "9 steps", "8 min", "Screwdriver, cloth".
struct MetaChip: View {
  let systemImage: String
  let text: String

  var body: some View {
    Label(text, systemImage: systemImage)
      .font(.footnote)
      .foregroundStyle(Color.ink)
      .padding(.horizontal, 10).padding(.vertical, 6)
      .glassEffect(.regular, in: .capsule)
  }
}

func clock(_ seconds: Double) -> String {
  let s = max(0, Int(seconds.rounded()))
  return String(format: "%d:%02d", s / 60, s % 60)
}
