#!/usr/bin/env bash
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
if ! command -v python >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1; then
  ln -s "$(command -v python3)" /usr/local/bin/python
fi

if ! command -v pip3 >/dev/null 2>&1; then
  apt-get update
  apt-get install -y --no-install-recommends python3 python3-pip ca-certificates
fi

python -m pip install --break-system-packages --upgrade pip
python -m pip install --break-system-packages mini-swe-agent
mini --help >/dev/null
