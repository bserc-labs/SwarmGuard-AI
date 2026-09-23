"""Exactly one CI job is responsible for the live security suite.

tests/test_sprint7_security.py drives a running server. Where it is *required*
it must fail when it cannot run, because a skip that means "we never checked"
reads as a pass. Everywhere else it must skip.

The switch used to be the generic CI variable. GitHub sets CI=true in every
job, so the unit-test job -- which collects the same file with no server and
no administrator -- failed on all six tests, and main went red over a suite
that job was never meant to run. The switch is now an explicit flag owned by
the one job that starts a server. These tests pin both halves: the wiring in
the workflow, and the behaviour behind the flag.
"""

from pathlib import Path

import pytest
import yaml

import tests.test_sprint7_security as live_suite

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
FLAG = live_suite.REQUIRE_FLAG
LIVE_FILE = "tests/test_sprint7_security.py"


@pytest.fixture(scope="module")
def workflow() -> dict:
    if not WORKFLOW.exists():
        pytest.skip("no workflow file in this checkout")
    with WORKFLOW.open() as fh:
        return yaml.safe_load(fh)


@pytest.fixture(scope="module")
def jobs(workflow) -> dict:
    return workflow["jobs"]


def _truthy(value) -> bool:
    return str(value).lower() in {"1", "true", "yes"}


def _runs_the_live_file(job: dict) -> bool:
    return any(LIVE_FILE in str(step.get("run", "")) for step in job.get("steps", []))


class TestTheWorkflowWiring:
    def test_the_job_that_runs_the_live_suite_requires_it(self, jobs):
        owners = [name for name, job in jobs.items() if _runs_the_live_file(job)]
        assert owners, "no job runs the live security suite; it would never execute"
        for name in owners:
            env = jobs[name].get("env", {})
            assert _truthy(env.get(FLAG)), (
                f"job {name!r} runs the live suite without {FLAG}: if the server "
                "fails to start, every test skips and the job stays green"
            )
            assert env.get("ADMIN_PASSWORD"), f"job {name!r} cannot provision fixtures"

    def test_no_other_job_requires_it(self, jobs):
        """A job with no server must be free to skip the file it merely collects."""
        for name, job in jobs.items():
            if _runs_the_live_file(job):
                continue
            assert FLAG not in job.get("env", {}), f"job {name!r} requires a suite it cannot run"
            for step in job.get("steps", []):
                assert FLAG not in step.get("env", {}), f"a step in {name!r} requires the suite"

    def test_the_flag_is_not_set_for_the_whole_workflow(self, workflow):
        assert FLAG not in (workflow.get("env") or {})


class TestTheSwitch:
    def test_it_skips_when_not_required_even_in_ci(self, monkeypatch):
        """The regression: CI=true alone must not turn a skip into a failure."""
        monkeypatch.setenv("CI", "true")
        monkeypatch.delenv(FLAG, raising=False)
        with pytest.raises(pytest.skip.Exception):
            live_suite._did_not_run("no server")

    def test_it_fails_when_required(self, monkeypatch):
        monkeypatch.setenv(FLAG, "1")
        with pytest.raises(pytest.fail.Exception, match="required but could not run"):
            live_suite._did_not_run("no server")

    @pytest.mark.parametrize("value", ["", "0", "false", "no"])
    def test_a_falsy_flag_does_not_require_it(self, monkeypatch, value):
        monkeypatch.setenv(FLAG, value)
        with pytest.raises(pytest.skip.Exception):
            live_suite._did_not_run("no server")


class TestTheReleaseJob:
    """build -> scan -> push, on main only, after everything else is green."""

    @pytest.fixture(scope="class")
    def release(self, jobs) -> dict:
        assert "release" in jobs, "CI publishes nothing: there is nothing to deploy or roll back to"
        return jobs["release"]

    def test_it_runs_only_for_a_push_to_main(self, release):
        condition = release["if"]
        assert "github.event_name == 'push'" in condition
        assert "github.ref == 'refs/heads/main'" in condition

    def test_it_waits_for_every_other_job(self, jobs, release):
        assert set(release["needs"]) == set(jobs) - {"release"}

    def test_it_may_write_packages_and_nothing_else(self, release):
        assert release["permissions"] == {"contents": "read", "packages": "write"}

    def test_images_are_scanned_before_they_are_pushed_and_the_scan_blocks(self, release):
        names = [step.get("name", "") for step in release["steps"]]
        scans = [i for i, n in enumerate(names) if n.startswith("Scan")]
        push = names.index("Push")
        assert len(scans) == 2 and all(i < push for i in scans)
        for i in scans:
            step = release["steps"][i]
            assert step["with"]["scan-type"] == "image"
            assert str(step["with"]["exit-code"]) == "1"
            assert "continue-on-error" not in step

    def test_the_sha_tag_is_the_full_commit(self, release):
        names_step = next(s for s in release["steps"] if s.get("id") == "names")
        assert "sha-${{ github.sha }}" in names_step["run"]

    def test_both_images_are_pushed_under_the_sha_tag(self, release):
        push = next(s for s in release["steps"] if s.get("name") == "Push")["run"]
        assert "steps.names.outputs.backend" in push and "steps.names.outputs.frontend" in push
        assert "docker push \"$image:${{ steps.names.outputs.sha_tag }}\"" in push

    def test_the_moving_tags_are_pushed_too_but_are_not_what_deploys(self, release):
        push = next(s for s in release["steps"] if s.get("name") == "Push")["run"]
        assert '"$image:main"' in push and '"$image:latest"' in push
        deploy = (ROOT / "scripts" / "deploy.sh").read_text()
        assert "sha-*)" in deploy, "deploy.sh must accept sha tags only"


class TestConcurrency:
    """A push to main must never cancel or replace another push's run."""

    def test_pull_requests_cancel_their_own_superseded_runs(self, workflow):
        assert workflow["concurrency"]["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"

    def test_every_push_is_its_own_group(self, workflow):
        """Per-ref groups let a later merge kill -- or, queued, replace -- an earlier release."""
        group = workflow["concurrency"]["group"]
        assert "github.event_name == 'push' && github.sha" in group
        assert "github.ref" in group, "pull requests still group by ref"


class TestDependencyAudits:
    """An advisory security gate is a gate nobody reads."""

    @pytest.fixture(scope="class")
    def steps(self, jobs) -> dict:
        return {step.get("name", ""): step for step in jobs["security-scan"]["steps"]}

    @pytest.mark.parametrize("name", ["Audit Python dependencies (blocking)", "Audit npm dependencies (blocking)"])
    def test_each_audit_blocks(self, steps, name):
        assert name in steps, f"{name!r} is missing from the security-scan job"
        assert "continue-on-error" not in steps[name], f"{name} must fail the build"

    def test_the_python_audit_covers_the_requirements(self, steps):
        assert "pip-audit -r requirements.txt" in steps["Audit Python dependencies (blocking)"]["run"]

    def test_the_npm_audit_threshold_is_high(self, steps):
        assert "--audit-level=high" in steps["Audit npm dependencies (blocking)"]["run"]

    def test_the_vulnerable_jwt_dependency_does_not_come_back(self):
        requirements = (ROOT / "backend" / "requirements.txt").read_text().lower()
        assert "python-jose" not in requirements and "ecdsa" not in requirements

