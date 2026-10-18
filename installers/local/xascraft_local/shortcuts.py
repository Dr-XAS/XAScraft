from __future__ import annotations

from pathlib import Path
import base64
import json
import os
import plistlib
import shlex
import shutil
import subprocess
import sys

from .common import python_in, run


def write_dispatcher(root: Path):
    # Stable icon target; never embeds a particular release directory.
    (root / "launch.py").write_text('''import json, pathlib, re, runpy, sys
root = pathlib.Path(__file__).resolve().parent
current = json.loads((root / "current.json").read_text())
release = current["release"]
if not re.fullmatch(r"[0-9a-f]{32}", release):
    raise RuntimeError("Invalid installed release identifier")
entry = root / "releases" / release / "source/installers/local/run.py"
sys.path.insert(0, str(entry.parent))
sys.argv = [str(entry), "--root", str(root), *sys.argv[1:]]
runpy.run_path(str(entry), run_name="__main__")
''', encoding="utf-8")


def create_shortcuts(root: Path, release: Path, destination: Path | None = None):
    """Per-user shortcuts; no administrator/system-wide install is required."""
    source = release / "source"
    original = source / "frontend/public/logos/drxas-mark-light.png"
    icon = root / "runtime/XAScraft.png"
    shutil.copy2(original, icon)
    commands = {"XAScraft": "launch", "XAScraft Manager": "manage"}
    if sys.platform == "darwin":
        destination = destination or Path.home() / "Applications"
        destination.mkdir(parents=True, exist_ok=True)
        # Convert the existing project artwork to the native icon container.
        iconset = root / "cache/XAScraft.iconset"
        iconset.mkdir(exist_ok=True)
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                target = iconset / f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
                subprocess.run(["sips", "-z", str(size * scale), str(size * scale), str(icon), "--out", str(target)],
                               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        native_icon = root / "runtime/XAScraft.icns"
        subprocess.run(["iconutil", "-c", "icns", "-o", str(native_icon), str(iconset)], check=True)
        for name, command in commands.items():
            app = destination / (name + ".app")
            # Do not replace a different app that happens to have the same name.
            marker = app / "Contents/xascraft-root.txt"
            if app.exists() and (not marker.exists() or marker.read_text() != str(root)):
                raise RuntimeError(f"A different application already exists at {app}.")
            executable = app / "Contents/MacOS/XAScraft"
            executable.parent.mkdir(parents=True, exist_ok=True)
            resources = app / "Contents/Resources"
            resources.mkdir(exist_ok=True)
            shutil.copy2(native_icon, resources / "XAScraft.icns")
            executable.write_text("#!/bin/sh\nexec " + " ".join(shlex.quote(str(a)) for a in
                (sys.executable, root / "launch.py", command)) + " >> "
                + shlex.quote(str(root / "logs/launcher.log")) + " 2>&1\n")
            executable.chmod(0o755)
            marker.write_text(str(root))
            with (app / "Contents/Info.plist").open("wb") as out:
                plistlib.dump({"CFBundleName": name, "CFBundleDisplayName": name,
                              "CFBundleIdentifier": "org.drxas.xascraft." + command,
                              "CFBundleExecutable": "XAScraft", "CFBundlePackageType": "APPL",
                              "CFBundleIconFile": "XAScraft.icns", "LSUIElement": True}, out)
    elif os.name == "nt":
        destination = destination or Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/XAScraft"
        destination.mkdir(parents=True, exist_ok=True)
        ico = root / "runtime/XAScraft.ico"
        run([python_in(release / ".venv"), "-c",
             "from PIL import Image; import sys; Image.open(sys.argv[1]).save(sys.argv[2], sizes=[(16,16),(32,32),(48,48),(256,256)])",
             icon, ico])
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        executable = pythonw if pythonw.exists() else Path(sys.executable)
        entries = [{"path": str(destination / (name + ".lnk")), "target": str(executable),
                    "args": subprocess.list2cmdline([str(root / "launch.py"), command]),
                    "icon": str(ico)} for name, command in commands.items()]
        # Pass paths as JSON data, never interpolate user paths into PowerShell code.
        env = os.environ.copy()
        env["XASCRAFT_SHORTCUTS"] = json.dumps(entries)
        code = '''$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
foreach ($item in ($env:XASCRAFT_SHORTCUTS | ConvertFrom-Json)) {
  $shortcut = $shell.CreateShortcut($item.path)
  $shortcut.TargetPath = $item.target
  $shortcut.Arguments = $item.args
  $shortcut.IconLocation = $item.icon
  $shortcut.WindowStyle = 7
  $shortcut.Save()
}
'''
        run(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand",
             base64.b64encode(code.encode("utf-16le")).decode()], env=env)
    else:
        destination = destination or Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "applications"
        destination.mkdir(parents=True, exist_ok=True)
        def quoted(value):
            return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$").replace("%", "%%") + '"'
        for name, command in commands.items():
            shortcut = destination / f"xascraft-{command}.desktop"
            shortcut.write_text("[Desktop Entry]\nType=Application\n" + f"Name={name}\n"
                + "Exec=" + " ".join(quoted(a) for a in (sys.executable, root / "launch.py", command))
                + f"\nIcon={icon}\nTerminal=false\nCategories=Science;Education;\n")
            shortcut.chmod(0o755)
