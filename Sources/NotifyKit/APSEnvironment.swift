import Foundation

/// Which APNs host this build's tokens belong to. A token minted by a dev build
/// only works against the sandbox; TestFlight/App Store tokens only against
/// production — so the server must be told, per device.
///
/// Read from the embedded provisioning profile's `aps-environment` entitlement.
/// App Store / TestFlight builds carry no embedded profile → production.
public enum APSEnvironment: String {
    case sandbox, production

    public static let current: APSEnvironment = {
        guard let url = Bundle.main.url(forResource: "embedded", withExtension: "mobileprovision"),
              let data = try? Data(contentsOf: url) else { return .production }
        return parse(profile: data)
    }()

    /// The profile is a CMS envelope around a plist; the plist is plain text
    /// inside it, so slicing out `<plist>…</plist>` is enough.
    static func parse(profile data: Data) -> APSEnvironment {
        guard let text = String(data: data, encoding: .isoLatin1),
              let start = text.range(of: "<plist"), let end = text.range(of: "</plist>"),
              let plist = try? PropertyListSerialization.propertyList(
                  from: Data(text[start.lowerBound..<end.upperBound].utf8), format: nil) as? [String: Any],
              let ents = plist["Entitlements"] as? [String: Any],
              let env = ents["aps-environment"] as? String
        else { return .production }
        return env == "development" ? .sandbox : .production
    }
}
