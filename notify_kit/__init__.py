"""notify_kit — reusable push notifications for small self-hosted apps.

Python half of a two-part contract (the Swift half lives in Sources/NotifyKit):
the app registers device tokens against an *audience*, and the server sends a
provider-neutral `Notification` to audiences through `PushService`.
"""
from .apns import ApnsClient, ApnsConfig, SendResult, make_jwt
from .payload import LEVELS, Notification, apns_payload
from .registry import Device, DeviceRegistry, JsonDeviceRegistry
from .service import Provider, PushService

__version__ = "0.2.0"

__all__ = ["ApnsClient", "ApnsConfig", "Device", "DeviceRegistry", "JsonDeviceRegistry",
           "LEVELS", "Notification", "Provider", "PushService", "SendResult",
           "apns_payload", "make_jwt", "__version__"]
