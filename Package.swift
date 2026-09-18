// swift-tools-version:5.9
// The Swift (client) half of notify_kit. The Python (server) half lives in
// notify_kit/ in this same repo — one contract, two packages.
import PackageDescription

let package = Package(
    name: "NotifyKit",
    platforms: [.iOS(.v16)],
    products: [.library(name: "NotifyKit", targets: ["NotifyKit"])],
    targets: [
        .target(name: "NotifyKit", path: "Sources/NotifyKit"),
        .testTarget(name: "NotifyKitTests", dependencies: ["NotifyKit"], path: "tests/NotifyKitTests"),
    ]
)
