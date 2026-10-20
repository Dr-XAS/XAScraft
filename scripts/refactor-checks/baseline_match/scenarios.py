"""The fixed list of baseline-match scenarios, all through the public HTTP API.

Each scenario is a function of a `run.Session`; `SCENARIOS` maps its name to it,
in the order they run. Every call is recorded as a step, so the captured file
holds every response the scenario saw.
"""

ATHENA = "/api/athena"


def new_project(s, step="create project"):
    return s.ok(step, "POST", f"{ATHENA}/projects")


def command(s, step, project, action, group_ids=(), **options):
    return s.ok(step, "POST", f"{ATHENA}/projects/{project['id']}/command",
                json={"version": project["version"], "action": action, "group_ids": list(group_ids),
                      "options": options})


def copper(s):
    """A new project holding the copper examples."""
    return command(s, "load copper examples", new_project(s), "example")


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


SCENARIOS = {
    "copper-examples": copper_examples,
}
