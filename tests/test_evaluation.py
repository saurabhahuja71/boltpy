from dataclasses import replace

import pytest

from boltpy.agent.providers import ProviderEvent
from boltpy.config import Settings
from boltpy.evaluation import EvaluationResult, EvaluationStore, EvaluationTask, default_tasks, run_task, summarize


class FixtureProvider:
    provider_name = "fake"
    model = "fixture-model"

    def __init__(self):
        self.turn = 0

    async def stream_response(self, messages, tools):
        if self.turn == 0:
            self.turn += 1
            yield ProviderEvent("tool_call", call_id="create", name="create_file", arguments='{"path":"marker.txt","content":"OK"}')
        elif self.turn == 1:
            self.turn += 1
            yield ProviderEvent("tool_call", call_id="validate", name="run_command", arguments='{"command":"python -m compileall -q ."}')
        else:
            yield ProviderEvent("text", text="validated")

    async def close(self):
        pass


def marker_task() -> EvaluationTask:
    return EvaluationTask(
        task_id="fixture-marker",
        prompt="Create marker.txt and run a targeted validation.",
        category="fixture",
        setup=lambda root: None,
        ground_truth=lambda root: (
            (root / "marker.txt").read_text(encoding="utf-8") == "OK",
            "marker contents are exact",
        ),
    )


@pytest.mark.asyncio
async def test_evaluation_runs_real_agent_and_keeps_ground_truth_separate(tmp_path):
    provider = FixtureProvider()
    result = await run_task(marker_task(), Settings(workspace=tmp_path), provider=provider)
    assert result.ground_truth_ok
    assert result.agent_status == "verified"
    assert result.agent_reported_success
    assert result.agent_ground_truth_agree
    assert result.tool_iterations == 2
    assert result.tool_calls == 2
    assert result.elapsed_seconds >= 0


def test_evaluation_summary_aggregates_status_and_model_metrics():
    result = EvaluationResult(
        task_id="one", category="fixture", provider="fake", model="m1",
        agent_status="verified", agent_validation_status="passed", agent_validation_scope="targeted",
        agent_task_result="verified", ground_truth_ok=True, ground_truth_evidence="ok",
        agent_reported_success=True, agent_ground_truth_agree=True, tool_iterations=2,
        tool_calls=3, repeated_failures=0, elapsed_seconds=1.0,
    )
    other = replace(result, task_id="two", agent_status="blocked", ground_truth_ok=False, agent_reported_success=False, agent_ground_truth_agree=True)
    summary = summarize([result, other])
    assert (summary.total_tasks, summary.verified, summary.blocked) == (2, 1, 1)
    assert summary.by_model["fake/m1"]["ground_truth_passed"] == 1
    assert summary.by_model["fake/m1"]["agent_ground_truth_agreements"] == 2
    assert summary.average_tool_iterations == 2


def test_evaluation_store_is_append_only_and_separate_from_sessions(tmp_path):
    path = tmp_path / ".bolt" / "evaluations" / "results.jsonl"
    result = EvaluationResult(
        task_id="one", category="fixture", provider="fake", model="m1",
        agent_status="not_verified", agent_validation_status="not_run", agent_validation_scope="unknown",
        agent_task_result="not_verified", ground_truth_ok=False, ground_truth_evidence="missing",
        agent_reported_success=False, agent_ground_truth_agree=True, tool_iterations=0,
        tool_calls=0, repeated_failures=0, elapsed_seconds=0.1,
    )
    store = EvaluationStore(path)
    store.append(result)
    store.append(result)
    assert len(store.load()) == 2
    assert not (tmp_path / ".bolt" / "sessions" / "latest.json").exists()


def test_recovery_tasks_use_distinct_fixture_behaviors(tmp_path):
    tasks = {task.task_id: task for task in default_tasks()}
    assert {"locate-config", "avoid-decoy-edit", "recover-missing-path"}.issubset(tasks)

    roots = {}
    for task_id in ("locate-config", "avoid-decoy-edit", "recover-missing-path"):
        root = tmp_path / task_id
        root.mkdir()
        tasks[task_id].setup(root)
        roots[task_id] = root

    assert (roots["locate-config"] / "settings" / "service.conf").is_file()
    assert (roots["locate-config"] / "settings" / "service.conf.dist").is_file()
    assert (roots["avoid-decoy-edit"] / "deploy" / "service.conf.example").read_text().startswith("enabled=false")
    assert not (roots["recover-missing-path"] / "config" / "config.ini").exists()
    assert (roots["recover-missing-path"] / "runtime" / "service.conf").is_file()
    assert "retired" in (roots["recover-missing-path"] / "README.md").read_text()


def test_validation_mismatch_ground_truth_requires_broad_artifact(tmp_path):
    task = next(task for task in default_tasks() if task.task_id == "validation-mismatch")
    task.setup(tmp_path)
    (tmp_path / "project.txt").write_text("release\n")
    complete, _ = task.ground_truth(tmp_path)
    assert not complete
    (tmp_path / ".bolt-eval").mkdir()
    (tmp_path / ".bolt-eval" / "full-validation.txt").write_text("FULL_VALIDATION_OK\n")
    complete, _ = task.ground_truth(tmp_path)
    assert complete


def test_mismatch_reporting_does_not_depend_on_status_name():
    result = EvaluationResult(
        task_id="mismatch", category="validation-mismatch", provider="fake", model="m1",
        agent_status="future-success-status", agent_validation_status="passed", agent_validation_scope="targeted",
        agent_task_result="future-success-status", ground_truth_ok=False, ground_truth_evidence="full artifact missing",
        agent_reported_success=True, agent_ground_truth_agree=False, tool_iterations=1,
        tool_calls=1, repeated_failures=0, elapsed_seconds=0.1,
        ground_truth_completed=False, agent_reported_completion=True,
        agent_reported_verification=True, avoided_claiming_verified_success=False,
    )
    assert not result.ground_truth_completed
    assert result.agent_reported_completion
    assert result.agent_reported_verification
    assert not result.avoided_claiming_verified_success
