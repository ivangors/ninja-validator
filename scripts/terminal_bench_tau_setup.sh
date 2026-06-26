#!/usr/bin/env bash
set -euo pipefail

if [ -z "${TAU_AGENT_REPO_URL:-}" ]; then
  echo "TAU_AGENT_REPO_URL is required"
  exit 1
fi

if ! command -v python >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1; then
  ln -s "$(command -v python3)" /usr/local/bin/python
fi

export DEBIAN_FRONTEND=noninteractive
if ! command -v git >/dev/null 2>&1; then
  apt-get update
  apt-get install -y --no-install-recommends git ca-certificates
fi

if ! command -v python >/dev/null 2>&1; then
  apt-get update
  apt-get install -y --no-install-recommends python3
  ln -s "$(command -v python3)" /usr/local/bin/python
fi

rm -rf /installed-agent/tau-agent
git clone --quiet --no-tags "$TAU_AGENT_REPO_URL" /installed-agent/tau-agent
cd /installed-agent/tau-agent
if [ -n "${TAU_AGENT_REF:-}" ]; then
  git fetch --quiet origin "$TAU_AGENT_REF" || true
  git checkout --quiet "$TAU_AGENT_REF"
fi
test -f agent.py

cat > /installed-agent/run_tau_agent.py <<'PY'
from __future__ import annotations

import importlib.util
import json
import os
import sys
import traceback
from pathlib import Path


def load_agent(agent_path: Path):
    spec = importlib.util.spec_from_file_location("tau_terminal_bench_agent", agent_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load agent from {agent_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    solve = getattr(module, "solve", None)
    if not callable(solve):
        raise RuntimeError(f"{agent_path} does not define solve(...)")
    return solve


def main() -> int:
    instruction = sys.argv[1] if len(sys.argv) > 1 else ""
    log_path = Path("/agent-logs/tau-terminal-bench-result.json")
    try:
        solve = load_agent(Path("/installed-agent/tau-agent/agent.py"))
        result = solve(
            repo_path="/app",
            issue=instruction,
            model=os.environ.get("TAU_MODEL") or None,
            api_base=os.environ.get("TAU_API_BASE") or None,
            api_key=os.environ.get("OPENROUTER_API_KEY") or None,
        )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(json.dumps({"ok": True, "result": result}, default=str), encoding="utf-8")
        return 0
    except Exception as exc:  # noqa: BLE001
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            json.dumps({"ok": False, "error": repr(exc), "traceback": traceback.format_exc()}),
            encoding="utf-8",
        )
        print(traceback.format_exc(), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
PY
