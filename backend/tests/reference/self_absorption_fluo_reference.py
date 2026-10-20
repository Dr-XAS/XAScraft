"""Write the FLUO self-absorption numbers that
`test_athena_self_absorption_matches_larch_3461938ac.py` pins.

Run it with the backend environment of a checkout of XAScraft commit 3461938ac, whose vendored
Larch is the reference, pointing at that tree's backend and at this tree's test file:

    <3461938ac checkout>/backend/.venv/bin/python -I backend/tests/reference/self_absorption_fluo_reference.py \
        --backend <3461938ac checkout>/backend

It runs BLAS single-threaded and uses a scratch data root. The cases, the HTTP calls and the
thread limit come from the test module, so the reference and the test make the same requests
under the same conditions.
"""
import argparse
import gzip
import json
from pathlib import Path
import sys
import tempfile

TESTS = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", type=Path, required=True, help="the reference tree's backend folder")
    parser.add_argument("--out", type=Path, default=TESTS / "fixtures" / "athena-self-absorption-fluo-larch-3461938ac.json.gz")
    args = parser.parse_args()
    sys.path[:0] = [str(args.backend.resolve()), str(TESTS)]
    import larch
    from fastapi.testclient import TestClient
    from xraylarch_web.config import Settings
    from xraylarch_web.main import create_app
    import test_athena_self_absorption_matches_larch_3461938ac as pinned

    with tempfile.TemporaryDirectory() as root, pinned.single_threaded_blas(), \
            TestClient(create_app(Settings(data_root=Path(root)))) as client:
        cases = {pinned.case_key(case): pinned.fluo_outputs(client, case) for case in pinned.CASES}
    record = {"reference": f"larch {larch.__version__}", "cases": cases}
    args.out.write_bytes(gzip.compress(json.dumps(record, sort_keys=True).encode(), mtime=0))
    print("wrote", args.out)


if __name__ == "__main__":
    main()
