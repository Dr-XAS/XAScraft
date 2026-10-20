"""Larch's remove_dups: upstream 98650acff changed it; the app's results do not change.

98650acff (in upstream 247278cef) swapped the builtin ``min`` for ``np.diff(work).min()`` in
remove_dups. On finite arrays both give the same value, so remove_dups returns the same bits.
With a NaN after the first step, the builtin ``min`` skipped it while numpy's gives NaN, so the
function now runs its de-duplication loop where it used to return the array unchanged, and can
move a point that sits within ``tiny`` of the last value before a NaN gap.

That case never reaches the app: both places that call remove_dups directly
(``athena_science.process_spectrum`` and ``athena_rebin.rebin_edge``) refuse NaN energies
first, in the same function. Inside Larch, the app's calls reach remove_dups with energies that
passed those checks.
"""
from types import SimpleNamespace

import numpy as np
import pytest
from larch.math import remove_dups
from larch.xafs.xafsutils import TINY_ENERGY

from xraylarch_web import athena_rebin, athena_science
from xraylarch_web.athena_rebin import ImportRebin, prepare_rebin
from xraylarch_web.athena_science import ScientificError, process_spectrum


def remove_dups_8d6cd41c2(arr, tiny=1.e-6):
    """larch.math.utils.remove_dups at upstream 8d6cd41c2, docstring left out."""
    try:
        work = np.asarray(arr)
    except Exception:
        print('remove_dups: argument is not an array')
    if work.size <= 1:
        return arr
    shape = work.shape
    work = work.flatten()
    min_step = min(np.diff(work))
    tval = (abs(min(work)) + abs(max(work))) /2.0
    if min_step > 10*tiny:
        return work
    previous_val = np.nan
    previous_add = 0
    npts = len(work)
    add = np.zeros(npts)
    for i in range(1, npts):
        if not np.isnan(work[i-1]):
            previous_val = work[i-1]
            previous_add = add[i-1]
        val = work[i]
        if np.isnan(val) or np.isnan(previous_val):
            continue
        diff = abs(val - previous_val)
        if diff < tiny:
            add[i] = previous_add + tiny
    return work+add


def finite_arrays():
    rng = np.random.default_rng(98650)
    yield [1, 2, 3, 3, 3, 4, 5, 6, 7, 7, 8]                    # the docstring's example
    yield np.array([8979.0])
    yield np.array([], dtype=float)
    yield np.array([0.0, -0.0, 1.0])
    yield np.array([[1.0, 2.0], [2.0, 3.0]])
    yield np.array([5.0, 4.0, 4.0, 3.0])                        # decreasing
    yield np.array([1.0, 1.0000001, 2.0], dtype=np.float32)
    yield np.arange(10, dtype=np.int64)
    for _ in range(2000):
        n = int(rng.integers(2, 60))
        steps = rng.choice([0.0, 1e-7, 3e-4, 2e-3, 0.5, 1.0, -0.3], size=n - 1)
        yield np.concatenate([[rng.uniform(-5, 9000)], steps]).cumsum()


def same_bits(a, b):
    a, b = np.asarray(a), np.asarray(b)
    return a.dtype == b.dtype and a.shape == b.shape and a.tobytes() == b.tobytes()


@pytest.mark.parametrize("tiny", [1e-6, TINY_ENERGY])
def test_finite_arrays_give_the_bits_remove_dups_gave_at_8d6cd41c2(tiny):
    for arr in finite_arrays():
        assert same_bits(remove_dups(arr, tiny=tiny), remove_dups_8d6cd41c2(arr, tiny=tiny)), arr


def test_a_nan_in_the_first_step_gives_the_same_bits_as_at_8d6cd41c2():
    arr = np.array([np.nan, 8979.0, 8979.0, 8980.0])
    assert same_bits(remove_dups(arr), remove_dups_8d6cd41c2(arr))


def test_a_nan_after_the_first_step_can_now_move_a_point_across_the_gap():
    """What changed, recorded so that a Larch bump that changes it again is noticed."""
    arr = np.array([1.0, 2.0, np.nan, 2.0000001, 3.0])
    assert same_bits(remove_dups_8d6cd41c2(arr), arr)
    np.testing.assert_array_equal(remove_dups(arr), [1.0, 2.0, np.nan, 2.0000011, 3.0])


@pytest.fixture
def recorded_remove_dups_calls(monkeypatch):
    """The arrays the app's own remove_dups calls receive."""
    calls = []

    def recording(arr, *args, **kwargs):
        calls.append(np.array(arr, dtype=float))
        return remove_dups(arr, *args, **kwargs)

    monkeypatch.setattr(athena_science, "remove_dups", recording)
    monkeypatch.setattr(athena_rebin, "remove_dups", recording)
    return calls


def edge_spectrum(n=200):
    energy = np.linspace(8900.0, 9300.0, n)
    return energy, np.arctan((energy - 8979.0) / 3.0) + 2.0


def test_process_spectrum_refuses_nan_energies_before_it_calls_remove_dups(recorded_remove_dups_calls):
    energy, mu = edge_spectrum()
    energy[50] = energy[51] - 1e-4                             # a close pair, so it would be called
    with_nan = energy.copy()
    with_nan[120] = np.nan
    with pytest.raises(ScientificError, match="NaN"):
        process_spectrum(with_nan, mu, {"energy_shift": 0.0})
    assert recorded_remove_dups_calls == []
    process_spectrum(energy, mu, {})                           # without the NaN it is called
    assert len(recorded_remove_dups_calls) == 1 and np.isfinite(recorded_remove_dups_calls[0]).all()


def test_import_rebinning_refuses_nan_energies_before_it_calls_remove_dups(recorded_remove_dups_calls):
    energy, mu = edge_spectrum(n=80)                           # short scans take remove_dups
    request = SimpleNamespace(rebin=ImportRebin(), data_type="mu", edge_policy=None)
    with_nan = energy.copy()
    with_nan[40] = np.nan
    mapped = {"x": with_nan, "samples": [{"y": mu}], "reference": None}
    with pytest.raises(ScientificError, match="nondecreasing"):
        prepare_rebin(mapped, request)
    assert recorded_remove_dups_calls == []
    prepare_rebin({"x": energy, "samples": [{"y": mu}], "reference": None}, request)
    assert len(recorded_remove_dups_calls) == 1 and np.isfinite(recorded_remove_dups_calls[0]).all()
