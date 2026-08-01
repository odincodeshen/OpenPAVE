#!/usr/bin/env bash
#
# One-command switch: PuppyPi ROS 1 (boot default) -> ROS 2 + OpenPAVE bridge.
# Run ON the robot. The box boots into ROS 1 (noetic, auto-start); run this when you
# want OpenPAVE's ROS 2 control plane. Captures the validated 2026-08-01 bring-up:
#
#   1. stop ROS 1 (puppypi)     -> frees the servo-board serial bus (both can't own it)
#   2. stop hiwonder `test`     -> frees TCP :8787 + de-noises DDS domain 0
#   3. start ROS 2 puppy_control (detached launch + health check)
#   4. start the OpenPAVE bridge INSIDE puppypi_ros2 (same ROS graph as puppy_control)
#   5. health ping is done by start_bridge.sh itself
#
# The dog will stand up in step 3 (controller takes over). Have it on the floor / elevated.
#
# To go back to ROS 1: just reboot (boot default is ROS 1), or:
#   docker stop puppypi_ros2 && docker start puppypi
#
# Env overrides: OPENPAVE_DIR (~/OpenPAVE), OPENPAVE_BRIDGE_DIR (~/openpave-bridge)
set -uo pipefail

log() { printf '[puppypi-ros2] %s\n' "$*"; }

OPENPAVE_DIR="${OPENPAVE_DIR:-$HOME/OpenPAVE}"
BRIDGE_DIR="${OPENPAVE_BRIDGE_DIR:-$HOME/openpave-bridge}"

command -v docker >/dev/null 2>&1 || { log "docker not found"; exit 1; }
[ -f "$OPENPAVE_DIR/scripts/start_puppy_control.sh" ] || { log "missing $OPENPAVE_DIR/scripts/start_puppy_control.sh"; exit 1; }
[ -f "$BRIDGE_DIR/start_bridge.sh" ] || { log "missing $BRIDGE_DIR/start_bridge.sh"; exit 1; }

log "1/4 stop ROS 1 (puppypi) — frees servo serial"
docker stop puppypi >/dev/null 2>&1 || true

log "2/4 stop hiwonder stack (test) — frees :8787 + DDS domain 0"
docker stop test >/dev/null 2>&1 || true

log "3/4 start ROS 2 puppy_control"
bash "$OPENPAVE_DIR/scripts/start_puppy_control.sh"

log "4/4 start OpenPAVE bridge in puppypi_ros2"
( cd "$BRIDGE_DIR" && PUPPY_EXEC_CONTAINER=puppypi_ros2 bash start_bridge.sh )

log "done — ROS 2 puppy_control + bridge up (ping above should show ready=True)."
log "next: start a body, e.g.  ROBOT_ADAPTER=puppypi_bridge PUPPY_BRIDGE_HOST=127.0.0.1 <body>"
