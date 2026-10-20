"""How far a variant capture moves from the reference capture, field by field."""
import json

import pytest

from summarize import summarize_dirs


def capture(folder, **scenarios):
    folder.mkdir()
    for name, document in scenarios.items():
        (folder / f"{name}.json").write_text(json.dumps(document))
    return folder


def fit(**body):
    return {"scenario": "fit", "steps": [{"step": "load", "status": 200, "body": {}},
                                         {"step": "fit", "status": 200, "body": body}]}


def test_identical_captures_summarize_as_identical(tmp_path):
    a = capture(tmp_path / "a", fit=fit(amp=0.74, chi=[0.1, 0.2]))
    b = capture(tmp_path / "b", fit=fit(amp=0.74, chi=[0.1, 0.2]))

    assert summarize_dirs(a, b) == {"fit": {"status": "identical", "fields": []}}


def test_a_moved_value_reports_its_step_field_and_abs_and_rel_difference(tmp_path):
    a = capture(tmp_path / "a", fit=fit(amp=0.8, sigma2=0.003))
    b = capture(tmp_path / "b", fit=fit(amp=0.6, sigma2=0.003))

    summary = summarize_dirs(a, b)["fit"]

    assert summary["status"] == "differs"
    [field] = summary["fields"]
    assert field["field"] == "fit: body.amp"
    assert field["values"] == 1
    assert field["max_abs"] == pytest.approx(0.2)
    assert field["max_rel"] == pytest.approx(0.25)  # relative to the reference value 0.8


def test_a_numeric_array_is_one_field_with_its_relative_rms_difference(tmp_path):
    a = capture(tmp_path / "a", fit=fit(groups=[{"chi": [3.0, 4.0]}, {"chi": [1.0, 1.0]}]))
    b = capture(tmp_path / "b", fit=fit(groups=[{"chi": [3.0, 4.5]}, {"chi": [1.0, 1.0]}]))

    [field] = summarize_dirs(a, b)["fit"]["fields"]

    assert field["field"] == "fit: body.groups[*].chi[*]"
    assert field["values"] == 1
    assert field["max_abs"] == pytest.approx(0.5)
    assert field["max_rel"] == pytest.approx(0.125)
    # |b - a| / |a| over the whole array: 0.5 / 5; the largest over the field's arrays
    assert field["max_rel_rms"] == pytest.approx(0.1)


def test_a_single_value_has_no_relative_rms(tmp_path):
    a = capture(tmp_path / "a", fit=fit(amp=0.8))
    b = capture(tmp_path / "b", fit=fit(amp=0.6))

    [field] = summarize_dirs(a, b)["fit"]["fields"]

    assert field["max_rel_rms"] is None


def test_numbers_inside_text_lines_are_compared_as_numbers(tmp_path):
    a = capture(tmp_path / "a", fit=fit(lines=["# energy mu", "8979.0, 0.5", "8980.0, 2.0e-01"]))
    b = capture(tmp_path / "b", fit=fit(lines=["# energy mu", "8979.0, 0.55", "8980.0, 2.0e-01"]))

    [field] = summarize_dirs(a, b)["fit"]["fields"]

    assert field["field"] == "fit: body.lines[*]"
    assert field["values"] == 1
    assert field["max_abs"] == pytest.approx(0.05)
    assert field["other"] == 0


def test_other_changes_are_counted_with_the_first_as_an_example(tmp_path):
    a = capture(tmp_path / "a", fit=fit(message="fit converged", warnings=["a"], extra=1))
    b = capture(tmp_path / "b", fit=fit(message="fit failed", warnings=["a", "b"], extra="1"))

    fields = {f["field"]: f for f in summarize_dirs(a, b)["fit"]["fields"]}

    assert fields["fit: body.message"]["other"] == 1
    assert fields["fit: body.message"]["values"] == 0
    assert fields["fit: body.message"]["example"] == '"fit converged" -> "fit failed"'
    assert fields["fit: body.warnings"]["example"] == "length 1 -> 2"
    assert fields["fit: body.extra"]["example"] == '1 -> "1"'


def test_a_step_that_fails_only_in_the_variant_makes_the_scenario_fail(tmp_path):
    reference = fit(amp=0.8)
    variant = fit(amp=0.8)
    variant["steps"][1].update(status=422, body={"detail": "invalid window name 'bessel'"})
    variant["error"] = "StepFailed: fit: HTTP 422"
    a = capture(tmp_path / "a", fit=reference)
    b = capture(tmp_path / "b", fit=variant)

    summary = summarize_dirs(a, b)["fit"]

    assert summary["status"] == "fails"
    assert summary["failure"] == ("fit: HTTP 200 -> 422 {\"detail\": \"invalid window name 'bessel'\"}; "
                                  "stopped: StepFailed: fit: HTTP 422")


def test_an_error_field_that_appears_only_in_the_variant_makes_the_scenario_fail(tmp_path):
    # The app reports Larch failures inside a 200 response, per group.
    message = "Larch processing failed (invalid window name bessel)"
    a = capture(tmp_path / "a", fit=fit(groups=[{"processing_error": None, "chi": [1.0, 2.0]}] * 3,
                                        preview={"x": [1.0]}))
    b = capture(tmp_path / "b", fit=fit(groups=[{"processing_error": message, "chi": [1.0, 2.0]}] * 2
                                        + [{"processing_error": None, "chi": [1.0, 2.0]}],
                                        preview={"x": [], "processing_error": message}))

    summary = summarize_dirs(a, b)["fit"]

    assert summary["status"] == "fails"
    assert summary["failure"] == (f"fit: body.groups[*].processing_error x2: {message}; "
                                  f"fit: body.preview.processing_error x1: {message}")


def test_a_scenario_missing_from_one_capture_is_reported(tmp_path):
    a = capture(tmp_path / "a", fit=fit(amp=0.8), merge=fit())
    b = capture(tmp_path / "b", fit=fit(amp=0.8))

    assert summarize_dirs(a, b)["merge"] == {"status": "missing", "fields": [],
                                             "failure": "only in the reference"}
