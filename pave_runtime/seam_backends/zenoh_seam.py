"""raw-zenoh seam backend — graduates ②a (experiments/neutral-seam).

Body serves over **raw zenoh** (zenoh-python, not rmw_zenoh) exchanging capability JSON; brain
sends one action and waits for the state reply. The body-endpoint logic is `pave_runtime.seam.dispatch`
(single source) — this backend only moves bytes. Cross-host: `ZENOH_LISTEN` (body) / `ZENOH_CONNECT`
(brain); single host uses zenoh peer multicast.
"""

from __future__ import annotations

import asyncio
import json
import os
import time

import zenoh  # lazy: only imported when the raw_zenoh backend is selected

from pave_runtime.seam import dispatch

ACTION_KEY = "openpave/action"        # down: {action, params}
STATE_KEY = "openpave/action_state"   # up: state dict


def _payload_bytes(sample) -> bytes:
    try:
        return sample.payload.to_bytes()
    except AttributeError:
        return bytes(sample.payload)


def _config() -> "zenoh.Config":
    conf = zenoh.Config()
    for key, env in (("connect/endpoints", "ZENOH_CONNECT"), ("listen/endpoints", "ZENOH_LISTEN")):
        val = os.environ.get(env)
        if val:
            conf.insert_json5(key, json.dumps([val]))
    return conf


class ZenohSeam:
    name = "raw_zenoh"

    async def serve(self, adapter) -> None:
        session = zenoh.open(_config())
        pub = session.declare_publisher(STATE_KEY)

        def on_action(sample) -> None:
            try:
                p = json.loads(_payload_bytes(sample))
            except json.JSONDecodeError:
                return
            state = dispatch(adapter, p.get("action", ""), p.get("params"))
            pub.put(json.dumps(state, ensure_ascii=False).encode("utf-8"))

        session.declare_subscriber(ACTION_KEY, on_action)
        print(f"[seam:raw_zenoh] body up · adapter={adapter.name} · caps={sorted(adapter.capabilities)}")
        try:
            while True:
                await asyncio.sleep(1)
        finally:
            session.close()

    async def send(self, action: str, params: dict | None = None,
                   *, target: str | None = None, timeout: float = 5.0) -> dict:
        session = zenoh.open(_config())
        replies: list[dict] = []
        session.declare_subscriber(STATE_KEY, lambda s: replies.append(json.loads(_payload_bytes(s))))
        pub = session.declare_publisher(ACTION_KEY)
        await asyncio.sleep(0.5)  # let discovery + subscription match
        pub.put(json.dumps({"action": action, "params": params or {}}).encode("utf-8"))
        deadline = time.time() + timeout
        while time.time() < deadline and not replies:
            await asyncio.sleep(0.05)
        session.close()
        return replies[-1] if replies else {"status": "no_reply", "error": "timeout", "action": action}
