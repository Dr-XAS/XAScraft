"""The fixed list of baseline-match scenarios, all through the public HTTP API.

Each scenario is a function of a `run.Session`; `SCENARIOS` maps its name to it,
in the order they run. Every call is recorded as a step, so the captured file
holds every response the scenario saw. Payloads follow the backend tests' and the
UI dialogs' shapes.
"""
from pathlib import Path

ATHENA = "/api/athena"
ARTEMIS = "/api/artemis"
REPO = Path(__file__).resolve().parents[3]
EXAMPLES = REPO / "examples"

F10, F50, F300 = "Cu foil · 10 K", "Cu foil · 50 K", "Cu foil · 300 K"
CU2O, SHARED_REFERENCE = "Cu₂O · room temperature", "Cu foil · shared reference"


# --- helpers -------------------------------------------------------------------------

def new_project(s, step="create project"):
    return s.ok(step, "POST", f"{ATHENA}/projects")


def command(s, step, project, action, group_ids=(), **options):
    return s.ok(step, "POST", f"{ATHENA}/projects/{project['id']}/command",
                json={"version": project["version"], "action": action, "group_ids": list(group_ids),
                      "options": options})


def analyze(s, step, project, action, group_ids, **options):
    return s.ok(step, "POST", f"{ATHENA}/projects/{project['id']}/analyze",
                json={"version": project["version"], "action": action, "group_ids": list(group_ids),
                      "options": options})


def preview(s, step, project, route, action, group_ids, **options):
    return s.ok(step, "POST", f"{ATHENA}/projects/{project['id']}/{route}",
                json={"version": project["version"], "action": action, "group_ids": list(group_ids),
                      "options": options})


def ids(project):
    return {group["label"]: group["id"] for group in project["groups"]}


def copper(s):
    """A new project holding the copper examples."""
    return command(s, "load copper examples", new_project(s), "example")


def unlinked_copper(s):
    """The copper examples with the foil scans detached from their shared reference."""
    project = copper(s)
    g = ids(project)
    return command(s, "detach foils from the shared reference", project, "assign_reference",
                   [g[F10], g[F50], g[F300]], reference_id=None)


def preview_and_restore(s, project, name, data, step="import"):
    """The UI's project import: stage a preview, then restore every group."""
    staged = s.ok(f"{step}: preview {name}", "POST", f"{ATHENA}/projects/{project['id']}/preview-project",
                  files={"file": (name, data)})
    return s.ok(f"{step}: restore all groups of {name}", "POST", f"{ATHENA}/projects/{project['id']}/restore-upload",
                json={"version": project["version"], "upload_id": staged["upload_id"], "group_ids": None})


def restore(s, project, name, data, step="import"):
    """The direct import route: one multipart upload restored into the project."""
    return s.ok(f"{step}: restore {name}", "POST", f"{ATHENA}/projects/{project['id']}/restore",
                params={"version": project["version"]}, files={"file": (name, data)})


def cuprite_model(example, kmax=None):
    """The Cu₂O example as the UI's model draft (strings in the numeric fields)."""
    transform = {key: (str(value) if key not in ("fitspace", "window", "kweight") else value)
                 for key, value in example["transform"].items()}
    if kmax is not None:
        transform["kmax"] = kmax
    return {
        "revision": 0,
        "parameters": [dict(parameter, id=f"parameter-{i}", value=str(parameter["value"]),
                            min="" if parameter["min"] is None else str(parameter["min"]),
                            max="" if parameter["max"] is None else str(parameter["max"]))
                       for i, parameter in enumerate(example["parameters"])],
        "paths": [dict(path, id=f"path-{i}", label=path["filename"], enabled=True, **settings)
                  for i, (path, settings) in enumerate(zip(example["paths"], example["path_parameters"]))],
        "transform": transform,
    }


def cuprite_fit_request(example, version):
    """The Cu₂O example as the numeric fit route's body."""
    paths = [{key: value for key, value in path.items() if key != "metadata"}
             | settings | {"id": f"p{i}", "label": path["filename"]}
             for i, (path, settings) in enumerate(zip(example["paths"], example["path_parameters"]), start=1)]
    return {"version": version, "parameters": example["parameters"], "paths": paths,
            "transform": example["transform"]}


# --- data sets -----------------------------------------------------------------------

def copper_examples(s):
    project = copper(s)
    pid = project["id"]
    s.ok("open project", "GET", f"{ATHENA}/projects/{pid}")
    for group in project["groups"]:
        for space in ("E", "k", "R", "q"):
            s.ok(f"export {group['label']} in {space}", "GET",
                 f"{ATHENA}/projects/{pid}/groups/{group['id']}/export", params={"space": space})
    for format in ("json", "prj"):
        s.ok(f"export project as {format}", "GET", f"{ATHENA}/projects/{pid}/export", params={"format": format})


def cuprite_fit(s):
    project = copper(s)
    example = s.ok("Cu₂O example model", "GET", f"{ARTEMIS}/examples/cuprite")
    group = ids(project)[CU2O]
    s.ok("fit the Cu₂O 4-path model", "POST", f"{ARTEMIS}/projects/{project['id']}/groups/{group}/fit",
         json=cuprite_fit_request(example, project["version"]))
    s.ok("fit the Cu₂O 4-path model (summary view)", "POST",
         f"{ARTEMIS}/projects/{project['id']}/groups/{group}/fit", params={"view": "summary"},
         json=cuprite_fit_request(example, project["version"]))


def curated_demo(s):
    project = command(s, "load curated demo", new_project(s), "example", dataset="curated-three-elements")
    s.ok("open project", "GET", f"{ATHENA}/projects/{project['id']}")
    s.ok("export project as json", "GET", f"{ATHENA}/projects/{project['id']}/export", params={"format": "json"})


def reference_library_lcf(s):
    path = EXAMPLES / "xafsdata/AthenaProjectFiles/AsKa.prj"
    project = restore(s, new_project(s), path.name, path.read_bytes())
    unknown = ids(project)["YLO2_a_1_AsKa.mrg"]
    suggestions = analyze(s, "suggest library standards", project, "lcf_suggest", [unknown], array="norm")["result"]
    project = command(s, "add the suggested standards", project, "add_references",
                      library_ids=[item["id"] for item in suggestions["suggestions"]])
    standards = [g["id"] for g in project["groups"] if g["source"].get("reference_library")]
    window = {"xmin": suggestions["xmin"], "xmax": suggestions["xmax"]}
    analyze(s, "combination search", project, "lcf_search", [unknown, *standards],
            array="norm", max_components=3, **window)
    analyze(s, "linear combination fit", project, "lcf", [unknown, *standards], array="norm", **window)


def bundled_project(path):
    def scenario(s):
        project = new_project(s)
        staged = s.ok(f"preview {path.name}", "POST", f"{ATHENA}/projects/{project['id']}/preview-project",
                      files={"file": (path.name, path.read_bytes())})
        first = staged["groups"][0]["id"]
        s.ok("preview the first group normalized", "GET",
             f"{ATHENA}/projects/{project['id']}/preview-project/{staged['upload_id']}/groups/{first}",
             params={"mode": "norm"})
        project = s.ok("import every group", "POST", f"{ATHENA}/projects/{project['id']}/restore-upload",
                       json={"version": project["version"], "upload_id": staged["upload_id"], "group_ids": None})
        s.reopen()
        s.ok("open the saved project", "GET", f"{ATHENA}/projects/{project['id']}")
    scenario.__doc__ = f"Open and import examples/{path.relative_to(EXAMPLES)}."
    return scenario


# --- operations ----------------------------------------------------------------------

def operation(action, route, group_labels, unlinked=False, **options):
    def scenario(s):
        project = unlinked_copper(s) if unlinked else copper(s)
        g = ids(project)
        resolved = {key: g.get(value, value) if isinstance(value, str) else value for key, value in options.items()}
        group_ids = [g[label] for label in group_labels]
        if route:
            preview(s, f"preview {action}", project, route, action, group_ids, **resolved)
        command(s, action, project, action, group_ids, **resolved)
    return scenario


OPERATIONS = {
    "merge": operation("merge", "merge/preview", [F10, F50, F300], method="demeter-larch", array="mu",
                       exclude_short_data=False),
    "sum": operation("sum", None, [F10, F300], array="mu",
                     weights=[1, 0.5]),
    "difference": operation("difference", "difference/preview", [F300], standard_id=F10, form="norm"),
    "align": operation("align", "alignment/preview", [F50, F300], unlinked=True,
                       method="demeter-larch", operation="auto", standard_id=F10),
    "calibrate": operation("calibrate", "calibration/preview", [F10], observed=8980, target=8982),
    "rebin": operation("rebin", "rebin/preview", [F10], e0=8978, pre_step=5, xanes_step=1, exafs_kstep=.1),
    "deglitch": operation("deglitch", "point-edit/preview", [F10], xmin=9100, xmax=9110),
    "truncate": operation("truncate", "point-edit/preview", [F10], xmin=8800, xmax=11000),
    "smooth": operation("smooth", "smooth/preview", [F10], method="savitzky_golay", window=7, order=2),
    "convolve": operation("convolve", "convolve/preview", [F10], form="gaussian", width=1),
    "deconvolve": operation("deconvolve", None, [F10], form="gaussian", width=1,
                            xmin=8950, xmax=9100),
    "self-absorption": operation("self_absorption", "self-absorption/preview", [F10],
                                 formula="Cu", element="Cu", edge="K", angle_in=45, angle_out=45),
    "mee-removal": operation("multi_electron", "mee/preview", [F10],
                             method="arctangent", shift=100, amplitude=.03, width=2),
}


# --- analyses ------------------------------------------------------------------------

def lcf(s):
    project = copper(s)
    g = ids(project)
    analyze(s, "linear combination fit", project, "lcf", [g[F300], g[F10], g[CU2O]],
            xmin=8960, xmax=9020, array="norm")


def pca(s):
    project = copper(s)
    analyze(s, "principal components", project, "pca", list(ids(project).values()),
            xmin=8960, xmax=9020, array="norm")


def peak_fit(s):
    project = copper(s)
    analyze(s, "peak fit", project, "peaks", [ids(project)[CU2O]], xmin=8970, xmax=9000, array="norm",
            peaks=[{"center": 8983, "sigma": 2, "amplitude": 0.3, "kind": "gaussian"},
                   {"center": 8993, "sigma": 3, "amplitude": 0.5, "kind": "lorentzian"}],
            background={"slope": 0, "intercept": 0,
                        "step": {"form": "arctan", "center": 8985, "sigma": 2, "amplitude": 1, "vary": True}})


def log_ratio(s):
    project = copper(s)
    g = ids(project)
    pair = [g[F10], g[F300]]
    e0 = project["groups"][0]["result"]["effective"]["e0"]
    project = command(s, "common transform parameters", project, "parameters", pair,
                      e0=e0, kmax=8, rwindow="hanning", dr=0)
    analyze(s, "log-ratio", project, "log_ratio", pair, kmin=3, kmax=7, array="norm")


# --- persistence ---------------------------------------------------------------------

def project_open_vs_import(s):
    project = copper(s)
    g = ids(project)
    project = command(s, "merge the foils", project, "merge", [g[F10], g[F50], g[F300]], array="mu")
    analyze(s, "linear combination fit", project, "lcf", [g[F300], g[F10], g[CU2O]],
            xmin=8960, xmax=9020, array="norm")
    example = s.ok("Cu₂O example model", "GET", f"{ARTEMIS}/examples/cuprite")
    s.ok("save a Cu₂O fit", "POST", f"{ARTEMIS}/projects/{project['id']}/groups/{g[CU2O]}/fit-saved",
         json={"version": project["version"], "model": cuprite_model(example)})
    exports = {format: s.call(f"export project as {format}", "GET", f"{ATHENA}/projects/{project['id']}/export",
                              params={"format": format}).content
               for format in ("json", "prj")}
    s.ok("list projects", "GET", f"{ATHENA}/projects")
    # Open: the saved project, read back by a restarted app, without reprocessing.
    s.reopen()
    s.ok("open: list projects", "GET", f"{ATHENA}/projects")
    s.ok("open: the saved project", "GET", f"{ATHENA}/projects/{project['id']}")
    # Import: the exported files into fresh projects, ids remapped and results recomputed.
    restore(s, new_project(s, "import: create project for json"), "craft-project.json", exports["json"],
            "import json")
    preview_and_restore(s, new_project(s, "import: create project for prj"), "craft-project.prj", exports["prj"],
                        "import prj")
    current = s.ok("reload the saved project", "GET", f"{ATHENA}/projects/{project['id']}")
    preview_and_restore(s, current, "craft-project.prj", exports["prj"], "import prj into itself")


def fit_history(s):
    project = copper(s)
    pid, group = project["id"], ids(project)[CU2O]
    base = f"{ARTEMIS}/projects/{pid}/groups/{group}"
    example = s.ok("Cu₂O example model", "GET", f"{ARTEMIS}/examples/cuprite")
    project = s.ok("save the model only", "POST", f"{base}/model",
                   json={"version": project["version"], "model": cuprite_model(example)})
    fits = []
    for kmax in ("12", "10"):
        saved = s.ok(f"save a fit with kmax {kmax}", "POST", f"{base}/fit-saved",
                     json={"version": project["version"], "model": cuprite_model(example, kmax)})
        project, fits = saved["project"], [*fits, saved["fit_id"]]
    saved = s.ok("save a fit through the numeric route", "POST", f"{base}/fits",
                 json=cuprite_fit_request(example, project["version"]))
    fits.append(saved["fit_id"])
    s.ok("list saved fits", "GET", f"{base}/fits")
    for fit in fits[:2]:  # the pair the comparison view reads
        s.ok("compare: full saved fit", "GET", f"{base}/fits/{fit}", params={"view": "full"})
        s.ok("saved fit summary", "GET", f"{base}/fits/{fit}")
    project = s.ok("open project", "GET", f"{ATHENA}/projects/{pid}")
    s.ok("remove the first saved fit", "POST", f"{base}/remove-fit",
         json={"version": project["version"], "fit_id": fits[0]})
    s.ok("list saved fits after removal", "GET", f"{base}/fits")
    exported = s.call("export project as prj", "GET", f"{ATHENA}/projects/{pid}/export",
                      params={"format": "prj"}).content
    imported = preview_and_restore(s, new_project(s, "create project for import"), "craft-project.prj", exported)
    target = ids(imported)[CU2O]
    s.ok("imported saved fits", "GET", f"{ARTEMIS}/projects/{imported['id']}/groups/{target}/fits")


# --- the list ------------------------------------------------------------------------

BUNDLED_PROJECTS = sorted(EXAMPLES.rglob("*.prj"))


def _bundled_name(path):
    return "bundled-project--" + str(path.relative_to(EXAMPLES).with_suffix("")).replace("/", "--")


SCENARIOS = {
    "copper-examples": copper_examples,
    "cuprite-4-path-fit": cuprite_fit,
    "curated-demo": curated_demo,
    "reference-library-lcf": reference_library_lcf,
    **{f"operation--{name}": scenario for name, scenario in OPERATIONS.items()},
    "analysis--lcf": lcf,
    "analysis--pca": pca,
    "analysis--peak-fit": peak_fit,
    "analysis--log-ratio": log_ratio,
    "project-open-vs-import": project_open_vs_import,
    "fit-history": fit_history,
    **{_bundled_name(path): bundled_project(path) for path in BUNDLED_PROJECTS},
}
