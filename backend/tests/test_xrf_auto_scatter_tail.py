"""Automatic selection must not alter a sound extraction or hide failed checks."""
import copy
import json

import numpy as np
import pytest

from xraylarch_web import athena_xrf_xas as engine
from xraylarch_web.athena_xrf_runtime import XrfRuntime
from xraylarch_web.athena_science import ScientificError
from test_athena_xrf_xas import E0, mu_true, scan_energies, synthetic_scan

pytestmark = pytest.mark.xrf_slow


def test_a_passing_default_is_not_refitted_or_numerically_changed(monkeypatch):
    energy = scan_energies(32)
    scan, counts, options, _ = synthetic_scan(
        points=32, detectors=1, poisson=False, calibration_points=3,
        target_scale=np.where(energy < E0, 0., mu_true(energy)))
    fixed = engine.extract(scan, counts, options.model_copy(update={'scatter_beta': 0.5}))
    assert fixed['quality']['fit']['checks']['pre_edge_null'] is True
    original = engine.fit_detector
    fits = []

    def once(*args, **kwargs):
        assert not fits, 'A passing default must not trigger another fit'
        fits.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(engine, 'fit_detector', once)
    automatic = engine.extract(scan, counts, options)
    for key in fixed.keys() - {'metadata'}:
        assert json.dumps(automatic[key], sort_keys=True) == json.dumps(fixed[key], sort_keys=True)
    assert automatic['metadata']['scatter_tail']['selected_beta'] == 0.5
    assert len(automatic['metadata']['scatter_tail']['candidates']) == 1
    assert automatic['metadata']['warnings'] == fixed['metadata']['warnings']


@pytest.fixture(scope='module')
def long_tail():
    # Only the generating tail differs from the existing synthetic Mn scan.
    # Selection sees counts, not generating amplitudes or target yields.
    scan, counts, options, _ = synthetic_scan(
        points=32, detectors=1, calibration_points=3, scatter_beta=8.)
    automatic_options = options.model_copy(update={'scatter_beta': None})
    # The server's fit cache lets the search reuse the explicit default's fit.
    resolved, windows = engine.resolve_windows(scan, automatic_options)
    runtime = XrfRuntime(1)
    try:
        fixed = runtime.extract(scan, counts, resolved.model_copy(update={'scatter_beta': 0.5}),
                                windows, 'long-tail-one-detector')
        automatic = runtime.extract(scan, counts, resolved, windows, 'long-tail-one-detector')
    finally:
        runtime.close()
    return scan, counts, automatic_options, fixed, automatic


def test_an_unmodelled_long_tail_is_not_left_in_the_pre_edge(long_tail):
    _, _, _, fixed, automatic = long_tail
    assert fixed['quality']['fit']['checks']['pre_edge_null'] is False
    before = abs(fixed['quality']['fit']['null_test']['mean_frac_of_jump'])
    after = abs(automatic['quality']['fit']['null_test']['mean_frac_of_jump'])
    choice = automatic['metadata']['scatter_tail']
    assert choice['selected_beta'] > 0.5
    assert after < before / 2
    selected = next(row for row in choice['candidates'] if row['beta'] == choice['selected_beta'])
    assert selected['null_test'] == automatic['quality']['fit']['null_test']
    assert selected['fits_converged'] and selected['eligible']
    assert automatic['metadata']['request']['scatter_beta'] is None
    assert any('Automatic scatter tail' in text for text in automatic['metadata']['warnings'])
    if automatic['quality']['fit']['checks']['pre_edge_null'] is False:
        assert any('still fails' in text for text in automatic['metadata']['warnings'])


def test_an_explicit_tail_is_not_replaced_even_when_its_check_fails(long_tail):
    scan, counts, options, fixed, _ = long_tail
    assert fixed['metadata']['scatter_tail']['selected_beta'] == 0.5
    assert fixed['metadata']['scatter_tail']['automatic'] is False
    assert fixed['metadata']['scatter_tail']['candidates'] == []
    request = options.model_copy(update={'scatter_beta': 8.})
    result = engine.extract(scan, counts, request)
    assert result['metadata']['request']['scatter_beta'] == 8.
    assert result['metadata']['scatter_tail']['selected_beta'] == 8.
    assert result['metadata']['scatter_tail']['candidates'] == []
    assert result['fit_counts'] != fixed['fit_counts']


@pytest.mark.parametrize('error', [
    ScientificError('All selected detector elements failed calibration'),
    np.linalg.LinAlgError('Singular matrix'),
    ValueError('array must not contain infs or NaNs'),
])
def test_failed_tail_trials_preserve_the_original_result_and_failure_warning(long_tail, monkeypatch, error):
    scan, counts, options, fixed, _ = long_tail

    def failed_trial(scan, counts, request, *args, **kwargs):
        if request.scatter_beta == 0.5:
            return copy.deepcopy(fixed)
        raise error

    monkeypatch.setattr(engine, '_extract_fixed', failed_trial)
    result = engine.extract(scan, counts, options)
    assert result['fit_counts'] == fixed['fit_counts']
    assert result['quality'] == fixed['quality']
    assert result['metadata']['scatter_tail']['selected_beta'] == 0.5
    assert all('error' in trial and not trial['eligible']
               for trial in result['metadata']['scatter_tail']['candidates'][1:])
    # The shortest longer tail was really tried and could not be fitted, so the
    # search stopped there rather than paying for three more failing fits; the
    # default is kept, the failed check still shows, and the user is told.
    tried = result['metadata']['scatter_tail']['candidates'][1:]
    assert [trial['beta'] for trial in tried] == [2.0]
    assert result['quality']['fit']['checks']['pre_edge_null'] is False
    assert any('stopping at 2, which could not be fitted; none was acceptable' in text
               for text in result['metadata']['warnings'])
    assert not any('selected' in text and 'Automatic scatter tail' in text
                   for text in result['metadata']['warnings'])


def two_copies(scan, counts):
    """Identical detector copies: one detector's tail selection, but real
    multi-process candidate dispatch."""
    scan = copy.deepcopy(scan)
    counts = np.repeat(counts, 2, axis=1)
    scan['deadtime']['ge'] = np.repeat(scan['deadtime']['ge'], 2, axis=1)
    scan['detectors']['ge'] = counts.shape
    scan['deadtime_corrected']['ge'] = 2
    return scan, counts


def test_cached_tail_candidates_cannot_reuse_the_default_fit(long_tail):
    scan, counts, options, fixed, expected = long_tail
    scan, counts = two_copies(scan, counts)
    options, windows = engine.resolve_windows(scan, options)
    runtime = XrfRuntime(2)
    dispatched = []
    original = runtime._parallel_fits

    def spy(tasks):
        fits = original(tasks)
        dispatched.append(([task[2].scatter_beta for task in tasks], fits is not None))
        return fits

    runtime._parallel_fits = spy
    try:
        # Prepopulate the same cache with an explicit default before searching.
        baseline = runtime.extract(scan, counts, options.model_copy(update={'scatter_beta': 0.5}),
                                   windows, 'long-tail-counts')
        np.testing.assert_allclose(baseline['fit_counts'], 2 * np.asarray(fixed['fit_counts']),
                                   rtol=1e-12)
        result = runtime.extract(scan, counts, options, windows, 'long-tail-counts')
        # A candidate served from the default's cached fit would select 0.5 here,
        # whether the fits ran in workers or, without a pool, serially.
        chosen, single = result['metadata']['scatter_tail'], expected['metadata']['scatter_tail']
        assert chosen['selected_beta'] == single['selected_beta'] > 0.5
        assert [row['beta'] for row in chosen['candidates']] == \
            [row['beta'] for row in single['candidates']]
        np.testing.assert_allclose(result['fit_counts'], 2 * np.asarray(expected['fit_counts']),
                                   rtol=1e-12)
        assert runtime.extract(scan, counts, options, windows, 'long-tail-counts') == result
        # Workers must receive each candidate's own tail, never the outer null
        # request (which a worker would fit at 0.5 for every candidate).
        if not dispatched or not all(ran for _, ran in dispatched):
            pytest.skip('process pool unavailable; the parallel branch did not run')
        tails = {beta for betas, _ in dispatched for beta in betas}
        assert None not in tails and tails > {0.5}
    finally:
        runtime.close()
