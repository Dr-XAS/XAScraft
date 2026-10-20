import sys
from pathlib import Path

# The checks are folders of scripts, not packages: put this one on the path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
