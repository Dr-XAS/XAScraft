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
def tail_runtime():
    runtime = XrfRuntime(1)
    yield runtime
    runtime.close()


@pytest.fixture(scope='module')
def long_tail(tail_runtime):
    # Only the generating tail differs from the existing synthetic Mn scan; at
    # this length a longer fitted tail passes the pre-edge check. Selection
    # sees counts, not generating amplitudes or target yields.
    scan, counts, options, _ = synthetic_scan(
        points=32, detectors=1, calibration_points=3, scatter_beta=16.)
    automatic_options = options.model_copy(update={'scatter_beta': None})
    # The server's fit cache lets the search reuse the explicit default's fit.
    resolved, windows = engine.resolve_windows(scan, automatic_options)
    fixed = tail_runtime.extract(scan, counts, resolved.model_copy(update={'scatter_beta': 0.5}),
                                 windows, LONG_TAIL)
    automatic = tail_runtime.extract(scan, counts, resolved, windows, LONG_TAIL)
    return scan, counts, automatic_options, fixed, automatic


LONG_TAIL = 'long-tail-one-detector'


def test_a_budget_limited_candidate_fit_is_never_served_to_an_explicit_request(
        long_tail, tail_runtime, monkeypatch):
    """The search fitted each tail under a lowered calibration budget and cached
    it; an explicit request for the chosen tail must get a full-budget fit."""
    scan, counts, options, _, automatic = long_tail
    chosen = automatic['metadata']['scatter_tail']['selected_beta']
    budgets = []
    original = engine.fit_detector

    def recorded(*args):
        budgets.append(args[5] if len(args) > 5 else None)
        return original(*args)

    monkeypatch.setattr(engine, 'fit_detector', recorded)
    resolved, windows = engine.resolve_windows(scan, options)
    tail_runtime.extract(scan, counts, resolved.model_copy(update={'scatter_beta': chosen}),
                         windows, LONG_TAIL)
    assert budgets == [None]


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
    assert automatic['quality']['fit']['checks']['pre_edge_null'] is True
    assert any('Automatic scatter tail: selected' in text
               for text in automatic['metadata']['warnings'])


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
    # Every longer tail was really tried and failed; the default is kept, the failed
    # check still shows, and the user is told the repair was attempted without success.
    tried = result['metadata']['scatter_tail']['candidates'][1:]
    assert [trial['beta'] for trial in tried] == [2.0, 4.0, 8.0, 16.0]
    assert result['quality']['fit']['checks']['pre_edge_null'] is False
    assert any('none met every acceptance criterion' in text for text in result['metadata']['warnings'])
    assert not any('selected' in text and 'Automatic scatter tail' in text
                   for text in result['metadata']['warnings'])


def test_a_candidate_that_cannot_be_fitted_does_not_end_the_search(long_tail, monkeypatch):
    """Convergence is not monotonic in the tail: a longer tail can fit where a
    shorter one failed, so one failure must not stop the search."""
    scan, counts, options, fixed, automatic = long_tail
    original = engine._extract_fixed

    def first_fails(scan, counts, request, *args, **kwargs):
        if request.scatter_beta == 0.5:
            return copy.deepcopy(fixed)
        if request.scatter_beta == 2.0:
            raise ScientificError('All selected detector elements failed calibration')
        return original(scan, counts, request, *args, **kwargs)

    monkeypatch.setattr(engine, '_extract_fixed', first_fails)
    result = engine.extract(scan, counts, options)
    assert [row['beta'] for row in result['metadata']['scatter_tail']['candidates']] == \
        [0.5, 2.0, 4.0, 8.0, 16.0]
    assert result['metadata']['scatter_tail']['selected_beta'] == \
        automatic['metadata']['scatter_tail']['selected_beta'] > 2.0


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


def test_a_longer_tail_that_still_fails_the_pre_edge_check_is_not_taken(tail_runtime):
    """Every longer tail fits and shrinks the pre-edge leak but none clears the
    check: taking the least bad one moved a held-out edge step further from the
    truth than the default, so the default must stay, unchanged."""
    scan, counts, options, _ = synthetic_scan(
        points=32, detectors=1, calibration_points=3, scatter_beta=8., poisson=False)
    resolved, windows = engine.resolve_windows(scan, options.model_copy(update={'scatter_beta': None}))
    fixed = tail_runtime.extract(scan, counts, resolved.model_copy(update={'scatter_beta': 0.5}),
                                 windows, 'improving-but-failing')
    result = tail_runtime.extract(scan, counts, resolved, windows, 'improving-but-failing')
    default, *longer = result['metadata']['scatter_tail']['candidates']
    assert [row['beta'] for row in longer] == [2.0, 4.0, 8.0, 16.0]
    # Non-vacuous: each longer tail was fitted and scored better than the default.
    assert all('error' not in row and row['null_score'] < default['null_score'] for row in longer)
    assert all(row['checks']['pre_edge_null'] is False and not row['eligible']
               and 'pre-edge null check did not pass' in row['rejected_reasons'] for row in longer)
    assert result['metadata']['scatter_tail']['selected_beta'] == 0.5
    assert result['fit_counts'] == fixed['fit_counts']


def _refused_default(original, record=None, error=None):
    """Stand in for _extract_fixed: the default 0.5 is refused (by `error`, a
    fit failure unless given), longer tails run for real unless refused too."""
    def extract_fixed(scan, counts, request, *args, **kwargs):
        if record is not None:
            record.append(request.scatter_beta)
        if request.scatter_beta == 0.5 or error is not None and request.scatter_beta in error:
            raise (error or {}).get(request.scatter_beta, engine.FitRefused(
                'All selected detector elements failed calibration or amplitude fitting.'))
        return original(scan, counts, request, *args, **kwargs)
    return extract_fixed


def _fail_default_fit(monkeypatch, failure):
    """Make only the default 0.5 fit fail, below _extract_fixed, so the
    production code itself must classify the refusal."""
    if failure == 'calibration':
        calibrate = engine.calibrate

        def stopped(fitter, *args, **kwargs):
            if fitter.options.scatter_beta == 0.5:
                kwargs['max_nfev'] = 1
            return calibrate(fitter, *args, **kwargs)
        monkeypatch.setattr(engine, 'calibrate', stopped)
    else:
        fit_detector = engine.fit_detector

        def shifted(*args):
            fitted = fit_detector(*args)
            if args[0].options.scatter_beta == 0.5:
                fitted['energy'] = fitted['energy'] + 5.0     # the line leaves the window
            return fitted
        monkeypatch.setattr(engine, 'fit_detector', shifted)


@pytest.mark.parametrize('failure', ['calibration', 'lost_line'])
def test_a_refused_default_is_rescued_by_a_longer_tail_that_passes_every_check(
        long_tail, monkeypatch, failure):
    scan, counts, options, _, _ = long_tail
    _fail_default_fit(monkeypatch, failure)
    with pytest.raises(engine.FitRefused):
        engine.extract(scan, counts, options.model_copy(update={'scatter_beta': 0.5}))
    result = engine.extract(scan, counts, options)
    choice = result['metadata']['scatter_tail']
    assert choice['selected_beta'] > 0.5
    assert 'FitRefused' in choice['candidates'][0]['error']
    selected = next(row for row in choice['candidates'] if row['beta'] == choice['selected_beta'])
    assert selected['eligible'] and selected['checks']['pre_edge_null'] is True
    assert result['quality']['fit']['checks']['pre_edge_null'] is True
    assert any('default 0.5 peak widths could not be fitted' in text
               for text in result['metadata']['warnings'])


def test_a_rescue_needs_detector_elements_that_agree_in_shape(long_tail, monkeypatch):
    """With no default to compare against, a candidate whose elements disagree
    must not be taken even when the summed spectrum passes every check."""
    scan, counts, options, _, _ = long_tail
    _fail_default_fit(monkeypatch, 'calibration')
    evidence = engine._tail_evidence

    def disagreeing(result, beta):
        found = evidence(result, beta)
        found['detector_agreement'] = dict(detectors=2, checks=dict(shape_agreement=False))
        return found
    monkeypatch.setattr(engine, '_tail_evidence', disagreeing)
    with pytest.raises(engine.FitRefused, match='also tried 2, 4, 8 and 16'):
        engine.extract(scan, counts, options)


def test_an_element_with_no_counts_is_refused_before_any_fit(long_tail, monkeypatch):
    """Missing counts cannot be repaired by another tail: an input error, named,
    and no calibration spent on it."""
    scan, counts, options, _, _ = long_tail
    calls = []
    monkeypatch.setattr(engine, 'calibrate', lambda *args, **kwargs: calls.append(1))
    with pytest.raises(ScientificError, match='element 1 recorded no counts') as error:
        engine.extract(scan, np.zeros_like(counts), options)
    assert not isinstance(error.value, engine.FitRefused) and not calls


def test_an_input_error_at_the_default_never_starts_a_tail_search(long_tail, monkeypatch):
    scan, counts, options, _, _ = long_tail
    tried = []
    missing = ScientificError('The scan has no channel named i0.')
    monkeypatch.setattr(engine, '_extract_fixed',
                        _refused_default(engine._extract_fixed, tried, {0.5: missing}))
    with pytest.raises(ScientificError, match='no channel named') as error:
        engine.extract(scan, counts, options)
    assert tried == [0.5] and not isinstance(error.value, engine.FitRefused)


def test_a_refusal_stands_when_no_longer_tail_can_be_fitted(long_tail, monkeypatch):
    scan, counts, options, _, _ = long_tail
    tried = []
    refused = {beta: engine.FitRefused('All selected detector elements failed calibration.')
               for beta in (0.5, 2.0, 4.0, 8.0, 16.0)}
    monkeypatch.setattr(engine, '_extract_fixed',
                        _refused_default(engine._extract_fixed, tried, refused))
    with pytest.raises(engine.FitRefused, match='also tried 2, 4, 8 and 16'):
        engine.extract(scan, counts, options)
    assert tried == [0.5, 2.0, 4.0, 8.0, 16.0]


def test_a_refused_explicit_tail_is_not_replaced(long_tail, monkeypatch):
    scan, counts, options, _, _ = long_tail
    tried = []
    refused = {8.0: engine.FitRefused('All selected detector elements failed calibration.')}
    monkeypatch.setattr(engine, '_extract_fixed',
                        _refused_default(engine._extract_fixed, tried, refused))
    with pytest.raises(engine.FitRefused):
        engine.extract(scan, counts, options.model_copy(update={'scatter_beta': 8.}))
    assert tried == [8.0]
