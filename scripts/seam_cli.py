#!/usr/bin/env python3
"""Unified seam body/brain over the pluggable transport.

The transport is chosen by `$SEAM_TRANSPORT` (raw_zenoh | device_connect | …) — **the same body and
brain code runs over any backend**; only the env var changes. This is the payoff of the transport
plugin (`pave_runtime.seam`).

  body:   SEAM_TRANSPORT=raw_zenoh ROBOT_ADAPTER=mock_arm python scripts/seam_cli.py serve
  brain:  SEAM_TRANSPORT=raw_zenoh python scripts/seam_cli.py send move_joint '{"joint":2,"position":0.5}'
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root

from pave_runtime.seam import create_seam_transport


async def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "serve"
    seam = create_seam_transport()  # picks backend from $SEAM_TRANSPORT

    if mode == "serve":
        # body only — the brain (send) never needs an adapter, so import lazily to keep
        # brain-side deployment light (no control_daemon required to send).
        from control_daemon.adapters import create_robot_adapter
        adapter = create_robot_adapter(os.getenv("ROBOT_ADAPTER", "mock_arm"))
        await seam.serve(adapter)

    elif mode == "send":
        if len(sys.argv) < 3:
            print("usage: seam_cli.py send ACTION [params_json]", file=sys.stderr)
            sys.exit(1)
        action = sys.argv[2]
        params = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        state = await seam.send(action, params)
        print("state:", json.dumps(state, ensure_ascii=False))

    else:
        print(f"unknown mode {mode!r}; use 'serve' or 'send'", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
