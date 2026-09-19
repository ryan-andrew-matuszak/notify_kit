import Foundation
import UIKit
import UserNotifications

/// The client half of notify_kit: ask permission, register the APNs token with
/// your server, and route taps. The server half (Python) decides who gets what.
///
/// Wire-up (SwiftUI):
///
///     @UIApplicationDelegateAdaptor(NotifyAppDelegate.self) var delegate
///     …
///     NotifyKit.shared.configure(.init(
///         registerURL: URL(string: "http://hub:8000/api/notify/devices")!,
///         headers: { ["X-Profile": "ryan"] }))
///     NotifyKit.shared.onOpen = { info in /* route info["deeplink"] */ }
///     await NotifyKit.shared.requestAuthorizationAndRegister()
///
/// If your app already has an app delegate, skip `NotifyAppDelegate` and forward
/// `didRegisterForRemoteNotificationsWithDeviceToken` to `didRegister(deviceToken:)`.
///
/// Server contract — `POST registerURL` with JSON `{token, env, label}` (env is
/// "sandbox" for Xcode dev builds, "production" for TestFlight/App Store), and
/// `DELETE registerURL/{token}` to unregister. Any `headers()` you supply ride
/// along (that's how the server knows the audience).
@MainActor
public final class NotifyKit: NSObject, ObservableObject {
    public static let shared = NotifyKit()

    public struct Config {
        public var registerURL: URL
        public var headers: () -> [String: String]
        public init(registerURL: URL, headers: @escaping () -> [String: String] = { [:] }) {
            self.registerURL = registerURL
            self.headers = headers
        }
    }

    @Published public private(set) var authorization: UNAuthorizationStatus = .notDetermined
    @Published public private(set) var token: String?
    @Published public private(set) var lastError: String?

    /// Called when the user taps a notification, with its custom string keys
    /// (everything the server put beside `aps`, e.g. `["deeplink": "…"]`).
    public var onOpen: (([String: String]) -> Void)?
    /// Called for a notification arriving while the app is in the foreground —
    /// e.g. to refresh an in-app feed. Return the presentation you want.
    public var onForeground: (([String: String]) -> UNNotificationPresentationOptions)?
    /// Called when the user taps one of a notification's action buttons (not the
    /// notification itself), with the action id and the payload's string keys.
    /// Runs in the background for non-foreground actions — iOS waits for it.
    public var onAction: ((String, [String: String]) async -> Void)?

    /// Register the notification categories (action buttons) this app knows.
    /// The server picks one per push (`Notification.category` / `aps.category`).
    public func setCategories(_ categories: Set<UNNotificationCategory>) {
        UNUserNotificationCenter.current().setNotificationCategories(categories)
    }

    private var config: Config?

    public func configure(_ config: Config) {
        self.config = config
        UNUserNotificationCenter.current().delegate = self
        Task { await refreshAuthorization() }
    }

    /// Prompts once (iOS only ever shows the system prompt a single time), then
    /// registers with APNs. Safe to call on every launch — re-registering is how
    /// a rotated token or a changed audience reaches the server.
    @discardableResult
    public func requestAuthorizationAndRegister(
        options: UNAuthorizationOptions = [.alert, .sound, .badge]
    ) async -> Bool {
        let granted = (try? await UNUserNotificationCenter.current().requestAuthorization(options: options)) ?? false
        await refreshAuthorization()
        if granted { UIApplication.shared.registerForRemoteNotifications() }
        return granted
    }

    public func refreshAuthorization() async {
        authorization = await UNUserNotificationCenter.current().notificationSettings().authorizationStatus
    }

    /// Forward the app delegate's device token here.
    public func didRegister(deviceToken: Data) {
        let hex = deviceToken.map { String(format: "%02x", $0) }.joined()
        token = hex
        Task { await upload(hex) }
    }

    public func didFailToRegister(_ error: Error) {
        lastError = error.localizedDescription
    }

    /// Re-send the current token (e.g. after the audience/profile changes).
    public func reregister() async {
        if let token { await upload(token) }
    }

    public func unregister() async {
        guard let config, let token else { return }
        var req = URLRequest(url: config.registerURL.appendingPathComponent(token))
        req.httpMethod = "DELETE"
        config.headers().forEach { req.setValue($1, forHTTPHeaderField: $0) }
        _ = try? await URLSession.shared.data(for: req)
    }

    private func upload(_ token: String) async {
        guard let config else { return }
        var req = URLRequest(url: config.registerURL)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        config.headers().forEach { req.setValue($1, forHTTPHeaderField: $0) }
        req.httpBody = try? JSONSerialization.data(withJSONObject: [
            "token": token, "env": APSEnvironment.current.rawValue, "label": UIDevice.current.name,
        ])
        do {
            let (_, resp) = try await URLSession.shared.data(for: req)
            let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
            lastError = (200..<300).contains(code) ? nil : "register failed (HTTP \(code))"
        } catch {
            lastError = error.localizedDescription
        }
    }
}

extension NotifyKit: UNUserNotificationCenterDelegate {
    nonisolated public func userNotificationCenter(
        _ center: UNUserNotificationCenter, willPresent notification: UNNotification
    ) async -> UNNotificationPresentationOptions {
        let info = Self.stringKeys(notification.request.content.userInfo)
        return await MainActor.run { onForeground?(info) ?? [.banner, .list, .sound] }
    }

    nonisolated public func userNotificationCenter(
        _ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse
    ) async {
        let info = Self.stringKeys(response.notification.request.content.userInfo)
        let action = response.actionIdentifier
        if action == UNNotificationDefaultActionIdentifier {
            await MainActor.run { onOpen?(info) }
        } else if action != UNNotificationDismissActionIdentifier {
            let handler = await MainActor.run { onAction }
            await handler?(action, info)
        }
    }

    /// The custom, string-valued payload keys (Sendable, unlike `userInfo`).
    nonisolated static func stringKeys(_ info: [AnyHashable: Any]) -> [String: String] {
        var out: [String: String] = [:]
        for (k, v) in info { if let k = k as? String, k != "aps", let v = v as? String { out[k] = v } }
        return out
    }
}

/// Drop-in app delegate for SwiftUI apps that don't have one of their own.
open class NotifyAppDelegate: NSObject, UIApplicationDelegate {
    open func application(_ application: UIApplication,
                          didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        Task { @MainActor in NotifyKit.shared.didRegister(deviceToken: deviceToken) }
    }

    open func application(_ application: UIApplication,
                          didFailToRegisterForRemoteNotificationsWithError error: Error) {
        Task { @MainActor in NotifyKit.shared.didFailToRegister(error) }
    }
}
