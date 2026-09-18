# notify_kit — working notes

Reusable push notifications. Python server half (`notify_kit/`) + Swift client
half (`Sources/NotifyKit/`) of ONE contract, in one repo (pyproject + Package.swift
both at the root so pip and SwiftPM each install straight from the GitHub URL).

## Non-negotiables
- **Domain-free.** The kit knows audiences (opaque strings) and `Notification`s.
  Routing, categories, quiet hours, feeds — all belong to the app, not here.
- **Core stays `httpx`-only;** APNs deps (`cryptography`, `h2`) are the `apns` extra.
- **Never raise into the app from a send.** Failures come back as `SendResult`s;
  dead tokens (410 / BadDeviceToken / DeviceTokenNotForTopic) are pruned by
  `PushService`.
- **Contract changes touch both halves + the README contract section together.**
- A new provider (SNS/FCM/ntfy) = a class with `send(token, n, env=) -> SendResult`.
- Public repo: no keys, tokens, or personal data. `*.p8` is gitignored.

## Tests
`python -m pytest -q` (offline, httpx.MockTransport) and
`xcodebuild -scheme NotifyKit -destination 'platform=iOS Simulator,name=iPhone 17' test`.
