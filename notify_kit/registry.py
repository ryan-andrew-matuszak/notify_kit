"""Which devices exist and who they belong to.

A device registers its push token with an `audience` — whatever the app uses to
target people (a user id, a profile name, "household"…). The kit doesn't care
what audiences mean; the app decides who a notification is for, the registry
answers "which tokens is that?".

`JsonDeviceRegistry` is the zero-infra default: one small JSON file, atomic
writes, an asyncio lock. Anything with the same four methods can stand in.
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Protocol

ENVS = ("production", "sandbox")


@dataclass
class Device:
    token: str
    audience: str
    env: str = "production"   # which APNs host this token belongs to
    label: str = ""           # e.g. "Ryan's iPhone" — for the admin view only
    updated: float = 0.0


class DeviceRegistry(Protocol):
    async def register(self, token: str, audience: str, *, env: str = "production",
                       label: str = "") -> Device: ...
    async def unregister(self, token: str) -> bool: ...
    async def for_audiences(self, audiences: Iterable[str]) -> list[Device]: ...
    async def all(self) -> list[Device]: ...


class JsonDeviceRegistry:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    def _load(self) -> dict[str, Device]:
        try:
            raw = json.loads(self.path.read_text())
            return {d["token"]: Device(**d) for d in raw if d.get("token")}
        except (FileNotFoundError, ValueError, TypeError):
            return {}

    def _save(self, devices: dict[str, Device]) -> None:
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".devices.")
        with os.fdopen(fd, "w") as f:
            json.dump([asdict(d) for d in devices.values()], f, indent=1)
        os.replace(tmp, self.path)

    async def register(self, token: str, audience: str, *, env: str = "production",
                       label: str = "") -> Device:
        token = (token or "").strip().lower()
        if not token or env not in ENVS:
            raise ValueError("register needs a token and env in " + str(ENVS))
        async with self._lock:
            devices = await asyncio.to_thread(self._load)
            # A token is one install; re-registering moves it (e.g. profile switch).
            devices[token] = Device(token, audience, env, label[:60], time.time())
            await asyncio.to_thread(self._save, devices)
            return devices[token]

    async def unregister(self, token: str) -> bool:
        async with self._lock:
            devices = await asyncio.to_thread(self._load)
            if devices.pop((token or "").strip().lower(), None) is None:
                return False
            await asyncio.to_thread(self._save, devices)
            return True

    async def for_audiences(self, audiences: Iterable[str]) -> list[Device]:
        want = set(audiences)
        async with self._lock:
            return [d for d in (await asyncio.to_thread(self._load)).values() if d.audience in want]

    async def all(self) -> list[Device]:
        async with self._lock:
            return list((await asyncio.to_thread(self._load)).values())
