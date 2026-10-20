"""The orchestrator reads the team regression tests' outcome from pytest's JUnit XML."""
from run_variants import regression_outcome

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
