"""Energy-unit guesses must not attach physical units to detector signals."""

from io import StringIO

import numpy as np
import pytest

from xraylarch_web.athena import AthenaStore
from xraylarch_web.athena_columns import suggest_columns
from xraylarch_web.config import Settings
from xraylarch_web.parsing import parse_upload


def column(name, *, start=7000., unit=None, role=None):
    return dict(column_id=name, name=name, preview=[start + i for i in range(5)],
                unit=unit, role_hint=role)


@pytest.mark.parametrize('start, expected', [(7000., 'eV'), (7., 'keV')])
def test_inspection_does_not_label_rising_ion_chamber_signals_as_energy(tmp_path, start, expected):
    # All detector previews deliberately rise, as they did in the tutorial scan.
    table = StringIO()
    np.savetxt(table, np.column_stack([start + np.arange(10) * .01,
                                     10000 + np.arange(10),
                                     3000 + np.arange(10),
                                     1000 + np.arange(10)]), header='energy I0 I1 I2')
    store = AthenaStore(Settings(data_root=tmp_path))
    project = store.create()
    inspected = store.inspect(project['id'], table.getvalue().encode(), 'synthetic-detectors.dat')
    units = {c['name'].lower(): inspected['column_units'][c['column_id']]
             for c in inspected['columns']}
    assert units == dict(energy=expected, i0=None, i1=None, i2=None)
    assert inspected['athena_suggestion']['units'] == expected
    assert inspected['athena_suggestion']['mode'] == 'transmission'


@pytest.mark.parametrize('name', ['energy', 'E', 'EnergyReadback', 'mono_energy', 'enrg'])
def test_named_energy_is_recognized_after_a_detector_column(name):
    suggestion, units = suggest_columns([column('I1'), column(name, start=7.)], 'scan.dat')
    assert suggestion['energy_column'] == name
    assert suggestion['units'] == 'keV'
    assert units == {'I1': None, name: 'keV'}


def test_energy_role_takes_precedence_and_suppresses_anonymous_fallback():
    suggestion, units = suggest_columns([
        column('col1'), column('energy', start=7.), column('mono_axis', role='energy'),
    ], 'scan.dat')
    assert suggestion['energy_column'] == 'mono_axis'
    assert units == dict(col1=None, energy='keV', mono_axis='eV')


@pytest.mark.parametrize('unit, start, expected', [('eV', 7., 'eV'), ('keV', 7000., 'keV')])
def test_explicit_energy_units_are_kept_even_without_an_energy_label(unit, start, expected):
    _, units = suggest_columns([column('axis', start=start, unit=unit)], 'scan.dat')
    assert units == {'axis': expected}


@pytest.mark.parametrize('start, expected', [(7000., 'eV'), (7., 'keV')])
def test_headerless_numeric_table_keeps_first_column_unit_guess(start, expected):
    data = '\n'.join(f'{start + i * .01} {1000 + i}' for i in range(10)).encode()
    parsed = parse_upload(data, 'anonymous.dat')
    suggestion, units = suggest_columns(parsed.inspection().model_dump()['columns'], 'anonymous.dat')
    first, signal = [c.column_id for c in parsed.columns]
    assert suggestion['energy_column'] == first
    assert suggestion['units'] == expected
    assert units == {first: expected, signal: None}


@pytest.mark.parametrize('name', ['I0', 'I1', 'I2', 'It', 'If', 'mu', 'chi', 'k', 'temperature'])
def test_first_column_named_as_a_nonenergy_quantity_does_not_get_energy_units(name):
    _, units = suggest_columns([column(name), column('col2')], 'scan.dat')
    assert all(unit is None for unit in units.values())


@pytest.mark.parametrize('name', ['energy', 'col1'])
def test_explicit_nonenergy_units_are_not_replaced_by_a_numeric_guess(name):
    _, units = suggest_columns([column(name, unit='counts')], 'scan.dat')
    assert units[name] is None
