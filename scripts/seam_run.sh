#!/usr/bin/env bash
# Run one seam endpoint from a four-dimension OpenPAVE recipe (configs/*.env).
#
#   usage: scripts/seam_run.sh <recipe.env> <body|brain> [seam_cli args...]
#     body                  -> seam_cli.py serve      (on the body host, e.g. PuppyPi)
#     brain send ACTION ..  -> seam_cli.py send ..     (on the brain host, e.g. DGX / Radxa O6)
#
# The recipe pins the four dimensions; this launcher binds SEAM_TRANSPORT + BODY_HOST into the
# transport's wire env, so the *same* recipe drives both endpoints:
#   raw_zenoh       body  -> ZENOH_LISTEN=tcp/0.0.0.0:$SEAM_ZENOH_PORT
#                   brain -> ZENOH_CONNECT=tcp/$BODY_HOST:$SEAM_ZENOH_PORT
#   device_connect  both  -> DEVICE_CONNECT_ALLOW_INSECURE=true  (D2D, zenoh multicast, no infra)
#
# seam_cli.py is located next to this script, and PYTHONPATH defaults to the repo root, so the
# launcher works both from a full checkout and from a minimal brain deploy (this script +
# pave_runtime/ + scripts/seam_cli.py under one directory).
set -euo pipefail

recipe="${1:-}"; role="${2:-}"
if [ -z "$recipe" ] || [ -z "$role" ]; then
  echo "usage: $0 <recipe.env> <body|brain> [seam_cli args...]" >&2; exit 2
fi
shift 2
[ -f "$recipe" ] || { echo "seam_run: recipe not found: $recipe" >&2; exit 2; }

set -a; . "$recipe"; set +a
: "${SEAM_TRANSPORT:?recipe must set SEAM_TRANSPORT}"
port="${SEAM_ZENOH_PORT:-7447}"

case "$SEAM_TRANSPORT" in
  raw_zenoh)
    if [ "$role" = body ]; then
      export ZENOH_LISTEN="tcp/0.0.0.0:$port"
    else
      : "${BODY_HOST:?recipe must set BODY_HOST for a raw_zenoh brain}"
      export ZENOH_CONNECT="tcp/$BODY_HOST:$port"
    fi ;;
  device_connect)
    export DEVICE_CONNECT_ALLOW_INSECURE="${DEVICE_CONNECT_ALLOW_INSECURE:-true}" ;;
  *) echo "seam_run: unknown SEAM_TRANSPORT=$SEAM_TRANSPORT" >&2; exit 2 ;;
esac

root="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="${PYTHONPATH:-$root}"

case "$role" in
  body)  py="${BODY_PYTHON:-python3}";  set -- serve ;;
  brain) py="${BRAIN_PYTHON:-python3}"
         [ "$#" -gt 0 ] || { echo "seam_run: brain needs a command, e.g. 'send home'" >&2; exit 2; } ;;
  *) echo "seam_run: role must be 'body' or 'brain', got '$role'" >&2; exit 2 ;;
esac

echo "[seam_run] recipe=$(basename "$recipe") role=$role transport=$SEAM_TRANSPORT py=$py" >&2
exec "$py" "$root/scripts/seam_cli.py" "$@"
