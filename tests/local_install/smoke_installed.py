"""Acceptance check for a DISPOSABLE installed edition; creates a bundled project."""
from pathlib import Path
import json
import subprocess
import sys
import urllib.request


def request(url, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=120) as res:
        return json.load(res)


def verify(root):
    current = json.loads((root / "current.json").read_text())
    release = root / "releases" / current["release"]
    metadata = json.loads((release / "release.json").read_text())
    python = metadata.get("controller_python", str(release / (".venv/Scripts/python.exe" if sys.platform == "win32" else ".venv/bin/python")))
    def command(name):
        return subprocess.check_output([python, str(root / "launch.py"), name], text=True)
    try:
        command("start")
        first = json.loads(command("status"))
        assert first["running"]
        command("start")  # Duplicate launch reuses the same services and browser origin.
        assert json.loads(command("status"))["url"] == first["url"]
        base = first["url"] + "/api/backend/api/athena"
        project = request(base + "/projects?view=summary", {"name": "Local installation persistence check"})
        project = project.get("project", project)
        project_id = project["id"]
        project = request(base + f"/projects/{project_id}/command?view=summary", {
            "version": project["version"], "action": "example", "group_ids": [], "options": {},
        })
        project = project.get("project", project)
        assert len(project["groups"]) > 0
        version = project["version"]
        command("stop")
        assert not json.loads(command("status"))["running"]
        command("start")
        restored = request(base + f"/projects/{project_id}?view=summary")
        restored = restored.get("project", restored)
        assert restored["id"] == project_id
        assert restored["version"] == version
        assert restored["groups"] == project["groups"]
        (root / "run/verified-project.json").write_text(json.dumps({"id": project_id, "version": version}))
        print(f"PASS: start, repeated start, proxy import, stop, restart and {len(project['groups'])} preserved spectra.")
    finally:
        command("quit")


if __name__ == "__main__":
    verify(Path(sys.argv[1]).resolve())
