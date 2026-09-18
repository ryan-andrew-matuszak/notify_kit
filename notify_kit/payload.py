"""The provider-neutral notification + the APNs payload built from it.

`Notification` is what an app hands the kit; each provider turns it into its own
wire shape. Pure and side-effect-free so it's trivially testable.
"""
from __future__ import annotations

from dataclasses import dataclass, field

#: iOS interruption levels, least → most intrusive. `passive` lands silently in
#: Notification Center; `active` is a normal banner; `time-sensitive` breaks
#: through Focus (needs the Time Sensitive entitlement on the app). `critical`
#: needs Apple's approval, so it's deliberately not offered.
LEVELS = ("passive", "active", "time-sensitive")


@dataclass
class Notification:
    title: str
    body: str = ""
    level: str = "active"
    #: Sound name for the device ("default" = the system sound; None = silent).
    sound: str | None = "default"
    #: Same id ⇒ the new notification REPLACES the old one on the device instead
    #: of stacking (APNs `apns-collapse-id`, ≤64 bytes). The anti-fatigue lever.
    collapse_id: str | None = None
    #: Groups notifications in Notification Center.
    thread_id: str | None = None
    #: The app-registered UNNotificationCategory id (action buttons).
    category: str | None = None
    badge: int | None = None
    #: How long APNs should keep retrying an offline device (seconds). None =
    #: deliver once or drop (APNs `apns-expiration: 0`).
    ttl: int | None = 3600
    #: Custom keys delivered alongside `aps` (e.g. {"deeplink": "app://feed"}).
    data: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.level not in LEVELS:
            raise ValueError(f"level must be one of {LEVELS}, got {self.level!r}")


def apns_payload(n: Notification) -> dict:
    """The JSON body APNs expects for an alert push."""
    alert = {"title": n.title}
    if n.body:
        alert["body"] = n.body
    aps: dict = {"alert": alert, "interruption-level": n.level}
    if n.sound:
        aps["sound"] = n.sound
    if n.thread_id:
        aps["thread-id"] = n.thread_id
    if n.category:
        aps["category"] = n.category
    if n.badge is not None:
        aps["badge"] = n.badge
    return {**n.data, "aps": aps}
