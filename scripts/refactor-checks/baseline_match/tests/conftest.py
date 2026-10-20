import sys
from pathlib import Path

# The harness is a folder of scripts, not a package: put it on the path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
