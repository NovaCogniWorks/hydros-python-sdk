#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
APP_NAME="hydros-control-algorithms"
PYTHON_BASE_IMAGE="${PYTHON_BASE_IMAGE:-registry.zot-oci.hydros.yuma.intra/yuma/images/public/dockerhub/library/python:3.11-slim-trixie}"
PODMAN_PULL_POLICY="${PODMAN_PULL_POLICY:-missing}"
IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-registry.zot-oci.hydros.yuma.intra/yuma/images/hydros/dev/${APP_NAME}}"
DEST_TLS_VERIFY="${DEST_TLS_VERIFY:-false}"
TARGET_PLATFORM="${TARGET_PLATFORM:-linux/amd64}"
TAG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag)
      TAG="${2:-}"
      [[ -n "${TAG}" ]] || { echo "--tag requires a value" >&2; exit 1; }
      shift 2
      ;;
    --platform)
      TARGET_PLATFORM="${2:-}"
      [[ -n "${TARGET_PLATFORM}" ]] || { echo "--platform requires a value" >&2; exit 1; }
      shift 2
      ;;
    -h|--help)
      cat <<'USAGE'
Usage:
  ./deploy/k3s/scripts/build_image.sh [tag]
  ./deploy/k3s/scripts/build_image.sh --tag <tag>
  ./deploy/k3s/scripts/build_image.sh --tag <tag> --platform linux/amd64

Environment:
  PYTHON_BASE_IMAGE base image, default registry.zot-oci.hydros.yuma.intra/yuma/images/public/dockerhub/library/python:3.11-slim-trixie
  PODMAN_PULL_POLICY pull policy, default missing; set never for offline debugging
  TARGET_PLATFORM target platform, default linux/amd64
  IMAGE_REPOSITORY target image repository, default registry.zot-oci.hydros.yuma.intra/yuma/images/hydros/dev/hydros-control-algorithms
USAGE
      exit 0
      ;;
    *)
      if [[ -z "${TAG}" ]]; then
        TAG="$1"
        shift
      else
        echo "unexpected argument: $1" >&2
        exit 1
      fi
      ;;
  esac
done

TAG="${TAG:-$(date +%Y%m%d-%H%M%S)}"
LOCAL_IMAGE="localhost/${APP_NAME}:${TAG}"
REMOTE_IMAGE="${IMAGE_REPOSITORY}:${TAG}"
TARGET_OS="${TARGET_PLATFORM%%/*}"
TARGET_ARCH="${TARGET_PLATFORM#*/}"
TARGET_ARCH="${TARGET_ARCH%%/*}"

# CONTAINER_ENGINE=docker selects the Docker daemon explicitly; Podman remains the default.
CONTAINER_ENGINE="${CONTAINER_ENGINE:-podman}"
case "${CONTAINER_ENGINE}" in
  podman) BUILD_PULL_ARGS=("--pull=${PODMAN_PULL_POLICY}") ;;
  docker)
    case "${PODMAN_PULL_POLICY}" in
      always) BUILD_PULL_ARGS=(--pull=true) ;;
      missing) BUILD_PULL_ARGS=(--pull=false) ;;
      *) echo "Docker mode supports pull policy missing or always; use Podman for never" >&2; exit 1 ;;
    esac
    ;;
  *) echo "CONTAINER_ENGINE must be docker or podman" >&2; exit 1 ;;
esac
command -v "${CONTAINER_ENGINE}" >/dev/null 2>&1 || { echo "missing command: ${CONTAINER_ENGINE}" >&2; exit 1; }

push_image() {
  if [[ "${CONTAINER_ENGINE}" == "docker" ]]; then
    docker tag "${LOCAL_IMAGE}" "${REMOTE_IMAGE}"
    docker push "${REMOTE_IMAGE}"
    return
  fi
  if [[ "$(uname -s)" == "Linux" ]]; then
    command -v skopeo >/dev/null 2>&1 || { echo "missing command: skopeo" >&2; exit 1; }
    skopeo copy --all --dest-tls-verify="${DEST_TLS_VERIFY}" \
      "containers-storage:${LOCAL_IMAGE}" \
      "docker://${REMOTE_IMAGE}"
  else
    podman push --tls-verify="${DEST_TLS_VERIFY}" "${LOCAL_IMAGE}" "${REMOTE_IMAGE}"
  fi
}

cd "${SCRIPT_DIR}"
"${CONTAINER_ENGINE}" build --platform "${TARGET_PLATFORM}" "${BUILD_PULL_ARGS[@]}" --build-arg BASE_IMAGE="${PYTHON_BASE_IMAGE}" -f custom-agent/power/Dockerfile -t "${LOCAL_IMAGE}" .
IMAGE_PLATFORM="$("${CONTAINER_ENGINE}" image inspect "${LOCAL_IMAGE}" --format '{{.Os}}/{{.Architecture}}')"
if [[ "${IMAGE_PLATFORM}" != "${TARGET_OS}/${TARGET_ARCH}" ]]; then
  echo "built image platform mismatch: expected ${TARGET_OS}/${TARGET_ARCH}, got ${IMAGE_PLATFORM}" >&2
  exit 1
fi
push_image
printf 'TAG=%s\n' "${TAG}"
printf 'IMAGE=%s\n' "${REMOTE_IMAGE}"
printf 'PLATFORM=%s\n' "${IMAGE_PLATFORM}"
