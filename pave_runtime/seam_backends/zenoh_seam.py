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
import uuid

import zenoh  # lazy: only imported when the raw_zenoh backend is selected

from pave_runtime.lease import BodyLease, guarded_dispatch

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
        lease = BodyLease()  # dead-man switch: a leased motion the brain stops renewing is STOPped here

        def on_action(sample) -> None:
            try:
                p = json.loads(_payload_bytes(sample))
            except json.JSONDecodeError:
                return
            if not isinstance(p, dict) or p.get("body_id") not in (None, lease.body_id):
                return
            state = guarded_dispatch(adapter, lease, p.get("action", ""), p.get("params"))
            state = {**state, "body_id": lease.body_id}
            if "correlation_id" in p:
                state["correlation_id"] = p["correlation_id"]
            pub.put(json.dumps(state, ensure_ascii=False).encode("utf-8"))

        session.declare_subscriber(ACTION_KEY, on_action)
        watcher = asyncio.ensure_future(
            lease.watch(adapter, emit=lambda e: print("[seam:lease]", json.dumps(e, ensure_ascii=False), flush=True))
        )
        print(f"[seam:raw_zenoh] body up · adapter={adapter.name} · caps={sorted(adapter.capabilities)}"
              f" · motion lease {lease.ttl_s:g}s")
        try:
            while True:
                await asyncio.sleep(1)
        finally:
            watcher.cancel()
            session.close()

    async def send(self, action: str, params: dict | None = None,
                   *, target: str | None = None, timeout: float = 5.0) -> dict:
        """Match only this request's reply; target optionally pins a lease_status body_id.

        Requires a body that echoes correlation_id. Untargeted legacy clients can still
        send to updated bodies, but updated clients cannot use uncorrelated old bodies.
        """
        session = zenoh.open(_config())
        try:
            replies: list[dict] = []
            correlation_id = uuid.uuid4().hex

            def on_state(sample):
                try:
                    state = json.loads(_payload_bytes(sample))
                except (ValueError, UnicodeDecodeError):
                    return
                if (isinstance(state, dict) and state.get("correlation_id") == correlation_id
                        and (target is None or state.get("body_id") == target)):
                    replies.append(state)

            session.declare_subscriber(STATE_KEY, on_state)
            pub = session.declare_publisher(ACTION_KEY)
            await asyncio.sleep(0.5)  # let discovery + subscription match
            pub.put(json.dumps({"action": action, "params": params or {},
                                "correlation_id": correlation_id, "body_id": target}).encode("utf-8"))
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline and not replies:
                await asyncio.sleep(0.05)
        finally:
            session.close()  # also when cancelled mid-send (a shutdown signal), not only on the happy path
        return replies[-1] if replies else {"status": "no_reply", "error": "timeout", "action": action}
