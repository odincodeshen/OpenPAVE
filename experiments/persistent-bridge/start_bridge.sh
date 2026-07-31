#!/usr/bin/env bash
# Start the Persistent Body-Side Bridge inside the puppy_control container (B2).
#
# IMPORTANT: run the bridge as the SAME user as puppy_control (ubuntu). FastDDS shared-memory
# segments are per-user, so a root bridge sees the services in discovery but its calls TIME OUT
# (the data channel is unreachable). Matching RMW + ROS_DOMAIN_ID matters too.
#
# NetworkMode=host on the container -> the bridge listens on 127.0.0.1 and the host-side adapter
# (ROBOT_ADAPTER=puppypi_bridge) connects over TCP localhost. If your container is NOT host-net,
# switch to a Unix socket over a shared volume (design §3.1).
#
# Run from this directory on the robot host:  bash start_bridge.sh
set -euo pipefail

CONTAINER="${PUPPY_EXEC_CONTAINER:-puppypi_ros2}"
BRIDGE_USER="${PUPPY_EXEC_USER:-ubuntu}"
PORT="${OPENPAVE_BRIDGE_PORT:-8787}"
WS_SETUP="${PUPPY_ROS_WS_SETUP:-/home/ubuntu/ros2_ws/install/setup.bash}"
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "[start_bridge] copying bridge files into $CONTAINER:/tmp/bridge"
docker exec "$CONTAINER" mkdir -p /tmp/bridge
for f in bridge_node.py bridge_protocol.py gait_steps.py; do
  docker cp "$HERE/$f" "$CONTAINER:/tmp/bridge/$f"
done

echo "[start_bridge] launching bridge as '$BRIDGE_USER' (FastDDS, domain 0) on 127.0.0.1:$PORT"
docker exec -d -u "$BRIDGE_USER" \
  -e RMW_IMPLEMENTATION=rmw_fastrtps_cpp -e ROS_DOMAIN_ID=0 -e OPENPAVE_BRIDGE_PORT="$PORT" \
  "$CONTAINER" bash -lc \
  "source /opt/ros/humble/setup.bash && source $WS_SETUP && cd /tmp/bridge && python3 bridge_node.py > /tmp/bridge.log 2>&1"

sleep 4
echo "[start_bridge] log:"; docker exec "$CONTAINER" tail -1 /tmp/bridge.log 2>/dev/null || true

echo "[start_bridge] health check (ping):"
python3 - "$PORT" <<'PY' || echo "  ping FAILED — check /tmp/bridge.log in the container"
import sys, socket, json
port = int(sys.argv[1])
s = socket.create_connection(("127.0.0.1", port), timeout=3)
s.sendall((json.dumps({"type": "ping", "version": "0.1", "id": "h"}) + "\n").encode())
msg = json.loads(s.recv(4096).decode().splitlines()[0]); d = msg.get("detail", {})
print(f"  pong ready={msg.get('ready')} services_ready={d.get('services_ready')} "
      f"controller={d.get('controller')} pid={d.get('bridge_pid')}")
s.close()
PY
