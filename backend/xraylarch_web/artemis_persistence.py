"""Bounded, inert Artemis drafts and fit archives owned by Athena groups."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal

import larch
from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import Field, ValidationError, field_validator, model_validator

from .artemis import FitPath, FitRequest, FitRouteRequest, PathInput, StrictModel, fit_group, inspect_path
from .artemis_attachments import local_project
from .errors import WebInputError
from .artemis_provenance import FeffSource, add_fit_provenance, text_sha256
from .agent_views import project_view

ProjectView = Literal["full", "summary", "parameters"]

MAX_HISTORY = 10
MAX_PROJECT_BYTES = 20_000_000
MAX_MODEL_BYTES = 4_500_000
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
TextNumber = Annotated[str, Field(max_length=64)]


def _fail(message):
    raise WebInputError("invalid_artemis_state", message, fields=("artemis",),
                        recovery="Review the saved model or fit history. Export an archive before removing saved fits.")


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


class Atom(StrictModel):
    atom: str = Field(max_length=8)
    x: float
    y: float
    z: float
    ipot: int = Field(ge=0, le=120)


class ViewerCluster(StrictModel):
    source: Literal["feff.inp"]
    atoms: list[Atom] = Field(max_length=4000)


class SourceCif(StrictModel):
    sha256: Digest
    label: str = Field(min_length=1, max_length=512)
    siteIndex: int = Field(ge=1)
    attachmentId: Identifier | None = None


class PathMetadata(StrictModel):
    reff: float = Field(gt=0, le=100)
    degen: float = Field(gt=0, le=100000)
    nleg: int = Field(ge=2, le=20)
    absorber: str = Field(max_length=8)
    edge: str = Field(max_length=16)
    geometry: list[Atom] = Field(max_length=20)
    kmin: float = Field(ge=0)
    kmax: float = Field(gt=0)
    viewerCluster: ViewerCluster | None = None
    sourceCif: SourceCif | None = None
    feff: FeffSource | None = None


class DraftPath(FitPath):
    metadata: PathMetadata


class DraftParameter(StrictModel):
    id: Identifier
    name: str = Field(max_length=32)
    kind: Literal["guess", "set", "def"]
    value: TextNumber
    min: TextNumber
    max: TextNumber
    expression: str = Field(max_length=256)


class DraftTransform(StrictModel):
    fitspace: Literal["k", "r"]
    window: Literal["hanning", "kaiser", "parzen", "welch"]
    kmin: TextNumber
    kmax: TextNumber
    dk: TextNumber
    rmin: TextNumber
    rmax: TextNumber
    dr: TextNumber
    kweight: list[int] = Field(max_length=4)

    @field_validator("kweight")
    @classmethod
    def weights(cls, values):
        if any(value not in range(4) for value in values) or len(values) != len(set(values)):
            raise ValueError("Select unique k weights from 0 to 3.")
        return values


class ModelDraft(StrictModel):
    parameters: list[DraftParameter] = Field(max_length=32)
    paths: list[DraftPath] = Field(max_length=24)
    transform: DraftTransform
    revision: int = Field(ge=0)

    @model_validator(mode="after")
    def bounded(self):
        for items in (self.parameters, self.paths):
            if len({item.id for item in items}) != len(items):
                raise ValueError("Model row IDs must be unique.")
        if any(len(path.content.encode("utf-8")) > 500_000 for path in self.paths):
            raise ValueError("Each FEFF file must not exceed 500 KB of UTF-8 text.")
        if sum(len(path.content.encode("utf-8")) for path in self.paths) > 4_000_000:
            raise ValueError("The total FEFF content must not exceed 4 MB of UTF-8 text.")
        if len(_json(self.model_dump(exclude_none=True))) > MAX_MODEL_BYTES:
            raise ValueError("The complete model must not exceed 4.5 MB.")
        return self


def model_data(model: ModelDraft) -> dict:
    return model.model_dump(exclude_none=True)


def input_fingerprint(group) -> str | None:
    result = group.get("result") or {}
    arrays = result.get("arrays") or {}
    k, chi = arrays.get("k", []), arrays.get("chi", [])
    if group.get("processing_error") or len(k) < 8 or len(k) != len(chi):
        return None
    return hashlib.sha256(_json({
        "schema": "artemis-input/v1", "data_type": group.get("data_type"),
        "k": k, "chi": chi, "larch_version": result.get("larch_version"),
        "rbkg": (result.get("effective") or {}).get("rbkg"),
    })).hexdigest()


def _finite_json(value, depth=0):
    if depth > 12:
        raise ValueError("Fit archive nesting is too deep.")
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, (int, float)) and math.isfinite(value):
        return
    if isinstance(value, list) and len(value) <= 10001:
        for item in value:
            _finite_json(item, depth + 1)
        return
    if isinstance(value, dict) and len(value) <= 100:
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 100:
                raise ValueError("Invalid fit archive key.")
            _finite_json(item, depth + 1)
        return
    raise ValueError("Fit archives must contain bounded, finite JSON values.")


def _curve(values, length=None):
    if not isinstance(values, list) or not 1 <= len(values) <= 10001 or (length is not None and len(values) != length):
        raise ValueError("Fit curves must have bounded, aligned lengths.")
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
        raise ValueError("Fit curves must be finite numbers.")


def validate_result(value):
    """Validate archives without evaluating saved expressions or running FEFF."""
    required = {"project_id", "group_id", "group_label", "version", "success", "message", "report", "warnings",
                "statistics", "parameters", "correlations", "paths", "transform", "metadata", "k", "r"}
    if not isinstance(value, dict) or not required <= set(value) or set(value) - required - {"plot_source"}:
        raise ValueError("A saved fit must contain the complete Artemis result.")
    _finite_json(value)
    if len(_json(value)) > 3_000_000:
        raise ValueError("A saved fit result must not exceed 3 MB.")
    for key in ("project_id", "group_id", "group_label", "message", "report"):
        if not isinstance(value[key], str) or len(value[key]) > (200_000 if key == "report" else 2000):
            raise ValueError("Invalid saved fit text.")
    if type(value["success"]) is not bool or type(value["version"]) is not int or value["version"] < 0:
        raise ValueError("Invalid saved fit status.")
    if not isinstance(value["warnings"], list) or len(value["warnings"]) > 100 or any(not isinstance(w, str) or len(w) > 2000 for w in value["warnings"]):
        raise ValueError("Invalid saved fit warnings.")
    from .artemis import FitTransform
    FitTransform.model_validate(value["transform"])
    statistics = value["statistics"]
    required_statistics = {"n_varys", "n_independent", "n_data", "nfev", "chi_square", "reduced_chi_square", "r_factor", "aic", "bic", "errorbars"}
    if (not isinstance(statistics, dict) or not required_statistics <= set(statistics)
            or set(statistics) - required_statistics - {"epsilon_k"}):
        raise ValueError("Invalid saved fit statistics.")
    if type(statistics["errorbars"]) is not bool or any(type(v) not in (int, float) for k, v in statistics.items() if k != "errorbars"):
        raise ValueError("Invalid saved fit statistics.")
    if not isinstance(value["parameters"], list) or not 1 <= len(value["parameters"]) <= 32:
        raise ValueError("Invalid saved fit parameters.")
    for parameter in value["parameters"]:
        if not isinstance(parameter, dict) or set(parameter) != {"name", "kind", "value", "initial", "stderr", "min", "max", "expression"}:
            raise ValueError("Invalid saved fit parameter.")
        if not isinstance(parameter["name"], str) or len(parameter["name"]) > 32 or parameter["kind"] not in ("guess", "set", "def") or not isinstance(parameter["expression"], str) or len(parameter["expression"]) > 256:
            raise ValueError("Invalid saved fit parameter identity.")
        for key in ("value", "initial", "stderr", "min", "max"):
            if parameter[key] is None and key in ("stderr", "min", "max"):
                continue
            if type(parameter[key]) not in (int, float):
                raise ValueError("Invalid saved fit parameter value.")
    if not isinstance(value["correlations"], list) or len(value["correlations"]) > 496:
        raise ValueError("Invalid saved fit correlations.")
    for row in value["correlations"]:
        if not isinstance(row, dict) or set(row) != {"left", "right", "value"} or not all(isinstance(row[k], str) for k in ("left", "right")) or type(row["value"]) not in (int, float):
            raise ValueError("Invalid saved fit correlation.")
    for space, names in (("k", {"x", "data", "model", "residual", "weight"}),
                         ("r", {"x", *(f"{curve}_{part}" for curve in ("data", "model", "residual") for part in ("mag", "re", "im"))})):
        curves = value[space]
        if not isinstance(curves, dict) or set(curves) != names:
            raise ValueError("Incomplete saved fit curves.")
        _curve(curves["x"])
        if any(b <= a for a, b in zip(curves["x"], curves["x"][1:])):
            raise ValueError("Saved fit axes must be strictly increasing.")
        for name in names - {"x", "weight"}:
            _curve(curves[name], len(curves["x"]))
    if type(value["k"]["weight"]) is not int or value["k"]["weight"] not in range(4):
        raise ValueError("Invalid saved fit k weight.")
    if not isinstance(value["paths"], list) or not 1 <= len(value["paths"]) <= 24:
        raise ValueError("Invalid saved fit paths.")
    metadata = value["metadata"]
    if not isinstance(metadata, dict):
        raise ValueError("Invalid saved fit metadata.")
    if "engine" in metadata and (not isinstance(metadata["engine"], str) or len(metadata["engine"]) > 100):
        raise ValueError("Invalid saved fit engine.")
    for key in ("input_sha256", "model_sha256"):
        if key in metadata and (not isinstance(metadata[key], str) or len(metadata[key]) != 64
                                or any(char not in "0123456789abcdef" for char in metadata[key])):
            raise ValueError("Invalid saved fit fingerprint.")
    seconds = metadata.get("seconds", {})
    if (not isinstance(seconds, dict) or len(seconds) > 10
            or any(type(v) not in (int, float) or v < 0 for v in seconds.values())):
        raise ValueError("Invalid saved fit timings.")
    sources = metadata.get("feff_sources", {})
    if (not isinstance(sources, dict) or len(sources) > 24
            or set(sources) - {path.get("id") for path in value["paths"] if isinstance(path, dict)}):
        raise ValueError("Invalid saved FEFF source identities.")
    for source in sources.values():
        FeffSource.model_validate(source)
    for path in value["paths"]:
        if not isinstance(path, dict) or set(path) - {"sigma2_expression"} != {"id", "label", "filename", "metadata", "values", "k", "r"}:
            raise ValueError("Incomplete saved fit path.")
        if "sigma2_expression" in path and (not isinstance(path["sigma2_expression"], str) or not 1 <= len(path["sigma2_expression"]) <= 256):
            raise ValueError("Invalid saved sigma2 expression.")
        if any(not isinstance(path[k], str) or len(path[k]) > 160 for k in ("id", "label", "filename")):
            raise ValueError("Invalid saved fit path identity.")
        PathMetadata.model_validate(path["metadata"])
        if not isinstance(path["values"], dict) or set(path["values"]) != {"s02", "e0", "deltar", "sigma2"} or any(type(v) not in (int, float) for v in path["values"].values()):
            raise ValueError("Invalid fitted path values.")
        if not isinstance(path["k"], dict) or set(path["k"]) != {"chi"} or not isinstance(path["r"], dict) or set(path["r"]) != {"mag", "re", "im"}:
            raise ValueError("Incomplete fitted path curves.")
        _curve(path["k"]["chi"], len(value["k"]["x"]))
        for values in path["r"].values():
            _curve(values, len(value["r"]["x"]))
    if "plot_source" in value:
        source = value["plot_source"]
        if (not isinstance(source, dict) or set(source) != {"schema_version", "data", "model", "paths"}
                or type(source["schema_version"]) is not int or source["schema_version"] != 1):
            raise ValueError("Invalid saved fit display source.")
        for name in ("data", "model"):
            _curve(source[name], len(value["k"]["x"]))
        if not isinstance(source["paths"], list) or len(source["paths"]) != len(value["paths"]):
            raise ValueError("Incomplete saved fit display paths.")
        for source_path, path in zip(source["paths"], value["paths"]):
            if (not isinstance(source_path, dict) or set(source_path) != {"id", "chi"}
                    or source_path["id"] != path["id"]):
                raise ValueError("Invalid saved fit display path identity.")
            _curve(source_path["chi"], len(value["k"]["x"]))
    return value


class FitOrigin(StrictModel):
    project_id: str = Field(max_length=200)
    group_id: str = Field(max_length=200)
    project_version: int = Field(ge=0)
    larch_version: str = Field(max_length=100)


class FitReceipt(StrictModel):
    key_sha256: Digest
    body_sha256: Digest


class FitArchive(StrictModel):
    id: Identifier
    created: str = Field(max_length=60)
    input_sha256: Digest
    origin: FitOrigin
    imported: bool = False
    model: ModelDraft
    result: dict
    receipt: FitReceipt | None = None

    @field_validator("created")
    @classmethod
    def timestamp(cls, value):
        if datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
            raise ValueError("Fit timestamps must include a timezone.")
        return value

    @field_validator("result")
    @classmethod
    def result_shape(cls, value):
        return validate_result(value)


class ArtemisState(StrictModel):
    schema_version: Literal[1] = 1
    model: ModelDraft
    history: list[FitArchive] = Field(default_factory=list, max_length=MAX_HISTORY)
    current_input_sha256: Digest | None = None

    @model_validator(mode="after")
    def unique_history(self):
        if len({record.id for record in self.history}) != len(self.history):
            raise ValueError("Saved fit IDs must be unique.")
        return self


def validate_state(value):
    try:
        return ArtemisState.model_validate(value).model_dump(exclude_none=True)
    except (ValidationError, ValueError, TypeError, OverflowError) as exc:
        _fail(f"Invalid saved Artemis model or history: {exc}")


def refresh_project(project):
    total = 0
    for group in project["groups"]:
        if "artemis" not in group:
            continue
        state = validate_state(group["artemis"])
        # This digest is derived from current science, never trusted from disk.
        state["current_input_sha256"] = input_fingerprint(group)
        group["artemis"] = state
        total += len(_json(state))
        if total > MAX_PROJECT_BYTES:
            _fail("Saved Artemis models and fit history exceed the 20 MB project limit.")


def imported_state(value):
    state = validate_state(value)
    state.pop("current_input_sha256", None)
    for record in state["history"]:
        record["imported"] = True
        record.pop("receipt", None)
    return state


class SaveModelRequest(StrictModel):
    version: int = Field(ge=0)
    model: ModelDraft


class RemoveFitRequest(StrictModel):
    version: int = Field(ge=0)
    fit_id: Identifier


async def bounded_model_request(request: Request) -> SaveModelRequest:
    return await _bounded_request(request, SaveModelRequest)


async def bounded_fit_request(request: Request) -> FitRouteRequest:
    return await _bounded_request(request, FitRouteRequest)


async def _bounded_request(request, model):
    # Bound streamed JSON before parsing, including requests with no length header.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 8_000_000:
            _fail("An Artemis model request must not exceed 8 MB.")
    try:
        return model.model_validate_json(body)
    except (ValidationError, ValueError, TypeError, OverflowError) as exc:
        _fail(f"Invalid Artemis model request: {exc}")


def prepared_model(model):
    value = model_data(model)
    for path in value["paths"]:
        cluster = path["metadata"].get("viewerCluster")
        source_cif = path["metadata"].get("sourceCif")
        feff = path["metadata"].get("feff")
        # Saved metadata never substitutes for reading the supplied FEFF text.
        path["metadata"] = inspect_path(PathInput(filename=path["filename"], content=path["content"]))["metadata"]
        if cluster is not None:
            path["metadata"]["viewerCluster"] = cluster
        if source_cif is not None:
            path["metadata"]["sourceCif"] = source_cif
        if feff is not None:
            if feff["path_sha256"] != text_sha256(path["content"]):
                _fail("The FEFF provenance does not match the path contents. Reimport the path.")
            path["metadata"]["feff"] = feff
    return value


def request_from_model(model, version):
    try:
        parameters = [{"name": p["name"].strip(), "kind": p["kind"],
                       "value": 0.0 if p["kind"] == "def" else float(p["value"]),
                       "expression": p["expression"].strip() if p["kind"] == "def" else "",
                       "min": float(p["min"]) if p["kind"] == "guess" and p["min"].strip() else None,
                       "max": float(p["max"]) if p["kind"] == "guess" and p["max"].strip() else None}
                      for p in model["parameters"]]
        transform = {key: float(value) if key in ("kmin", "kmax", "dk", "rmin", "rmax", "dr") else value
                     for key, value in model["transform"].items()}
        return FitRequest.model_validate({"version": version, "parameters": parameters, "transform": transform,
            "paths": [{key: value for key, value in path.items() if key != "metadata"} for path in model["paths"]]})
    except (ValueError, TypeError) as exc:
        _fail(f"Complete the model before fitting: {exc}")


def draft_from_request(request: FitRequest, sources):
    """The server owns browser row IDs, strings and inspected path metadata."""
    body = request.model_dump()
    return prepared_model(ModelDraft.model_validate(dict(
        revision=0,
        parameters=[dict(row, id=f"parameter-{i}", value=str(row["value"]),
                         min="" if row["min"] is None else str(row["min"]),
                         max="" if row["max"] is None else str(row["max"]))
                    for i, row in enumerate(body["parameters"])],
        paths=[dict(row, metadata=inspect_path(PathInput(filename=row["filename"], content=row["content"]))["metadata"]
                    | ({"feff": sources[row["id"]]} if row["id"] in sources else {})) for row in body["paths"]],
        transform={key: str(value) if key in ("kmin", "kmax", "dk", "rmin", "rmax", "dr") else value
                   for key, value in body["transform"].items()},
    )))


def model_fingerprint(model):
    # Revision, display metadata and row IDs are not part of the numerical fit.
    return request_fingerprint(request_from_model(model, 0))


def request_fingerprint(request):
    body = request.model_dump(exclude={"version"})
    for path in body["paths"]:
        for key in ("id", "label", "filename"):
            path.pop(key, None)
    return hashlib.sha256(_json(body)).hexdigest()


def archive_summary(record, current_input):
    from .agent_fit import fit_summary
    result = fit_summary(record["result"], saved=True)
    return dict(id=record["id"], created=record["created"], imported=record.get("imported", False),
                origin=record["origin"], input_sha256=record["input_sha256"],
                model_sha256=record["result"].get("metadata", {}).get("model_sha256") or model_fingerprint(record["model"]),
                stale=record["input_sha256"] != current_input, result=result)


def build_persistence_router(store, jobs=None):
    router = APIRouter(tags=["Artemis project models"])

    @router.get("/projects/{ident}/groups/{group_id}/export")
    def export_model(ident: str, group_id: str, format: Literal["larix"] = "larix",
                     version: int | None = Query(default=None, ge=0)):
        from .artemis_export import export_larix

        with store.storage.lock(ident):
            project = local_project(store, ident)
            if version is not None:
                store.check(project, version)
            source = copy.deepcopy(store.group(project, group_id))
        content, warnings = export_larix(source, project["version"])
        headers = {"Content-Disposition": f'attachment; filename="artemis-{group_id}.larix"',
                   "Cache-Control": "no-store"}
        if warnings:
            headers["X-Artemis-Export-Warnings"] = json.dumps(warnings, ensure_ascii=True)
        return Response(content=content, media_type="application/octet-stream", headers=headers)

    @router.post("/projects/{ident}/groups/{group_id}/model")
    def save_model(ident: str, group_id: str, request: SaveModelRequest = Depends(bounded_model_request),
                   view: ProjectView = "full"):
        with store.storage.lock(ident):
            old = local_project(store, ident)
            store.check(old, request.version)
            store.group(old, group_id)
        model = prepared_model(request.model)
        with store.storage.lock(ident):
            old = local_project(store, ident)
            store.check(old, request.version)
            project = copy.deepcopy(old)
            group = store.group(project, group_id)
            if group.get("artemis", {}).get("model") == model:
                return project_view(old, view)
            group["artemis"] = {"schema_version": 1, "model": model,
                                "history": group.get("artemis", {}).get("history", [])}
            return project_view(store.save(project, old, f"Saved EXAFS model: {group['label']}"), view)

    def save_fit(ident, group_id, request, view, idempotency_key):
        body_hash = hashlib.sha256(_json(dict(group_id=group_id, body=request.model_dump(exclude={"version"})))).hexdigest()
        key_hash = text_sha256(idempotency_key) if idempotency_key is not None else None
        receipt_file = f"artemis-fit-{key_hash}.json" if key_hash else None

        def reply(project, fit_id, replay=False):
            group = store.group(project, group_id)
            record = next((r for r in group.get("artemis", {}).get("history", []) if r["id"] == fit_id), None)
            output = dict(project=project_view(project, view), fit_id=fit_id)
            if view != "full":
                output["fit"] = archive_summary(record, input_fingerprint(group)) if record else None
            if replay:
                output["idempotent_replay"] = True
                output["fit_present"] = record is not None
            return output

        def replay(project):
            if receipt_file is None:
                return None
            try:
                receipt = store.storage.read_json(ident, receipt_file)
            except FileNotFoundError:
                receipt = next((dict(r["receipt"], fit_id=r["id"], group_id=g["id"]) for g in project["groups"]
                                for r in g.get("artemis", {}).get("history", [])
                                if r.get("receipt", {}).get("key_sha256") == key_hash), None)
            if receipt is None:
                return None
            if receipt["body_sha256"] != body_hash or receipt["group_id"] != group_id:
                _fail("This Idempotency-Key was already used for different fit inputs. Use a new key.")
            return reply(project, receipt["fit_id"], True)

        with store.storage.lock(ident):
            old = local_project(store, ident)
            if (previous := replay(old)) is not None:
                return previous
            store.check(old, request.version)
            source = copy.deepcopy(store.group(old, group_id))
            if len(source.get("artemis", {}).get("history", [])) >= MAX_HISTORY:
                _fail("This spectrum already has 10 saved fits. Export an archive or remove a saved fit before fitting again.")
        if isinstance(request, FitRouteRequest):
            sources = {}
            fit_request = request.resolve(jobs, sources=sources)
            model = draft_from_request(fit_request, sources)
        else:
            model = prepared_model(request.model)
            fit_request = request_from_model(model, request.version)
        result = dict(project_id=ident, version=request.version, **fit_group(source, fit_request))
        add_fit_provenance(result, {path["id"]: path["metadata"]["feff"] for path in model["paths"]
                                    if path.get("enabled", True) and "feff" in path["metadata"]})
        result["metadata"].update(input_sha256=input_fingerprint(source), model_sha256=model_fingerprint(model))
        record = {"id": uuid.uuid4().hex, "created": datetime.now(timezone.utc).isoformat(),
                  "input_sha256": input_fingerprint(source), "model": model, "result": result, "imported": False,
                  "origin": {"project_id": ident, "group_id": group_id, "project_version": request.version,
                             "larch_version": larch.__version__}}
        if key_hash is not None:
            record["receipt"] = dict(key_sha256=key_hash, body_sha256=body_hash)
        with store.storage.lock(ident):
            old = local_project(store, ident)
            if (previous := replay(old)) is not None:
                return previous
            store.check(old, request.version)
            project = copy.deepcopy(old)
            group = store.group(project, group_id)
            group["artemis"] = {"schema_version": 1, "model": model,
                                "history": [*group.get("artemis", {}).get("history", []), record]}
            saved = store.save(project, old, f"Saved EXAFS fit: {group['label']}")
            if receipt_file is not None:
                try:
                    store.storage.write_json(ident, receipt_file, dict(body_sha256=body_hash, group_id=group_id, fit_id=record["id"]))
                except OSError:
                    logging.getLogger(__name__).warning("Could not write fit receipt for %s", ident, exc_info=True)
            return reply(saved, record["id"])

    @router.post("/projects/{ident}/groups/{group_id}/fit-saved")
    def fit_saved(ident: str, group_id: str, request: SaveModelRequest = Depends(bounded_model_request),
                  view: ProjectView = "full",
                  idempotency_key: str | None = Header(default=None, min_length=1, max_length=200, alias="Idempotency-Key")):
        return save_fit(ident, group_id, request, view, idempotency_key)

    @router.post("/projects/{ident}/groups/{group_id}/fits")
    def fit_numeric(ident: str, group_id: str, request: FitRouteRequest = Depends(bounded_fit_request),
                    view: ProjectView = "summary",
                    idempotency_key: str | None = Header(default=None, min_length=1, max_length=200, alias="Idempotency-Key")):
        return save_fit(ident, group_id, request, view, idempotency_key)

    @router.get("/projects/{ident}/groups/{group_id}/fits")
    def fit_history(ident: str, group_id: str):
        with store.storage.lock(ident):
            project = local_project(store, ident)
            group = store.group(project, group_id)
            current = input_fingerprint(group)
            history = group.get("artemis", {}).get("history", [])
            return dict(project_id=ident, group_id=group_id, version=project["version"], count=len(history),
                        limit=MAX_HISTORY, current_input_sha256=current,
                        fits=[archive_summary(record, current) for record in history])

    @router.get("/projects/{ident}/groups/{group_id}/fits/{fit_id}")
    def fit_detail(ident: str, group_id: str, fit_id: str, view: Literal["summary", "full"] = "summary"):
        with store.storage.lock(ident):
            project = local_project(store, ident)
            group = store.group(project, group_id)
            record = next((r for r in group.get("artemis", {}).get("history", []) if r["id"] == fit_id), None)
            if record is None:
                _fail("The saved fit was not found. Query this spectrum's fits history for available IDs.")
            summary = archive_summary(record, input_fingerprint(group))
            return dict(project_id=ident, group_id=group_id, version=project["version"],
                        fit=summary if view == "summary" else dict(record, stale=summary["stale"]))

    @router.post("/projects/{ident}/groups/{group_id}/remove-fit")
    def remove_fit(ident: str, group_id: str, request: RemoveFitRequest, view: ProjectView = "full"):
        with store.storage.lock(ident):
            old = local_project(store, ident)
            store.check(old, request.version)
            project = copy.deepcopy(old)
            group = store.group(project, group_id)
            state = group.get("artemis")
            if state is None or not any(record["id"] == request.fit_id for record in state["history"]):
                _fail("The saved fit was not found. Reload the project history.")
            state["history"] = [record for record in state["history"] if record["id"] != request.fit_id]
            return project_view(store.save(project, old, f"Removed saved EXAFS fit: {group['label']}"), view)

    return router
