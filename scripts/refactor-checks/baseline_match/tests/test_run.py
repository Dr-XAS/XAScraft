"""The runner records what the public HTTP API returned, step by step."""
import gzip
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from compare import compare_dirs
from run import Session

HERE = Path(__file__).resolve().parents[1]
BACKEND = HERE.parents[2] / "backend"


def tiny_app():
    app = FastAPI()

    @app.get("/project")
    def project():
        return {"id": "Qm9yWZ1x8kTq0aLw3v_Hn7Zc", "norm": [0.1, 1 / 3]}

    @app.get("/export")
    def export():
        payload = json.dumps({"groups": [{"label": "Cu foil"}]}).encode()
        return Response(gzip.compress(payload, mtime=12345), media_type="application/octet-stream",
                        headers={"Content-Disposition": 'attachment; filename="copper.prj"'})

    @app.get("/csv")
    def csv():
        return Response("energy,mu\n8979.0,0.5\n", media_type="text/csv")

    @app.get("/missing")
    def missing():
        return Response('{"error": {"message": "not found"}}', status_code=404, media_type="application/json")

    return app


def test_json_text_and_gzip_bodies_are_recorded_as_their_content():
    session = Session(lambda: TestClient(tiny_app()))

    assert session.ok("load", "GET", "/project")["norm"] == [0.1, 1 / 3]
    session.call("export", "GET", "/export")
    session.call("csv", "GET", "/csv")
    session.call("missing", "GET", "/missing")

    assert session.steps == [
        {"step": "load", "request": "GET /project", "status": 200, "content_type": "application/json",
         "body": {"id": "Qm9yWZ1x8kTq0aLw3v_Hn7Zc", "norm": [0.1, 1 / 3]}},
        {"step": "export", "request": "GET /export", "status": 200, "content_type": "application/octet-stream",
         "content_disposition": 'attachment; filename="copper.prj"',
         "gzip": True, "body": {"groups": [{"label": "Cu foil"}]}},
        {"step": "csv", "request": "GET /csv", "status": 200, "content_type": "text/csv; charset=utf-8",
         "body": "energy,mu\n8979.0,0.5\n"},
        {"step": "missing", "request": "GET /missing", "status": 404, "content_type": "application/json",
         "body": {"error": {"message": "not found"}}},
    ]


def test_a_failed_step_a_scenario_depends_on_stops_it():
    session = Session(lambda: TestClient(tiny_app()))

    with pytest.raises(Exception, match="404"):
        session.ok("missing", "GET", "/missing")


@pytest.mark.skipif(not (BACKEND / "xraylarch_web").is_dir(), reason="needs the repository's backend")
def test_a_scenario_captured_twice_compares_equal(tmp_path):
    env = {key: value for key, value in os.environ.items() if not key.startswith("XRAYLARCH_")}
    for name in ("first", "second"):
        subprocess.run([sys.executable, str(HERE / "run.py"), "--backend", str(BACKEND),
                        "--out", str(tmp_path / name), "--only", "copper-examples"],
                       check=True, env=env, cwd=tmp_path)

    assert (tmp_path / "first" / "copper-examples.json").is_file()
    assert compare_dirs(tmp_path / "first", tmp_path / "second") == []
