#!/usr/bin/env bash
#
# One-command PuppyPi bring-up. Run this ON THE PuppyPi. It:
#   1. starts the ROS 2 container,
#   2. clears any existing puppy_control (single instance — avoids duplicate nodes),
#   3. launches puppy_control DETACHED (survives — never ctrl-c a foreground launch),
#      sourcing BOTH /opt/ros/humble and the ros2_ws workspace,
#   4. restarts a stale ros2 daemon, then verifies puppy_control responds.
#
# Captures the lessons from the real-robot session — see experiments/zenoh-mve/puppypi_test.md.
# This is the robust, detached bring-up (survives ctrl-c, single-instance, health-checked).
#
# Env (defaults match the validated setup):
#   PUPPY_EXEC_CONTAINER (puppypi_ros2)  PUPPY_EXEC_USER (ubuntu)  PUPPY_WORKDIR (/home/ubuntu)
#   PUPPY_ROS_WS_SETUP (/home/ubuntu/ros2_ws/install/setup.bash)
#   ROS_DOMAIN_ID (0)  PUPPY_RMW_IMPLEMENTATION (rmw_fastrtps_cpp)
#   PUPPY_LAUNCH_CMD (ros2 launch puppy_control puppy_control.launch.py)  STARTUP_WAIT_SEC (12)

set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CONTAINER="${PUPPY_EXEC_CONTAINER:-puppypi_ros2}"
EXEC_USER="${PUPPY_EXEC_USER:-ubuntu}"
WORKDIR="${PUPPY_WORKDIR:-/home/ubuntu}"
WS_SETUP="${PUPPY_ROS_WS_SETUP:-/home/ubuntu/ros2_ws/install/setup.bash}"
DOMAIN="${ROS_DOMAIN_ID:-0}"
RMW="${PUPPY_RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}"
LAUNCH_CMD="${PUPPY_LAUNCH_CMD:-ros2 launch puppy_control puppy_control.launch.py}"
WAIT="${STARTUP_WAIT_SEC:-12}"

log() { printf '[puppy] %s\n' "$*"; }

command -v docker >/dev/null 2>&1 || { log "docker not found"; exit 1; }
docker inspect "$CONTAINER" >/dev/null 2>&1 || { log "container not found: $CONTAINER (set PUPPY_EXEC_CONTAINER)"; exit 1; }

env_src="source /opt/ros/humble/setup.bash 2>/dev/null; source ${WS_SETUP} 2>/dev/null; export ROS_DOMAIN_ID=${DOMAIN} RMW_IMPLEMENTATION=${RMW};"

log "starting container: $CONTAINER"
docker start "$CONTAINER" >/dev/null

log "clearing any existing puppy_control (single instance)"
docker exec "$CONTAINER" bash -lc \
  'pkill -f "launch puppy_control" 2>/dev/null; pkill -f "puppy_control/lib/puppy_control/puppy_control" 2>/dev/null; sleep 2' || true

log "restarting ros2 daemon"
docker exec -u "$EXEC_USER" "$CONTAINER" bash -lc "${env_src} ros2 daemon stop" >/dev/null 2>&1 || true

log "launching puppy_control (detached): $LAUNCH_CMD"
docker exec -d -u "$EXEC_USER" -w "$WORKDIR" "$CONTAINER" bash -lc "${env_src} ${LAUNCH_CMD}"

log "waiting ${WAIT}s for puppy_control to come up..."
sleep "$WAIT"

# verify via the health-check script if available, else inline
if [ -x "${here}/check_puppy_control.sh" ]; then
  PUPPY_EXEC_CONTAINER="$CONTAINER" PUPPY_EXEC_USER="$EXEC_USER" PUPPY_ROS_WS_SETUP="$WS_SETUP" \
    ROS_DOMAIN_ID="$DOMAIN" PUPPY_RMW_IMPLEMENTATION="$RMW" bash "${here}/check_puppy_control.sh"
  exit $?
fi

if docker exec -u "$EXEC_USER" "$CONTAINER" bash -lc \
     "${env_src} timeout 10 ros2 service call /puppy_control/set_mark_time std_srvs/srv/SetBool '{data: false}'" 2>&1 \
     | grep -q "success=True"; then
  log "OK — puppy_control up and responding"
  exit 0
fi
log "WARN — launched but health check did not confirm; see experiments/zenoh-mve/puppypi_test.md"
exit 1
