#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Publish hydros-agent-sdk with uv.

Usage:
  scripts/publish.sh [options] [-- extra uv publish args]

Options:
  -r, --repository <pypi|testpypi>
      Target repository. Defaults to pypi.

  --dry-run
      Build and validate the package, then run uv publish without uploading.

  --skip-build
      Reuse existing files in dist/.

  --skip-check
      Skip twine metadata validation.

  --package-name <name>
      Publish with a temporary package name. The project files are copied to
      a temporary directory before pyproject.toml is changed. This is intended
      for preview package verification, not the official hydros-agent-sdk release.

  --version <version>
      Publish with a temporary package version. If --package-name is used and
      --version is omitted, a timestamped dev version is generated.

  -y, --yes
      Required when publishing to PyPI.

  -h, --help
      Show this help.

Authentication:
  Export UV_PUBLISH_TOKEN before publishing.

Examples:
  UV_PUBLISH_TOKEN="pypi-..." scripts/publish.sh --yes
  UV_PUBLISH_TOKEN="pypi-..." scripts/publish.sh --package-name hydros-agent-sdk-preview --yes
  scripts/publish.sh --dry-run
EOF
}

expected_package_name="hydros-agent-sdk"
repository="pypi"
dry_run=false
skip_build=false
skip_check=false
confirmed=false
package_name_override=""
package_version_override=""
publish_extra_args=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    -r|--repository)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for $1" >&2
        exit 2
      fi
      repository="$2"
      shift 2
      ;;
    --dry-run)
      dry_run=true
      shift
      ;;
    --skip-build)
      skip_build=true
      shift
      ;;
    --skip-check)
      skip_check=true
      shift
      ;;
    --package-name)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for $1" >&2
        exit 2
      fi
      package_name_override="$2"
      shift 2
      ;;
    --version)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for $1" >&2
        exit 2
      fi
      package_version_override="$2"
      shift 2
      ;;
    -y|--yes)
      confirmed=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      publish_extra_args+=("$@")
      break
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd "${script_dir}/.." && pwd)"
cd "${project_root}"

if [[ -n "${package_name_override}" && ! "${package_name_override}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  echo "Invalid package name: ${package_name_override}" >&2
  exit 2
fi

if [[ -n "${package_version_override}" && ! "${package_version_override}" =~ ^[A-Za-z0-9][A-Za-z0-9.!+_-]*$ ]]; then
  echo "Invalid package version: ${package_version_override}" >&2
  exit 2
fi

case "${repository}" in
  pypi)
    publish_url="https://upload.pypi.org/legacy/"
    check_url="https://pypi.org/simple/"
    ;;
  testpypi)
    publish_url="https://test.pypi.org/legacy/"
    check_url="https://test.pypi.org/simple/"
    ;;
  *)
    echo "Unsupported repository: ${repository}" >&2
    echo "Expected: testpypi or pypi" >&2
    exit 2
    ;;
esac

if [[ "${repository}" == "pypi" && -n "${package_name_override}" && "${dry_run}" == "false" && "${confirmed}" == "false" ]]; then
  echo "Refusing to publish a temporary package name to PyPI without --yes." >&2
  exit 2
fi

if [[ "${repository}" == "pypi" && "${dry_run}" == "false" && "${confirmed}" == "false" ]]; then
  echo "Refusing to publish to PyPI without --yes." >&2
  exit 2
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required but was not found in PATH." >&2
  exit 127
fi

if [[ "${dry_run}" == "false" && -z "${UV_PUBLISH_TOKEN:-}" ]]; then
  echo "UV_PUBLISH_TOKEN is required for publishing." >&2
  exit 2
fi

cleanup_dir=""
cleanup() {
  if [[ -n "${cleanup_dir}" && -d "${cleanup_dir}" ]]; then
    rm -rf "${cleanup_dir}"
  fi
}
trap cleanup EXIT

if [[ -n "${package_name_override}" || -n "${package_version_override}" ]]; then
  if ! command -v rsync >/dev/null 2>&1; then
    echo "rsync is required for temporary package publishing." >&2
    exit 127
  fi

  temp_project="$(mktemp -d "${TMPDIR:-/tmp}/hydros-agent-sdk-publish.XXXXXX")"
  cleanup_dir="${temp_project}"

  rsync -a \
    --exclude ".git/" \
    --exclude ".idea/" \
    --exclude ".venv/" \
    --exclude "build/" \
    --exclude "dist/" \
    --exclude "*.egg-info/" \
    --exclude "output/" \
    --exclude "docs/.venv/" \
    "${project_root}/" "${temp_project}/"

  cd "${temp_project}"

  if [[ -n "${package_name_override}" ]]; then
    perl -0pi -e "s/^name = \".*\"/name = \"${package_name_override}\"/m" pyproject.toml
  fi

  if [[ -z "${package_version_override}" ]]; then
    current_version="$(sed -n 's/^version = \"\\(.*\\)\"/\\1/p' pyproject.toml | head -n 1)"
    package_version_override="${current_version}.dev$(date +%Y%m%d%H%M%S)"
  fi

  perl -0pi -e "s/^version = \".*\"/version = \"${package_version_override}\"/m" pyproject.toml

  echo "Using temporary package metadata:"
  sed -n '/^\[project\]/,/^\[/p' pyproject.toml | sed -n '1,8p'
else
  package_name="$(sed -n 's/^name = "\(.*\)"/\1/p' pyproject.toml | head -n 1)"
  if [[ "${package_name}" != "${expected_package_name}" ]]; then
    echo "Unexpected package name in pyproject.toml: ${package_name}" >&2
    echo "Expected: ${expected_package_name}" >&2
    exit 2
  fi
fi

if [[ "${skip_build}" == "false" ]]; then
  echo "Cleaning old build artifacts..."
  rm -rf dist build ./*.egg-info

  echo "Building package..."
  uv build
elif [[ ! -d dist ]]; then
  echo "dist/ does not exist; run without --skip-build first." >&2
  exit 2
fi

if [[ "${skip_check}" == "false" ]]; then
  echo "Checking package metadata..."
  uv run --no-project --with twine twine check dist/*
fi

publish_args=(
  --publish-url "${publish_url}"
  --check-url "${check_url}"
)

if [[ "${dry_run}" == "true" ]]; then
  publish_args+=(--dry-run)
fi

publish_args+=("${publish_extra_args[@]}")

publish_package_name="$(sed -n 's/^name = "\(.*\)"/\1/p' pyproject.toml | head -n 1)"
publish_package_version="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -n 1)"

echo "Publishing ${publish_package_name} ${publish_package_version} to ${repository}..."
uv publish "${publish_args[@]}" dist/*
