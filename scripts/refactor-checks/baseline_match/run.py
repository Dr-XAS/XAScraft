"""Run the baseline-match scenarios against one worktree's backend.

    <worktree>/backend/.venv/bin/python run.py --backend <worktree>/backend --out <dir>
        [--only NAME ...] [--list]

Imports that worktree's backend, drives its public HTTP API with a TestClient on a
scratch data root (one per scenario), and writes one normalized JSON file per
scenario to <dir>. The same runner works on the baseline and the refactored tree.
"""
import argparse
import datetime as dt
import gzip
import json
import os
import platform
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Bit-for-bit runs need single-threaded BLAS and XRF; set before numpy loads.
DETERMINISM_ENV = {"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                   "VECLIB_MAXIMUM_THREADS": "1", "XRAYLARCH_XRF_WORKERS": "1"}


class StepFailed(RuntimeError):
    """A step the rest of the scenario depends on did not succeed."""


class Session:
    """One scenario's HTTP client plus the record of every step it took."""

    def __init__(self, client_factory):
        self._factory = client_factory
        self.client = client_factory()
        self.steps = []

    def call(self, step, method, url, **kwargs):
        response = self.client.request(method, url, **kwargs)
        entry = {"step": step, "request": f"{method} {url}", "status": response.status_code,
                 "content_type": response.headers.get("content-type")}
        if "content-disposition" in response.headers:
            entry["content_disposition"] = response.headers["content-disposition"]
        content = response.content
        if content[:2] == b"\x1f\x8b":
            # .prj exports are gzip; the header carries an mtime, so keep the payload only.
            content = gzip.decompress(content)
            entry["gzip"] = True
        entry["body"] = _decode(content)
        self.steps.append(entry)
        return response

    def ok(self, step, method, url, **kwargs):
        """Call, and stop the scenario unless the step succeeded; returns the JSON body."""
        response = self.call(step, method, url, **kwargs)
        if response.status_code >= 400:
            raise StepFailed(f"{step}: HTTP {response.status_code}")
        return self.steps[-1]["body"]

    def reopen(self):
        """A fresh app and client on the same data root, as after a restart."""
        self.close()
        self.client = self._factory()
        self.steps.append({"step": "reopen (new app on the same data root)"})

    def close(self):
        close = getattr(self.client, "close", None)
        if close:
            close()


def _decode(content):
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        import hashlib
        return {"bytes_sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
    try:
        return json.loads(text)
    except ValueError:
        return {"lines": [_line(line) for line in text.split("\n")]}


def _line(line):
    """A text line, or its JSON object when the line carries one (e.g. `# Athena-Web {...}`)."""
    start = line.find("{")
    if start >= 0 and line.endswith("}"):
        try:
            value = json.loads(line[start:])
        except ValueError:
            return line
        if isinstance(value, dict):
            return {"prefix": line[:start], "json": value}
    return line


def _dates(*moments):
    return {m.date().isoformat() for m in moments} | {m.astimezone(dt.timezone.utc).date().isoformat()
                                                      for m in moments}


def _git_revision(path):
    import subprocess
    try:
        return subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend", type=Path, help="the worktree's backend/ folder")
    parser.add_argument("--out", type=Path, help="capture folder to write")
    parser.add_argument("--only", nargs="+", default=None, help="run only these scenario names")
    parser.add_argument("--list", action="store_true", help="print the scenario names and exit")
    args = parser.parse_args(argv)

    sys.path.insert(0, str(HERE))
    from scenarios import SCENARIOS
    from normalize import normalize

    if args.list:
        print("\n".join(SCENARIOS))
        return 0
    if args.backend is None or args.out is None:
        parser.error("--backend and --out are required")
    unknown = set(args.only or ()) - set(SCENARIOS)
    if unknown:
        parser.error(f"unknown scenarios: {', '.join(sorted(unknown))}")

    os.environ.update(DETERMINISM_ENV)
    scratch = Path(tempfile.mkdtemp(prefix="baseline-match-"))
    # main.py builds an app at import time from the environment: point it at scratch.
    os.environ["XRAYLARCH_DATA_ROOT"] = str(scratch / "import-time")
    backend = args.backend.resolve()
    sys.path.insert(0, str(backend))

    import larch
    from fastapi.testclient import TestClient
    from xraylarch_web.config import Settings
    from xraylarch_web.main import create_app

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    names = args.only or list(SCENARIOS)
    (out / "_run.txt").write_text("\n".join([
        f"backend: {backend}", f"git_revision: {_git_revision(backend)}",
        f"larch: {larch.__version__} ({larch.__file__})", f"python: {sys.version.split()[0]} ({sys.executable})",
        f"platform: {platform.platform()}", f"started: {dt.datetime.now().astimezone().isoformat()}",
        f"scenarios: {len(names)}", ""]))

    failures = 0
    try:
        for name in names:
            root = scratch / "scenarios" / name
            root.mkdir(parents=True)
            started = dt.datetime.now().astimezone()
            session = Session(lambda root=root: TestClient(create_app(Settings(data_root=root))))
            error = None
            try:
                SCENARIOS[name](session)
            except Exception as exc:  # recorded, so a broken step shows up as a difference
                error = f"{type(exc).__name__}: {exc}"
                if not isinstance(exc, StepFailed):
                    traceback.print_exc()
            finally:
                session.close()
            document = {"scenario": name, "steps": session.steps}
            if error:
                document["error"] = error
                failures += 1
            document = normalize(document, larch_version=larch.__version__,
                                 run_dates=_dates(started, dt.datetime.now().astimezone()))
            (out / f"{name}.json").write_text(json.dumps(document, ensure_ascii=False, allow_nan=True))
            print(f"{name}: {len(session.steps)} steps" + (f", stopped: {error}" if error else ""), flush=True)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    print(f"{len(names)} scenarios written to {out}; {failures} stopped early", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
