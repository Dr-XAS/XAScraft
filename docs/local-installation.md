# XAScraft on your computer

The local edition uses the same interface and scientific code as the web service.
It starts private services on `127.0.0.1` and opens your browser. You do not need to
install Python, Node.js, Git, Docker, or a desktop GUI toolkit yourself.

## Install from source

Download and extract this repository, or use an existing checkout. Keep the entire
source folder, including `examples/`, until installation finishes.

| Platform | Entry point | Application icons |
| --- | --- | --- |
| macOS Intel / Apple Silicon | Double-click `Install.command` | `~/Applications/XAScraft.app` and `XAScraft Manager.app` |
| Windows x64 | Double-click `Install Windows.cmd` | Start menu → XAScraft |
| Linux x86-64 | Run `bash Install.command` | Desktop environment's applications menu |

The first installation needs internet access and several GB of free space. It
downloads a checksum-pinned uv installer, private Python 3.12.14 and Node 24.21.0,
installs the repository's Larch code with release-constrained dependencies, and
builds the production frontend. The optional Torch/JAX engines are not installed.
System Python, Node, shell profiles and administrator-owned directories are not
changed. Updating needs room for the old version, the new version and a data backup.

Apple Silicon currently uses the bundled Intel FEFF executables through Rosetta 2.
The installer runs a real FEFF calculation and reports a failure if the required
native runtime is unavailable. Install Rosetta through macOS if prompted by that
failure, then retry. Linux ARM and Windows ARM are not supported in this edition.
Windows and Linux installers should be treated as preview support until the
platform matrix passes on the particular release; testing on macOS alone is not
evidence for those platforms. Corporate execution policies may require your IT
team to allow the unsigned source installer.

For a ZIP whose executable permission was not preserved, run `bash Install.command`
in a terminal in the extracted folder. For automated Windows installation, invoke
`installers/local/install-windows.ps1` directly; the `.cmd` wrapper pauses to keep
diagnostic messages visible for interactive users.

## Daily use

- Open **XAScraft** to start the services and open the application in your browser.
- Open **XAScraft Manager** to see the installed version, start/stop the application,
  inspect logs, check for releases, or install an update.
- Save your work before **Stop** or **Quit Manager**. Closing a browser tab does not
  stop the services. **Quit Manager** stops both services and the Manager.
- Repeated launches reuse the Manager. Application ports are selected once and
  preserved across updates so the browser retains the same origin and local state.
  If another process occupies a saved port, the Manager reports it instead of
  killing the process or silently moving the application.

Ordinary analysis and bundled references run locally after installation. External
database queries still need their corresponding network services. Hosted Dr.XAS
integration and Slack notifications are disabled; the installation does not copy
the source checkout's `.env`, project data, or provider secrets.

## Data and versions

| Platform | Private installation directory |
| --- | --- |
| macOS | `~/Library/Application Support/XAScraft` |
| Windows | `%LOCALAPPDATA%\XAScraft` |
| Linux | `${XDG_DATA_HOME:-~/.local/share}/XAScraft` |

The directory contains:

```text
data/                 Projects, preferences, scientific caches
releases/<id>/        One source snapshot, Python environment and frontend build
runtime/              Private Python, Node, installer and icons
current.json          Active version and stable application ports
backups/<time>/       Data and version pointer saved before an update
logs/                 Installation, application and verification diagnostics
launch.py             Stable target used by the application icons
```

The source checkout is copied; subsequent edits or deletion of the original source
folder do not change an installed version. Each snapshot has its own content hash,
source Git revision when available, exact installed Python package list, and
installation check result. A working-tree build is labeled `local-<hash>` and is
not represented as an official release. The app's existing build badge and bug
report diagnostics retain build metadata for identifying the installation.

For a custom location, set `XASCRAFT_INSTALL_ROOT` before running the installer.
Keep it outside the source folder and on a local filesystem. The installation
directory is user-private; do not share it as a multi-user server.

## Update while development continues

Source users can stop XAScraft, obtain updated source, and run the installer again
with the same installation directory. No automatic `git pull` runs against your
checkout, and no update is performed at startup.

For ordinary users, **Check for updates** reads published GitHub releases from
**Dr-XAS/XAScraft** only. It accepts stable `xascraft-vMAJOR.MINOR.PATCH` releases
with the `xascraft-source.zip` asset and a GitHub SHA-256 asset digest. Upstream
Larch releases, branches, prereleases, drafts and unverified assets are ignored.
If none are published yet, the Manager says so; source installation still works.

After stopping analysis, click **Install update**. The installer prepares a new
version alongside the old one, verifies the backend, frontend proxy, bundled
spectra and native FEFF using temporary data, backs up your stopped application
data, then switches `current.json`. Failed builds/checks leave the old version
selected. Reopen XAScraft after the update to load the new Manager code.

Previous versions and backups are retained. Automatic downgrades are disabled:
opening newer project data with older code may be unsafe after a schema change.
For recovery, keep the current data intact and restore a matched `data/` backup
and its `current.json` only while all services are stopped. There is deliberately
no button that silently overwrites newer work with an older backup.

## Troubleshooting and command line

The Manager's **Show logs** displays recent diagnostics. Complete logs are in the
installation directory. If startup fails, the XAScraft shortcut opens the Manager
with the error. After an abnormal Manager termination, surviving services can
occupy the saved ports; restart the computer or stop those known processes before
retrying. The installer refuses to update while those ports are occupied.

For automation, use the private Python interpreter with the installed `launch.py`:

```text
python <installation-directory>/launch.py start
python <installation-directory>/launch.py status
python <installation-directory>/launch.py stop
python <installation-directory>/launch.py check-updates
python <installation-directory>/launch.py update --tag xascraft-v0.1.0
python <installation-directory>/launch.py quit
```

`python` above denotes the installed interpreter recorded as `controller_python`
in the active version's `release.json`. `--no-shortcuts` skips icon creation during
installation. The source CLI can create test icons in an explicit directory:
`python installers/local/run.py --root <installation-directory> shortcuts --directory <folder>`.

## Maintainer release procedure

Keep ordinary development on `master`. The **Local installation** workflow tests
source installation on macOS, Windows and Linux; it does not deploy a hosted app.
When a version is ready, a tag such as `xascraft-v0.1.0` triggers the same checks.
Only after all platform checks pass does that tag workflow attach the source ZIP
and checksum to a GitHub release in `Dr-XAS/XAScraft`. Creating a tag/release remains
a separate publication action; adding these scripts does not publish anything.

To build a source asset locally without publishing:

```bash
python installers/local/run.py package --source . --tag xascraft-v0.1.0 \
  --output /tmp/xascraft-source.zip
```

This first edition builds dependencies on the user's computer. A signed prebuilt
`.dmg`/Windows installer, update progress inside the main scientific interface,
automatic old-version cleanup and optional-engine installation are future work.
