"""Hermes plugin entry point.

The implementation lives in `src/`; this package only makes the repo importable
when Hermes loads the symlinked plugin directory.
"""

import sys
from pathlib import Path

# resolve() follows the symlink so this path works whether loaded from
# ~/.hermes/plugins/mmd/ (symlink) or from the repo directory directly.
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from src.mmd import register  # noqa: F401, E402

__all__ = ["register"]
