#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

load_config_file() {
  local config_path="$1"
  local line key value

  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"

    [[ -z "$line" || "$line" == \#* ]] && continue
    [[ "$line" == export\ * ]] && line="${line#export }"
    [[ "$line" == *=* ]] || continue

    key="${line%%=*}"
    value="${line#*=}"
    key="${key%"${key##*[![:space:]]}"}"
    value="${value#"${value%%[![:space:]]*}"}"

    if [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ && -z "${!key+x}" ]]; then
      printf -v "$key" '%s' "$value"
      export "$key"
    fi
  done <"$config_path"
}

OPENPAVE_CONFIG="${OPENPAVE_CONFIG:-}"
if [[ -n "$OPENPAVE_CONFIG" ]]; then
  if [[ "$OPENPAVE_CONFIG" != /* ]]; then
    OPENPAVE_CONFIG="$ROOT/$OPENPAVE_CONFIG"
  fi
  if [[ ! -f "$OPENPAVE_CONFIG" ]]; then
    printf '[openpave][error] config file not found: %s\n' "$OPENPAVE_CONFIG" >&2
    exit 1
  fi
  load_config_file "$OPENPAVE_CONFIG"
fi

PYTHON_BIN="${OPENPAVE_PYTHON:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="${OPENPAVE_PYTHON:-python3}"
fi

RUN_DIR="${OPENPAVE_RUN_DIR:-$ROOT/.openpave/run}"
LOG_DIR="${OPENPAVE_LOG_DIR:-$ROOT/.openpave/logs}"
mkdir -p "$RUN_DIR" "$LOG_DIR"

INTENT_PATH="${INTENT_PATH:-/tmp/vla_intent.json}"
COMMAND_RESULT_PATH="${COMMAND_RESULT_PATH:-/tmp/vla_command_result.json}"
ROBOT_STATE_PATH="${ROBOT_STATE_PATH:-/tmp/vla_robot_state.json}"

INTENT_PORT="7071"
INTENT_INGRESS_URL="${INTENT_INGRESS_URL:-http://127.0.0.1:${INTENT_PORT}/intent}"

ROBOT_ADAPTER="${ROBOT_ADAPTER:-mock}"
STOP_ROBOT_ON_EXIT="${STOP_ROBOT_ON_EXIT:-1}"
STOP_ROBOT_ON_EXIT_TIMEOUT_SEC="${STOP_ROBOT_ON_EXIT_TIMEOUT_SEC:-3}"
ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"
RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}"
ROS_SVC_IMAGE="${ROS_SVC_IMAGE:-ros:humble}"
ROS_PUB_IMAGE="${ROS_PUB_IMAGE:-puppy-ros2-cli:humble}"

UI_HOST="${UI_HOST:-0.0.0.0}"
UI_PORT="${UI_PORT:-8090}"
UI_MODEL="${UI_MODEL:-llava-hf/llava-v1.6-mistral-7b-hf}"
UI_API_BASE="${UI_API_BASE:-http://localhost:8000/v1}"
UI_API_KEY="${UI_API_KEY:-EMPTY}"
ROBOT_IP_ADDRESS="${ROBOT_IP_ADDRESS:-192.168.0.8}"
UI_NO_SSL="${UI_NO_SSL:-1}"
UI_HOME="${UI_HOME:-/tmp}"
UI_PYTHONPATH="${PYTHONPATH:-}"
if [[ -d "$ROOT/ui/src" ]]; then
  if [[ -n "$UI_PYTHONPATH" ]]; then
    UI_PYTHONPATH="$ROOT/ui/src:$UI_PYTHONPATH"
  else
    UI_PYTHONPATH="$ROOT/ui/src"
  fi
fi

PIDS=()
SHUTTING_DOWN=0
STOP_SENT_ON_EXIT=0

log() {
  printf '[openpave] %s\n' "$*"
}

warn() {
  printf '[openpave][warn] %s\n' "$*" >&2
}

http_get() {
  local url="$1"
  if command -v curl >/dev/null 2>&1; then
    curl -fsS "$url" >/dev/null 2>&1
  else
    "$PYTHON_BIN" - "$url" <<'PY'
import sys
import urllib.request

try:
    with urllib.request.urlopen(sys.argv[1], timeout=1.5) as response:
        sys.exit(0 if 200 <= response.status < 500 else 1)
except Exception:
    sys.exit(1)
PY
  fi
}

wait_for_http() {
  local name="$1"
  local url="$2"
  local attempts="${3:-40}"
  local delay="${4:-0.25}"

  for _ in $(seq 1 "$attempts"); do
    if http_get "$url"; then
      log "$name ready: $url"
      return 0
    fi
    sleep "$delay"
  done

  warn "$name did not become ready: $url"
  return 1
}

start_process() {
  local name="$1"
  local logfile="$2"
  shift 2

  log "starting $name"
  log "  log: $logfile"
  "$@" >"$logfile" 2>&1 &
  local pid=$!
  PIDS+=("$pid")
  printf '%s\n' "$pid" >"$RUN_DIR/$name.pid"
  log "  pid: $pid"
}

post_stop_intent_on_exit() {
  if [[ "$STOP_SENT_ON_EXIT" == "1" ]]; then
    return 0
  fi
  STOP_SENT_ON_EXIT=1

  if [[ "$STOP_ROBOT_ON_EXIT" != "1" && "$STOP_ROBOT_ON_EXIT" != "true" ]]; then
    return 0
  fi
  if [[ "$ROBOT_ADAPTER" != "puppypi" ]]; then
    return 0
  fi
  if ! http_get "http://127.0.0.1:${INTENT_PORT}/healthz"; then
    warn "cannot send shutdown STOP because Intent Ingress is not reachable"
    return 0
  fi

  log "sending shutdown STOP intent for physical robot safety"
  if command -v curl >/dev/null 2>&1; then
    curl -fsS \
      -X POST "http://127.0.0.1:${INTENT_PORT}/intent" \
      -H 'Content-Type: application/json' \
      -d '{"intent":"STOP","source":"launcher-shutdown"}' >/dev/null 2>&1 || {
        warn "failed to send shutdown STOP intent"
        return 0
      }
  else
    "$PYTHON_BIN" - "http://127.0.0.1:${INTENT_PORT}/intent" <<'PY'
import json
import sys
import urllib.request

data = json.dumps({"intent": "STOP", "source": "launcher-shutdown"}).encode()
request = urllib.request.Request(
    sys.argv[1],
    data=data,
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(request, timeout=1.5):
        pass
except Exception:
    sys.exit(1)
PY
  fi

  sleep "$STOP_ROBOT_ON_EXIT_TIMEOUT_SEC"
}

shutdown() {
  local code=$?
  if [[ "$SHUTTING_DOWN" == "1" ]]; then
    exit "$code"
  fi
  SHUTTING_DOWN=1
  post_stop_intent_on_exit
  if [[ ${#PIDS[@]} -gt 0 ]]; then
    log "shutting down managed processes"
    for pid in "${PIDS[@]}"; do
      if kill -0 "$pid" >/dev/null 2>&1; then
        kill "$pid" >/dev/null 2>&1 || true
      fi
    done
    wait "${PIDS[@]}" >/dev/null 2>&1 || true
  fi
  exit "$code"
}
trap shutdown EXIT INT TERM

print_config() {
  cat <<EOF
[openpave] configuration
  ROOT=$ROOT
  OPENPAVE_CONFIG=${OPENPAVE_CONFIG:-}
  PYTHON_BIN=$PYTHON_BIN
  ROBOT_ADAPTER=$ROBOT_ADAPTER
  STOP_ROBOT_ON_EXIT=$STOP_ROBOT_ON_EXIT
  INTENT_PATH=$INTENT_PATH
  COMMAND_RESULT_PATH=$COMMAND_RESULT_PATH
  ROBOT_STATE_PATH=$ROBOT_STATE_PATH
  INTENT_INGRESS_URL=$INTENT_INGRESS_URL
  UI=http://127.0.0.1:$UI_PORT/
  PAVE=http://127.0.0.1:$UI_PORT/pave
  UI_API_BASE=$UI_API_BASE
  UI_MODEL=$UI_MODEL
  ROBOT_IP_ADDRESS=$ROBOT_IP_ADDRESS
  INTENT_FORWARDING_ENABLED=${INTENT_FORWARDING_ENABLED:-1}
  TROT_CONFIRMATIONS=${TROT_CONFIRMATIONS:-2}
  TROT_CONFIRMATION_WINDOW_MS=${TROT_CONFIRMATION_WINDOW_MS:-1500}
  LOG_DIR=$LOG_DIR
EOF
}

check_external_dependencies() {
  local models_url="${UI_API_BASE%/}/models"
  if http_get "$models_url"; then
    log "vLLM/OpenAI-compatible endpoint reachable: $models_url"
  else
    warn "vLLM/OpenAI-compatible endpoint not reachable: $models_url"
    warn "the UI can still start, but VLM inference will fail until the backend is running"
  fi

  if [[ "$ROBOT_ADAPTER" == "puppypi" ]]; then
    log "ROBOT_ADAPTER=puppypi selected; make sure the robot-side ROS2 controller is already running"
    log "  ROS_DOMAIN_ID=$ROS_DOMAIN_ID"
    log "  RMW_IMPLEMENTATION=$RMW_IMPLEMENTATION"
  else
    log "ROBOT_ADAPTER=$ROBOT_ADAPTER selected; physical robot commands are not expected unless the adapter targets hardware"
  fi
}

print_config
check_external_dependencies

start_process "intent_ingress" "$LOG_DIR/intent_ingress.log" \
  env PYTHONUNBUFFERED=1 \
  INTENT_PATH="$INTENT_PATH" \
  "$PYTHON_BIN" -m intent_ingress.server

wait_for_http "Intent Ingress" "http://127.0.0.1:${INTENT_PORT}/healthz"

start_process "control_daemon" "$LOG_DIR/control_daemon.log" \
  env PYTHONUNBUFFERED=1 \
  INTENT_PATH="$INTENT_PATH" \
  COMMAND_RESULT_PATH="$COMMAND_RESULT_PATH" \
  ROBOT_STATE_PATH="$ROBOT_STATE_PATH" \
  ROBOT_ADAPTER="$ROBOT_ADAPTER" \
  ROS_DOMAIN_ID="$ROS_DOMAIN_ID" \
  RMW_IMPLEMENTATION="$RMW_IMPLEMENTATION" \
  ROS_SVC_IMAGE="$ROS_SVC_IMAGE" \
  ROS_PUB_IMAGE="$ROS_PUB_IMAGE" \
  "$PYTHON_BIN" -m control_daemon.daemon

sleep 0.5

UI_CMD=(
  env
  HOME="$UI_HOME"
  PYTHONPATH="$UI_PYTHONPATH"
  INTENT_INGRESS_URL="$INTENT_INGRESS_URL"
  COMMAND_RESULT_PATH="$COMMAND_RESULT_PATH"
  ROBOT_STATE_PATH="$ROBOT_STATE_PATH"
  ROBOT_IP_ADDRESS="$ROBOT_IP_ADDRESS"
  INTENT_FORWARDING_ENABLED="${INTENT_FORWARDING_ENABLED:-1}"
  TROT_CONFIRMATIONS="${TROT_CONFIRMATIONS:-2}"
  TROT_CONFIRMATION_WINDOW_MS="${TROT_CONFIRMATION_WINDOW_MS:-1500}"
  PYTHONUNBUFFERED=1
  "$PYTHON_BIN"
  -B
  -m
  live_vlm_webui.server
  --host "$UI_HOST"
  --port "$UI_PORT"
  --model "$UI_MODEL"
  --api-base "$UI_API_BASE"
  --api-key "$UI_API_KEY"
)

if [[ "$UI_NO_SSL" == "1" || "$UI_NO_SSL" == "true" ]]; then
  UI_CMD+=(--no-ssl)
fi

start_process "openpave-ui" "$LOG_DIR/openpave-ui.log" "${UI_CMD[@]}"

wait_for_http "live-vlm-webui" "http://127.0.0.1:${UI_PORT}/" 80 0.25 || {
  warn "live-vlm-webui failed health check; inspect $LOG_DIR/openpave-ui.log"
}

if http_get "http://127.0.0.1:${UI_PORT}/pave"; then
  log "OpenPAVE console ready: http://127.0.0.1:${UI_PORT}/pave"
else
  warn "OpenPAVE /pave console is not available in the current live-vlm-webui checkout"
fi

cat <<EOF

[openpave] managed services are running

  Full live-vlm-webui:
    http://127.0.0.1:$UI_PORT/

  OpenPAVE console:
    http://127.0.0.1:$UI_PORT/pave

  Runtime debug files:
    $INTENT_PATH
    $COMMAND_RESULT_PATH
    $ROBOT_STATE_PATH

  Logs:
    $LOG_DIR/intent_ingress.log
    $LOG_DIR/control_daemon.log
    $LOG_DIR/openpave-ui.log

[openpave] press Ctrl+C to stop managed services

EOF

while true; do
  sleep 3600
done
