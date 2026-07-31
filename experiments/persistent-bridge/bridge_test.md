# B1 — persistent bridge: mock bring-up & latency

B1 validates the **persistent bridge** on a plain host with **no robot**: a long-lived rclpy node
keeps its service clients connected and answers action requests over a localhost socket. See the
design doc for the goals; this is the runbook + result.

Everything runs in **one** ROS 2 container (FastDDS, so mock + bridge share one graph); the socket
is localhost. No PuppyPi, no puppy_control.

## Files

| File | Role |
|------|------|
| `bridge_protocol.py` | wire protocol: newline-JSON, sync request/result + reserved async fields |
| `gait_steps.py` | shared step executor; service clients cached in a caller-owned dict (reuse) |
| `mock_controller.py` | mock puppy_control: std_srvs services (`set_running`/`set_mark_time`/`go_home`) |
| `bridge_node.py` | persistent node + socket server; clients reused across requests |
| `bridge_client.py` | body-side client; `__main__` benchmarks STOP over the bridge |
| `bench_cold.py` | cold baseline: fresh node + discovery **per action** (the "before") |
| `test_bridge_protocol.py` | protocol unit tests (pure JSON, no ROS) — 11 tests |

## Run (on a plain host, e.g. RPi5 `.13`)

```bash
# deploy the files (e.g. to ~/openpave-bridge), then one container:
docker run -d --name openpave-b1 --net=host \
  -e RMW_IMPLEMENTATION=rmw_fastrtps_cpp -e ROS_DOMAIN_ID=0 \
  --shm-size=256m --ulimit memlock=-1:-1 \
  -v ~/openpave-bridge:/ws \
  --entrypoint bash odinlmshen/ros2-zenoh-arm:jazzy-edge -lc "sleep infinity"

# mock puppy_control (background)
docker exec -d openpave-b1 bash -lc \
  "source /opt/ros/jazzy/setup.bash && cd /ws && python3 mock_controller.py > /tmp/mock.log 2>&1"

# persistent bridge (background)
docker exec -d openpave-b1 bash -lc \
  "source /opt/ros/jazzy/setup.bash && cd /ws && python3 bridge_node.py > /tmp/bridge.log 2>&1"

# benchmark: cold baseline vs bridge
docker exec openpave-b1 bash -lc "source /opt/ros/jazzy/setup.bash && cd /ws && python3 bench_cold.py 5"
docker exec openpave-b1 bash -lc "source /opt/ros/jazzy/setup.bash && cd /ws && python3 bridge_client.py 5"
```

Cleanup: `docker rm -f openpave-b1`.

## Result (RPi5 `.13`, mock, FastDDS, n=5, 2026-07-31)

| STOP (3 service calls) | latency |
|------------------------|--------:|
| **cold** — fresh node + discovery per action | avg **320 ms** (265–529) |
| **bridge** — persistent, clients reused | avg **1.7 ms** (1.5–1.8) |

**~190× faster**, and far more consistent. Every request returned `ok=True`; the bridge log shows
5 consecutive requests handled on the one connection.

### Reading

- The bridge pays node startup + service **discovery once** (at startup). After that each STOP is
  just `socket + 3 already-connected call()` → ~ms.
- The cold baseline pays discovery **every action** → hundreds of ms — and that is *without*
  docker exec. On the real robot (B2) the "before" also carries the docker exec cost, which is why
  opt A measured STOP at 2740 ms. So the bridge's win on real hardware should be even larger.

## Success criteria — met

- [x] bridge stays up, runs a step list against the mock, returns the correct result (`ok=True`)
- [x] multiple consecutive actions — socket protocol stable
- [x] bridge per-action latency **far below** cold / A (1.7 ms vs 320 ms / 2740 ms)
- [x] skeleton (protocol / node / client / shared step executor) ready to hand to B2

## Hand-off to B2

Swap `mock_controller` for the **real puppy_control** (bridge runs inside its container), integrate
the bridge into `PuppyPiLocalAdapter` (try bridge, fall back to A), add a start/health script, and
measure real HOME/STOP before(A)/after(B). The protocol + node + client carry over unchanged.
The reserved async fields (`mode:"async"`, `op:"action"`, `progress`/`cancel`) are where AMR-style
long-running navigation slots in later — no wire-format change.
