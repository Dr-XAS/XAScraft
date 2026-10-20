"""Write the step-1 FLUO self-absorption numbers that
`test_athena_self_absorption_step1_numbers.py` pins.

Run it with the step-1 tree's backend environment (the baseline worktree, tag
`refactor-baseline`), pointing at that tree's backend and at this tree's test file:

    <baseline>/backend/.venv/bin/python -I backend/tests/reference/self_absorption_step1_reference.py \
        --backend <baseline>/backend

with OPENBLAS_NUM_THREADS=OMP_NUM_THREADS=MKL_NUM_THREADS=1 and XRAYLARCH_DATA_ROOT set to a
scratch folder. The cases and the HTTP calls come from the test module, so the reference and
the test make the same requests.
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
    parser.add_argument("--out", type=Path, default=TESTS / "fixtures" / "athena-self-absorption-fluo-step1.json.gz")
    args = parser.parse_args()
    sys.path[:0] = [str(args.backend.resolve()), str(TESTS)]
    import larch
    from fastapi.testclient import TestClient
    from xraylarch_web.config import Settings
    from xraylarch_web.main import create_app
    import test_athena_self_absorption_step1_numbers as pinned

    with tempfile.TemporaryDirectory() as root, \
            TestClient(create_app(Settings(data_root=Path(root)))) as client:
        cases = {case: pinned.fluo_outputs(client, case) for case in pinned.CASES}
    record = {"reference": f"larch {larch.__version__}", "cases": cases}
    args.out.write_bytes(gzip.compress(json.dumps(record, sort_keys=True).encode(), mtime=0))
    print("wrote", args.out)


if __name__ == "__main__":
    main()
