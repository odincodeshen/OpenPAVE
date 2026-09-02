#!/usr/bin/env bash
# Deploy the minimal OpenPAVE seam bundle to a remote host (a brain, or a body without the repo).
#
#   usage: scripts/deploy_seam.sh <ssh-host> [dest_dir] [venv_python]
#     <ssh-host>     e.g. odin@192.168.0.24   (a brain)  or  radxa@192.168.0.5
#     [dest_dir]     remote install dir, default ~/openpave-seam  ($HOME expands on the remote)
#     [venv_python]  if given, pip-installs requirements-seam.txt into it on the remote
#
# Bundles pave_runtime/ + scripts/{seam_cli.py,seam_run.sh} + configs/ + requirements-seam*.txt
# (no __pycache__), so the remote can run, from <dest_dir>:
#   scripts/seam_run.sh configs/<recipe>.env brain send home     # brain
#   scripts/seam_run.sh configs/<recipe>.env body                # body (adds control_daemon if serving)
#
# The brain needs no control_daemon (seam_cli imports the adapter lazily). A *body* that serves a
# real adapter (e.g. camera_usb) also needs control_daemon/ on PYTHONPATH — deploy the full repo on
# such a host instead, or extend this bundle. See docs/seam-validation-runbook.md.
set -euo pipefail

host="${1:-}"
if [ -z "$host" ]; then
  echo "usage: $0 <ssh-host> [dest_dir] [venv_python]" >&2; exit 2
fi
dest="${2:-\$HOME/openpave-seam}"   # deliberately unexpanded here; $HOME resolves on the remote
venv_py="${3:-}"

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

for f in pave_runtime scripts/seam_cli.py scripts/seam_run.sh configs requirements-seam.txt; do
  [ -e "$f" ] || { echo "deploy_seam: missing $f (run from a full checkout)" >&2; exit 2; }
done

tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT
COPYFILE_DISABLE=1 tar czf "$tmp" --exclude='__pycache__' \
  pave_runtime scripts/seam_cli.py scripts/seam_run.sh configs \
  requirements-seam.txt requirements-seam-camera.txt

echo "[deploy_seam] $host:$dest"
scp -q "$tmp" "$host:/tmp/openpave-seam.tgz"
ssh "$host" "rm -rf $dest && mkdir -p $dest && tar xzf /tmp/openpave-seam.tgz -C $dest && rm -f /tmp/openpave-seam.tgz && echo '  extracted to '$dest"

if [ -n "$venv_py" ]; then
  echo "[deploy_seam] pip install -r requirements-seam.txt into $venv_py"
  ssh "$host" "$venv_py -m pip install -q -r $dest/requirements-seam.txt && echo '  seam deps installed'"
fi

echo "[deploy_seam] done."
