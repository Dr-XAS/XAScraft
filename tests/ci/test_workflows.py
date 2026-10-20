"""The GitHub workflows parse, name only files that exist, and get Larch from the patch queue.

Nothing here runs a workflow; GitHub does that.  These checks catch the mistakes that
show up only after a push: a YAML error, a step or path filter that names a file that was
moved or deleted, and a workflow that installs Larch from the repository instead of
building it from ``larch-patches``.  Needs PyYAML (pinned in the release constraints).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((REPO / ".github" / "workflows").glob("*.y*ml"))

# Repository paths as steps write them: relative, starting at a top-level entry.
# A path preceded by "/" or "$" (e.g. "$GITHUB_WORKSPACE/backend/.venv") is skipped:
# it is built at run time, often for a file the job creates.
TOP_LEVEL = r"(?:\.github|backend|frontend|larch-patches|scripts|tests|installers|deploy|examples)"
REPO_PATH = re.compile(rf"(?<![\w$./-])(?:{TOP_LEVEL}/[\w./*-]*[\w*]|Install\.command)")


def repo_paths(run: str) -> list[str]:
    return REPO_PATH.findall(re.sub(r"(^|\s)\./", r"\1", run, flags=re.M))


def load(path: Path) -> dict:
    data = yaml.safe_load(path.read_text())
    # YAML 1.1 reads the key "on" as True.
    if True in data:
        data["on"] = data.pop(True)
    return data


def steps(workflow: dict):
    for job in workflow["jobs"].values():
        yield from job.get("steps", [])


def test_there_are_workflows():
    assert WORKFLOWS


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_parses_with_triggers_and_jobs(path):
    workflow = load(path)
    assert workflow.get("on"), "no triggers"
    assert workflow.get("jobs"), "no jobs"
    for name, job in workflow["jobs"].items():
        assert job.get("runs-on"), f"job {name} has no runs-on"
        assert job.get("steps"), f"job {name} has no steps"


def test_upstream_larch_workflows_are_gone():
    names = {p.name for p in WORKFLOWS}
    assert not names & {"test-ubuntu.yml", "test-windows.yml"}


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_path_filters_match_files(path):
    workflow = load(path)
    triggers = workflow["on"] if isinstance(workflow["on"], dict) else {}
    missing = []
    for trigger in triggers.values():
        for pattern in (trigger or {}).get("paths", []):
            if not any(REPO.glob(pattern.removeprefix("!"))):
                missing.append(pattern)
    assert not missing, f"path filters match nothing: {missing}"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_steps_name_only_existing_files(path):
    workflow = load(path)
    named = []
    for step in steps(workflow):
        named += repo_paths(step.get("run", ""))
        for key in ("node-version-file", "cache-dependency-path"):
            if key in step.get("with", {}):
                named.append(step["with"][key])
    missing = sorted({p for p in named if not any(REPO.glob(p))})
    assert not missing, f"steps name files that do not exist: {missing}"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_no_workflow_installs_larch_from_the_repository(path):
    # The repository root is no longer a Larch package; Larch comes from
    # larch-patches/build.py (directly, through install-dev.sh, or through the deploy
    # script's install_release_backend) or from the local installer.
    root_install = re.compile(r"pip\s+(?:wheel|install)\b[^\n]*?\s(?:-e\s+)?[\"']?\.(?:\[[\w,]+\])?[\"']?(?:\s|$)")
    offenders = [s.get("name", s.get("run", "")[:40]) for s in steps(load(path))
                 if root_install.search(s.get("run", ""))]
    assert not offenders, f"steps install the repository root: {offenders}"


def test_web_backend_installs_come_from_the_deploy_script():
    # Every workflow that makes the backend's venv installs Larch through
    # install_release_backend, which builds it with larch-patches/build.py.
    for path in WORKFLOWS:
        for step in steps(load(path)):
            run = step.get("run", "")
            if "backend/.venv" in run and "python -m venv" in run:
                assert "install_release_backend" in run, f"{path.name}: {step.get('name')}"


def test_a_workflow_builds_the_patched_larch_and_runs_both_suites():
    runs = {p.name: "\n".join(s.get("run", "") for s in steps(load(p))) for p in WORKFLOWS}
    builders = [n for n, r in runs.items() if "larch-patches/install-dev.sh" in r]
    assert builders, "no workflow builds the patched Larch"
    for name in builders:
        assert "larch-patches/tests" in runs[name], f"{name}: no team regression tests"
        assert "larch-patches/run-upstream-tests.sh" in runs[name], f"{name}: no upstream suite"
