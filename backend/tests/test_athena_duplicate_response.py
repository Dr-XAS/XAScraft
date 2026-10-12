"""Duplicate replies transfer only new spectra while retaining complete undo state."""

from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

import xraylarch_web.athena as athena
from xraylarch_web.athena import AthenaStore, Command
from xraylarch_web.config import Settings
from xraylarch_web.main import create_app


@pytest.fixture(scope="module")
def spectrum(tmp_path_factory):
    store = AthenaStore(Settings(data_root=tmp_path_factory.mktemp("duplicate-spectrum")))
    data = np.loadtxt(Path(__file__).parents[2] / "examples/xafsdata/cu_rt01.xmu")
    return store.make_group("Copper", data[:, 0], data[:, 1], source={
        "original_filename": "cu_rt01.xmu", "raw_arrays": {"signal": data[:, 1].tolist()},
        "xdi_metadata": {"attributes": {"scan": {"process": "Imported copper"}}},
    })


@pytest.fixture
def workspace(tmp_path, spectrum, monkeypatch):
    settings = Settings(data_root=tmp_path)
    store = AthenaStore(settings)
    initial = store.create()
    groups = [dict(deepcopy(spectrum), id=f"group-{index}", marked=True, frozen=False)
              for index in range(3)]
    groups[0].update(reference_id="group-1", background_standard_id="group-2", frozen=True)
    groups[0]["artemis"] = {"schema_version": 1, "history": [], "model": {
        "revision": 0, "paths": [], "parameters": [{
            "id": "amplitude", "name": "amp", "kind": "guess", "value": "0.9",
            "min": "0", "max": "2", "expression": "",
        }], "transform": {"fitspace": "r", "window": "hanning", "kmin": "3", "kmax": "12",
                          "dk": "2", "rmin": "1", "rmax": "3", "dr": "0.5", "kweight": [2]},
    }}
    project = store.save({**initial, "groups": groups, "group_folders": [
        {"id": "samples", "name": "Samples", "group_ids": ["group-0", "group-1"]},
    ]}, initial, "Test spectra")

    def forbidden(*args, **kwargs):
        pytest.fail("Duplicating must reuse cached scientific arrays without processing")
    monkeypatch.setattr(AthenaStore, "process", forbidden)
    monkeypatch.setattr(athena, "process_spectrum", forbidden)
    with TestClient(create_app(settings)) as client:
        yield store, client, project


def command(client, project, **changes):
    payload = {"version": project["version"], "action": "duplicate",
               "group_ids": ["group-0"], "options": {}, "response_mode": "duplicate", **changes}
    return client.post(f"/api/athena/projects/{project['id']}/command", json=payload)


def reconstruct(before, delta):
    groups = {group["id"]: group for group in before["groups"] + delta["groups"]}
    return {**before, **{key: value for key, value in delta.items()
                        if key not in {"kind", "base_version", "group_order", "groups"}},
            "groups": [groups[group_id] for group_id in delta["group_order"]]}


def test_compact_duplicate_reconstructs_saved_project_and_keeps_science(workspace):
    store, client, before = workspace
    response = command(client, before)
    assert response.status_code == 200, response.text
    delta = response.json()
    assert delta["kind"] == "duplicate"
    assert delta["base_version"] == before["version"]
    assert delta["version"] == before["version"] + 1
    assert len(delta["groups"]) == 1
    duplicate = delta["groups"][0]
    source = before["groups"][0]
    assert delta["last_operation"]["created_group_ids"] == [duplicate["id"]]
    assert delta["group_order"] == ["group-0", duplicate["id"], "group-1", "group-2"]
    assert delta["group_folders"][0]["group_ids"] == delta["group_order"][:3]
    assert delta["group_added_orders"][duplicate["id"]] > max(before["group_added_orders"].values())
    assert duplicate["label"] == source["label"] + " · copy"
    assert duplicate["marked"] and not duplicate["frozen"]
    assert duplicate["reference_id"] is None
    assert duplicate["background_standard_id"] == source["background_standard_id"]
    for key in ("energy", "mu", "parameters", "result", "processing_error", "artemis"):
        assert duplicate[key] == source[key]
    assert duplicate["source"]["raw_arrays"] == source["source"]["raw_arrays"]
    assert duplicate["source"]["original_filename"] == source["source"]["original_filename"]
    assert duplicate["source"]["xdi_metadata"]["attributes"]["scan"]["process"] == "Imported copper; "
    saved = store.load(before["id"])
    assert reconstruct(before, delta) == saved
    assert [group for group in saved["groups"] if group["id"] != duplicate["id"]] == before["groups"]
    for group in before["groups"]:
        assert saved["group_versions"][group["id"]] == before["group_versions"][group["id"]]
    assert len(response.content) < len(json.dumps(saved)) / 3


def test_multiple_duplicates_are_deduplicated_and_inserted_next_to_sources(workspace):
    store, client, before = workspace
    response = command(client, before, group_ids=["group-2", "group-0", "group-2"])
    assert response.status_code == 200, response.text
    delta = response.json()
    assert len(delta["groups"]) == 2
    first, second = delta["groups"]
    assert delta["group_order"] == ["group-0", first["id"], "group-1", "group-2", second["id"]]
    assert reconstruct(before, delta) == store.load(before["id"])


def test_duplicate_is_independent_in_memory_and_undo_redo_restore_exact_arrays(workspace):
    store, client, before = workspace
    saved = store.command(before["id"], Command(version=before["version"], action="duplicate", group_ids=["group-0"]))
    source, duplicate = saved["groups"][:2]
    duplicate["mu"][0] += 1
    duplicate["result"]["arrays"]["norm"][0] += 1
    duplicate["source"]["raw_arrays"]["signal"][0] += 1
    duplicate["parameters"]["energy_shift"] += 1
    duplicate["artemis"]["model"]["parameters"][0]["value"] = "0.5"
    assert source == before["groups"][0]
    persisted = store.load(before["id"])
    assert persisted["groups"][1]["mu"] == source["mu"]
    undone = command(client, persisted, action="undo", group_ids=[], response_mode="project").json()
    assert undone["groups"] == before["groups"]
    assert undone["group_folders"] == before["group_folders"]
    redone = command(client, undone, action="redo", group_ids=[], response_mode="project").json()
    assert redone["groups"] == persisted["groups"]
    assert redone["group_folders"] == persisted["group_folders"]


def test_default_response_stays_full_and_stale_duplicate_does_not_apply(workspace):
    store, client, before = workspace
    response = command(client, before, response_mode="project")
    assert response.status_code == 200
    saved = store.load(before["id"])
    assert response.json() == saved
    assert "kind" not in response.json()
    stale = command(client, before)
    assert stale.status_code == 409
    assert store.load(before["id"]) == saved


def test_duplicate_response_refreshes_analyses_saved_without_a_revision(workspace):
    store, client, before = workspace
    analysis = store._persist_analysis(before["id"], {
        "kind": "pca", "project_version": before["version"], "group_ids": ["group-0"],
        "options": {}, "result": {"explained_variance_ratio": [1.0]},
    })
    delta = command(client, before).json()
    assert delta["analyses"] == [analysis]
    assert reconstruct(before, delta) == store.load(before["id"])


def test_idempotent_retry_after_later_edit_returns_full_current_project(workspace):
    store, client, before = workspace
    payload = {"version": before["version"], "action": "duplicate", "group_ids": ["group-0"],
               "response_mode": "duplicate"}
    url = f"/api/athena/projects/{before['id']}/command"
    headers = {"Idempotency-Key": "duplicate-once"}
    first = client.post(url, json=payload, headers=headers)
    assert first.status_code == 200
    delta = first.json()
    saved = reconstruct(before, delta)
    updated = command(client, saved, action="metadata", options={"label": "Changed after duplicate"},
                      response_mode="project").json()
    retry = client.post(url, json=payload, headers=headers)
    assert retry.status_code == 200
    assert "kind" not in retry.json()
    assert retry.json()["groups"] == updated["groups"]
    assert retry.json()["last_operation"]["idempotent_replay"]["version_after"] == delta["version"]
    assert store.load(before["id"])["groups"] == updated["groups"]


@pytest.mark.parametrize("action", ["metadata", "selection", "parameters", "copy_series", "undo"])
def test_duplicate_response_rejects_other_actions_before_mutation(workspace, action):
    store, client, before = workspace
    snapshot = store.storage.path(before["id"], "project.json").read_bytes()
    response = command(client, before, action=action)
    assert response.status_code == 422
    assert store.storage.path(before["id"], "project.json").read_bytes() == snapshot
