#!/usr/bin/env bash
set -euo pipefail

DEPLOY_ENV="${DEPLOY_ENV:-}"

if [ "$#" -gt 0 ]; then
    case "$1" in
        prod|production)
            DEPLOY_ENV="production"
            shift
            ;;
        stag|staging)
            DEPLOY_ENV="staging"
            shift
            ;;
        test|testing)
            DEPLOY_ENV="testing"
            shift
            ;;
    esac
fi

case "${DEPLOY_ENV}" in
    production)
        DEFAULT_DEPLOY_HOST="192.168.20.52"
        DEFAULT_HYDROS_CLUSTER_ID="hydros-cluster-production"
        DEFAULT_MQTT_BROKER_URL="tcp://mqtt.production.hydros.yuma.intra"
        ;;
    staging)
        DEFAULT_DEPLOY_HOST="192.168.20.51"
        DEFAULT_HYDROS_CLUSTER_ID="hydros-cluster-staging"
        DEFAULT_MQTT_BROKER_URL="tcp://192.168.50.112"
        ;;
    testing)
        DEFAULT_DEPLOY_HOST="192.168.20.51"
        DEFAULT_HYDROS_CLUSTER_ID="hydros-cluster-testing"
        DEFAULT_MQTT_BROKER_URL="tcp://mqtt.testing.hydros.yuma.intra"
        ;;
    "")
        DEFAULT_DEPLOY_HOST="192.168.20.52"
        DEFAULT_HYDROS_CLUSTER_ID="hydros-cluster-staging"
        DEFAULT_MQTT_BROKER_URL="tcp://hydros-mqtt-broker-internal.hydros.svc.cluster.local"
        ;;
    *)
        echo "Unsupported deploy environment: ${DEPLOY_ENV}" >&2
        echo "Usage: $0 [prod|stag|test] [start_agents_args...]" >&2
        exit 1
        ;;
esac

DEPLOY_HOST="${DEPLOY_HOST:-${DEFAULT_DEPLOY_HOST}}"
DEPLOY_DOCKER_PORT="${DEPLOY_DOCKER_PORT:-2375}"
export DOCKER_HOST="${DOCKER_HOST:-tcp://${DEPLOY_HOST}:${DEPLOY_DOCKER_PORT}}"
VERSION="${VERSION:-v1.0.0}"

BASE_IMAGE="${BASE_IMAGE:-python:3.11-slim}"
IMAGE_NAME="${IMAGE_NAME:-hydros-power-agent}"
CONTAINER_NAME="${CONTAINER_NAME:-hydros-power-agent}"
HYDROS_NODE_ID="${HYDROS_NODE_ID:-}"
HYDROS_CLUSTER_ID="${HYDROS_CLUSTER_ID:-${DEFAULT_HYDROS_CLUSTER_ID}}"
MQTT_BROKER_URL="${MQTT_BROKER_URL:-${DEFAULT_MQTT_BROKER_URL}}"
MQTT_BROKER_PORT="${MQTT_BROKER_PORT:-1883}"
MQTT_TOPIC="${MQTT_TOPIC:-}"
MQTT_USERNAME="${MQTT_USERNAME:-hydros_agent_user}"
MQTT_PASSWORD="${MQTT_PASSWORD:-HbGcDx125a}"
DEFAULT_AGENT_START_ARGS="${HYDROS_AGENT_START_ARGS:-${START_ARGS:-outflowplan scheduling}}"
HYDROS_AGENT_START_ARGS="${DEFAULT_AGENT_START_ARGS}"
PORT="${PORT:-8025}"
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
if [ -n "${DEPLOY_ENV}" ]; then
    echo "Deploy environment: ${DEPLOY_ENV}"
fi
echo "Docker host: ${DOCKER_HOST}"
echo "Hydros cluster: ${HYDROS_CLUSTER_ID}"
echo "MQTT broker: ${MQTT_BROKER_URL}:${MQTT_BROKER_PORT}"
echo "Container start args: ${HYDROS_AGENT_START_ARGS}"
if [ -n "${DEBUG_PORT}" ]; then
    echo "Debug port: ${DEBUG_PORT}"
fi
docker build \
    -f "${POWER_DIR}/Dockerfile" \
    --build-arg BASE_IMAGE="${BASE_IMAGE}" \
    -t "${IMAGE_NAME}:${VERSION}" \
    "${REPO_ROOT}"

docker tag "${IMAGE_NAME}:${VERSION}" "${IMAGE_NAME}:latest"

docker rm -f "${CONTAINER_NAME}" || true
docker volume create "${LOG_VOLUME}" >/dev/null

PORT_ARGS=(-p "${PORT}:${PORT}")
if [ -n "${DEBUG_PORT}" ] && [ "${DEBUG_PORT}" != "${PORT}" ]; then
    PORT_ARGS+=(-p "${DEBUG_PORT}:${DEBUG_PORT}")
fi

docker run -d \
    "${PORT_ARGS[@]}" \
    --name "${CONTAINER_NAME}" \
    --restart=always \
    -e HYDROS_NODE_ID="${HYDROS_NODE_ID}" \
    -e HYDROS_CLUSTER_ID="${HYDROS_CLUSTER_ID}" \
    -e MQTT_BROKER_URL="${MQTT_BROKER_URL}" \
    -e MQTT_BROKER_PORT="${MQTT_BROKER_PORT}" \
    -e MQTT_TOPIC="${MQTT_TOPIC}" \
    -e MQTT_USERNAME="${MQTT_USERNAME}" \
    -e MQTT_PASSWORD="${MQTT_PASSWORD}" \
    -e HYDROS_AGENT_START_ARGS="${HYDROS_AGENT_START_ARGS}" \
    -v "${LOG_VOLUME}:/opt/hydros/custom-agent/power/logs" \
    "${IMAGE_NAME}:${VERSION}" \
    bash ./start_agents.sh
