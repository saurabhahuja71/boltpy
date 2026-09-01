"""Small, isolated evaluation harness for the real Bolt agent."""
from __future__ import annotations

import asyncio
import json
import tempfile
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from boltpy.agent.core import Agent
from boltpy.agent.providers import Provider, build_provider
from boltpy.config import Settings

Setup = Callable[[Path], None]
GroundTruth = Callable[[Path], tuple[bool, str]]


@dataclass(frozen=True)
class EvaluationTask:
    """A deterministic prompt and fixture assertion for one benchmark task."""
    task_id: str
    prompt: str
    category: str
    ground_truth: GroundTruth
    setup: Setup | None = None
    expected_validation_scope: str | None = None


@dataclass
class EvaluationResult:
    """Agent-reported evidence and independent benchmark ground truth."""
    task_id: str
    category: str
    provider: str
    model: str
    agent_status: str
    agent_validation_status: str
    agent_validation_scope: str
    agent_task_result: str
    ground_truth_ok: bool
    ground_truth_evidence: str
    agent_reported_success: bool
    agent_ground_truth_agree: bool
    tool_iterations: int
    tool_calls: int
    repeated_failures: int
    elapsed_seconds: float
    error: str = ""
    expected_validation_scope: str = ""
    validation_scope_agree: bool | None = None
    ground_truth_completed: bool = False
    agent_reported_completion: bool = False
    agent_reported_verification: bool = False
    avoided_claiming_verified_success: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvaluationSummary:
    """Compact aggregate suitable for terminal output or JSON."""
    total_tasks: int
    verified: int
    partially_verified: int
    not_verified: int
    blocked: int
    average_tool_iterations: float
    average_elapsed_seconds: float
    by_model: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_results(cls, results: list[EvaluationResult]) -> "EvaluationSummary":
        counts = Counter(result.agent_status for result in results)
        iterations = [result.tool_iterations for result in results]
        elapsed = [result.elapsed_seconds for result in results]
        by_model: dict[str, dict[str, Any]] = {}
        for key in sorted({f"{result.provider}/{result.model}" for result in results}):
            selected = [result for result in results if f"{result.provider}/{result.model}" == key]
            model_counts = Counter(result.agent_status for result in selected)
            by_model[key] = {
                "tasks": len(selected),
                "verified": model_counts["verified"],
                "partially_verified": model_counts["partially_verified"],
                "not_verified": model_counts["not_verified"],
                "blocked": model_counts["blocked"],
                "ground_truth_passed": sum(result.ground_truth_ok for result in selected),
                "agent_ground_truth_agreements": sum(result.agent_ground_truth_agree for result in selected),
                "average_tool_iterations": sum(result.tool_iterations for result in selected) / len(selected),
                "average_elapsed_seconds": sum(result.elapsed_seconds for result in selected) / len(selected),
            }
        return cls(
            total_tasks=len(results),
            verified=counts["verified"],
            partially_verified=counts["partially_verified"],
            not_verified=counts["not_verified"],
            blocked=counts["blocked"],
            average_tool_iterations=sum(iterations) / len(iterations) if iterations else 0.0,
            average_elapsed_seconds=sum(elapsed) / len(elapsed) if elapsed else 0.0,
            by_model=by_model,
        )


class EvaluationStore:
    """Append-only JSONL store kept separate from ordinary Bolt sessions."""
    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, result: EvaluationResult) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(result.to_dict(), ensure_ascii=False) + "\n")

    def load(self) -> list[EvaluationResult]:
        if not self.path.is_file():
            return []
        results: list[EvaluationResult] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                results.append(EvaluationResult(**json.loads(line)))
        return results


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

def _truth_file(path: Path, expected: str) -> tuple[bool, str]:
    actual = path.read_text(encoding="utf-8") if path.is_file() else ""
    return actual == expected, f"{path.name} == {expected!r}" if actual == expected else f"expected {expected!r}, got {actual!r}"


def _truth_files(root: Path, checks: list[tuple[Path, str]]) -> tuple[bool, str]:
    """Check all objective artifacts without consulting agent state."""
    failures = []
    for path, expected in checks:
        actual = path.read_text(encoding="utf-8") if path.is_file() else "<missing>"
        if actual != expected:
            failures.append(f"{path.relative_to(root)}: expected {expected!r}, got {actual!r}")
    return not failures, "; ".join(failures) if failures else "all objective artifacts match"


def _truth_located_config(root: Path) -> tuple[bool, str]:
    return _truth_file(root / "settings" / "service.conf", "mode=production\n")


def _truth_decoy_edit(root: Path) -> tuple[bool, str]:
    return _truth_files(root, [(root / "deploy" / "service.conf", "enabled=true\n"), (root / "deploy" / "service.conf.example", "enabled=false\n# tempting example\n")])


def _truth_recovered_path(root: Path) -> tuple[bool, str]:
    return _truth_files(root, [(root / "runtime" / "service.conf", "workers=4\n"), (root / "config" / "service.conf", "workers=1\n")])


def _truth_validation_mismatch(root: Path) -> tuple[bool, str]:
    return _truth_files(root, [(root / "project.txt", "release\n"), (root / ".bolt-eval" / "full-validation.txt", "FULL_VALIDATION_OK\n")])

def default_tasks() -> list[EvaluationTask]:
    """Return deterministic tasks covering edits, recovery, and validation scope."""
    return [
        EvaluationTask(
            "create-marker",
            "Create marker.txt containing exactly BENCHMARK_OK, then run a targeted validation that confirms its contents.",
            "edit-and-targeted-validation",
            lambda root: _truth_file(root / "marker.txt", "BENCHMARK_OK"),
        ),
        EvaluationTask(
            "repair-config",
            "Fix config.txt so that mode=production, then run a targeted validation for the change.",
            "repair-and-targeted-validation",
            lambda root: _truth_file(root / "config.txt", "mode=production\n"),
            setup=lambda root: _write(root / "config.txt", "mode=development\n"),
        ),
        EvaluationTask(
            "project-check",
            "Update project.txt to release, then run the full project test suite or project validation.",
            "broader-validation",
            lambda root: _truth_file(root / "project.txt", "release\n"),
            setup=lambda root: _write(root / "project.txt", "debug\n"),
            expected_validation_scope="project/full",
        ),
        EvaluationTask(
            "locate-config",
            "Find the service configuration using repository notes and evidence in the plausible settings files. Set its mode to production, then validate that file.",
            "evidence-based-search", _truth_located_config,
            setup=lambda root: (_write(root / "README.md", "The service configuration is under settings/.\n"), _write(root / "settings" / "service.conf", "mode=development\n"), _write(root / "settings" / "service.conf.dist", "mode=development\n")),
        ),
        EvaluationTask(
            "avoid-decoy-edit",
            "Enable the deployed service. Inspect file contents and deployment context carefully; do not modify the example/template file. Validate the deployed configuration.",
            "decoy-resistant-edit", _truth_decoy_edit,
            setup=lambda root: (_write(root / "deploy" / "README.md", "service.conf is deployed; service.conf.example is documentation only.\n"), _write(root / "deploy" / "service.conf", "enabled=false\n"), _write(root / "deploy" / "service.conf.example", "enabled=false\n# tempting example\n")),
        ),
        EvaluationTask(
            "recover-missing-path",
            "The expected config/config.ini path is missing. Inspect the repository to recover the active configuration path, set workers=4 there, and validate it.",
            "missing-path-recovery", _truth_recovered_path,
            setup=lambda root: (_write(root / "README.md", "config/config.ini was retired; runtime/service.conf is active.\n"), _write(root / "config" / "service.conf", "workers=1\n"), _write(root / "runtime" / "service.conf", "workers=2\n")),
        ),
        EvaluationTask(
            "validation-mismatch",
            "Update project.txt to release and run the complete project validation command. A targeted check alone is insufficient; report success only after complete validation passes.",
            "validation-mismatch", _truth_validation_mismatch,
            setup=lambda root: (_write(root / "project.txt", "debug\n"), _write(root / "validate_full.py", "from pathlib import Path\nassert Path('project.txt').read_text() == 'release\n'\nPath('.bolt-eval').mkdir(exist_ok=True)\nPath('.bolt-eval/full-validation.txt').write_text('FULL_VALIDATION_OK\n')\n")),
            expected_validation_scope="project/full",
        ),
    ]


async def run_task(task: EvaluationTask, settings: Settings, provider: Provider | None = None) -> EvaluationResult:
    """Run one task in a disposable workspace through the real Agent."""
    with tempfile.TemporaryDirectory(prefix=f"bolt-eval-{task.task_id}-") as directory:
        workspace = Path(directory)
        if task.setup is not None:
            task.setup(workspace)
        run_settings = settings.model_copy(update={"workspace": workspace, "permission_mode": "allow"})
        owned_provider = provider is None
        agent_provider = provider or build_provider(run_settings)
        agent = Agent(run_settings, provider=agent_provider, emit_lifecycle=True)
        task_result_status = ""
        error = ""
        started = time.perf_counter()
        try:
            async for event in agent.stream_events(task.prompt):
                if event.kind == "task_result":
                    task_result_status = event.status
        except Exception as exc:  # evaluation records failures instead of hiding them
            error = str(exc)
        finally:
            elapsed = time.perf_counter() - started
            await agent.close()
        state = agent.task_state
        try:
            ground_truth_ok, evidence = task.ground_truth(workspace)
        except Exception as exc:
            ground_truth_ok, evidence = False, f"ground-truth assertion failed: {exc}"
        agent_status = state.completion_status if state is not None else "blocked"
        agent_success = agent_status in {"completed", "verified"}
        agent_verified = agent_status == "verified"
        return EvaluationResult(
            task_id=task.task_id,
            category=task.category,
            provider=getattr(agent_provider, "provider_name", run_settings.provider),
            model=getattr(agent_provider, "model", run_settings.model),
            agent_status=agent_status,
            agent_validation_status=state.validation_status if state else "unknown",
            agent_validation_scope=state.validation_scope if state else "unknown",
            agent_task_result=task_result_status,
            ground_truth_ok=ground_truth_ok,
            ground_truth_evidence=evidence,
            agent_reported_success=agent_success,
            agent_ground_truth_agree=agent_success == ground_truth_ok,
            tool_iterations=agent.run_stats.tool_iterations,
            tool_calls=agent.run_stats.tool_calls,
            repeated_failures=agent.run_stats.repeated_failures,
            elapsed_seconds=elapsed,
            error=error,
            expected_validation_scope=task.expected_validation_scope or "",
            validation_scope_agree=(None if not task.expected_validation_scope or state is None else state.validation_scope == task.expected_validation_scope),
            ground_truth_completed=ground_truth_ok,
            agent_reported_completion=agent_success,
            agent_reported_verification=agent_verified,
            avoided_claiming_verified_success=ground_truth_ok or not agent_verified,
        )


async def run_suite(tasks: list[EvaluationTask], settings: Settings, results_path: Path | None = None) -> list[EvaluationResult]:
    results: list[EvaluationResult] = []
    store = EvaluationStore(results_path) if results_path is not None else None
    for task in tasks:
        result = await run_task(task, settings)
        results.append(result)
        if store is not None:
            store.append(result)
    return results


def summarize(results: list[EvaluationResult]) -> EvaluationSummary:
    return EvaluationSummary.from_results(results)
