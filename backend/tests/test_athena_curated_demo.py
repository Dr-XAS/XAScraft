"""Curated demo loading uses temporary synthetic data, never collaborator data."""
from copy import deepcopy
import hashlib
import json

import numpy as np
import pytest

from xraylarch_web import athena_curated_demo
from xraylarch_web.athena import AthenaStore, Command
from xraylarch_web.config import Settings
from xraylarch_web.errors import WebInputError


def command(store, project, action="example", **options):
    if action == "example":
        options.setdefault("dataset", "curated-three-elements")
    return store.command(project["id"], Command(
        version=project["version"], action=action, options=options))


@pytest.fixture
def demo(tmp_path, monkeypatch, xas_arrays):
    root = tmp_path / "assets"
    root.mkdir()
    manifest = {"schema_version": 1, "id": "curated-three-elements",
                "name": "Three element demo", "description": "Synthetic test fixture", "folders": []}
    measured = {}
    for element, e0 in (("Ni", 8333), ("Cu", 8980), ("Fe", 7112)):
        folder = {"element": element, "name": element + " demo", "spectra": []}
        (root / element).mkdir()
        modes = ("transmission", "fluorescence") if element == "Ni" else ("transmission",)
        for mode in modes:
            ident = f"{element}-{mode}"
            data = np.column_stack((xas_arrays[0] + e0 - 8980, xas_arrays[1]))
            if mode == "fluorescence":
                data[:, 1] *= 0.002
            path = root / element / f"{ident}.dat"
            np.savetxt(path, data, fmt="%.17g", header="energy_eV mu")
            measured[ident] = data
            folder["spectra"].append({
                "id": ident, "label": ident, "file": path.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "edge": "K", "mode": mode,
                "parameters": {"e0": e0, "pre1": -150, "pre2": -30, "norm1": 100,
                               "norm2": 300, "kmax": 8, "bkg_kmax": 8},
                "source": {"filename": ident + ".raw", "citation": "Synthetic test data",
                           "measurement_id": element + "-scan-1", "mapping": {"mode": mode}},
                "notes": "Synthetic fixture", "marked": element == "Ni",
            })
        manifest["folders"].append(folder)
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(athena_curated_demo, "MANIFEST_PATH", path)
    return AthenaStore(Settings(data_root=tmp_path / "runtime")), path, manifest, measured


def test_curated_demo_preserves_sources_and_organizes_three_elements(demo):
    store, _, manifest, measured = demo
    loaded = command(store, store.create())
    assert loaded["name"] == manifest["name"]
    assert loaded["version"] == 1
    assert [folder["name"] for folder in loaded["group_folders"]] == ["Ni demo", "Cu demo", "Fe demo"]
    assert [len(folder["group_ids"]) for folder in loaded["group_folders"]] == [2, 1, 1]
    assert [group["marked"] for group in loaded["groups"]] == [True, True, False, False]
    assert "artemis_example" not in loaded["last_operation"]
    assert not loaded.get("artemis_structures")
    assert loaded["last_operation"]["curated_demo"]["group_ids"] == [g["id"] for g in loaded["groups"]]
    for group in loaded["groups"]:
        ident = group["source"]["curated_demo"]["spectrum_id"]
        np.testing.assert_array_equal(group["energy"], measured[ident][:, 0])
        np.testing.assert_array_equal(group["mu"], measured[ident][:, 1])
        assert group["source"]["filename"] == ident + ".raw"
        assert group["source"]["citation"] == "Synthetic test data"
        assert group["notes"] == "Synthetic fixture"
        assert group["source"]["edge_identity"]["element"] == ident.split("-")[0]
        assert group["reference_id"] is None
        assert group["processing_error"] is None
        assert group["result"]["arrays"]["chi"] and group["result"]["arrays"]["chir_mag"]
    assert store.load(loaded["id"]) == loaded
    undone = command(store, loaded, "undo")
    assert undone["groups"] == [] and undone["group_folders"] == []
    redone = command(store, undone, "redo")
    assert redone["groups"] == loaded["groups"]
    assert redone["group_folders"] == loaded["group_folders"]


@pytest.mark.parametrize("format", ["json", "prj"])
def test_curated_demo_folder_and_provenance_round_trip(demo, format):
    store, _, _, _ = demo
    loaded = command(store, store.create())
    exported = store.export_project(loaded["id"], format)
    target = store.create()
    restored = store.restore(target["id"], target["version"], exported, f"demo.{format}")
    by_id = {group["id"]: group["label"] for group in restored["groups"]}
    assert [(folder["name"], [by_id[key] for key in folder["group_ids"]]) for folder in restored["group_folders"]] == [
        ("Ni demo", ["Ni-transmission", "Ni-fluorescence"]),
        ("Cu demo", ["Cu-transmission"]), ("Fe demo", ["Fe-transmission"]),
    ]
    for before, after in zip(loaded["groups"], restored["groups"], strict=True):
        assert after["source"]["curated_demo"] == before["source"]["curated_demo"]
        assert after["source"]["measurement_id"] == before["source"]["measurement_id"]
        np.testing.assert_array_equal(after["energy"], before["energy"])
        np.testing.assert_array_equal(after["mu"], before["mu"])


def test_curated_demo_preserves_existing_project(demo, xas_arrays):
    store, _, _, _ = demo
    original = store.create()
    original["name"] = "My experiment"
    existing = store.make_group("Existing", *xas_arrays)
    original["groups"].append(existing)
    original["group_folders"] = [{"id": "existing-folder", "name": "Existing folder", "group_ids": [existing["id"]]}]
    store.storage.write_json(original["id"], "project.json", original)
    original = store.load(original["id"])
    loaded = command(store, original)
    assert loaded["name"] == "My experiment"
    assert loaded["groups"][0] == original["groups"][0]
    assert loaded["group_folders"][0] == original["group_folders"][0]
    assert command(store, loaded, "undo")["groups"] == original["groups"]


def test_only_explicit_same_element_references_are_linked(demo):
    store, path, manifest, _ = demo
    copper = manifest["folders"][1]["spectra"][0]
    reference = dict(deepcopy(copper), id="Cu-reference", label="Cu-reference")
    copper["reference_id"] = reference["id"]
    manifest["folders"][1]["spectra"].append(reference)
    path.write_text(json.dumps(manifest))
    loaded = command(store, store.create())
    by_key = {group["source"]["curated_demo"]["spectrum_id"]: group for group in loaded["groups"]}
    assert by_key["Cu-transmission"]["reference_id"] == by_key["Cu-reference"]["id"]
    assert all(by_key[key]["reference_id"] is None for key in ("Ni-transmission", "Ni-fluorescence", "Fe-transmission"))


def test_curated_source_warning_stays_visible_after_reprocessing_and_reload(demo):
    store, path, manifest, _ = demo
    warning = "No self-absorption correction was applied to this fluorescence measurement."
    manifest["folders"][0]["spectra"][1]["source"]["warnings"] = [warning, warning]
    path.write_text(json.dumps(manifest))
    loaded = command(store, store.create())
    fluorescence = loaded["groups"][1]
    assert fluorescence["result"]["warnings"].count(warning) == 1
    updated = store.command(loaded["id"], Command(
        version=loaded["version"], action="parameters", group_ids=[fluorescence["id"]], options={"rbkg": 1.1}))
    assert updated["groups"][1]["result"]["warnings"].count(warning) == 1
    reloaded = store.load(updated["id"])
    assert reloaded["groups"][1]["result"]["warnings"].count(warning) == 1
    assert reloaded["groups"][1]["source"]["warnings"] == [warning, warning]
    for format in ("json", "prj"):
        exported = store.export_project(updated["id"], format)
        target = store.create()
        restored = store.restore(target["id"], 0, exported, f"demo.{format}")
        assert restored["groups"][1]["result"]["warnings"].count(warning) == 1


@pytest.mark.parametrize("failure", ["missing", "checksum", "invalid_recipe", "invalid_axis", "outside_asset", "cross_element_reference", "invalid_warnings"])
def test_invalid_curated_demo_does_not_mutate_project(demo, failure):
    store, path, manifest, _ = demo
    record = manifest["folders"][-1]["spectra"][0]
    asset = path.parent / record["file"]
    if failure == "missing":
        asset.unlink()
    elif failure == "checksum":
        asset.write_bytes(asset.read_bytes() + b"\n# changed\n")
    elif failure == "invalid_recipe":
        record["parameters"]["kmax"] = -1
    elif failure == "invalid_axis":
        raw = np.loadtxt(asset)
        raw[10, 0] = raw[9, 0]
        np.savetxt(asset, raw)
        record["sha256"] = hashlib.sha256(asset.read_bytes()).hexdigest()
    elif failure == "outside_asset":
        record["file"] = "../outside.dat"
    elif failure == "cross_element_reference":
        record["reference_id"] = "Cu-transmission"
    elif failure == "invalid_warnings":
        record["source"]["warnings"] = "This must be a list."
    path.write_text(json.dumps(manifest))
    original = store.create()
    with pytest.raises(WebInputError, match="curated demo"):
        command(store, original)
    assert store.load(original["id"]) == original


def test_unknown_example_collection_is_refused(demo):
    store, _, _, _ = demo
    original = store.create()
    with pytest.raises(WebInputError, match="dataset"):
        command(store, original, dataset="not-a-demo")
    assert store.load(original["id"]) == original


@pytest.fixture
def demo_with_model(demo):
    # The model uses existing public Cu reference FEFF/CIF assets; the spectra
    # remain temporary synthetic measurements from the demo fixture.
    from xraylarch_web.artemis import FitRequest, copper_example
    from xraylarch_web.artemis_attachments import structure_attachment
    from xraylarch_web.artemis_persistence import draft_from_request

    store, path, manifest, measured = demo
    example = copper_example()
    request = FitRequest.model_validate({
        "version": 0, "parameters": example["parameters"],
        "transform": dict(example["transform"], kmax=8),
        "paths": [{key: value for key, value in example["path"].items() if key != "metadata"}
                  | {"id": "cu-first-shell", "label": "Cu first shell"}],
    })
    model = draft_from_request(request, {})
    attachment = structure_attachment(13088)
    for model_path in model["paths"]:
        model_path["metadata"]["sourceCif"] = {
            "sha256": attachment["sha256"], "label": "Cu reference CIF", "siteIndex": 1,
            "attachmentId": attachment["id"],
        }
    bundle = {"schema_version": 1, "structure": attachment, "model": model}
    bundle_path = path.parent / "Cu/model.json"
    bundle_path.write_text(json.dumps(bundle))
    manifest["folders"][1]["spectra"][0]["fitting_model"] = {
        "file": "Cu/model.json", "sha256": hashlib.sha256(bundle_path.read_bytes()).hexdigest(),
    }
    path.write_text(json.dumps(manifest))
    return demo, bundle_path, bundle


def test_bundled_fitting_model_is_saved_only_on_its_spectrum_without_running_fit(demo_with_model, monkeypatch):
    from xraylarch_web import artemis, artemis_persistence

    (store, _, _, _), _, bundle = demo_with_model
    def unexpected_fit(*args, **kwargs):
        pytest.fail("Loading a fitting starter must not optimize a fit.")
    monkeypatch.setattr(artemis, "fit_group", unexpected_fit)
    monkeypatch.setattr(artemis_persistence, "fit_group", unexpected_fit)
    loaded = command(store, store.create())
    assert ["artemis" in group for group in loaded["groups"]] == [False, False, True, False]
    copper = loaded["groups"][2]
    attachment, = loaded["artemis_structures"]
    assert attachment["sha256"] == bundle["structure"]["sha256"]
    assert attachment["structure"]["cif"] == bundle["structure"]["structure"]["cif"]
    assert copper["artemis"]["history"] == []
    assert len(copper["artemis"]["current_input_sha256"]) == 64
    assert copper["artemis"]["model"]["paths"][0]["content"] == bundle["model"]["paths"][0]["content"]
    assert copper["artemis"]["model"]["paths"][0]["metadata"]["sourceCif"]["attachmentId"] == attachment["id"]
    assert loaded["last_operation"]["curated_demo"]["fitting_models"] == [{
        "group_id": copper["id"], "attachment_id": attachment["id"],
    }]
    assert store.load(loaded["id"])["groups"][2]["artemis"] == copper["artemis"]
    undone = command(store, loaded, "undo")
    assert not undone.get("artemis_structures") and not undone["groups"]
    redone = command(store, undone, "redo")
    assert redone["groups"][2]["artemis"] == copper["artemis"]
    for format in ("json", "prj"):
        exported = store.export_project(redone["id"], format)
        target = store.create()
        restored = store.restore(target["id"], 0, exported, f"demo.{format}")
        saved = restored["groups"][2]["artemis"]
        assert saved["model"] == copper["artemis"]["model"]
        assert saved["history"] == []
        assert restored["artemis_structures"] == loaded["artemis_structures"]


def test_bundled_model_reuses_existing_cif_and_remaps_its_attachment_id(demo_with_model):
    (store, _, _, _), _, bundle = demo_with_model
    original = store.create()
    existing = dict(deepcopy(bundle["structure"]), id="existing-copper-cif")
    original["artemis_structures"] = [existing]
    store.storage.write_json(original["id"], "project.json", original)
    loaded = command(store, original)
    assert loaded["artemis_structures"] == [existing]
    assert loaded["groups"][2]["artemis"]["model"]["paths"][0]["metadata"]["sourceCif"]["attachmentId"] == existing["id"]


def test_integrated_demo_keeps_spectra_only_without_reading_local_fitting_assets(demo_with_model):
    (store, _, _, _), bundle_path, _ = demo_with_model
    bundle_path.unlink()
    original = store.create()
    original["integration"] = True
    store.storage.write_json(original["id"], "project.json", original)
    loaded = command(store, original)
    assert len(loaded["groups"]) == 4
    assert not loaded.get("artemis_structures")
    assert all("artemis" not in group for group in loaded["groups"])
    assert loaded["last_operation"]["curated_demo"]["fitting_models"] == []


@pytest.mark.parametrize("failure", ["checksum", "cif_mismatch", "wrong_element", "invalid_path", "invalid_model"])
def test_invalid_fitting_bundle_leaves_project_unchanged(demo_with_model, failure):
    (store, path, manifest, _), bundle_path, bundle = demo_with_model
    record = manifest["folders"][1]["spectra"][0]
    if failure == "cif_mismatch":
        bundle["model"]["paths"][0]["metadata"]["sourceCif"]["sha256"] = "0" * 64
    elif failure == "wrong_element":
        manifest["folders"][0]["spectra"][0]["fitting_model"] = record.pop("fitting_model")
        record = manifest["folders"][0]["spectra"][0]
    elif failure == "invalid_path":
        bundle["model"]["paths"][0]["content"] = "This is not FEFF data."
    elif failure == "invalid_model":
        bundle["model"]["parameters"][0]["value"] = "unfinished"
    bundle_path.write_text(json.dumps(bundle))
    if failure != "checksum":
        record["fitting_model"]["sha256"] = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    else:
        record["fitting_model"]["sha256"] = "0" * 64
    path.write_text(json.dumps(manifest))
    original = store.create()
    with pytest.raises(WebInputError, match="curated fitting model"):
        command(store, original)
    assert store.load(original["id"]) == original


def write_fitting_bundle(fixture):
    (store, path, manifest, _), bundle_path, bundle = fixture
    bundle_path.write_text(json.dumps(bundle))
    manifest["folders"][1]["spectra"][0]["fitting_model"]["sha256"] = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    path.write_text(json.dumps(manifest))
    return store


@pytest.fixture
def demo_with_fit(demo_with_model):
    """A fully inert synthetic archive with real public FEFF file geometry."""
    from xraylarch_web.artemis_persistence import input_fingerprint, model_fingerprint, request_from_model

    (store, _, manifest, measured), _, bundle = demo_with_model
    record = manifest["folders"][1]["spectra"][0]
    source = store.make_group("Synthetic source", *measured[record["id"]].T, parameters=record["parameters"])
    model = deepcopy(bundle["model"])
    # A prior project had its own attachment ID. Only this display reference
    # should be rebound; the original fit identity and numerical hashes stay.
    for path in model["paths"]:
        path["metadata"]["sourceCif"]["attachmentId"] = "original-source-cif"
    request = request_from_model(model, 7)
    fit_paths = []
    for path in model["paths"]:
        if path["enabled"]:
            fit_paths.append({
                "id": path["id"], "label": path["label"], "filename": path["filename"],
                "metadata": deepcopy(path["metadata"]), "sigma2_expression": path["sigma2"],
                "values": {"s02": 0.9, "e0": 0.0, "deltar": 0.0, "sigma2": 0.004},
                "k": {"chi": [0.1, 0.2]}, "r": {"mag": [0.1, 0.2], "re": [0.1, 0.2], "im": [0.0, 0.0]},
            })
    fingerprint = input_fingerprint(source)
    result = {
        "project_id": "source-project", "group_id": "source-group", "group_label": "Synthetic archive",
        "version": 7, "success": True, "message": "Synthetic result", "report": "Synthetic archived report",
        "warnings": ["Synthetic FEFF diagnostic", "Demo review: inspect the synthetic residual."],
        "statistics": {"n_varys": 4, "n_independent": 10.0, "n_data": 20, "nfev": 5,
                       "chi_square": 1.0, "reduced_chi_square": 0.1, "r_factor": 0.01,
                       "aic": 2.0, "bic": 3.0, "errorbars": True, "epsilon_k": 0.01},
        "parameters": [dict(name=row.name, kind=row.kind, value=row.value, initial=row.value,
                            stderr=0.1, min=row.min, max=row.max, expression=row.expression)
                       for row in request.parameters],
        "correlations": [], "paths": fit_paths, "transform": request.transform.model_dump(),
        "metadata": {"engine": "synthetic", "input_sha256": fingerprint, "model_sha256": model_fingerprint(model)},
        "k": {"x": [1.0, 2.0], "data": [0.11, 0.22], "model": [0.1, 0.2], "residual": [0.01, 0.02], "weight": 2},
        "r": {"x": [1.0, 2.0], **{f"{curve}_{part}": [0.1, 0.2]
              for curve in ("data", "model", "residual") for part in ("mag", "re", "im")}},
        "plot_source": {"schema_version": 1, "data": [0.11, 0.22], "model": [0.1, 0.2],
                        "paths": [{"id": path["id"], "chi": [0.1, 0.2]} for path in fit_paths]},
    }
    bundle["fit"] = {
        "id": "synthetic-fit", "created": "2026-01-01T00:00:00+00:00", "input_sha256": fingerprint,
        "origin": {"project_id": "source-project", "group_id": "source-group", "project_version": 7,
                   "larch_version": "synthetic"},
        "imported": False, "model": model, "result": result,
        "receipt": {"key_sha256": "1" * 64, "body_sha256": "2" * 64},
    }
    write_fitting_bundle(demo_with_model)
    return demo_with_model


def test_bundled_fit_preserves_archived_curves_warnings_origin_and_round_trips(demo_with_fit, monkeypatch):
    from xraylarch_web import artemis, artemis_persistence

    (store, _, _, _), _, bundle = demo_with_fit
    def unexpected_fit(*args, **kwargs):
        pytest.fail("Loading a saved demo result must never optimize it again.")
    monkeypatch.setattr(artemis, "fit_group", unexpected_fit)
    monkeypatch.setattr(artemis, "feffit", unexpected_fit)
    monkeypatch.setattr(artemis_persistence, "fit_group", unexpected_fit)
    loaded = command(store, store.create())
    group = loaded["groups"][2]
    attachment, = loaded["artemis_structures"]
    expected = deepcopy(bundle["fit"])
    expected["imported"] = True
    expected.pop("receipt")
    for paths in (expected["model"]["paths"], expected["result"]["paths"]):
        for path in paths:
            path["metadata"]["sourceCif"]["attachmentId"] = attachment["id"]
    assert group["artemis"]["history"] == [expected]
    assert group["artemis"]["current_input_sha256"] == expected["input_sha256"]
    assert loaded["last_operation"]["curated_demo"]["fitting_models"] == [{
        "group_id": group["id"], "attachment_id": attachment["id"], "fit_id": expected["id"],
    }]
    assert [len(item.get("artemis", {}).get("history", [])) for item in loaded["groups"]] == [0, 0, 1, 0]
    assert AthenaStore(store.settings).load(loaded["id"])["groups"][2]["artemis"] == group["artemis"]
    undone = command(store, loaded, "undo")
    assert undone["groups"] == [] and not undone.get("artemis_structures")
    redone = command(store, undone, "redo")
    assert redone["groups"][2]["artemis"] == group["artemis"]
    for format in ("json", "prj"):
        target = store.create()
        restored = store.restore(target["id"], 0, store.export_project(loaded["id"], format), f"demo.{format}")
        assert restored["groups"][2]["artemis"] == group["artemis"]
        assert restored["artemis_structures"] == loaded["artemis_structures"]


def test_bundled_fit_is_stale_after_processing_change_without_rewriting_archive(demo_with_fit):
    from xraylarch_web.artemis_persistence import archive_summary

    (store, _, _, _), _, _ = demo_with_fit
    loaded = command(store, store.create())
    group = loaded["groups"][2]
    original = deepcopy(group["artemis"]["history"][0])
    updated = store.command(loaded["id"], Command(
        version=loaded["version"], action="parameters", group_ids=[group["id"]], options={"rbkg": 1.3}))
    state = updated["groups"][2]["artemis"]
    assert state["history"] == [original]
    assert state["current_input_sha256"] != original["input_sha256"]
    assert archive_summary(original, state["current_input_sha256"])["stale"] is True
    assert store.load(updated["id"])["groups"][2]["artemis"] == state


def test_bundled_fit_keeps_original_input_digest_when_initial_processing_has_drifted(demo_with_fit):
    (store, path, manifest, _), _, bundle = demo_with_fit
    manifest["folders"][1]["spectra"][0]["parameters"]["rbkg"] = 1.3
    path.write_text(json.dumps(manifest))
    loaded = command(store, store.create())
    state = loaded["groups"][2]["artemis"]
    assert state["history"][0]["input_sha256"] == bundle["fit"]["input_sha256"]
    assert state["current_input_sha256"] != bundle["fit"]["input_sha256"]


def test_repeated_demo_load_reuses_cif_and_remaps_both_model_and_result(demo_with_fit):
    (store, _, _, _), _, bundle = demo_with_fit
    original = store.create()
    attachment = deepcopy(bundle["structure"])
    attachment["id"] = "existing-cif"
    original["artemis_structures"] = [attachment]
    store.storage.write_json(original["id"], "project.json", original)
    loaded = command(store, original)
    repeated = command(store, loaded)
    assert repeated["artemis_structures"] == [attachment]
    for index in (2, 6):
        state = repeated["groups"][index]["artemis"]
        archive, = state["history"]
        for paths in (state["model"]["paths"], archive["model"]["paths"], archive["result"]["paths"]):
            assert all(path["metadata"]["sourceCif"]["attachmentId"] == attachment["id"] for path in paths)
        assert archive["origin"] == bundle["fit"]["origin"]
        assert archive["result"]["group_id"] == "source-group"
    assert repeated["groups"][:4] == loaded["groups"]


@pytest.mark.parametrize("failure", [
    "schema", "checksum", "archive_model", "archive_model_hash", "archive_input_hash", "archive_origin",
    "result_transform", "result_parameters", "result_path", "archive_cif", "result_cif", "curves", "two_fits",
])
def test_invalid_bundled_fit_is_atomic(demo_with_fit, failure):
    (store, path, manifest, _), bundle_path, bundle = demo_with_fit
    archive = bundle["fit"]
    if failure == "schema":
        archive["stale"] = False
    elif failure == "archive_model":
        archive["model"]["parameters"][0]["value"] = "0.8"
    elif failure == "archive_model_hash":
        archive["result"]["metadata"]["model_sha256"] = "0" * 64
    elif failure == "archive_input_hash":
        archive["input_sha256"] = "0" * 64
    elif failure == "archive_origin":
        archive["result"]["group_id"] = "unrelated-source"
    elif failure == "result_transform":
        archive["result"]["transform"]["kmax"] = 7
    elif failure == "result_parameters":
        archive["result"]["parameters"][0]["initial"] = 0.8
    elif failure == "result_path":
        archive["result"]["paths"][0]["metadata"]["reff"] = 9.0
    elif failure == "archive_cif":
        archive["model"]["paths"][0]["metadata"]["sourceCif"]["sha256"] = "0" * 64
    elif failure == "result_cif":
        archive["result"]["paths"][0]["metadata"]["sourceCif"]["sha256"] = "0" * 64
    elif failure == "curves":
        archive["result"]["r"]["model_re"].pop()
    elif failure == "two_fits":
        bundle["fit"] = [archive, deepcopy(archive)]
    write_fitting_bundle(demo_with_fit)
    if failure == "checksum":
        bundle_path.write_text(bundle_path.read_text() + " ")
    original = store.create()
    with pytest.raises(WebInputError, match="curated fitting model"):
        command(store, original)
    assert store.load(original["id"]) == original
