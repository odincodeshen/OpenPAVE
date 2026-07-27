# live-vlm-webui server-side hook (STOP/TROT → Intent Ingress)

Goal: forward inference results to Intent Ingress without relying on browser-side JS.

## Where to patch
`src/live_vlm_webui/server.py`

The project already sends:
```python
out = {"type": "vlm_response", "text": text, "metrics": metrics}
send_to_session(session_id, json.dumps(out))
```

Add a small helper that POSTs `STOP/TROT` to Intent Ingress.

## Minimal patch (example)

1) Add import:
```python
import requests
import time
import os
```

2) Add globals + helper near the top of the file:
```python
INTENT_INGRESS_URL = os.environ.get("INTENT_INGRESS_URL", "http://127.0.0.1:7071/intent")
INTENT_DEDUP_MS = int(os.environ.get("INTENT_DEDUP_MS", "300"))
_last_intent_sent = {"text": None, "ts": 0.0}

def maybe_post_intent(text: str):
    t = (text or "").strip().upper()
    if t not in ("STOP", "TROT"):
        return
    now = time.time() * 1000.0
    if _last_intent_sent["text"] == t and (now - _last_intent_sent["ts"]) < INTENT_DEDUP_MS:
        return
    _last_intent_sent["text"] = t
    _last_intent_sent["ts"] = now
    try:
        requests.post(INTENT_INGRESS_URL, json={"text": t}, timeout=0.2)
    except Exception:
        pass
```

3) In `get_session_callback(...): callback(text, metrics)` add before `send_to_session(...)`:
```python
maybe_post_intent(text)
```

## Verify
- Run `intent_ingress.py`
- Start webui server with:
```bash
export INTENT_INGRESS_URL="http://127.0.0.1:7071/intent"
```
- When UI shows STOP/TROT, `intent_ingress.py` should log HTTP 200.
