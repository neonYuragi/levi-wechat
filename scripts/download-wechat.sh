#!/usr/bin/env bash
set -euo pipefail

# Download the newest supported version for this architecture, as declared in
# docker/wechat-builds.yaml. The helper verifies version, arch, SHA256 and BuildID.

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
exec python3 "$ROOT_DIR/docker/download_wechat.py" "$@"
