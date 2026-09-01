#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "Usage: $0 <prod|stag|test> [start_agents_args...]" >&2
}

if [ "$#" -eq 0 ]; then
    usage
    exit 2
fi

case "$1" in
    prod|production)
        DEPLOY_ENV="production"
        ;;
    stag|staging)
        DEPLOY_ENV="staging"
        ;;
    test|testing)
        DEPLOY_ENV="testing"
        ;;
    *)
        echo "Unsupported deploy environment: $1" >&2
        usage
        exit 2
        ;;
esac
shift

case "${DEPLOY_ENV}" in
    production)
        DEPLOY_HOST="192.168.20.52"
        HYDROS_CLUSTER_ID="hydros-cluster-production"
        MQTT_BROKER_URL="tcp://mqtt.production.hydros.yuma.intra"
        ;;
    staging)
        DEPLOY_HOST="192.168.20.51"
        HYDROS_CLUSTER_ID="hydros-cluster-staging"
        MQTT_BROKER_URL="tcp://192.168.50.112"
        ;;
    testing)
        DEPLOY_HOST="192.168.20.51"
        HYDROS_CLUSTER_ID="hydros-cluster-testing"
        MQTT_BROKER_URL="tcp://mqtt.testing.hydros.yuma.intra"
        ;;
    *)
        echo "Internal error: unsupported normalized deploy environment: ${DEPLOY_ENV}" >&2
        exit 1
        ;;
esac

if [ -n "${DEPLOY_HOST_OVERRIDE:-}" ]; then
    DEPLOY_HOST="${DEPLOY_HOST_OVERRIDE}"
fi

DEPLOY_DOCKER_PORT="${DEPLOY_DOCKER_PORT:-2375}"
export DOCKER_HOST="tcp://${DEPLOY_HOST}:${DEPLOY_DOCKER_PORT}"
VERSION="${VERSION:-v1.0.0}"

BASE_IMAGE="${BASE_IMAGE:-python:3.11-slim}"
IMAGE_NAME="${IMAGE_NAME:-hydros-power-agent}"
CONTAINER_NAME="${CONTAINER_NAME:-hydros-power-agent}"
HYDROS_NODE_ID="${HYDROS_NODE_ID:-}"
MQTT_BROKER_PORT="${MQTT_BROKER_PORT:-1883}"
MQTT_TOPIC="${MQTT_TOPIC:-}"
MQTT_USERNAME="${MQTT_USERNAME:-hydros_agent_user}"
MQTT_PASSWORD="${MQTT_PASSWORD:-HbGcDx125a}"
DEFAULT_AGENT_START_ARGS="${HYDROS_AGENT_START_ARGS:-${START_ARGS:-scheduling}}"
HYDROS_AGENT_START_ARGS="${DEFAULT_AGENT_START_ARGS}"
PORT="${PORT:-8015}"
HYDROS_CONTROL_ALGORITHM_HOST="${HYDROS_CONTROL_ALGORITHM_HOST:-0.0.0.0}"
HYDROS_CONTROL_ALGORITHM_PORT="${HYDROS_CONTROL_ALGORITHM_PORT:-8015}"
DEBUG_PORT="${DEBUG_PORT:-}"
LOG_VOLUME="${LOG_VOLUME:-${CONTAINER_NAME}-logs}"

if [ "$#" -gt 0 ]; then
    HAS_AGENT_ARG=false
    SKIP_NEXT=false
    for arg in "$@"; do
        if [ "${SKIP_NEXT}" = true ]; then
            SKIP_NEXT=false
            continue
        fi

        case "${arg}" in
            --debug-port)
                SKIP_NEXT=true
                ;;
            -*)
                ;;
            *)
                HAS_AGENT_ARG=true
                ;;
        esac
    done

    if [ "${HAS_AGENT_ARG}" = true ]; then
        HYDROS_AGENT_START_ARGS="$*"
    else
        HYDROS_AGENT_START_ARGS="$* ${DEFAULT_AGENT_START_ARGS}"
    fi
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
POWER_DIR="${REPO_ROOT}/custom-agent/power"

echo "Building ${IMAGE_NAME}:${VERSION} with base image ${BASE_IMAGE}"
echo "Deploy environment: ${DEPLOY_ENV}"
echo "Docker host: ${DOCKER_HOST}"
echo "Hydros cluster: ${HYDROS_CLUSTER_ID}"
echo "MQTT broker: ${MQTT_BROKER_URL}:${MQTT_BROKER_PORT}"
echo "Container start args: ${HYDROS_AGENT_START_ARGS}"
echo "Control API port mapping: ${PORT}:${HYDROS_CONTROL_ALGORITHM_PORT}"
if [ -n "${DEBUG_PORT}" ]; then
    echo "Debug port: ${DEBUG_PORT}"
fi
docker build \
    -f "${POWER_DIR}/Dockerfile" \
    --build-arg BASE_IMAGE="${BASE_IMAGE}" \
    -t "${IMAGE_NAME}:${VERSION}" \
    "${REPO_ROOT}"

if ! docker run --rm --entrypoint /bin/bash "${IMAGE_NAME}:${VERSION}" -c \
    'test -s /opt/hydros/custom-agent/power/scheduling/power_scheduling_agent.py && grep -q '\''POWER_SCHEDULING_RUNTIME_REVISION = "2026-08-24-central-outflow-planning-v11"'\'' /opt/hydros/custom-agent/power/scheduling/power_scheduling_agent.py && test -s /opt/hydros/custom-agent/power/data/time_series_power_planning.json && test -s /opt/hydros/custom-agent/power/data/mpc_config.yaml && test -s /opt/hydros/custom-agent/power/data/initial_states.yaml && test -s /opt/hydros/custom-agent/power/data/constrains_targets.yaml'; then
    echo "Built image is missing required sources, bundled HydroSim inputs, or the expected power scheduling runtime revision; deployment aborted." >&2
    exit 1
fi

docker tag "${IMAGE_NAME}:${VERSION}" "${IMAGE_NAME}:latest"

docker rm -f "${CONTAINER_NAME}" || true
docker volume create "${LOG_VOLUME}" >/dev/null

PORT_ARGS=(-p "${PORT}:${HYDROS_CONTROL_ALGORITHM_PORT}")
if [ -n "${DEBUG_PORT}" ] && [ "${DEBUG_PORT}" != "${PORT}" ]; then
    PORT_ARGS+=(-p "${DEBUG_PORT}:${DEBUG_PORT}")
fi

if ! CONTAINER_ID="$(
    docker run -d \
        "${PORT_ARGS[@]}" \
        --name "${CONTAINER_NAME}" \
        --restart=always \
        --label "hydros.deploy.environment=${DEPLOY_ENV}" \
        --label "hydros.deploy.cluster=${HYDROS_CLUSTER_ID}" \
        --label "hydros.deploy.script=docker-deploy-power.sh" \
        -e HYDROS_NODE_ID="${HYDROS_NODE_ID}" \
        -e HYDROS_CLUSTER_ID="${HYDROS_CLUSTER_ID}" \
        -e MQTT_BROKER_URL="${MQTT_BROKER_URL}" \
        -e MQTT_BROKER_PORT="${MQTT_BROKER_PORT}" \
        -e MQTT_TOPIC="${MQTT_TOPIC}" \
        -e MQTT_USERNAME="${MQTT_USERNAME}" \
        -e MQTT_PASSWORD="${MQTT_PASSWORD}" \
        -e HYDROS_AGENT_START_ARGS="${HYDROS_AGENT_START_ARGS}" \
        -e HYDROS_CONTROL_ALGORITHM_HOST="${HYDROS_CONTROL_ALGORITHM_HOST}" \
        -e HYDROS_CONTROL_ALGORITHM_PORT="${HYDROS_CONTROL_ALGORITHM_PORT}" \
        -v "${LOG_VOLUME}:/opt/hydros/custom-agent/power/logs" \
        "${IMAGE_NAME}:${VERSION}" \
        bash ./start_agents.sh
)"; then
    echo "Failed to start ${CONTAINER_NAME}; removing the failed container." >&2
    docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
    exit 1
fi

if [ "$(docker inspect --format '{{.State.Running}}' "${CONTAINER_NAME}")" != "true" ]; then
    echo "Container ${CONTAINER_NAME} was created but is not running." >&2
    docker logs --tail 100 "${CONTAINER_NAME}" >&2 || true
    exit 1
fi

echo "Deployed container ${CONTAINER_NAME} (${CONTAINER_ID}) to ${DEPLOY_ENV}."
