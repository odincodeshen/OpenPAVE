"""Intent schema v0.1 helpers.

The helpers in this module keep the current file-bus MVP small while giving
`intent-ingress` and `control-daemon` one shared runtime contract.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Any


SCHEMA_VERSION = "0.1"
SUPPORTED_INTENTS = {"STOP", "TROT", "HOME", "MOVE"}
TEXT_ALIASES = {"STOP", "TROT", "HOME", "TURN_LEFT", "LEFT", "TURN_RIGHT", "RIGHT"}

VX_MIN = -0.5
VX_MAX = 0.5
YAW_MIN = -1.0
YAW_MAX = 1.0
DURATION_MIN_MS = 100
DURATION_MAX_MS = 5000


class IntentValidationError(ValueError):
    """Raised when an intent payload cannot be normalized safely."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_float(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise IntentValidationError(f"{field} must be a number") from exc
    if not math.isfinite(result):
        raise IntentValidationError(f"{field} must be finite")
    return result


def _as_int(value: Any, field: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise IntentValidationError(f"{field} must be an integer") from exc
    return result


def _range(value: float, field: str, lower: float, upper: float) -> float:
    if value < lower or value > upper:
        raise IntentValidationError(f"{field} must be between {lower} and {upper}")
    return value


def _optional_confidence(value: Any) -> float | None:
    if value is None:
        return None
    confidence = _as_float(value, "confidence")
    return _range(confidence, "confidence", 0.0, 1.0)


def _move_params(payload: dict[str, Any]) -> dict[str, Any]:
    params = payload.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise IntentValidationError("params must be an object")

    vx = _as_float(params.get("vx", payload.get("vx", 0.0)), "params.vx")
    yaw = _as_float(params.get("yaw", payload.get("yaw", 0.0)), "params.yaw")
    duration_ms = _as_int(
        params.get("duration_ms", payload.get("duration_ms", 500)),
        "params.duration_ms",
    )

    return {
        "vx": _range(vx, "params.vx", VX_MIN, VX_MAX),
        "yaw": _range(yaw, "params.yaw", YAW_MIN, YAW_MAX),
        "duration_ms": int(
            _range(duration_ms, "params.duration_ms", DURATION_MIN_MS, DURATION_MAX_MS)
        ),
    }


def _intent_from_text(text: str) -> tuple[str, dict[str, Any], bool]:
    normalized = text.strip().upper()

    if normalized == "TROT":
        return "TROT", {}, False
    if normalized == "STOP":
        return "STOP", {}, False
    if normalized == "HOME":
        return "HOME", {}, False
    if normalized in {"TURN_LEFT", "LEFT"}:
        return "MOVE", {"vx": 0.0, "yaw": -0.4, "duration_ms": 600}, False
    if normalized in {"TURN_RIGHT", "RIGHT"}:
        return "MOVE", {"vx": 0.0, "yaw": 0.6, "duration_ms": 600}, False

    return "STOP", {}, True


def normalize_intent_payload(
    payload: dict[str, Any],
    *,
    default_source: str = "unknown",
    safe_default: bool = True,
) -> dict[str, Any]:
    """Normalize legacy or schema-v0.1 payloads into one intent shape.

    Supported inputs:
    - {"text": "STOP"}
    - {"intent": "MOVE", "vx": 0.0, "yaw": 0.6, "duration_ms": 600}
    - {"schema_version": "0.1", "intent": "MOVE", "params": {...}}
    """

    if not isinstance(payload, dict):
        raise IntentValidationError("payload must be an object")

    source = str(payload.get("source") or payload.get("_src") or default_source)
    request_id = str(payload.get("request_id") or uuid.uuid4())
    timestamp = str(payload.get("timestamp") or payload.get("_ts") or now_iso())
    confidence = _optional_confidence(payload.get("confidence"))
    raw_text = None
    params: dict[str, Any] = {}
    safety_fallback = False

    if "text" in payload and str(payload.get("text", "")).strip():
        raw_text = str(payload.get("text", ""))
        intent, params, safety_fallback = _intent_from_text(raw_text)
    else:
        intent = str(payload.get("intent", "")).strip().upper()
        if intent in TEXT_ALIASES and intent not in SUPPORTED_INTENTS:
            raw_text = intent
            intent, params, safety_fallback = _intent_from_text(raw_text)
            intent = str(intent).upper()
        if intent not in SUPPORTED_INTENTS:
            if not safe_default:
                raise IntentValidationError(f"unsupported intent: {intent or '<empty>'}")
            intent = "STOP"
            safety_fallback = True
        elif not params:
            params = _move_params(payload) if intent == "MOVE" else {}

    if intent == "MOVE":
        params = _move_params({"params": params})

    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
        "intent": intent,
        "params": params,
        "source": source,
        "timestamp": timestamp,
    }
    if confidence is not None:
        result["confidence"] = confidence
    if raw_text is not None:
        result["raw_text"] = raw_text
    if safety_fallback:
        result["safety_fallback"] = True

    return result


def intent_action_key(intent: dict[str, Any]) -> tuple[Any, ...]:
    """Stable de-dup key for daemon action dispatch."""

    params = intent.get("params") if isinstance(intent.get("params"), dict) else {}
    return (
        intent.get("intent"),
        params.get("vx"),
        params.get("yaw"),
        params.get("duration_ms"),
    )


# Translator: legacy locomotion intent (v0.1) -> capability {action, params}. This keeps
# existing file-bus / intent-ingress payloads working while the dispatch runs on the graduated
# capability model (see pave_runtime.capability_schema). Locomotion is one capability vocabulary;
# other robot classes speak their own actions natively.
_INTENT_TO_ACTION = {"STOP": "stop", "TROT": "trot", "HOME": "home", "MOVE": "move"}


def intent_to_capability_action(normalized: dict[str, Any]) -> dict[str, Any]:
    """Map a normalized v0.1 intent onto a capability action.

    ``STOP/TROT/HOME -> stop/trot/home`` (no params); ``MOVE -> move`` carrying vx/yaw/duration_ms.
    Unknown intents fall back to the safe ``stop``.
    """
    intent = str(normalized.get("intent", "STOP")).upper()
    action = _INTENT_TO_ACTION.get(intent, "stop")
    params = dict(normalized.get("params") or {}) if action == "move" else {}
    return {"action": action, "params": params}
