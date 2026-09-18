"""`PushService` — the one seam an app sends through.

    push = PushService(ApnsClient(cfg), JsonDeviceRegistry(path))
    await push.send(["ryan"], Notification("Timer done", "Pasta"))

Fans a notification out to every device in the given audiences, and forgets
tokens APNs reports as permanently dead so the registry heals itself. With no
provider configured it's a harmless no-op, so an app can wire it in before the
keys exist.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Iterable, Protocol

from .payload import Notification
from .apns import SendResult
from .registry import DeviceRegistry

log = logging.getLogger("notify_kit")


class Provider(Protocol):
    async def send(self, token: str, n: Notification, *, env: str = "production") -> SendResult: ...


class PushService:
    def __init__(self, provider: Provider | None, registry: DeviceRegistry):
        self.provider = provider
        self.registry = registry

    @property
    def configured(self) -> bool:
        return self.provider is not None

    async def send(self, audiences: Iterable[str], n: Notification) -> list[SendResult]:
        if self.provider is None:
            return []
        devices = await self.registry.for_audiences(audiences)
        results = await asyncio.gather(*(self.provider.send(d.token, n, env=d.env) for d in devices))
        for res in results:
            if res.dead:
                log.info("dropping dead push token …%s (%s)", res.token[-6:], res.reason)
                await self.registry.unregister(res.token)
            elif not res.ok:
                log.warning("push to …%s failed: %s %s", res.token[-6:], res.status, res.reason)
        return list(results)
