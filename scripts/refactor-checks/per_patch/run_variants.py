"""Per-patch report (check 3): how far each patch moves results from the full patch set.

    python3 run_variants.py --work DIR --out DIR --upstream PATH_OR_URL
        [--python PYTHON3.12] [--variants full 0003 pure ...] [--baseline CAPTURE] [--keep-captures]

Variants: `full` (the whole series, the reference), each patch left out in turn (`0001`, ...,
`build.py --exclude`), and `pure` (`build.py --pure-upstream`). `0005+0006+0007` leaves out
several patches, for a patch that later patches need. A selection build.py refuses is recorded
as not building. For each variant:

1. build Larch with `larch-patches/build.py` into WORK/build-<variant>;
2. install its wheel into one scratch venv (WORK/venv, made like the release env: the
   release constraints as requirements and constraints, then backend/requirements.txt);
3. capture the baseline-match scenarios against this tree's backend (WORK/capture-<variant>);
4. run the team regression tests (`larch-patches/tests`, without test_series/test_build);
5. summarize the capture against the `full` capture into OUT/<variant>.json.

`full` runs first, unless --reference names an existing `full` capture. Its capture is
compared exactly with --baseline when given. Captures and
builds are deleted once summarized (about 430 MB each), unless --keep-captures. OUT/sections.md
gets one report section per variant.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
HARNESS = HERE.parent / "baseline_match"
CONSTRAINTS = REPO / "deploy" / "python-release-constraints.txt"
DETERMINISM_ENV = {"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                   "VECLIB_MAXIMUM_THREADS": "1", "XRAYLARCH_XRF_WORKERS": "1"}

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HARNESS))


def regression_outcome(junit_xml):
    """{passed, failed, skipped} from a pytest JUnit XML file; failures and errors are named."""
    passed, failed, skipped = 0, [], []
    for case in ET.parse(junit_xml).iter("testcase"):
        name = f"{case.get('classname', '').rsplit('.', 1)[-1]}::{case.get('name')}"
        if case.find("failure") is not None or case.find("error") is not None:
            failed.append(name)
        elif case.find("skipped") is not None:
            skipped.append(name)
        else:
            passed += 1
    return {"passed": passed, "failed": failed, "skipped": skipped}


def _series():
    return sorted((REPO / "larch-patches" / "series").glob("[0-9][0-9][0-9][0-9]-*.patch"))


def patch_numbers():
    return [p.name[:4] for p in _series()]


def title(variant):
    if variant == "full":
        return "Full patch set (the reference)"
    if variant == "pure":
        return "Pure upstream (no patches)"
    numbers = variant.split("+")
    files = [p.name for p in _series() if p.name[:4] in numbers]
    return f"Without {' + '.join(numbers)} ({', '.join(f'`{f}`' for f in files)})"


def _run(cmd, log, **kwargs):
    log.write(f"\n$ {' '.join(map(str, cmd))}\n")
    log.flush()
    return subprocess.run([str(c) for c in cmd], stdout=log, stderr=subprocess.STDOUT, **kwargs)


def make_venv(base_python, venv, log):
    python = venv / "bin" / "python"
    if not python.exists():
        _run([base_python, "-m", "venv", venv], log, check=True)
        _run([python, "-m", "pip", "install", "--no-input", "-r", CONSTRAINTS, "-c", CONSTRAINTS], log, check=True)
        _run([python, "-m", "pip", "install", "--no-input", "-r", "requirements.txt", "-c", CONSTRAINTS],
             log, check=True, cwd=REPO / "backend")
    return python


class BuildFailed(Exception):
    """build.py refused this selection of patches (e.g. a later patch needs the one left out)."""


def run_variant(variant, python, args, log):
    build = args.work / f"build-{variant}"
    shutil.rmtree(build, ignore_errors=True)
    if variant == "full":
        selection = []
    elif variant == "pure":
        selection = ["--pure-upstream"]
    else:
        selection = [arg for number in variant.split("+") for arg in ("--exclude", number)]
    built = _run([python, "-I", REPO / "larch-patches" / "build.py", "--out", build, "--upstream", args.upstream,
                  "--build-python", python, *selection], log)
    if built.returncode != 0:
        log.flush()
        errors = [line for line in (args.out / f"{variant}.log").read_text().splitlines()
                  if line.startswith("build.py: error:")]
        raise BuildFailed(errors[-1].removeprefix("build.py: error:").strip().rstrip(":")
                          if errors else f"build.py exited {built.returncode}")
    identity = json.loads((build / "IDENTITY").read_text())
    [wheel] = (build / "dist").glob("*.whl")
    _run([python, "-m", "pip", "uninstall", "--yes", "xraylarch"], log)
    _run([python, "-m", "pip", "install", "--no-input", "-c", CONSTRAINTS, wheel], log, check=True)
    _run([python, "-m", "pip", "check"], log, check=True)
    got = subprocess.run([python, "-I", "-c", "import larch; print(larch.__version__)"], cwd=args.work,
                         capture_output=True, text=True, check=True).stdout.strip()
    if got != identity["version"]:
        raise RuntimeError(f"{variant}: installed larch {got}, IDENTITY says {identity['version']}")

    env = {**os.environ, **DETERMINISM_ENV}
    capture = args.work / f"capture-{variant}"
    shutil.rmtree(capture, ignore_errors=True)
    _run([python, HARNESS / "run.py", "--backend", REPO / "backend", "--out", capture], log, check=True, env=env)
    junit = args.out / f"{variant}-regression.xml"
    _run([python, "-m", "pytest", "-p", "no:cacheprovider", "-q", "larch-patches/tests",
          "-k", "not test_series and not test_build", f"--junitxml={junit}"], log, env=env, cwd=REPO)
    shutil.rmtree(build, ignore_errors=True)
    return identity, capture, regression_outcome(junit)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--work", type=Path, required=True, help="scratch folder: venv, builds, captures")
    parser.add_argument("--out", type=Path, required=True, help="where the summaries and logs go")
    parser.add_argument("--upstream", required=True, help="local xraylarch clone (only read) or git URL")
    parser.add_argument("--python", default=sys.executable, help="Python 3.12 to make the venv from")
    parser.add_argument("--variants", nargs="+", default=None, help="default: full, each patch, pure")
    parser.add_argument("--baseline", type=Path, default=None, help="capture to compare `full` with exactly")
    parser.add_argument("--reference", type=Path, default=None,
                        help="an existing `full` capture to use instead of running `full` again")
    parser.add_argument("--keep-captures", action="store_true")
    args = parser.parse_args(argv)

    from compare import compare_dirs
    from report import variant_section
    from summarize import summarize_dirs

    args.work, args.out = args.work.resolve(), args.out.resolve()
    args.work.mkdir(parents=True, exist_ok=True)
    args.out.mkdir(parents=True, exist_ok=True)
    variants = [v for v in args.variants or [*patch_numbers(), "pure"] if v != "full"]
    if args.reference is None:
        variants.insert(0, "full")

    with open(args.out / "venv.log", "a") as log:
        python = make_venv(args.python, args.work / "venv", log)
    reference = args.reference.resolve() if args.reference else None
    for variant in variants:
        try:
            with open(args.out / f"{variant}.log", "w") as log:
                identity, capture, tests = run_variant(variant, python, args, log)
        except BuildFailed as exc:
            result = {"variant": variant, "title": title(variant), "build_error": str(exc)}
            (args.out / f"{variant}.json").write_text(json.dumps(result, indent=1))
            print(f"{variant}: does not build: {exc}", flush=True)
            continue
        result = {"variant": variant, "title": title(variant), "identity": identity, "tests": tests}
        if variant == "full":
            reference = capture
            if args.baseline:
                differences = compare_dirs(args.baseline, capture)
                result["vs_baseline"] = {"baseline": str(args.baseline), "differences": len(differences),
                                         "first": differences[:20]}
        result["summary"] = summarize_dirs(reference, capture)
        (args.out / f"{variant}.json").write_text(json.dumps(result, indent=1, allow_nan=True))
        if variant != "full" and not args.keep_captures:
            shutil.rmtree(capture, ignore_errors=True)
        counts = {s: sum(1 for x in result["summary"].values() if x["status"] == s)
                  for s in ("identical", "differs", "fails", "missing")}
        print(f"{variant}: {counts}; regression {tests['passed']} passed, {len(tests['failed'])} failed",
              flush=True)
    if reference and args.reference is None and not args.keep_captures:
        shutil.rmtree(reference, ignore_errors=True)

    results = [json.loads(p.read_text()) for p in sorted(args.out.glob("*.json"))]
    order = {v: i for i, v in enumerate(["full", *patch_numbers(), "pure"])}
    results.sort(key=lambda r: (order.get(r["variant"].split("+")[0], len(order)), r["variant"]))
    (args.out / "sections.md").write_text("\n".join(
        variant_section(r["title"], r.get("summary", {}), r.get("tests"), r.get("build_error"))
        for r in results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
