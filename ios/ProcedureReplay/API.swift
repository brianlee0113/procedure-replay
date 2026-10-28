// Client for the Mac server (src/pr/server.py). Guide fields follow contract v1 (docs/B0_guide_eval_plan.md §2).
// Server URL and user come from the launch environment: PR_SERVER (default http://localhost:8000), PR_USER.

import Foundation

enum API {
  static let base = URL(string: ProcessInfo.processInfo.environment["PR_SERVER"] ?? "http://localhost:8000")!
  static let user = ProcessInfo.processInfo.environment["PR_USER"] ?? "luis"
  static let userName = ProcessInfo.processInfo.environment["PR_USER_NAME"] ?? "Luis Ortega"

  /// Absolute URL for a server path such as `/guides/x/cover.jpg`; images can't send headers, so add ?user=.
  static func url(_ path: String) -> URL {
    var c = URLComponents(url: base.appendingPathComponent(path), resolvingAgainstBaseURL: false)!
    c.queryItems = [URLQueryItem(name: "user", value: user)]
    return c.url!
  }

  private static let decoder: JSONDecoder = {
    let d = JSONDecoder()
    d.keyDecodingStrategy = .convertFromSnakeCase
    return d
  }()

  private static func request(_ path: String, method: String = "GET") -> URLRequest {
    var r = URLRequest(url: base.appendingPathComponent(path))
    r.httpMethod = method
    r.setValue(user, forHTTPHeaderField: "X-User")
    return r
  }

  private static func send<T: Decodable>(_ r: URLRequest, as: T.Type = T.self) async throws -> T {
    let (data, response) = try await URLSession.shared.data(for: r)
    guard let http = response as? HTTPURLResponse else { throw APIError(message: "No response from the server") }
    guard (200..<300).contains(http.statusCode) else {
      let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"]
      throw APIError(message: "\(http.statusCode): \(detail.map { "\($0)" } ?? "request failed")")
    }
    return try decoder.decode(T.self, from: data)
  }

  /// Upload a recording. `sourceVideoId` is the licensed video fed to the mock glasses, so the upload inherits
  /// its license at the server's license gate.
  static func uploadRecording(file: URL, task: String, sourceVideoId: String, marks: [Double]) async throws -> Job {
    let boundary = "pr-\(UUID().uuidString)"
    var r = request("recordings", method: "POST")
    r.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
    var body = Data()
    func field(_ name: String, _ value: String) {
      body.append("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(name)\"\r\n\r\n\(value)\r\n".data(using: .utf8)!)
    }
    field("task", task)
    field("source_video_id", sourceVideoId)
    field("author_name", userName)
    field("marks", "[" + marks.map { String(format: "%.2f", $0) }.joined(separator: ",") + "]")
    body.append("--\(boundary)\r\nContent-Disposition: form-data; name=\"video\"; filename=\"recording.mp4\"\r\nContent-Type: video/mp4\r\n\r\n".data(using: .utf8)!)
    body.append(try Data(contentsOf: file))
    body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
    r.httpBody = body
    return try await send(r)
  }

  static func job(_ id: String) async throws -> Job { try await send(request("jobs/\(id)")) }

  static func guide(_ id: String) async throws -> GuideResponse { try await send(request("guides/\(id)")) }

  static func editStep(guideId: String, index: Int, _ edit: StepEdit) async throws -> GuideStep {
    var r = request("guides/\(guideId)/steps/\(index)", method: "PATCH")
    r.setValue("application/json", forHTTPHeaderField: "Content-Type")
    r.httpBody = try JSONEncoder().encode(edit)
    return try await send(r)
  }
}

struct APIError: LocalizedError {
  let message: String
  var errorDescription: String? { message }
}

struct Job: Decodable {
  let id: String
  let guideId: String
  let status: String  // queued | running | done | error
  let stages: [String: String]  // stage → queued | running | done
  let error: String?
}

struct Clip: Codable, Hashable {
  var startS: Double
  var endS: Double
}

struct Quote: Codable, Hashable {
  let text: String
  let startS: Double
}

struct GuideStep: Codable, Identifiable, Hashable {
  var index: Int
  var title: String
  var instruction: String
  var doneWhen: String
  var startS: Double
  var endS: Double
  var clip: Clip
  var coverS: Double
  var keyObjects: [String]
  var quote: Quote?
  var onScreenText: [String]
  var clipUrl: String?
  var coverUrl: String?

  var id: Int { index }
}

struct Guide: Decodable {
  let guideId: String
  let sourceVideoId: String
  let durationS: Double
  let title: String
  let summary: String
  let category: String
  let tools: [String]
  var steps: [GuideStep]
}

struct GuideMeta: Decodable {
  let author: String
  let authorName: String
  let visibility: String
}

struct GuideResponse: Decodable {
  var guide: Guide
  let meta: GuideMeta
  let categoryLabel: String
}

/// Draft edit: any subset of the step's text, or new bounds (a re-cut).
struct StepEdit: Encodable {
  var title: String?
  var instruction: String?
  var doneWhen: String?
  var startS: Double?
  var endS: Double?

  enum CodingKeys: String, CodingKey {
    case title, instruction
    case doneWhen = "done_when"
    case startS = "start_s"
    case endS = "end_s"
  }
}
