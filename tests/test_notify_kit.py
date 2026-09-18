"""Offline tests — APNs is mocked with httpx.MockTransport; the JWT is verified
against a throwaway P-256 key."""
import base64
import json

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from notify_kit import (ApnsClient, ApnsConfig, JsonDeviceRegistry, Notification,
                        PushService, apns_payload, make_jwt)
from notify_kit.apns import headers_for


def _key():
    k = ec.generate_private_key(ec.SECP256R1())
    pem = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                          serialization.NoEncryption()).decode()
    return k, pem


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def test_jwt_is_valid_es256():
    k, pem = _key()
    tok = make_jwt("TEAM123", "KEY456", pem, now=1700000000)
    h, c, sig = tok.split(".")
    assert json.loads(_unb64(h)) == {"alg": "ES256", "kid": "KEY456"}
    assert json.loads(_unb64(c)) == {"iss": "TEAM123", "iat": 1700000000}
    raw = _unb64(sig)
    assert len(raw) == 64
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    k.public_key().verify(der, f"{h}.{c}".encode(), ec.ECDSA(hashes.SHA256()))  # raises if bad


def test_payload_and_headers():
    n = Notification("Timer done", "Pasta", level="time-sensitive", collapse_id="timer:t1",
                     thread_id="timers", data={"deeplink": "remote://feed"})
    p = apns_payload(n)
    assert p["aps"]["alert"] == {"title": "Timer done", "body": "Pasta"}
    assert p["aps"]["interruption-level"] == "time-sensitive"
    assert p["aps"]["thread-id"] == "timers" and p["deeplink"] == "remote://feed"
    h = headers_for(n, "com.example.app", "JWT")
    assert h["apns-topic"] == "com.example.app" and h["apns-priority"] == "10"
    assert h["apns-collapse-id"] == "timer:t1"
    assert headers_for(Notification("x", level="passive"), "t", "j")["apns-priority"] == "5"


def test_level_validated():
    with pytest.raises(ValueError):
        Notification("x", level="critical")


async def test_registry_roundtrip(tmp_path):
    reg = JsonDeviceRegistry(tmp_path / "devices.json")
    await reg.register("ABC", "ryan", label="Ryan's iPhone")
    await reg.register("def", "lia", env="sandbox")
    assert [d.token for d in await reg.for_audiences(["ryan"])] == ["abc"]  # lower-cased
    await reg.register("abc", "lia")   # re-register moves audience, no duplicate
    assert len(await reg.all()) == 2
    assert {d.token for d in await reg.for_audiences(["lia"])} == {"abc", "def"}
    assert await reg.unregister("def") and not await reg.unregister("def")
    with pytest.raises(ValueError):
        await reg.register("x", "ryan", env="staging")


async def test_service_sends_and_prunes_dead_tokens(tmp_path):
    _, pem = _key()
    seen = []

    def handler(req: httpx.Request):
        seen.append((req.url.host, req.url.path, json.loads(req.content)))
        if req.url.path.endswith("/dead"):
            return httpx.Response(410, json={"reason": "Unregistered"})
        return httpx.Response(200, headers={"apns-id": "id-1"})

    client = ApnsClient(ApnsConfig("T", "K", "com.example.app", key_pem=pem),
                        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    reg = JsonDeviceRegistry(tmp_path / "d.json")
    await reg.register("good", "ryan", env="sandbox")
    await reg.register("dead", "ryan")
    await reg.register("other", "lia")
    push = PushService(client, reg)

    res = await push.send(["ryan"], Notification("Hi"))
    assert sorted(r.ok for r in res) == [False, True]
    hosts = {path.rsplit("/", 1)[1]: host for host, path, _ in seen}
    assert hosts == {"good": "api.sandbox.push.apple.com", "dead": "api.push.apple.com"}
    assert [d.token for d in await reg.all()] == ["good", "other"]  # dead one pruned


async def test_unconfigured_service_is_noop(tmp_path):
    push = PushService(None, JsonDeviceRegistry(tmp_path / "d.json"))
    assert not push.configured and await push.send(["ryan"], Notification("x")) == []
