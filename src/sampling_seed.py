from __future__ import annotations

import hashlib
import os

# Greedy decoding uses temperature=0; low top_p is belt-and-suspenders for sampling APIs.
VALIDATOR_TOP_P = float(os.environ.get("TAU_TOP_P", "0.01"))


def deterministic_sampling_seed(*, configured: int | None = None, material: str = "") -> int:
    """Return the sampling seed: a constant 42.

    At temperature 0 (greedy) the seed does not affect the output, so there is no
    reason to derive it from ``material`` (kept for call-site compatibility but
    ignored). An explicit ``configured`` value (TAU_*_SEED) still overrides.
    """
    if configured is not None:
        return int(configured) & 0x7FFFFFFF
    return 42


def judge_seed_material(
    *,
    task_name: str,
    model: str,
    king_patch: str,
    challenger_patch: str,
) -> str:
    patch_digest = hashlib.sha256(f"{king_patch}\0{challenger_patch}".encode("utf-8")).hexdigest()
    return f"judge:{task_name}:{model}:{patch_digest}"


def solver_seed_material(*, task_name: str, solution_name: str, agent_hash: str) -> str:
    return f"solver:{task_name}:{solution_name}:{agent_hash}"
