"""Shows which Larch and which example data a run tests, so a run is never ambiguous.

Also marks the team's Larch regression tests ``regression``: every test here except the
queue's own checks (``QUEUE_CHECKS``), which build Larch, need git and upstream, or
check that the full patched build is installed.  Callers
select them with ``-m regression`` (and the queue checks with ``-m "not regression"``), so
this file is the one place that knows which files are which.
"""

from pathlib import Path

from examples_path import examples_dir

HERE = Path(__file__).resolve().parent
QUEUE_CHECKS = {"test_series.py", "test_build.py", "test_upstream_suite.py", "test_installed.py"}


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "regression: a Larch regression test, run against the installed Larch "
                   "(larch-patches/tests/conftest.py)")


def pytest_collection_modifyitems(items):
    for item in items:
        path = Path(item.path).resolve()
        if path.parent == HERE and path.name not in QUEUE_CHECKS:
            item.add_marker("regression")


def pytest_report_header(config):
    try:
        import larch
        where = f"larch {larch.__version__} from {larch.__file__}"
    except Exception as exc:  # report, don't hide, a broken install
        where = f"larch not importable: {exc!r}"
    return [where, f"examples: {examples_dir()}"]
