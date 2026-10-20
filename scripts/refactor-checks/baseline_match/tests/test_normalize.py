"""The declared normalization: what a capture keeps, renumbers and masks."""
from normalize import normalize

PROJECT = "Qm9yWZ1x8kTq0aLw3v_Hn7Zc"   # athena uid(): secrets.token_urlsafe(18)
GROUP_A = "a1B2c3D4e5F6g7H8i9J0k_Lm"
GROUP_B = "Zz9Yy8Xx7Ww6Vv5Uu4Tt3Ss2"
VERSION = "2026.3.1.post534+g3461938ac"
FIT = "dd984a22584d48968524aaa119e55a19"  # uuid4().hex


def test_ids_are_renumbered_by_first_appearance_as_values_and_keys():
    document = {
        "id": PROJECT,
        "groups": [{"id": GROUP_A}, {"id": GROUP_B, "reference_id": GROUP_A}],
        "group_versions": {GROUP_B: 2, GROUP_A: 1},
        "fit_id": FIT,
    }

    assert normalize(document, larch_version=VERSION, run_dates={"2026-10-20"}) == {
        "id": "ID#1",
        "groups": [{"id": "ID#2"}, {"id": "ID#3", "reference_id": "ID#2"}],
        "group_versions": {"ID#3": 2, "ID#2": 1},
        "fit_id": "ID#4",
    }


def test_a_known_id_inside_longer_text_is_renumbered_the_same_way():
    document = {"id": GROUP_A,
                "headers": {"content-disposition": f'attachment; filename="artemis-{GROUP_A}.larix"'}}

    assert normalize(document, larch_version=VERSION, run_dates={"2026-10-20"})["headers"] == {
        "content-disposition": 'attachment; filename="artemis-ID#1.larix"'}


def test_the_declared_volatile_fields_are_masked_and_nothing_else():
    version = "2026.3.1.post35+g8d6cd41c2.xascraft.9b231a511159"
    document = {
        "created": "2026-10-20T06:31:07.120934+00:00",
        "history": [{"time": "2026-10-20T06:31:07.121+00:00", "message": "Loaded examples"}],
        "origin": {"larch_version": version, "project_version": 3},
        "header": f"# XDI/1.0 Larch/{version}",
        "input_sha256": "9" * 64,
        "fits": {"current_input_sha256": "8" * 64, "model_sha256": "7" * 64},
        "metadata": {"seconds": {"fit": 0.41, "optimizer": 0.4, "total": 0.5}, "nfev": 41},
        "seconds": 3.0,
    }

    assert normalize(document, larch_version=version, run_dates={"2026-10-20"}) == {
        "created": "<timestamp>",
        "history": [{"time": "<timestamp>", "message": "Loaded examples"}],
        "origin": {"larch_version": "<larch_version>", "project_version": 3},
        "header": "# XDI/1.0 Larch/<larch_version>",
        "input_sha256": "<input_sha256>",
        "fits": {"current_input_sha256": "<input_sha256>", "model_sha256": "7" * 64},
        "metadata": {"seconds": "<seconds>", "nfev": 41},
        "seconds": 3.0,
    }


def test_a_timestamp_carried_in_the_data_rather_than_minted_by_the_run_is_kept():
    document = {"xdi": {"Scan.start_time": "2001-06-26T22:27:31"}, "created": "2026-10-20 23:59:59"}

    assert normalize(document, larch_version=VERSION, run_dates={"2026-10-20"}) == {
        "xdi": {"Scan.start_time": "2001-06-26T22:27:31"}, "created": "<timestamp>"}


def test_names_with_the_shape_of_an_id_outside_id_fields_are_kept():
    document = {"effective": {"background_standard_kmin": 2.0},
                "label": "CuHERFD_Chalcopyrite_001", "source": "CuHERFD_Chalcopyrite_001",
                "standard_id": "as-k-kankite"}

    assert normalize(document, larch_version=VERSION, run_dates={"2026-10-20"}) == document


def test_ids_are_found_in_every_id_field_shape():
    document = {"group_ids": [GROUP_A], "parents": [GROUP_B], "attachmentId": FIT,
                "group_added_orders": {PROJECT: 0}, "label": f"merge of {GROUP_A}"}

    assert normalize(document, larch_version=VERSION, run_dates={"2026-10-20"}) == {
        "group_ids": ["ID#1"], "parents": ["ID#2"], "attachmentId": "ID#3",
        "group_added_orders": {"ID#4": 0}, "label": "merge of ID#1"}


def test_text_that_merely_looks_like_part_of_an_id_is_kept():
    document = {"label": "Cu foil 10 K", "note": "a1B2c3D4e5F6g7H8i9J0k_Lmn is 25 characters"}

    assert normalize(document, larch_version=VERSION, run_dates={"2026-10-20"}) == document
