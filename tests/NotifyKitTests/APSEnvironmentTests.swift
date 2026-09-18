import XCTest
@testable import NotifyKit

final class APSEnvironmentTests: XCTestCase {
    private func profile(_ env: String?) -> Data {
        let ent = env.map { "<key>aps-environment</key><string>\($0)</string>" } ?? ""
        let plist = """
        <?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict>\
        <key>Entitlements</key><dict>\(ent)</dict></dict></plist>
        """
        // Mimic the binary CMS envelope around the plist.
        return Data([0x30, 0x82, 0x00, 0xff]) + Data(plist.utf8) + Data([0x00, 0xa0])
    }

    func testDevelopmentIsSandbox() {
        XCTAssertEqual(APSEnvironment.parse(profile: profile("development")), .sandbox)
    }

    func testProductionAndMissing() {
        XCTAssertEqual(APSEnvironment.parse(profile: profile("production")), .production)
        XCTAssertEqual(APSEnvironment.parse(profile: profile(nil)), .production)
        XCTAssertEqual(APSEnvironment.parse(profile: Data()), .production)
    }
}

final class PayloadKeysTests: XCTestCase {
    func testStringKeysDropsApsAndNonStrings() {
        let info: [AnyHashable: Any] = ["aps": ["alert": "x"], "deeplink": "app://feed", "n": 3]
        XCTAssertEqual(NotifyKit.stringKeys(info), ["deeplink": "app://feed"])
    }
}
