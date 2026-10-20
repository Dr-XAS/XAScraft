"""The team's regression test added to upstream's tests/test_read_beamlinedata.py (patch 0004).

Only this test is the team's; the rest of that upstream file stays upstream's.
"""


def test_aps12bm_label_with_two_underscores_or_no_number_keeps_its_column():
    # 'pref, suff = word.split("_")' raised on '5_I0_corr', failing the read,
    # and a label written without its number was dropped, shifting every
    # later label one column to the left.
    from larch.io.xafs_beamlines import APS12BM_BeamlineData
    header = ['#C exafs_region 50 275 225 1 0 0 0',
              '#C 1_Energy (keV) 2_sec 3_I0 4_I0_corr It 6_If']
    bldat = APS12BM_BeamlineData(header)
    assert bldat.get_array_labels() == ['energy', 'sec', 'i0', 'i0_corr', 'it', 'if']
    assert bldat.energy_units == 'keV'
