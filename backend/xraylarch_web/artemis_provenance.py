"""Portable FEFF diagnostics carried with paths, including after job expiry."""
from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import Field, field_validator

from .artemis import StrictModel

INPUT_GENERATOR = "xascraft-feff-input/v2"


class FeffDiagnostic(StrictModel):
    code: str = Field(max_length=80)
    severity: Literal["warning", "info"]
    message: str = Field(max_length=2000)
    raw: str = Field(default="", max_length=2000)


class FeffSource(StrictModel):
    job_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    path_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cif_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_generator: str = Field(max_length=100)
    engine: str = Field(max_length=100)
    executable_sha256: dict[str, str] = Field(default_factory=dict, max_length=6)
    warnings: list[str] = Field(default_factory=list, max_length=100)
    diagnostics: list[FeffDiagnostic] = Field(default_factory=list, max_length=100)

    @field_validator("executable_sha256")
    @classmethod
    def valid_executables(cls, values):
        import re
        if any(key not in ("rdinp", "pot", "xsph", "pathfinder", "genfmt", "ff2x")
               or re.fullmatch(r"[0-9a-f]{64}", value) is None for key, value in values.items()):
            raise ValueError("Invalid FEFF executable fingerprint.")
        return values

    @field_validator("warnings")
    @classmethod
    def bounded_warnings(cls, values):
        if any(len(value) > 2000 for value in values):
            raise ValueError("Each FEFF warning must not exceed 2000 characters.")
        return values


def text_sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def path_source(job, path):
    provenance = job.get("provenance", {})
    return FeffSource(
        job_id=job["id"], path_sha256=text_sha256(path["content"]),
        input_sha256=text_sha256(provenance.get("feff_input", "")),
        cif_sha256=text_sha256(provenance.get("cif", "")),
        input_generator=provenance.get("input_generator", "legacy/unknown"),
        engine=provenance.get("engine", "FEFF8L"),
        executable_sha256=provenance.get("executable_sha256", {}),
        warnings=job.get("warnings", []), diagnostics=job.get("diagnostics", []),
    ).model_dump()


def add_fit_provenance(result, sources):
    """Sources are keyed by model path ID, not ephemeral path numbers."""
    if not sources:
        return result
    result["metadata"]["feff_sources"] = sources
    warnings = result["warnings"]
    for source in sources.values():
        for warning in source["warnings"]:
            message = f"FEFF: {warning}"
            if message not in warnings:
                warnings.append(message)
    return result
