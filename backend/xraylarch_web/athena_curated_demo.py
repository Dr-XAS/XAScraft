"""Manifest-backed measured demos, kept separate from the copper regression fixture.

Each asset contains the measured energy and extracted mu columns. Its original
file, channel mapping and acquisition provenance stay in source metadata; the
loader neither aligns measurements nor invents linked reference channels.
"""
from __future__ import annotations

import copy
import hashlib
from io import BytesIO
import json
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .athena_e0 import atomic_edge
from .athena_science import AthenaParameters
from .errors import WebInputError

MANIFEST_PATH = Path(__file__).resolve().parents[2] / "examples/athena/curated_demo/manifest.json"
DATASET_ID = "curated-three-elements"


class _FittingAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class _Spectrum(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=200)
    file: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    edge: str = "K"
    mode: Literal["transmission", "fluorescence", "direct"]
    parameters: AthenaParameters = Field(default_factory=AthenaParameters)
    source: dict[str, Any] = Field(default_factory=dict)
    notes: str = Field(default="", max_length=20_000)
    marked: bool = Field(default=True, strict=True)
    reference_id: str | None = None
    fitting_model: _FittingAsset | None = None

    @field_validator("source")
    @classmethod
    def source_warnings_are_text(cls, value):
        warnings = value.get("warnings", [])
        if not isinstance(warnings, list) or not all(isinstance(item, str) for item in warnings):
            raise ValueError("Source warnings must be a list of strings.")
        return value


class _Folder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    element: str
    name: str = Field(min_length=1, max_length=100)
    spectra: list[_Spectrum] = Field(min_length=1, max_length=100)


class _Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    id: Literal["curated-three-elements"]
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    folders: list[_Folder] = Field(min_length=3, max_length=3)


def _unavailable(message):
    return WebInputError(
        "athena_example_unavailable", message,
        recovery="Restore the curated demo manifest and its matching data files, then retry.",
    )


def _asset_bytes(root, asset):
    path = (root / asset.file).resolve()
    if not path.is_relative_to(root) or Path(asset.file).is_absolute():
        raise ValueError("Asset path must stay inside the curated demo directory.")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != asset.sha256:
        raise ValueError("The asset checksum does not match its manifest.")
    return data


def _bundled_fit(value, model, version):
    """Check an inert archive against its original numerical recipe and FEFF files."""
    from .artemis_persistence import FitArchive, ModelDraft, model_fingerprint, prepared_model, request_from_model

    archive = FitArchive.model_validate(value).model_dump(exclude_none=True)
    checked = prepared_model(ModelDraft.model_validate(archive["model"]))
    fingerprint = model_fingerprint(checked)
    result = archive["result"]
    if (fingerprint != model_fingerprint(model)
            or result["metadata"].get("model_sha256") != fingerprint
            or result["metadata"].get("input_sha256") != archive["input_sha256"]):
        raise ValueError("The saved fit fingerprints disagree with its bundled model or original input.")
    origin = archive["origin"]
    if (result["project_id"] != origin["project_id"] or result["group_id"] != origin["group_id"]
            or result["version"] != origin["project_version"]):
        raise ValueError("The saved fit result disagrees with its recorded origin.")
    request = request_from_model(checked, version)
    if result["transform"] != request.transform.model_dump():
        raise ValueError("The saved fit transform disagrees with its model.")
    parameters = {row["name"]: row for row in result["parameters"]}
    if len(parameters) != len(result["parameters"]) or set(parameters) != {row.name for row in request.parameters}:
        raise ValueError("The saved fit parameters disagree with its model.")
    for definition in request.parameters:
        row = parameters[definition.name]
        if (any(row[key] != getattr(definition, key) for key in ("kind", "min", "max", "expression"))
                or (definition.kind != "def" and row["initial"] != definition.value)):
            raise ValueError("The saved fit parameter recipe disagrees with its model.")
    current_paths = {path["id"]: path for path in model["paths"]}
    archive_paths = {path["id"]: path for path in archive["model"]["paths"]}
    if set(current_paths) != set(archive_paths):
        raise ValueError("The saved fit path identities disagree with its bundled model.")
    science_keys = ("reff", "degen", "nleg", "absorber", "edge", "geometry", "kmin", "kmax")
    def same_cif(left, right):
        return left is not None and right is not None and all(
            left.get(key) == right.get(key) for key in ("sha256", "siteIndex"))

    for path in checked["paths"]:
        saved = archive_paths[path["id"]]
        current = current_paths[path["id"]]
        if (saved["content"] != current["content"] or saved["enabled"] != current["enabled"]
                or any(saved["metadata"][key] != path["metadata"][key] for key in science_keys)
                or not same_cif(saved["metadata"].get("sourceCif"), current["metadata"].get("sourceCif"))
                or saved["metadata"].get("feff") != current["metadata"].get("feff")):
            raise ValueError("The saved fit FEFF paths disagree with its bundled model.")
    active = {key: path for key, path in archive_paths.items() if path["enabled"]}
    if len(result["paths"]) != len(active) or {path["id"] for path in result["paths"]} != set(active):
        raise ValueError("The saved fit result must contain exactly the enabled FEFF paths.")
    for path in result["paths"]:
        metadata = active[path["id"]]["metadata"]
        if (any(path["metadata"][key] != metadata[key] for key in science_keys)
                or ("sourceCif" in path["metadata"] and not same_cif(path["metadata"]["sourceCif"], metadata.get("sourceCif")))
                or ("feff" in path["metadata"] and path["metadata"]["feff"] != metadata.get("feff"))
                or ("sigma2_expression" in path and path["sigma2_expression"] != active[path["id"]]["sigma2"])):
            raise ValueError("The saved fit result disagrees with its enabled FEFF path metadata.")
        source = result["metadata"].get("feff_sources", {}).get(path["id"])
        if source is not None and source != metadata.get("feff"):
            raise ValueError("The saved fit result disagrees with its FEFF calculation provenance.")
    return archive


def _attach_fitting_model(root, asset, group, project):
    """Retain a checked model, optional archived fit and CIF, without optimization."""
    from .artemis_attachments import merge_attachments, source_identity, validate_attachments
    from .artemis_persistence import ModelDraft, imported_state, prepared_model, request_from_model

    try:
        data = _asset_bytes(root, asset)
        if len(data) > 16_000_000:
            raise ValueError("A bundled model, fit and CIF must not exceed 16 MB.")
        bundle = json.loads(data)
        required = {"schema_version", "structure", "model"}
        if (not isinstance(bundle, dict) or not required <= set(bundle) or set(bundle) - required - {"fit"}
                or type(bundle["schema_version"]) is not int or bundle["schema_version"] != 1):
            raise ValueError("A fitting bundle needs schema_version 1, structure, model and optionally one fit.")
        attachment, = validate_attachments([bundle["structure"]])
        model = prepared_model(ModelDraft.model_validate(bundle["model"]))
        request_from_model(model, project["version"])  # A usable numeric start; no optimization.
        if not any(path["enabled"] for path in model["paths"]):
            raise ValueError("A fitting starter needs at least one enabled FEFF path.")
        identity = group["source"]["edge_identity"]
        sites = {site["index"]: site for site in attachment["structure"]["sites"]}
        for path in model["paths"]:
            metadata = path["metadata"]
            source_cif = metadata.get("sourceCif", {})
            site = sites.get(source_cif.get("siteIndex"))
            if (source_cif.get("sha256") != attachment["sha256"] or site is None
                    or site["element"] != identity["element"]):
                raise ValueError("The fitting path must name the attached CIF and its absorbing site.")
            if metadata["absorber"] != identity["element"] or metadata["edge"] != identity["edge"]:
                raise ValueError("The FEFF absorber and edge must match the measured spectrum.")
            if metadata.get("feff", {}).get("cif_sha256", attachment["sha256"]) != attachment["sha256"]:
                raise ValueError("The FEFF provenance disagrees with the attached CIF.")
        history = [_bundled_fit(bundle["fit"], model, project["version"])] if "fit" in bundle else []
        attachments = merge_attachments(project.get("artemis_structures", []), [attachment])
        attached = next(item for item in attachments if source_identity(item) == source_identity(attachment))
        path_lists = [model["paths"]]
        for archive in history:
            path_lists.extend((archive["model"]["paths"], archive["result"]["paths"]))
        for paths in path_lists:
            for path in paths:
                if "sourceCif" in path["metadata"]:
                    path["metadata"]["sourceCif"]["attachmentId"] = attached["id"]
        # Import provenance is retained; save/load derives current_input_sha256
        # from the processed spectrum, so dependency or recipe drift stays stale.
        state = imported_state({"schema_version": 1, "model": model, "history": history})
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise _unavailable(f"The curated fitting model for '{group['label']}' could not be loaded: {exc}") from exc
    project["artemis_structures"] = attachments
    group["artemis"] = state
    group["source"]["curated_demo"]["fitting_model"] = asset.model_dump()
    return {"group_id": group["id"], "attachment_id": attached["id"],
            **({"fit_id": history[0]["id"]} if history else {})}


def append_curated_demo(store, project: dict) -> dict:
    """Validate every asset, then append three folders in the command's Undo step."""
    # Lazy imports avoid a cycle with the command dispatcher.
    from .athena import _exchange_budget, uid

    try:
        manifest = _Manifest.model_validate_json(MANIFEST_PATH.read_bytes())
    except (OSError, ValidationError) as exc:
        raise _unavailable("The curated demo manifest is missing or invalid.") from exc
    elements = {folder.element for folder in manifest.folders}
    if len(elements) != 3:
        raise _unavailable("The curated demo needs three different absorbing elements.")
    records = [record for folder in manifest.folders for record in folder.spectra]
    if len({record.id for record in records}) != len(records):
        raise _unavailable("The curated demo contains duplicate spectrum identifiers.")
    if len(project["groups"]) + len(records) > 100:
        raise WebInputError("athena_invalid", "A project can contain at most 100 groups.")

    root = MANIFEST_PATH.parent.resolve()
    groups, folders, by_key, identities = [], [], {}, {}
    for folder in manifest.folders:
        folder_ids = []
        for record in folder.spectra:
            try:
                identity = atomic_edge(folder.element, record.edge)
                data = _asset_bytes(root, record)
                raw = np.loadtxt(BytesIO(data), ndmin=2)
                if raw.shape[1] != 2:
                    raise ValueError("Each asset must contain exactly energy and mu columns.")
                source = copy.deepcopy(record.source)
                mapping = source.setdefault("mapping", {})
                if not isinstance(mapping, dict) or mapping.get("mode", record.mode) != record.mode:
                    raise ValueError("The acquisition mode disagrees with the source mapping.")
                mapping.setdefault("mode", record.mode)
                source.setdefault("filename", Path(record.file).name)
                source["edge_identity"] = {
                    "element": identity["element"], "edge": identity["edge"], "origin": "curated",
                }
                source["curated_demo"] = {
                    "id": manifest.id, "spectrum_id": record.id,
                    "file": record.file, "sha256": record.sha256,
                }
                group = store.make_group(
                    record.label, raw[:, 0], raw[:, 1],
                    parameters=record.parameters.model_dump(), source=source,
                )
                if group["processing_error"]:
                    raise ValueError(group["processing_error"])
            except (OSError, ValueError, IndexError) as exc:
                raise _unavailable(f"The curated demo data '{record.label}' could not be loaded: {exc}") from exc
            group.update(marked=record.marked, notes=record.notes)
            groups.append(group)
            by_key[record.id] = group
            identities[record.id] = (identity["element"], identity["edge"])
            folder_ids.append(group["id"])
        folders.append({"id": uid(), "name": folder.name, "group_ids": folder_ids})

    _exchange_budget([*project["groups"], *groups], store.settings)
    project["groups"].extend(groups)
    project.setdefault("group_folders", []).extend(folders)
    for record in records:
        if record.reference_id is None:
            continue
        if record.reference_id not in by_key or identities[record.id] != identities[record.reference_id]:
            raise _unavailable(f"The curated demo reference for '{record.label}' must name a spectrum at the same element and edge.")
        # Only explicit, provenance-backed sample/reference pairs in the
        # manifest are linked. A folder does not imply a shared reference.
        store.assign_reference(project, [by_key[record.id]], by_key[record.reference_id])
    fitting_models = []
    if project.get("integration") is not True:
        for record in records:
            if record.fitting_model is not None:
                fitting_models.append(_attach_fitting_model(root, record.fitting_model, by_key[record.id], project))
    if project["name"] == "Untitled project":
        project["name"] = manifest.name
    return {"id": manifest.id, "name": manifest.name,
            "folder_ids": [folder["id"] for folder in folders],
            "group_ids": [group["id"] for group in groups], "fitting_models": fitting_models}
