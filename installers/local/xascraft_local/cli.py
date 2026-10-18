from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import webbrowser

from .common import default_root, prepare_root, read_json


def main():
    parser = argparse.ArgumentParser(description="Install, run and update a private local XAScraft edition.")
    parser.add_argument("--root", type=Path, default=default_root(), help="Private application/data directory")
    commands = parser.add_subparsers(dest="command", required=True)
    install = commands.add_parser("install", help="Install/update from an explicitly selected source folder")
    install.add_argument("--source", type=Path, required=True)
    install.add_argument("--uv", type=Path, required=True)
    install.add_argument("--no-shortcuts", action="store_true")
    for command in ("launch", "manage", "serve", "start", "stop", "quit", "status", "check-updates"):
        commands.add_parser(command)
    update = commands.add_parser("update", help="Install a previously checked official release; requires stopped app")
    update.add_argument("--tag", required=True)
    shortcuts = commands.add_parser("shortcuts", help="Create the application and Manager icons")
    shortcuts.add_argument("--directory", type=Path)
    package = commands.add_parser("package", help="Create a versioned source release asset")
    package.add_argument("--source", type=Path, required=True)
    package.add_argument("--output", type=Path, required=True)
    package.add_argument("--tag", required=True)
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    try:
        if args.command == "package":
            from .source import package_source
            package_source(args.source.resolve(), args.output.resolve(), args.tag)
            print(f"Created {args.output}")
            return
        prepare_root(root)
        if args.command == "install":
            source = args.source.expanduser().resolve()
            if root == source or root.is_relative_to(source):
                raise RuntimeError("Choose an installation directory outside the source code folder.")
            from .install import install_source
            uv = root / ("runtime/uv/uv.exe" if os.name == "nt" else "runtime/uv/uv")
            uv.parent.mkdir(parents=True, exist_ok=True)
            if args.uv.resolve() != uv:
                shutil.copy2(args.uv, uv)
            result = install_source(root, source, uv, make_shortcuts=not args.no_shortcuts)
            print(f"Installed {result['label']}. Open XAScraft or XAScraft Manager from your applications.\nData: {root / 'data'}")
            return
        if not read_json(root / "current.json"):
            raise RuntimeError("XAScraft is not installed here. Run the installer first.")
        if args.command == "shortcuts":
            from .shortcuts import create_shortcuts
            current = read_json(root / "current.json")
            create_shortcuts(root, root / "releases" / current["release"], args.directory)
            return
        from .manager import ensure_manager, manager_request, manager_status, open_manager, serve
        if args.command == "serve":
            serve(root)
            return
        if args.command == "status":
            print(json.dumps(manager_status(root) or {"running": False, "manager": "stopped"}, indent=2))
            return
        ensure_manager(root)
        if args.command == "manage":
            open_manager(root)
            return
        action = {"launch": "start", "check-updates": "check"}.get(args.command, args.command)
        status = manager_status(root)
        if not (action == "start" and status and status["busy"] == "start"):
            manager_request(root, action, tag=getattr(args, "tag", None))
        deadline = time.monotonic() + (3600 if action == "update" else 240)
        while time.monotonic() < deadline:
            status = manager_status(root)
            if status is None and action == "quit":
                print("XAScraft Manager stopped.")
                return
            if status and not status["busy"]:
                if status["error"]:
                    if args.command == "launch":
                        open_manager(root)
                    raise RuntimeError(status["error"])
                if args.command == "launch":
                    webbrowser.open(status["url"])
                print(json.dumps(status, indent=2))
                return
            time.sleep(0.4)
        raise RuntimeError("Operation is still running. Open XAScraft Manager to see its status and logs.")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"XAScraft: {exc}\nLogs: {root / 'logs'}", file=sys.stderr)
        raise SystemExit(1)
