import re
from pathlib import Path

from hydros_agent_sdk.version import SDK_USER_AGENT, __version__, get_sdk_version


def test_sdk_version_uses_pyproject_version():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    content = pyproject.read_text(encoding="utf-8")
    version = re.search(r'(?m)^version\s*=\s*"([^"]+)"', content)

    assert version is not None
    assert get_sdk_version() == version.group(1)
    assert __version__ == version.group(1)


def test_sdk_user_agent_uses_sdk_version():
    assert SDK_USER_AGENT == f"Hydros-Agent-SDK/{__version__}"
