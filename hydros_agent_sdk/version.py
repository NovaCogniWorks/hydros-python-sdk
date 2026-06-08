"""SDK version helpers.

`pyproject.toml` is the single source of truth for the package version.
When running from a source checkout, read that file directly; when running
from an installed wheel, fall back to package metadata.
"""

from __future__ import annotations

import re
from importlib import metadata
from pathlib import Path


PACKAGE_NAME = "hydros-agent-sdk"
_UNKNOWN_VERSION = "0.0.0"


def _read_pyproject_version() -> str | None:
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if not pyproject.exists():
        return None

    try:
        content = pyproject.read_text(encoding="utf-8")
    except OSError:
        return None

    project_section = re.search(
        r"(?ms)^\[project\]\s*(.*?)(?=^\[|\Z)",
        content,
    )
    if project_section is None:
        return None

    package_name = re.search(r'(?m)^name\s*=\s*"([^"]+)"', project_section.group(1))
    if package_name is None or package_name.group(1) != PACKAGE_NAME:
        return None

    version = re.search(r'(?m)^version\s*=\s*"([^"]+)"', project_section.group(1))
    if version is None:
        return None
    return version.group(1)


def get_sdk_version() -> str:
    """Return the Hydros Agent SDK version from the canonical source."""
    source_version = _read_pyproject_version()
    if source_version:
        return source_version

    try:
        return metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        return _UNKNOWN_VERSION


__version__ = get_sdk_version()
SDK_USER_AGENT = f"Hydros-Agent-SDK/{__version__}"
