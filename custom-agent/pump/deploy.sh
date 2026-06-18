#!/usr/bin/env bash
set -euo pipefail

APP_NAME="hydros-pump-agent"
CONTAINER_NAME="hydros-pump-agent"
APP_PORT=8015
CONTAINER_PORT=8015
DEFAULT_TARGET_PORT="2375"
BASE_IMAGE="${BASE_IMAGE:-python:3.11-slim}"
APT_MIRROR="https://mirrors.aliyun.com"
TARGET_PLATFORM="${TARGET_PLATFORM:-linux/amd64}"
DEFAULT_AGENT_START_ARGS="outflowplan scheduling"

MODE=""
CUSTOM_TAG=""
LOCAL_IMAGE_NAME=""
TARGET_HOST=""
TARGET_PORT=""
SKIP_BUILD=false
DEBUG_PORT=""
LOG_VOLUME="${CONTAINER_NAME}-logs"
HYDROS_AGENT_START_ARGS="${HYDROS_AGENT_START_ARGS:-${START_ARGS:-${DEFAULT_AGENT_START_ARGS}}}"
RUNTIME_ENV_OVERRIDES=()

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

log_header() {
    echo -e "\n${CYAN}${BOLD}================================================================================${NC}"
    echo -e "${CYAN}${BOLD}  $1${NC}"
    echo -e "${CYAN}${BOLD}================================================================================${NC}"
}

log_step() {
    echo -e "\n${BLUE}${BOLD}[STEP $1]${NC} ${BLUE}$2${NC}"
}

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

check_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        log_error "命令 '$1' 未安装"
        exit 1
    fi
}

show_usage() {
    local exit_code="${1:-0}"
    cat <<USAGE
${APP_NAME} Python 部署脚本

用法:
  $0 deploy --target-host <host> [选项] [agent...]
  $0 build-image --tag <version>

部署选项:
  --tag <tag>          指定镜像 tag；未指定时默认使用 v1.0.0
  --target-host <host> 目标 Docker 主机，deploy 模式必填
  --target-port <port> 目标 Docker API 端口，默认: ${DEFAULT_TARGET_PORT}
  --skip-build         跳过 Docker 构建，直接复用指定 tag 镜像
  --port <port>        覆盖宿主机映射端口，默认: ${APP_PORT}
  --debug-port <port>  额外暴露调试端口
  --log-volume <name>  覆盖日志 volume，默认: ${LOG_VOLUME}
  --start-args <args>  覆盖容器启动 agent 参数，默认: ${DEFAULT_AGENT_START_ARGS}
  KEY=VALUE            追加传入容器的环境变量

示例:
  $0 deploy --target-host 192.168.20.51 --target-port 2375
  $0 deploy --target-host 192.168.20.51 --target-port 2375 --tag v1.0.1 outflowplan scheduling
  $0 deploy --target-host 192.168.20.51 --target-port 2375 MQTT_BROKER_URL=192.168.20.10
  $0 build-image --tag v1.0.1
USAGE
    exit "${exit_code}"
}

validate_positive_int() {
    local name="$1"
    local value="$2"
    if ! [[ "${value}" =~ ^[1-9][0-9]*$ ]]; then
        log_error "${name} 必须是正整数，当前值: ${value}"
        exit 1
    fi
}

add_runtime_env_override() {
    local assignment="$1"
    local key="${assignment%%=*}"

    if ! [[ "${key}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
        log_error "环境变量名非法: ${key}"
        exit 1
    fi

    RUNTIME_ENV_OVERRIDES+=("${assignment}")
}

append_agent_arg() {
    if [ "${HYDROS_AGENT_START_ARGS}" = "${DEFAULT_AGENT_START_ARGS}" ]; then
        HYDROS_AGENT_START_ARGS="$1"
    else
        HYDROS_AGENT_START_ARGS="${HYDROS_AGENT_START_ARGS} $1"
    fi
}

parse_arguments() {
    if [ $# -eq 0 ]; then
        show_usage
    fi

    MODE="$1"
    shift

    case "${MODE}" in
        deploy|build-image)
            ;;
        -h|--help)
            show_usage 0
            ;;
        *)
            log_error "未知命令: ${MODE}"
            show_usage 1
            ;;
    esac

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --tag)
                [ $# -ge 2 ] || { log_error "--tag 需要一个参数"; exit 1; }
                CUSTOM_TAG="$2"
                shift 2
                ;;
            --target-host)
                [ $# -ge 2 ] || { log_error "--target-host 需要一个参数"; exit 1; }
                TARGET_HOST="$2"
                shift 2
                ;;
            --target-port)
                [ $# -ge 2 ] || { log_error "--target-port 需要一个参数"; exit 1; }
                validate_positive_int "--target-port" "$2"
                TARGET_PORT="$2"
                shift 2
                ;;
            --skip-build)
                SKIP_BUILD=true
                shift
                ;;
            --port)
                [ $# -ge 2 ] || { log_error "--port 需要一个参数"; exit 1; }
                validate_positive_int "--port" "$2"
                APP_PORT="$2"
                shift 2
                ;;
            --debug-port)
                [ $# -ge 2 ] || { log_error "--debug-port 需要一个参数"; exit 1; }
                validate_positive_int "--debug-port" "$2"
                DEBUG_PORT="$2"
                shift 2
                ;;
            --log-volume)
                [ $# -ge 2 ] || { log_error "--log-volume 需要一个参数"; exit 1; }
                LOG_VOLUME="$2"
                shift 2
                ;;
            --start-args)
                [ $# -ge 2 ] || { log_error "--start-args 需要一个参数"; exit 1; }
                HYDROS_AGENT_START_ARGS="$2"
                shift 2
                ;;
            -h|--help)
                show_usage 0
                ;;
            *)
                if [[ "$1" == *=* ]]; then
                    add_runtime_env_override "$1"
                    shift
                elif [[ "$1" == -* ]]; then
                    log_error "未知参数: $1"
                    show_usage 1
                else
                    append_agent_arg "$1"
                    shift
                fi
                ;;
        esac
    done
}

resolve_paths() {
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
    PUMP_DIR="${REPO_ROOT}/custom-agent/pump"
}

resolve_image_names() {
    if [ -z "${CUSTOM_TAG}" ]; then
        CUSTOM_TAG="v1.0.0"
    fi

    LOCAL_IMAGE_NAME="${APP_NAME}:${CUSTOM_TAG}"
}

setup_environment() {
    if [ "${MODE}" = "deploy" ] && [ -z "${TARGET_HOST}" ]; then
        log_error "deploy 模式必须指定 --target-host <host>"
        exit 1
    fi

    TARGET_PORT="${TARGET_PORT:-${DEFAULT_TARGET_PORT}}"
    export DOCKER_HOST="tcp://${TARGET_HOST}:${TARGET_PORT}"

    log_info "Docker主机: ${TARGET_HOST}:${TARGET_PORT}"
    log_info "Docker Host: ${DOCKER_HOST}"
}

build_image() {
    log_step 1 "Docker 镜像构建"
    check_command docker
    resolve_paths
    resolve_image_names

    if [ "${SKIP_BUILD}" = true ]; then
        log_warning "已跳过 Docker 构建，复用镜像: ${LOCAL_IMAGE_NAME}"
        return
    fi

    log_info "构建镜像: ${LOCAL_IMAGE_NAME}"
    log_info "基础镜像: ${BASE_IMAGE}"
    log_info "APT 源: ${APT_MIRROR}"
    log_info "目标平台: ${TARGET_PLATFORM}"
    docker build \
        --platform "${TARGET_PLATFORM}" \
        -f "${PUMP_DIR}/Dockerfile" \
        --build-arg BASE_IMAGE="${BASE_IMAGE}" \
        --build-arg APT_MIRROR="${APT_MIRROR}" \
        -t "${LOCAL_IMAGE_NAME}" \
        "${REPO_ROOT}"

    docker tag "${LOCAL_IMAGE_NAME}" "${APP_NAME}:latest"
    log_success "镜像构建成功"
}

cleanup_container() {
    log_step 2 "清理旧容器"

    if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        log_info "停止并删除旧容器: ${CONTAINER_NAME}"
        docker stop "${CONTAINER_NAME}" >/dev/null 2>&1 || true
        docker rm "${CONTAINER_NAME}" >/dev/null 2>&1 || true
        log_success "旧容器已清理"
    else
        log_info "无运行中的旧容器"
    fi
}

add_default_runtime_env() {
    RUNTIME_ENV_OVERRIDES+=("HYDROS_AGENT_START_ARGS=${HYDROS_AGENT_START_ARGS}")

    local name
    for name in HYDROS_NODE_ID HYDROS_CLUSTER_ID MQTT_BROKER_URL MQTT_BROKER_PORT MQTT_TOPIC MQTT_USERNAME MQTT_PASSWORD; do
        if [ -n "${!name:-}" ]; then
            RUNTIME_ENV_OVERRIDES+=("${name}=${!name}")
        fi
    done
}

build_run_args() {
    RUN_ARGS=(
        -d
        -p "${APP_PORT}:${CONTAINER_PORT}"
        --name "${CONTAINER_NAME}"
        --restart=always
        -e TZ=Asia/Shanghai
    )

    if [ -n "${DEBUG_PORT}" ] && [ "${DEBUG_PORT}" != "${APP_PORT}" ]; then
        RUN_ARGS+=(-p "${DEBUG_PORT}:${DEBUG_PORT}")
    fi

    local item
    for item in "${RUNTIME_ENV_OVERRIDES[@]}"; do
        RUN_ARGS+=(-e "${item}")
    done

    RUN_ARGS+=(
        -v "${LOG_VOLUME}:/opt/hydros/custom-agent/pump/logs"
        "${LOCAL_IMAGE_NAME}"
        bash
        ./start_agents.sh
    )
}

start_container() {
    log_step 3 "启动新容器"
    resolve_image_names
    add_default_runtime_env
    build_run_args

    docker volume create "${LOG_VOLUME}" >/dev/null

    log_info "容器启动参数: ${HYDROS_AGENT_START_ARGS}"
    log_info "端口映射: ${APP_PORT}:${CONTAINER_PORT}"
    if [ -n "${DEBUG_PORT}" ]; then
        log_info "调试端口: ${DEBUG_PORT}:${DEBUG_PORT}"
    fi
    log_info "执行: docker run -p ${APP_PORT}:${CONTAINER_PORT} --name ${CONTAINER_NAME} ..."
    docker run "${RUN_ARGS[@]}" >/dev/null
    log_success "容器启动指令已下发"
}

show_deploy_summary() {
    log_header "部署完成"
    echo "  应用: ${APP_NAME}"
    echo "  Docker主机: ${TARGET_HOST}:${TARGET_PORT}"
    echo "  镜像: ${LOCAL_IMAGE_NAME}"
    echo "  容器: ${CONTAINER_NAME}"
    echo "  端口: ${APP_PORT}:${CONTAINER_PORT}"
    echo "  时间: $(date '+%Y-%m-%d %H:%M:%S')"
}

show_build_summary() {
    log_header "构建完成"
    echo "  本地镜像: ${LOCAL_IMAGE_NAME}"
    echo "  时间: $(date '+%Y-%m-%d %H:%M:%S')"
}

run_deploy() {
    log_header "${APP_NAME} Python 部署系统"
    check_command docker
    setup_environment
    build_image
    cleanup_container
    start_container
    show_deploy_summary
}

run_build_image() {
    log_header "${APP_NAME} 镜像构建"
    build_image
    show_build_summary
}

main() {
    parse_arguments "$@"

    case "${MODE}" in
        deploy)
            run_deploy
            ;;
        build-image)
            run_build_image
            ;;
    esac
}

main "$@"
