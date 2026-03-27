"""Bootstrap local imports for agent entrypoints.

Python imports ``sitecustomize`` automatically during startup when it is
available on ``sys.path``. This lets the local launcher find the repository
root even when the shell script does not export the correct ``PYTHONPATH``.
"""

from pathlib import Path
import sys


CURRENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = next(
    (parent for parent in CURRENT_DIR.parents if (parent / "hydros_agent_sdk").is_dir()),
    None,
)

if REPO_ROOT is not None:
    repo_root_str = str(REPO_ROOT)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)
