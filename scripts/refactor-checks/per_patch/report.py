"""Markdown for the per-patch report, from `summarize.summarize_dirs` summaries."""


def _g(value):
    return "–" if value is None else f"{value:.3g}"


def _worst_field(fields):
    numeric = [f for f in fields if f["values"]]
    with_rms = [f for f in numeric if f["max_rel_rms"] is not None]
    if with_rms:
        return max(with_rms, key=lambda f: f["max_rel_rms"])
    if numeric:
        return max(numeric, key=lambda f: f["max_rel"])
    return fields[0] if fields else None


def scenario_row(name, summary):
    """Totals over a scenario's fields; the worst relative RMS names its field."""
    fields = summary["fields"]
    numeric = [f for f in fields if f["values"]]
    rms = [f["max_rel_rms"] for f in numeric if f["max_rel_rms"] is not None]
    worst = _worst_field(fields)
    return {
        "scenario": name,
        "values": sum(f["values"] for f in fields),
        "other": sum(f["other"] for f in fields),
        "max_abs": max((f["max_abs"] for f in numeric), default=None),
        "max_rel": max((f["max_rel"] for f in numeric), default=None),
        "max_rel_rms": max(rms, default=None),
        "worst_field": worst["field"] if worst else "",
    }


def _sort_key(row):
    return -(row["max_rel_rms"] if row["max_rel_rms"] is not None else row["max_rel"] or 0.0)


def variant_section(title, summary, tests, build_error=None):
    """One `##` section: counts, regression tests, failing scenarios, differing scenarios."""
    if build_error:
        return f"## {title}\n\nDoes not build: {build_error}\n"
    counts = {status: sum(1 for s in summary.values() if s["status"] == status)
              for status in ("identical", "differs", "fails", "missing")}
    lines = [f"## {title}", ""]
    if counts["identical"] == len(summary):
        lines.append(f"Identical to the full patch set in all {len(summary)} scenarios.")
    else:
        text = f"{counts['identical']} identical, {counts['differs']} differ, {counts['fails']} fail."
        if counts["missing"]:
            text += f" {counts['missing']} missing."
        lines.append(text)
    if tests is not None:
        failed = tests["failed"]
        lines += ["", f"Team regression tests: {tests['passed']} passed, {len(failed)} failed"
                  + (f" ({', '.join(failed)})." if failed else ".")]

    failing = {n: s for n, s in summary.items() if s["status"] in ("fails", "missing")}
    if failing:
        lines += ["", "Scenarios that fail:", "", "| Scenario | Failure |", "| --- | --- |"]
        lines += [f"| {n} | {s['failure'].replace('|', '/')} |" for n, s in failing.items()]

    rows = sorted((scenario_row(n, s) for n, s in summary.items() if s["status"] == "differs"),
                  key=_sort_key)
    if rows:
        lines += ["", "Scenarios that differ (worst relative RMS first):", "",
                  "| Scenario | Values differing | Other changes | Max abs | Max rel | Max rel RMS | Field |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        lines += [f"| {r['scenario']} | {r['values']} | {r['other']} | {_g(r['max_abs'])} | "
                  f"{_g(r['max_rel'])} | {_g(r['max_rel_rms'])} | `{r['worst_field']}` |" for r in rows]
    return "\n".join(lines) + "\n"
