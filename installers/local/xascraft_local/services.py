"""Own live process handles; never kill processes based on a saved PID."""
from __future__ import annotations

from pathlib import Path
import json
import os
import signal
import subprocess
import time
import urllib.request

from .common import python_in, read_json, require_free_port, runtime_env


def request_json(url: str, data=None, *, token=None, timeout=10):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, headers=headers,
                                     data=json.dumps(data).encode() if data is not None else None)
    # Local service traffic must never be sent through a configured HTTP proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        return json.load(response)


class ServicePair:
    def __init__(self, root: Path, release: Path, ports: dict, *, data=None, log_prefix="app"):
        self.root, self.release, self.ports = root, release, ports
        self.data, self.log_prefix = data, log_prefix
        self.children: list[subprocess.Popen] = []
        self.logs = []

    @property
    def url(self):
        return f"http://127.0.0.1:{self.ports['frontend']}"

    @property
    def backend_url(self):
        return f"http://127.0.0.1:{self.ports['backend']}"

    def healthy(self) -> bool:
        return len(self.children) == 2 and all(child.poll() is None for child in self.children)

    def active(self) -> bool:
        return any(child.poll() is None for child in self.children)

    def _spawn(self, args, cwd, env, component):
        log = (self.root / "logs" / f"{self.log_prefix}-{component}.log").open("ab")
        self.logs.append(log)
        kwargs = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
                  if os.name == "nt" else {"start_new_session": True})
        self.children.append(subprocess.Popen([str(a) for a in args], cwd=cwd, env=env,
            stdin=subprocess.DEVNULL, stdout=log, stderr=log, **kwargs))

    def start(self, *, timeout=180):
        if self.children:
            raise RuntimeError("This service pair is already started.")
        for port in self.ports.values():
            require_free_port(port)
        source = self.release / "source"
        metadata = read_json(self.release / "release.json")
        env = runtime_env(self.root, source, metadata, self.data)
        node = Path(metadata["node"])
        env["PATH"] = str(node.parent) + os.pathsep + env.get("PATH", "")
        env.update(BACKEND_URL=self.backend_url, NEXT_BACKEND_URL=self.backend_url)
        try:
            self._spawn([python_in(self.release / ".venv"), "-m", "uvicorn", "xraylarch_web.main:app",
                         "--host", "127.0.0.1", "--port", self.ports["backend"]],
                        source / "backend", env, "backend")
            self._spawn([node, source / "frontend/node_modules/next/dist/bin/next", "start",
                         "-H", "127.0.0.1", "-p", self.ports["frontend"]],
                        source / "frontend", env, "frontend")
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if not self.healthy():
                    raise RuntimeError("A local service exited during startup. See the backend/frontend logs.")
                try:
                    backend = request_json(self.backend_url + "/health", timeout=2)
                    proxy = request_json(self.url + "/api/backend/health", timeout=2)
                    expected = metadata.get("revision") or "unknown"
                    if backend.get("status") == "ok" and backend.get("git_revision") == expected and proxy.get("status") == "ok":
                        return
                except (OSError, ValueError):
                    pass
                time.sleep(0.4)
            raise RuntimeError("Startup timed out. See the backend/frontend logs.")
        except BaseException:
            self.stop()
            raise

    def stop(self):
        # Use process objects retained by this manager, never PID files/port owners.
        for child in reversed(self.children):
            if child.poll() is None:
                try:
                    if os.name == "nt":
                        subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW, check=False)
                    else:
                        os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        for child in reversed(self.children):
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    child.kill()
                else:
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                child.wait(timeout=10)
        self.children.clear()
        for log in self.logs:
            log.close()
        self.logs.clear()


def science_smoke(pair: ServicePair) -> dict:
    """Real bundled data + real native FEFF, isolated from the user's projects."""
    base = pair.backend_url
    created = request_json(base + "/api/athena/projects?view=summary", {"name": "Installation check"})
    project = created.get("project", created)
    project_id = project["id"]
    result = request_json(base + f"/api/athena/projects/{project_id}/command?view=summary", {
        "version": project["version"], "action": "example", "group_ids": [], "options": {},
    }, timeout=120)
    project = result.get("project", result)
    groups = project.get("groups", [])
    if not groups or any(group.get("processing_error") for group in groups):
        raise RuntimeError("The bundled spectrum processing check failed.")
    job = request_json(base + "/api/artemis/feff/jobs?view=summary", {
        "amcsd_id": 13088, "absorber": "Cu", "site_index": 1, "path_radius": 3,
    }, timeout=60)
    deadline = time.monotonic() + 120
    while job["status"] == "running" and time.monotonic() < deadline:
        time.sleep(0.5)
        job = request_json(base + f"/api/artemis/feff/jobs/{job['id']}?view=summary")
    if job["status"] != "complete" or not job.get("paths"):
        raise RuntimeError("Native FEFF check failed: " + str(job.get("message", job["status"]))
                           + ". On Apple Silicon, check that Rosetta 2 is installed.")
    return {"example_groups": len(groups), "feff_paths": len(job["paths"])}
