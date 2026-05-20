import sys
from pathlib import Path

# Allow importing src.mmd from the repo root when loaded from this directory.
_repo_root = Path(__file__).parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from src.mmd import register  # noqa: F401, E402
