from xascraft_local import source

from test_local_install import distribution


def test_the_snapshot_ships_the_notice_beside_the_license(tmp_path):
    """examples/ ships in the snapshot, so the NOTICE that credits xraylarch for it ships too."""
    original = distribution(tmp_path / "original")
    (original / "LICENSE").write_text("MIT License\n")
    (original / "NOTICE").write_text("examples/ comes from xraylarch\n")
    destination = tmp_path / "snapshot"
    source.snapshot(original, destination)
    assert (destination / "LICENSE").read_text() == "MIT License\n"
    assert (destination / "NOTICE").read_text() == "examples/ comes from xraylarch\n"
