"""How far a variant capture moves from a reference capture.

    python summarize.py <reference capture dir> <variant capture dir> [--json OUT]

Both folders are baseline-match captures (`baseline_match/run.py`). For each scenario,
every differing value is grouped into a field: the step's name plus the JSON path inside
the step, with list indices written `[*]`, so an array is one field.
"""
import json
import math
import re
from pathlib import Path

_NUMBER = re.compile(r"([-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?)")
_SHOWN = 160


class _Field:
    def __init__(self, name):
        self.name = name
        self.values = 0
        self.max_abs = 0.0
        self.max_rel = 0.0
        self.max_rel_rms = None
        self.other = 0
        self.example = None

    def number(self, a, b):
        self.values += 1
        diff = abs(a - b)
        self.max_abs = max(self.max_abs, diff)
        self.max_rel = max(self.max_rel, _ratio(diff, abs(a)))

    def array(self, a, b):
        """A whole numeric array that differs: |b - a| / |a| in the 2-norm."""
        rel_rms = _ratio(math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b))),
                         math.sqrt(sum(x * x for x in a)))
        self.max_rel_rms = rel_rms if self.max_rel_rms is None else max(self.max_rel_rms, rel_rms)

    def change(self, description):
        """A difference that is not a number: text, type, a missing key, a length."""
        self.other += 1
        if self.example is None:
            self.example = description if len(description) <= _SHOWN else description[:_SHOWN] + "…"

    def record(self):
        return {"field": self.name, "values": self.values, "max_abs": self.max_abs,
                "max_rel": self.max_rel, "max_rel_rms": self.max_rel_rms,
                "other": self.other, "example": self.example}


def _ratio(diff, scale):
    return diff / scale if scale else (0.0 if diff == 0 else math.inf)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _show(value):
    return json.dumps(value, ensure_ascii=False)


def _numbers_in_text(a, b):
    """The differing number pairs of two strings that differ only in their numbers, else None."""
    pa, pb = _NUMBER.split(a), _NUMBER.split(b)
    if len(pa) != len(pb) or pa[0::2] != pb[0::2]:
        return None
    return [(float(x), float(y)) for x, y in zip(pa[1::2], pb[1::2]) if x != y]


def _walk(a, b, path, field_for):
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(a.keys() | b.keys()):
            if key not in b:
                field_for(path).change(f"key {_show(key)} only in the reference")
            elif key not in a:
                field_for(path).change(f"key {_show(key)} only in the variant")
            else:
                _walk(a[key], b[key], f"{path}.{key}", field_for)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            field_for(path).change(f"length {len(a)} -> {len(b)}")
        for x, y in zip(a, b):
            _walk(x, y, f"{path}[*]", field_for)
        if (len(a) == len(b) and len(a) > 1 and all(map(_is_number, a)) and all(map(_is_number, b))
                and any(repr(x) != repr(y) for x, y in zip(a, b))):
            field_for(f"{path}[*]").array(a, b)
    elif _is_number(a) and _is_number(b) and type(a) is type(b):
        if repr(a) != repr(b):
            field_for(path).number(a, b)
    elif isinstance(a, str) and isinstance(b, str):
        if a != b:
            pairs = _numbers_in_text(a, b)
            if pairs is None:
                field_for(path).change(f"{_show(a)} -> {_show(b)}")
            for x, y in pairs or ():
                field_for(path).number(x, y)
    elif type(a) is not type(b) or a != b:
        field_for(path).change(f"{_show(a)} -> {_show(b)}")


def _failed(step):
    return isinstance(step.get("status"), int) and step["status"] >= 400


def summarize_documents(reference, variant):
    """Scenario summary: status, one record per differing field, and why it fails if it does.

    A scenario fails when a step that succeeded in the reference fails in the variant, or
    when the variant stops early with an error the reference does not have.
    """
    fields, failures = {}, []
    ref_steps, var_steps = reference.get("steps", []), variant.get("steps", [])
    for ref_step, var_step in zip(ref_steps, var_steps):
        step = ref_step.get("step", "?")

        def field_for(path, step=step):
            name = f"{step}: {path.lstrip('.')}"
            return fields.setdefault(name, _Field(name))

        if ref_step.get("status") != var_step.get("status"):
            transition = f"HTTP {ref_step.get('status')} -> {var_step.get('status')}"
            field_for("status").change(transition)
            if _failed(var_step) and not _failed(ref_step):
                failures.append(f"{step}: {transition} {_show(var_step.get('body'))[:_SHOWN]}")
        for key in sorted(ref_step.keys() & var_step.keys() - {"step", "status"}):
            _walk(ref_step[key], var_step[key], f".{key}", field_for)
    if len(ref_steps) != len(var_steps):
        fields.setdefault("(steps)", _Field("(steps)")).change(f"{len(ref_steps)} steps -> {len(var_steps)}")
    if variant.get("error") != reference.get("error"):
        fields.setdefault("(error)", _Field("(error)")).change(
            f"{_show(reference.get('error'))} -> {_show(variant.get('error'))}")
        if variant.get("error"):
            failures.append(f"stopped: {variant['error']}")
    summary = {"status": "fails" if failures else "differs" if fields else "identical",
               "fields": [f.record() for f in fields.values()]}
    if failures:
        summary["failure"] = "; ".join(failures)
    return summary


def summarize_dirs(reference, variant):
    """{scenario: summary} for every scenario in either capture folder."""
    reference, variant = Path(reference), Path(variant)
    names = {p.stem for p in reference.glob("*.json")} | {p.stem for p in variant.glob("*.json")}
    out = {}
    for name in sorted(names):
        a, b = reference / f"{name}.json", variant / f"{name}.json"
        if not b.exists():
            out[name] = {"status": "missing", "fields": [], "failure": "only in the reference"}
        elif not a.exists():
            out[name] = {"status": "missing", "fields": [], "failure": "only in the variant"}
        else:
            out[name] = summarize_documents(json.loads(a.read_text()), json.loads(b.read_text()))
    return out
