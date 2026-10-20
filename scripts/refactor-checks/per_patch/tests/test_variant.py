"""Variant names: `full`, `pure`, or the patches left out (`0003`, `0005+0006+0007`)."""
import pytest

from variant import Variant

SERIES = ["0001-a.patch", "0002-b.patch", "0003-c.patch"]


def test_full_and_pure_select_everything_and_nothing():
    assert Variant.parse("full").build_args() == []
    assert Variant.parse("pure").build_args() == ["--pure-upstream"]


def test_a_left_out_selection_names_each_patch_for_build_py():
    variant = Variant.parse("0002+0003")

    assert variant.excluded == ("0002", "0003")
    assert variant.build_args() == ["--exclude", "0002", "--exclude", "0003"]


@pytest.mark.parametrize("text", ["", "3", "0003+", "0003+full", "none"])
def test_anything_else_is_refused(text):
    with pytest.raises(ValueError, match="variant"):
        Variant.parse(text)


def test_titles_name_the_left_out_patch_files():
    assert Variant.parse("full").title(SERIES) == "Full patch set (the reference)"
    assert Variant.parse("pure").title(SERIES) == "Pure upstream (no patches)"
    assert Variant.parse("0002+0003").title(SERIES) == (
        "Without 0002 + 0003 (`0002-b.patch`, `0003-c.patch`)")


def test_variants_sort_full_first_then_by_first_patch_left_out_then_pure():
    names = ["pure", "0003", "0002+0003", "full", "0002", "0001"]

    ordered = sorted(names, key=lambda name: Variant.parse(name).sort_key(SERIES))

    assert ordered == ["full", "0001", "0002", "0002+0003", "0003", "pure"]
