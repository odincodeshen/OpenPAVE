#!/usr/bin/env bash
#
# Verify the PuppyPi's ROS 2 puppy_control is up and *responding*.
#
# Run this ON THE PuppyPi host (it docker-execs into the puppy_control container). It calls a
# harmless service (set_mark_time:false — no motion) and expects a response. If the call hangs
# (a stale ros2 daemon, or puppy_control was ctrl-c'd / duplicated), it restarts the ros2 daemon
# once and retries. See experiments/zenoh-mve/puppypi_test.md for the full runbook.
#
# Config via env (defaults match the validated setup):
#   PUPPY_EXEC_CONTAINER (puppypi_ros2)  PUPPY_EXEC_USER (ubuntu)
#   PUPPY_ROS_WS_SETUP (/home/ubuntu/ros2_ws/install/setup.bash)
#   ROS_DOMAIN_ID (0)  PUPPY_RMW_IMPLEMENTATION (rmw_fastrtps_cpp)  CHECK_TIMEOUT_SEC (10)
#
# Exit 0 = puppy_control responding; exit 1 = not responding.

set -uo pipefail

CONTAINER="${PUPPY_EXEC_CONTAINER:-puppypi_ros2}"
EXEC_USER="${PUPPY_EXEC_USER:-ubuntu}"
WS_SETUP="${PUPPY_ROS_WS_SETUP:-/home/ubuntu/ros2_ws/install/setup.bash}"
DOMAIN="${ROS_DOMAIN_ID:-0}"
RMW="${PUPPY_RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}"
TIMEOUT="${CHECK_TIMEOUT_SEC:-10}"
SERVICE="/puppy_control/set_mark_time"

_env="source /opt/ros/humble/setup.bash 2>/dev/null; source ${WS_SETUP} 2>/dev/null; export ROS_DOMAIN_ID=${DOMAIN} RMW_IMPLEMENTATION=${RMW};"

_call() {
  docker exec -u "${EXEC_USER}" "${CONTAINER}" bash -lc \
    "${_env} timeout ${TIMEOUT} ros2 service call ${SERVICE} std_srvs/srv/SetBool '{data: false}'" 2>&1
}

echo "[check] puppy_control health via ${SERVICE} (container=${CONTAINER})"

if _call | grep -q "success=True"; then
  echo "[check] OK — puppy_control responding"
  exit 0
fi

echo "[check] no response — restarting ros2 daemon and retrying..."
docker exec -u "${EXEC_USER}" "${CONTAINER}" bash -lc "${_env} ros2 daemon stop" >/dev/null 2>&1
sleep 2

out="$(_call)"
if echo "${out}" | grep -q "success=True"; then
  echo "[check] OK after daemon restart — puppy_control responding"
  exit 0
fi

echo "[check] FAILED — puppy_control not responding." >&2
echo "${out}" | tail -3 >&2
echo "[check] Is puppy_control launched, a single instance, and not ctrl-c'd?" >&2
echo "[check] See experiments/zenoh-mve/puppypi_test.md (Step 1)." >&2
exit 1
