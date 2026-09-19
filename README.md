# notify_kit

Reusable push notifications for small self-hosted apps — **one contract, two
packages** in one repo:

| Half | Where | Does |
|---|---|---|
| Server (Python) | `notify_kit/` | APNs client (.p8 token auth, HTTP/2), device registry, `PushService` fan-out that prunes dead tokens |
| Client (Swift)  | `Sources/NotifyKit/` | permission prompt, APNs token → your server, sandbox/production detection, tap routing |

The kit knows nothing about *your* domain. The app decides **who** a
notification is for (an *audience* — a user id, a profile, "household"…) and
**when**; the kit gets it onto the right phones.

## The contract

The client registers each install against an audience:

```
POST   <registerURL>           {"token": "<hex>", "env": "sandbox|production", "label": "Ryan's iPhone"}
DELETE <registerURL>/<token>
```

The audience rides along in whatever headers you configure (e.g. `X-Profile: ryan`)
and the server maps it. Tokens from Xcode dev builds only work against APNs
**sandbox**; TestFlight/App Store tokens only against **production** — the client
reports which, and the server sends to the matching host.

## Server (Python)

```bash
pip install "notify_kit[apns] @ https://github.com/ryan-andrew-matuszak/notify_kit/archive/refs/heads/main.tar.gz"
```

```python
from notify_kit import ApnsClient, ApnsConfig, JsonDeviceRegistry, Notification, PushService

push = PushService(
    ApnsClient(ApnsConfig(team_id="…", key_id="…", topic="com.you.app", key_path="~/AuthKey.p8")),
    JsonDeviceRegistry("push_devices.json"),
)
await push.registry.register(token, "ryan", env="sandbox")          # from your POST route
await push.send(["ryan"], Notification("Timer done", "Pasta",
                                       level="time-sensitive", collapse_id="timer:t1"))
```

`Notification.level` is the iOS interruption level: `passive` (silent, Notification
Center only), `active` (normal), `time-sensitive` (breaks through Focus — the app
needs the Time Sensitive Notifications capability). `collapse_id` makes a newer
push *replace* an older one on the device instead of stacking — use it.

With no provider (`PushService(None, registry)`) sends are a no-op, so you can
wire it in before the keys exist.

## Client (Swift)

Add the package (this repo URL) in Xcode / XcodeGen, then:

```swift
@UIApplicationDelegateAdaptor(NotifyAppDelegate.self) var delegate

NotifyKit.shared.configure(.init(registerURL: hub.appending(path: "api/notify/devices"),
                                 headers: { ["X-Profile": profile] }))
NotifyKit.shared.onOpen = { info in route(info["deeplink"]) }
await NotifyKit.shared.requestAuthorizationAndRegister()
```

Action buttons: register categories once, then handle taps —

```swift
NotifyKit.shared.setCategories([UNNotificationCategory(identifier: "timer",
    actions: [UNNotificationAction(identifier: "SNOOZE_5", title: "Snooze 5 min")],
    intentIdentifiers: [])])
NotifyKit.shared.onAction = { action, info in /* call your server */ }
```

and send with `Notification(..., category="timer")`.

The app target needs the **Push Notifications** capability (and **Time Sensitive
Notifications** if you use that level).

## Apple setup (once per team)

1. developer.apple.com ▸ Keys ▸ **+** ▸ enable *Apple Push Notifications service* →
   download the `.p8` (one download only), note the **Key ID** and **Team ID**.
   One key serves every app on the team.
2. Enable *Push Notifications* on each app's identifier (automatic signing usually
   does this for you).
3. Keep the `.p8` on the server only — never in git (`*.p8` is gitignored here).

## Tests

```bash
pip install -e ".[test]" && python -m pytest -q                              # Python, offline (MockTransport)
xcodebuild -scheme NotifyKit -destination 'platform=iOS Simulator,name=iPhone 17' test
```
