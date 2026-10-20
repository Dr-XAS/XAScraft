"""The report section for one variant, from its summary."""
from report import variant_section


def field(name, values=1, max_abs=0.0, max_rel=0.0, max_rel_rms=None, other=0, example=None):
    return {"field": name, "values": values, "max_abs": max_abs, "max_rel": max_rel,
            "max_rel_rms": max_rel_rms, "other": other, "example": example}


def test_a_variant_identical_everywhere_says_so():
    summary = {"copper": {"status": "identical", "fields": []},
               "merge": {"status": "identical", "fields": []}}

    text = variant_section("Without 0001", summary, tests={"passed": 12, "failed": []})

    assert text.startswith("## Without 0001\n")
    assert "Identical to the full patch set in all 2 scenarios." in text
    assert "Team regression tests: 12 passed, 0 failed." in text


def test_a_variant_that_does_not_build_says_why():
    text = variant_section("Without 0005", {}, tests=None,
                           build_error="patch 0006-x.patch does not apply")

    assert text == "## Without 0005\n\nDoes not build: patch 0006-x.patch does not apply\n"


def test_failing_and_differing_scenarios_are_listed_worst_first():
    summary = {
        "copper": {"status": "identical", "fields": []},
        "fit": {"status": "differs", "fields": [
            field("fit: body.chi[*]", values=300, max_abs=2e-4, max_rel=0.5, max_rel_rms=1.5e-4),
            field("fit: body.amp", values=1, max_abs=1e-6, max_rel=1e-6)]},
        "lcf": {"status": "differs", "fields": [
            field("lcf: body.weights[*]", values=2, max_abs=0.01, max_rel=0.02, max_rel_rms=0.015),
            field("lcf: body.message", values=0, other=1, example='"a" -> "b"')]},
        "athena": {"status": "fails", "failure": "preview: HTTP 200 -> 422 {}", "fields": [
            field("preview: status", values=0, other=1, example="HTTP 200 -> 422")]},
    }

    text = variant_section("Without 0003", summary, tests={"passed": 10, "failed": ["test_bessel"]})

    assert "1 identical, 2 differ, 1 fail." in text
    assert "Team regression tests: 10 passed, 1 failed (test_bessel)." in text
    assert "| athena | preview: HTTP 200 -> 422 {} |" in text
    # differing scenarios, worst relative RMS first, naming the field that has it
    lcf_row = text.index("| lcf | 2 | 1 | 0.01 | 0.02 | 0.015 | `lcf: body.weights[*]` |")
    fit_row = text.index("| fit | 301 | 0 | 0.0002 | 0.5 | 0.00015 | `fit: body.chi[*]` |")
    assert lcf_row < fit_row
