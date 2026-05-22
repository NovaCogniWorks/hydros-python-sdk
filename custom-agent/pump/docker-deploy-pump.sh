#!/usr/bin/env bash
set -euo pipefail

export DOCKER_HOST="${DOCKER_HOST:-tcp://prod.hydros.yuma.intra:2375}"
VERSION="${VERSION:-v1.0.0}"

BASE_IMAGE="${BASE_IMAGE:-python:3.11-slim}"
IMAGE_NAME="${IMAGE_NAME:-hydros-pump-agent}"
CONTAINER_NAME="${CONTAINER_NAME:-hydros-pump-agent}"
HYDROS_NODE_ID="${HYDROS_NODE_ID:-docker-edge}"
HYDROS_CLUSTER_ID="${HYDROS_CLUSTER_ID:-}"
MQTT_BROKER_URL="${MQTT_BROKER_URL:-}"
MQTT_BROKER_PORT="${MQTT_BROKER_PORT:-}"
MQTT_TOPIC="${MQTT_TOPIC:-}"
MQTT_USERNAME="${MQTT_USERNAME:-}"
MQTT_PASSWORD="${MQTT_PASSWORD:-}"
START_ARGS="${START_ARGS:-outflowplan scheduling}"
PORT="${PORT:-8015}"
LOG_VOLUME="${LOG_VOLUME:-${CONTAINER_NAME}-logs}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PUMP_DIR="${REPO_ROOT}/custom-agent/pump"

echo "Building ${IMAGE_NAME}:${VERSION} with base image ${BASE_IMAGE}"
docker build \
    -f "${PUMP_DIR}/Dockerfile" \
    --build-arg BASE_IMAGE="${BASE_IMAGE}" \
    -t "${IMAGE_NAME}:${VERSION}" \
    "${REPO_ROOT}"

docker tag "${IMAGE_NAME}:${VERSION}" "${IMAGE_NAME}:latest"

docker rm -f "${CONTAINER_NAME}" || true
docker volume create "${LOG_VOLUME}" >/dev/null

docker run -d \
    -p "${PORT}:${PORT}" \
    --name "${CONTAINER_NAME}" \
    --restart=always \
    -e HYDROS_NODE_ID="${HYDROS_NODE_ID}" \
    -e HYDROS_CLUSTER_ID="${HYDROS_CLUSTER_ID}" \
    -e MQTT_BROKER_URL="${MQTT_BROKER_URL}" \
    -e MQTT_BROKER_PORT="${MQTT_BROKER_PORT}" \
    -e MQTT_TOPIC="${MQTT_TOPIC}" \
    -e MQTT_USERNAME="${MQTT_USERNAME}" \
    -e MQTT_PASSWORD="${MQTT_PASSWORD}" \
    -v "${LOG_VOLUME}:/opt/hydros/custom-agent/pump/logs" \
    "${IMAGE_NAME}:${VERSION}" \
    bash ./start_agents.sh ${START_ARGS}
