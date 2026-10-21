"""Where the regression tests find xraylarch's example data.

Default: the repository's ``examples/`` folder (``larch-patches/../examples``), which stays
when the root ``tests/`` folder goes.  Set ``XASCRAFT_EXAMPLES_DIR`` to use another copy, for
example the ``examples/`` folder of a patched upstream source tree.
"""

import os
from pathlib import Path


def examples_dir() -> Path:
    configured = os.environ.get("XASCRAFT_EXAMPLES_DIR")
    if configured:
        return Path(configured).resolve()
    return Path(__file__).resolve().parents[2] / "examples"


# The copper FEFF paths (feff0001.dat, ...) that the FEFF path tests read.
FEFF_CU = examples_dir() / "feffit" / "Feff_Cu"
