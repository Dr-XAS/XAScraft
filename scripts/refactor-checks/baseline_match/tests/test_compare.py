"""Exact comparison of two capture folders."""
import json
import math

from compare import compare_dirs


def capture(folder, **scenarios):
    folder.mkdir()
    for name, document in scenarios.items():
        (folder / f"{name}.json").write_text(json.dumps(document))
    return folder


def test_identical_captures_have_no_differences(tmp_path):
    document = {"steps": [{"status": 200, "body": {"norm": [0.1, 0.2]}}]}
    a = capture(tmp_path / "a", copper=document)
    b = capture(tmp_path / "b", copper=document)

    assert compare_dirs(a, b) == []


def test_a_float_moved_by_one_ulp_is_reported_at_its_path(tmp_path):
    value = 0.30000000000000004
    a = capture(tmp_path / "a", copper={"steps": [{"body": {"norm": [0.1, value]}}]})
    b = capture(tmp_path / "b", copper={"steps": [{"body": {"norm": [0.1, math.nextafter(value, 1)]}}]})

    assert compare_dirs(a, b) == [
        "copper: $.steps[0].body.norm[1]: 0.30000000000000004 != 0.3000000000000001"]


def test_every_differing_path_is_reported_including_type_keys_and_files(tmp_path):
    a = capture(tmp_path / "a", copper={"n": 1, "only_a": True, "list": [1, 2]}, gone={})
    b = capture(tmp_path / "b", copper={"n": 1.0, "only_b": None, "list": [1]}, new={})

    assert compare_dirs(a, b) == [
        "copper: $.list: length 2 != 1",
        "copper: $.n: 1 != 1.0",
        "copper: $.only_a: only in first",
        "copper: $.only_b: only in second",
        "gone: only in first",
        "new: only in second",
    ]
