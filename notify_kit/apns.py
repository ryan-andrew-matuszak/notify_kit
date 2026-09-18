"""Apple Push Notification service — token-based (.p8) auth over HTTP/2.

One `.p8` key (Apple Developer ▸ Keys, "Apple Push Notifications service")
signs for every app on the team, so a new app only needs its own `topic` (bundle
id). The provider JWT is ES256, cached and re-minted every ~50 minutes (Apple
rejects tokens older than an hour and throttles re-minting faster than 20 min).

Needs the `apns` extra (`cryptography` for ES256, `h2` for HTTP/2 — APNs speaks
nothing else). The pure pieces (`make_jwt`, the header builder) are testable
without the network.
"""
from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from .payload import Notification, apns_payload

HOSTS = {"production": "https://api.push.apple.com",
         "sandbox": "https://api.sandbox.push.apple.com"}
JWT_MAX_AGE = 50 * 60

#: APNs `reason`s that mean the token will never work again → drop it. 410
#: (Unregistered) is the classic; BadDeviceToken usually means the token belongs
#: to the other environment, and the app re-registers with the right one anyway.
DEAD_REASONS = {"Unregistered", "BadDeviceToken", "DeviceTokenNotForTopic"}


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def make_jwt(team_id: str, key_id: str, key_pem: str, *, now: float | None = None) -> str:
    """The ES256 provider token APNs expects in `authorization: bearer …`."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    header = _b64url(json.dumps({"alg": "ES256", "kid": key_id}, separators=(",", ":")).encode())
    claims = _b64url(json.dumps({"iss": team_id, "iat": int(now or time.time())},
                                separators=(",", ":")).encode())
    signing_input = f"{header}.{claims}".encode()
    key = serialization.load_pem_private_key(key_pem.encode(), password=None)
    der = key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)  # JWS wants raw r||s, not DER
    return f"{header}.{claims}.{_b64url(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"


@dataclass(frozen=True)
class ApnsConfig:
    team_id: str
    key_id: str
    topic: str            # the app's bundle id
    key_pem: str = ""     # the .p8 contents; or give key_path
    key_path: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.team_id and self.key_id and self.topic and (self.key_pem or self.key_path))

    def pem(self) -> str:
        return self.key_pem or Path(self.key_path).expanduser().read_text()


@dataclass
class SendResult:
    token: str
    ok: bool
    status: int = 0
    reason: str = ""
    apns_id: str = ""

    @property
    def dead(self) -> bool:
        """The token is permanently invalid — the caller should forget it."""
        return self.status == 410 or self.reason in DEAD_REASONS


def headers_for(n: Notification, topic: str, jwt: str) -> dict:
    h = {"authorization": f"bearer {jwt}", "apns-topic": topic, "apns-push-type": "alert",
         # 5 = conserve power (fine for passive); 10 = deliver now.
         "apns-priority": "5" if n.level == "passive" else "10",
         "apns-expiration": str(int(time.time()) + n.ttl) if n.ttl else "0"}
    if n.collapse_id:
        h["apns-collapse-id"] = n.collapse_id.encode()[:64].decode(errors="ignore")
    return h


class ApnsClient:
    """Sends to one app (topic). Reuse one instance — it holds the HTTP/2
    connection and the cached JWT."""

    def __init__(self, cfg: ApnsConfig, *, client: httpx.AsyncClient | None = None):
        self.cfg = cfg
        self._client = client
        self._jwt = ""
        self._jwt_at = 0.0

    def _token(self) -> str:
        if not self._jwt or time.time() - self._jwt_at > JWT_MAX_AGE:
            self._jwt = make_jwt(self.cfg.team_id, self.cfg.key_id, self.cfg.pem())
            self._jwt_at = time.time()
        return self._jwt

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(http2=True, timeout=10)
        return self._client

    async def send(self, token: str, n: Notification, *, env: str = "production") -> SendResult:
        url = f"{HOSTS.get(env, HOSTS['production'])}/3/device/{token}"
        try:
            r = await self._http().post(url, json=apns_payload(n),
                                        headers=headers_for(n, self.cfg.topic, self._token()))
        except Exception as e:  # network down, TLS, bad key … never raise into the app
            return SendResult(token, False, 0, f"{type(e).__name__}: {e}")
        reason = ""
        if r.status_code != 200:
            try:
                reason = r.json().get("reason", "")
            except Exception:
                reason = r.text[:200]
            if r.status_code == 403 and reason in ("ExpiredProviderToken", "InvalidProviderToken"):
                self._jwt = ""  # re-mint next time
        return SendResult(token, r.status_code == 200, r.status_code, reason,
                          r.headers.get("apns-id", ""))

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
