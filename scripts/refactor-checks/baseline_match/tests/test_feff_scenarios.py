"""The FEFF path preview and theory simulation scenarios record what the Artemis routes drew."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
BACKEND = HERE.parents[2] / "backend"


@pytest.fixture(scope="module")
def captured(tmp_path_factory):
    out = tmp_path_factory.mktemp("capture")
    env = {key: value for key, value in os.environ.items() if not key.startswith("XRAYLARCH_")}
    subprocess.run([sys.executable, str(HERE / "run.py"), "--backend", str(BACKEND), "--out", str(out),
                    "--only", "artemis-path-preview", "artemis-theory-simulation"],
                   check=True, env=env, cwd=out)
    return {name: json.loads((out / f"{name}.json").read_text())
            for name in ("artemis-path-preview", "artemis-theory-simulation")}


def steps(document, prefix):
    return [step for step in document["steps"] if step["step"].startswith(prefix)]


pytestmark = pytest.mark.skipif(not (BACKEND / "xraylarch_web").is_dir(), reason="needs the repository's backend")


def test_copper_and_cuprite_previews_are_drawn_at_the_requested_values_and_k_weights(captured):
    document = captured["artemis-path-preview"]
    assert "error" not in document
    previews = steps(document, "preview ")
    assert [step["status"] for step in previews] == [200] * len(previews)
    drawn = {step["step"]: step["body"] for step in previews}

    copper, perturbed = drawn["preview copper"], drawn["preview copper, perturbed values"]
    assert [path["values"]["sigma2"] for path in copper["paths"]] == [0.008]
    assert [path["values"]["sigma2"] for path in perturbed["paths"]] == [0.0102]
    assert copper["k"]["chi"] != perturbed["k"]["chi"]
    assert drawn["preview copper, k weight 3 to k 20"]["k"]["weight"] == 3
    assert drawn["preview copper, k weight 3 to k 20"]["transform"]["kmax"] == 20
    assert len(drawn["preview copper twice, same FEFF content"]["paths"]) == 2

    cuprite = drawn["preview Cu₂O 4 paths"]
    assert len(cuprite["paths"]) == 4
    assert drawn["preview Cu₂O 4 paths, k weight 1"]["k"]["weight"] == 1
    assert drawn["preview Cu₂O 4 paths, perturbed values"]["k"]["chi"] != cuprite["k"]["chi"]


def test_a_feff_calculation_is_simulated_added_as_theory_and_replayed(captured):
    document = captured["artemis-theory-simulation"]
    assert "error" not in document
    simulated = {step["step"]: step for step in steps(document, "simulate")}
    assert [step["status"] for step in simulated.values()] == [200] * 3
    default = simulated["simulate every path"]["body"]
    assert default["paths"] and default["source"]["paths"][0]["content"].strip()
    debye = simulated["simulate with Debye disorder, k weight 3"]["body"]
    assert debye["k"]["weight"] == 3 and debye["simulation"]["request"]["disorder_model"] == "debye"
    assert len(simulated["simulate the first two paths, k weight 1"]["body"]["paths"]) == 2

    added = steps(document, "add the simulation to the project")[0]
    assert added["status"] == 200
    assert "theory" in added["body"]["groups"][-1]["source"]["tags"]
    replays = steps(document, "replay the saved theory")
    assert [step["status"] for step in replays] == [200, 200]
    assert replays[1]["body"]["k"]["weight"] == 1
