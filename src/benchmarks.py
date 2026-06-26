from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, replace
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BenchmarkSpec:
    name: str
    description: str
    source_url: str
    install_hint: str
    default_command: tuple[str, ...]
    default_dataset: str | None = None
    default_split: str | None = None


@dataclass(frozen=True, slots=True)
class RunloopBenchmarkSpec:
    name: str
    benchmark_id: str
    description: str
    source_url: str


@dataclass(frozen=True, slots=True)
class BenchmarkRun:
    name: str
    command: tuple[str, ...]
    output_dir: Path
    source_url: str
    description: str

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["command"] = list(self.command)
        payload["output_dir"] = str(self.output_dir)
        return payload


BENCHMARK_SPECS: tuple[BenchmarkSpec, ...] = (
    BenchmarkSpec(
        name="rebench",
        description="Fresh SWE-rebench issue/PR tasks in SWE-bench format.",
        source_url="https://swe-rebench.com/",
        install_hint=(
            "Use mini-swe-agent or SWE-rebench's SWE-bench fork with the "
            "nebius/SWE-rebench-leaderboard dataset."
        ),
        default_command=(
            "mini-extra",
            "swebench",
            "--dataset",
            "nebius/SWE-rebench-leaderboard",
            "--split",
            "2026_05",
        ),
        default_dataset="nebius/SWE-rebench-leaderboard",
        default_split="2026_05",
    ),
    BenchmarkSpec(
        name="deepswe",
        description="Datacurve DeepSWE original long-horizon coding-agent tasks.",
        source_url="https://github.com/datacurve-ai/deep-swe",
        install_hint="Install Pier with `uv tool install datacurve-pier` and clone datacurve-ai/deep-swe.",
        default_command=(
            "pier",
            "run",
            "-p",
            "deep-swe/tasks",
            "--agent",
            "mini-swe-agent",
        ),
    ),
    BenchmarkSpec(
        name="terminal-bench",
        description="Terminal-Bench task completion in sandboxed command-line environments.",
        source_url="https://www.tbench.ai/",
        install_hint="Install the Terminal-Bench CLI, then confirm available datasets with `tb datasets list`.",
        default_command=(
            "tb",
            "run",
            "--dataset",
            "terminal-bench-core==0.1.1",
            "--agent",
            "terminus",
        ),
        default_dataset="terminal-bench-core==0.1.1",
    ),
)

RUNLOOP_BENCHMARK_SPECS: tuple[RunloopBenchmarkSpec, ...] = (
    RunloopBenchmarkSpec(
        name="swe-bench-verified",
        benchmark_id="swe-bench-verified",
        description="Runloop public SWE-bench Verified benchmark.",
        source_url="https://runloop.ai/public-benchmarks",
    ),
    RunloopBenchmarkSpec(
        name="terminal-bench",
        benchmark_id="terminal-bench-2",
        description="Runloop public Terminal-Bench benchmark.",
        source_url="https://runloop.ai/public-benchmarks",
    ),
)

PRESET_TASK_COUNTS = {
    "smoke": 1,
    "mini": 3,
    "nightly": 25,
}


def benchmark_specs_by_name(specs: tuple[BenchmarkSpec, ...] = BENCHMARK_SPECS) -> dict[str, BenchmarkSpec]:
    return {spec.name: spec for spec in specs}


def runloop_specs_by_name(
    specs: tuple[RunloopBenchmarkSpec, ...] = RUNLOOP_BENCHMARK_SPECS,
) -> dict[str, RunloopBenchmarkSpec]:
    return {spec.name: spec for spec in specs}


def selected_benchmark_specs(names: list[str] | None) -> tuple[BenchmarkSpec, ...]:
    specs_by_name = benchmark_specs_by_name()
    if not names:
        return BENCHMARK_SPECS

    unknown_names = sorted(set(names) - set(specs_by_name))
    if unknown_names:
        known = ", ".join(sorted(specs_by_name))
        unknown = ", ".join(unknown_names)
        raise ValueError(f"Unknown benchmark(s): {unknown}. Known benchmarks: {known}")
    return tuple(specs_by_name[name] for name in names)


def selected_runloop_specs(names: list[str] | None) -> tuple[RunloopBenchmarkSpec, ...]:
    specs_by_name = runloop_specs_by_name()
    if not names:
        return RUNLOOP_BENCHMARK_SPECS

    unknown_names = sorted(set(names) - set(specs_by_name))
    if unknown_names:
        known = ", ".join(sorted(specs_by_name))
        unknown = ", ".join(unknown_names)
        raise ValueError(f"Unknown Runloop benchmark(s): {unknown}. Known benchmarks: {known}")
    return tuple(specs_by_name[name] for name in names)


def task_count_for_preset(*, preset: str | None, n_tasks: int | None) -> int | None:
    if n_tasks is not None:
        return n_tasks
    if preset is None:
        return None
    return PRESET_TASK_COUNTS[preset]


def command_with_overrides(
    spec: BenchmarkSpec,
    *,
    agent: str | None,
    model: str | None,
    n_tasks: int | None,
    sample_seed: int | None,
) -> tuple[str, ...]:
    command = spec.default_command
    command = _replace_or_append_option(command, "--agent", agent)
    command = _append_option(command, "--model", model)
    command = _append_option(command, "--n-tasks", str(n_tasks) if n_tasks is not None else None)
    command = _append_option(
        command,
        "--sample-seed",
        str(sample_seed) if sample_seed is not None else None,
    )
    return command


def runloop_command(
    spec: RunloopBenchmarkSpec,
    *,
    agents: tuple[str, ...],
    scenario_ids: tuple[str, ...],
    timeout: int | None,
    n_concurrent_trials: int | None,
    run_name: str,
) -> tuple[str, ...]:
    command = (
        "rli",
        "benchmark-job",
        "run",
    )
    for agent in agents:
        command = (*command, "--agent", agent)
    command = (
        (*command, "--scenarios", *scenario_ids)
        if scenario_ids
        else (*command, "--benchmark", spec.benchmark_id)
    )
    command = (*command, "-n", run_name)
    command = _append_option(command, "--timeout", str(timeout) if timeout is not None else None)
    return _append_option(
        command,
        "--n-concurrent-trials",
        str(n_concurrent_trials) if n_concurrent_trials is not None else None,
    )


def runloop_timeout_for_preset(preset: str | None) -> int | None:
    if preset == "smoke":
        return 120
    if preset == "mini":
        return 300
    return None


def runloop_concurrency_for_preset(preset: str | None) -> int | None:
    if preset in {"smoke", "mini"}:
        return 10
    if preset == "nightly":
        return 50
    return None


def benchmark_runs(
    *,
    names: list[str] | None,
    agent: str | None,
    model: str | None,
    n_tasks: int | None,
    sample_seed: int | None,
    output_root: Path,
) -> tuple[BenchmarkRun, ...]:
    return tuple(
        BenchmarkRun(
            name=spec.name,
            command=command_with_overrides(
                spec,
                agent=agent,
                model=model,
                n_tasks=n_tasks,
                sample_seed=sample_seed,
            ),
            output_dir=output_root / spec.name,
            source_url=spec.source_url,
            description=spec.description,
        )
        for spec in selected_benchmark_specs(names)
    )


def runloop_benchmark_runs(
    *,
    names: list[str] | None,
    agent: str,
    baseline: str | None,
    scenario_ids: tuple[str, ...],
    timeout: int | None,
    n_concurrent_trials: int | None,
    output_root: Path,
) -> tuple[BenchmarkRun, ...]:
    agents = (agent,) if baseline is None else (agent, baseline)
    return tuple(
        BenchmarkRun(
            name=f"runloop-{spec.name}",
            command=runloop_command(
                spec,
                agents=agents,
                scenario_ids=scenario_ids,
                timeout=timeout,
                n_concurrent_trials=n_concurrent_trials,
                run_name=f"tau-{spec.name}",
            ),
            output_dir=output_root / "runloop" / spec.name,
            source_url=spec.source_url,
            description=spec.description,
        )
        for spec in selected_runloop_specs(names)
    )


def run_benchmark_plan(runs: tuple[BenchmarkRun, ...], *, dry_run: bool) -> list[dict]:
    return [_run_or_describe(run, dry_run=dry_run) for run in runs]


def write_benchmark_report(report_path: Path, report: list[dict]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def specs_as_dicts(specs: tuple[BenchmarkSpec, ...] = BENCHMARK_SPECS) -> list[dict]:
    return [
        {
            **asdict(replace(spec, default_command=tuple(spec.default_command))),
            "default_command": list(spec.default_command),
        }
        for spec in specs
    ]


def runloop_specs_as_dicts(
    specs: tuple[RunloopBenchmarkSpec, ...] = RUNLOOP_BENCHMARK_SPECS,
) -> list[dict]:
    return [asdict(spec) for spec in specs]


def _run_or_describe(run: BenchmarkRun, *, dry_run: bool) -> dict:
    if dry_run:
        return {**run.to_dict(), "status": "planned", "returncode": None}

    run.output_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        run.command,
        cwd=run.output_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    (run.output_dir / "stdout.txt").write_text(result.stdout, encoding="utf-8")
    (run.output_dir / "stderr.txt").write_text(result.stderr, encoding="utf-8")
    return {
        **run.to_dict(),
        "status": "passed" if result.returncode == 0 else "failed",
        "returncode": result.returncode,
    }


def _append_option(command: tuple[str, ...], option: str, value: str | None) -> tuple[str, ...]:
    if value is None:
        return command
    return (*command, option, value)


def _replace_or_append_option(command: tuple[str, ...], option: str, value: str | None) -> tuple[str, ...]:
    if value is None or option not in command:
        return _append_option(command, option, value)

    index = command.index(option)
    if index == len(command) - 1:
        return command
    return (*command[: index + 1], value, *command[index + 2 :])
