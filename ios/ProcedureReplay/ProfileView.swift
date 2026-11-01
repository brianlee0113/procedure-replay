// Someone else's profile, opened by tapping an author's name or avatar (Figma "Flow — social profiles").
// It shows only their public guides; their saved and liked guides stay private, so GET /users/{id} never sends them.

import SwiftUI

struct ProfileView: View {
  let userId: String

  @State private var user: UserProfile?
  @State private var error: String?
  @State private var opened: GuideCard?
  @Environment(\.dismiss) private var dismiss
  @Environment(\.slideBack) private var slideBack

  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 16) {
        if let user {
          ProfileHeader(name: user.name, role: user.role, profile: user.profile)
          VStack(spacing: 8) {
            Text("Guides \(user.guides.count)").font(.subheadline.weight(.semibold)).foregroundStyle(Color.ink)
            Rectangle().fill(Color.ink).frame(height: 2)
          }
          .padding(.top, 4)
          Label("\(firstName(user.name))'s saved and liked guides are private.", systemImage: "lock")
            .font(.caption).foregroundStyle(Color.inkSecondary)
          if user.guides.isEmpty {
            Text("No public guides yet.").font(.callout).foregroundStyle(Color.inkSecondary)
          } else {
            CoverGrid(cards: user.guides, showsStatus: false) { card in withoutAnimation { opened = card } }
          }
        } else if let error {
          StateMessage(symbol: "person.crop.circle.badge.exclamationmark", title: "Couldn't open this profile",
                       message: error, actionTitle: "Try again") { Task { await load() } }
        } else {
          ProgressView().frame(maxWidth: .infinity).padding(.top, 60)
        }
      }
      .padding(.horizontal, 16)
      .padding(.top, 8)
      .padding(.bottom, 40)
    }
    .safeAreaInset(edge: .top, spacing: 0) { navBar }
    .background(Color.canvas)
    .refreshable { await load() }
    .task { if user == nil { await load() } }
    .fullScreenCover(item: $opened) { card in
      NavigationStack { GuideView(model: GuideModel(guideId: card.guideId)) }.edgeSwipeBack()
    }
    .onChange(of: opened) { if opened == nil { Task { await load() } } }  // likes may have changed
  }

  private var navBar: some View {
    ZStack {
      Text(user?.name ?? "").font(.headline).foregroundStyle(Color.ink)
      HStack {
        Button { if let slideBack { slideBack() } else { dismiss() } } label: {
          Image(systemName: "chevron.left").font(.system(size: 17, weight: .semibold)).frame(width: 44, height: 44)
        }
        .glassEffect(.regular.interactive(), in: .circle)
        .foregroundStyle(Color.ink)
        .accessibilityLabel("Back")
        Spacer()
      }
    }
    .padding(.horizontal, 16)
    .padding(.vertical, 6)
    .background(Color.canvas)
  }

  private func firstName(_ name: String) -> String { name.split(separator: " ").first.map(String.init) ?? name }

  private func load() async {
    do {
      user = try await API.user(userId)
      error = nil
    } catch {
      self.error = error.localizedDescription
    }
  }
}
