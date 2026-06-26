from __future__ import annotations

import os
import shlex
from pathlib import Path

from terminal_bench_tau_agent import AbstractInstalledAgent, TerminalCommand


def _env_value(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default)


def openrouter_model_name(model_name: str) -> str:
    return model_name if model_name.startswith("openrouter/") else f"openrouter/{model_name}"


def setup_script_path() -> Path:
    return Path(__file__).resolve().parents[1] / "scripts" / "terminal_bench_mini_swe_setup.sh"


class TauMiniSweAgent(AbstractInstalledAgent):
    @staticmethod
    def name() -> str:
        return "tau-mini-swe-agent"

    def __init__(self, model_name: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._model_name = openrouter_model_name(model_name)

    @property
    def _env(self) -> dict[str, str]:
        openrouter_key = _env_value("OPENROUTER_API_KEY")
        return {
            "MSWEA_CONFIGURED": "true",
            "MSWEA_API_KEY": _env_value("MSWEA_API_KEY", openrouter_key),
            "OPENROUTER_API_KEY": openrouter_key,
            "MSWEA_COST_TRACKING": "ignore_errors",
            "NO_COLOR": "1",
        }

    @property
    def _install_agent_script_path(self) -> Path:
        return setup_script_path()

    def _run_agent_commands(self, instruction: str) -> list[TerminalCommand]:
        escaped_instruction = shlex.quote(instruction)
        return [
            TerminalCommand(
                command=f"mini -m {shlex.quote(self._model_name)} -t {escaped_instruction} -y --exit-immediately",
                min_timeout_sec=0.0,
                max_timeout_sec=float("inf"),
                block=True,
                append_enter=True,
            ),
        ]
