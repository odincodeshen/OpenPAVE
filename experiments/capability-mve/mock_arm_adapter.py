"""MockArmAdapter — a manipulation-class robot, to prove the architecture is generic.

It declares manipulation capabilities (not locomotion) and logs each action. No hardware. Swap
this for a real arm adapter later; the transport (zenoh seam) and the generic body node do not
change — that reuse is the point of Plan A.
"""

from __future__ import annotations

from typing import Any

from capability_adapter import ActionResult


class MockArmAdapter:
    name = "mock_arm"
    # manipulation capabilities + the common safe verbs (stop/estop/home)
    capabilities = frozenset({"estop", "stop", "home", "grasp", "release", "move_joint"})

    # per-capability required params (the adapter's own contract; absent = no params required)
    _required: dict[str, tuple[str, ...]] = {"move_joint": ("joint", "position")}

    def execute(self, action: str, params: dict[str, Any]) -> ActionResult:
        missing = [k for k in self._required.get(action, ()) if k not in params]
        if missing:
            return ActionResult.failed(f"'{action}' requires params {missing}", {"action": action})
        print(f"[mock_arm] {action} params={params}")
        return ActionResult.ok({"action": action, "params": params})
