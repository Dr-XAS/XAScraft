"""The orchestrator: the regression outcome from pytest's JUnit XML, and the reference build."""
import pytest

import run_variants
from run_variants import BuildFailed, regression_outcome

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" errors="0" failures="1" skipped="1" tests="4">
<testcase classname="test_xafs_defects" name="test_a" time="0.1"/>
<testcase classname="test_xafs_defects" name="test_b" time="0.1"><failure message="boom"/></testcase>
<testcase classname="test_xrf_model" name="test_c[x]" time="0.1"><error message="setup"/></testcase>
<testcase classname="test_xrf_model" name="test_d" time="0.1"><skipped message="no wx"/></testcase>
</testsuite></testsuites>
"""


def test_outcome_counts_passes_and_names_failures_errors_and_skips(tmp_path):
    xml = tmp_path / "junit.xml"
    xml.write_text(JUNIT)

    assert regression_outcome(xml) == {"passed": 1,
                                 "failed": ["test_xafs_defects::test_b", "test_xrf_model::test_c[x]"],
                                 "skipped": ["test_xrf_model::test_d"]}


@pytest.mark.parametrize("content", [None, "", "<testsuites><testsuite>"], ids=["missing", "empty", "cut-off"])
def test_a_pytest_run_that_left_no_readable_report_is_recorded_as_crashed(tmp_path, content):
    xml = tmp_path / "junit.xml"
    if content is not None:
        xml.write_text(content)

    outcome = regression_outcome(xml, returncode=-11)

    assert outcome["passed"] == 0 and outcome["failed"] == [] and outcome["skipped"] == []
    assert "exit -11" in outcome["crashed"]


def test_when_the_reference_build_fails_the_run_stops_and_says_so(tmp_path, monkeypatch):
    built = []

    def run_variant(variant, python, args, log):
        built.append(variant)
        raise BuildFailed("patch 0003-c.patch does not apply")

    monkeypatch.setattr(run_variants, "make_venv", lambda *args: "python")
    monkeypatch.setattr(run_variants, "run_variant", run_variant)

    with pytest.raises(SystemExit) as stopped:
        run_variants.main(["--work", str(tmp_path / "work"), "--out", str(tmp_path / "out"),
                           "--upstream", "x", "--variants", "full", "0001", "pure"])

    assert built == ["full"]
    assert "reference build `full` failed" in str(stopped.value)
    assert "0003-c.patch does not apply" in str(stopped.value)
