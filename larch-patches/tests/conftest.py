"""Shows which Larch and which example data a run tests, so a run is never ambiguous."""

from examples_path import examples_dir


def pytest_report_header(config):
    try:
        import larch
        where = f"larch {larch.__version__} from {larch.__file__}"
    except Exception as exc:  # report, don't hide, a broken install
        where = f"larch not importable: {exc!r}"
    return [where, f"examples: {examples_dir()}"]
