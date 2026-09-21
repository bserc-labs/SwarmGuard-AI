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
