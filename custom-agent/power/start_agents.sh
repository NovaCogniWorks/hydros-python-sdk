#!/bin/bash
# Hydros Agent 启动脚本 - 在单个进程中运行多个 agents

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH}"

PYTHON_EXEC="${PROJECT_ROOT}/.venv/bin/python"
if [ ! -x "$PYTHON_EXEC" ]; then
    PYTHON_EXEC="python3"
fi

CONTROL_SERVICE_PID=""
CONTROL_SERVICE_LOG="${SCRIPT_DIR}/logs/power-control-algorithm-service.log"
CONTROL_SERVICE_SCRIPT="${SCRIPT_DIR}/control_algorithm_service.py"

show_help() {
    echo -e "${GREEN}Hydros Agent 启动脚本${NC}"
    echo ""
    echo "用法: $0 [选项] [agent1] [agent2] ..."
    echo ""
    echo "选项:"
    echo "  -h, --help          显示帮助信息"
    echo "  -l, --list          列出所有可用的 agent"
    echo "  --check, --doctor   检查配置和 agent 加载，不连接 MQTT"
    echo "  -a, --all           启动所有 agent"
    echo "  -L, --logs          查看日志"
    echo "  -d, --debug         启用远程调试模式 (debugpy)"
    echo "  --debug-port PORT   指定调试端口 (默认: 5678)"
    echo "  --debug-nowait      不等待调试器连接，直接启动"
    echo "  --full-log          使用完整日志格式（生产环境），默认使用简化格式"
    echo ""
    echo "可用的 agent:"
    echo "  使用 $0 --list 查看当前目录自动发现的真实 agent 列表"
    echo ""
    echo "示例:"
    echo "  $0 outflowplan               # 启动 power outflow plan agent"
    echo "  $0 outflowplan scheduling    # 在同一进程中启动多个 agents"
    echo "  $0 --all                    # 启动所有 agents"
    echo "  $0 --logs                   # 查看日志"
    echo "  $0 --debug outflowplan       # 启用调试模式启动 power outflow plan agent"
    echo "  $0 -d outflowplan pump       # 启用调试模式启动多个 agents"
    echo "  $0 --debug --debug-nowait outflowplan  # 调试模式但不等待调试器"
    echo ""
    echo "调试模式:"
    echo "  • 使用 debugpy 进行远程调试"
    echo "  • 默认监听端口: 5678"
    echo "  • 支持 VS Code、PyCharm 等 IDE"
    echo "  • 可以设置断点、单步调试、查看变量等"
    echo "  • 需要先安装: pip install debugpy"
    echo ""
    echo "特性:"
    echo "  • 所有 agents 在同一个进程中运行"
    echo "  • 默认同时启动电站边缘控制 API 服务"
    echo "  • 前台运行，可以在控制台看到日志"
    echo "  • 所有日志保存到 custom-agent/power/logs/"
    echo "  • 使用 Ctrl+C 优雅停止所有 agents 和控制 API 服务"
    echo ""
}

# 检查配置文件
check_config() {
    if [ ! -f "${SCRIPT_DIR}/env.properties" ]; then
        echo -e "${YELLOW}警告: 共享配置文件不存在${NC}"
        echo -e "${YELLOW}请创建 ${SCRIPT_DIR}/env.properties 并填入实际的 MQTT broker、cluster 和 node 信息${NC}"
        echo ""
        return 1
    fi
    return 0
}

apply_environment_override() {
    local environment_name="$1"
    local property_name="$2"
    local value="${!environment_name:-}"

    if [ -z "${value}" ]; then
        return 0
    fi

    local escaped_value
    escaped_value="$(printf '%s' "${value}" | sed 's/[&|\\]/\\&/g')"

    if grep -q "^${property_name}=" "${SCRIPT_DIR}/env.properties"; then
        sed -i "s|^${property_name}=.*$|${property_name}=${escaped_value}|" "${SCRIPT_DIR}/env.properties"
    else
        printf '\n%s=%s\n' "${property_name}" "${value}" >> "${SCRIPT_DIR}/env.properties"
    fi
}

apply_environment_overrides() {
    apply_environment_override "MQTT_BROKER_URL" "mqtt_broker_url"
    apply_environment_override "MQTT_BROKER_PORT" "mqtt_broker_port"
    apply_environment_override "MQTT_TOPIC" "mqtt_topic"
    apply_environment_override "MQTT_USERNAME" "mqtt_username"
    apply_environment_override "MQTT_PASSWORD" "mqtt_password"
    apply_environment_override "HYDROS_CLUSTER_ID" "hydros_cluster_id"
    apply_environment_override "HYDROS_NODE_ID" "hydros_node_id"
}

view_logs() {
    echo -e "${GREEN}日志文件:${NC}"
    echo ""

    if [ -f "${SCRIPT_DIR}/logs/hydros.log" ]; then
        echo "  ${SCRIPT_DIR}/logs/hydros.log"
    else
        echo "  (hydros.log 不存在)"
    fi

    if [ -f "${CONTROL_SERVICE_LOG}" ]; then
        echo "  ${CONTROL_SERVICE_LOG}"
    else
        echo "  (power-control-algorithm-service.log 不存在)"
    fi

    echo ""
}

cleanup_control_service() {
    if [ -n "${CONTROL_SERVICE_PID}" ] && kill -0 "${CONTROL_SERVICE_PID}" 2>/dev/null; then
        echo -e "${BLUE}Stopping power control algorithm service (PID: ${CONTROL_SERVICE_PID})...${NC}"
        kill "${CONTROL_SERVICE_PID}" 2>/dev/null || true
        wait "${CONTROL_SERVICE_PID}" 2>/dev/null || true
    fi
}

start_control_algorithm_service() {
    mkdir -p "${SCRIPT_DIR}/logs"

    if [ ! -f "${CONTROL_SERVICE_SCRIPT}" ]; then
        echo -e "${RED}错误: 找不到电站边缘控制服务脚本${NC}"
        echo -e "${RED}路径: ${CONTROL_SERVICE_SCRIPT}${NC}"
        return 1
    fi

    echo -e "${GREEN}启动电站边缘控制 API 服务...${NC}"
    echo -e "${BLUE}  Log file: ${CONTROL_SERVICE_LOG}${NC}"

    "${PYTHON_EXEC}" "${CONTROL_SERVICE_SCRIPT}" >> "${CONTROL_SERVICE_LOG}" 2>&1 &
    CONTROL_SERVICE_PID=$!

    sleep 1
    if ! kill -0 "${CONTROL_SERVICE_PID}" 2>/dev/null; then
        echo -e "${RED}错误: 电站边缘控制 API 服务启动失败${NC}"
        echo -e "${YELLOW}请检查日志: ${CONTROL_SERVICE_LOG}${NC}"
        return 1
    fi

    echo -e "${GREEN}✓ 电站边缘控制 API 服务已启动 (PID: ${CONTROL_SERVICE_PID})${NC}"
    echo ""
    return 0
}

main() {
    if [ $# -eq 0 ] && [ -n "${HYDROS_AGENT_START_ARGS:-${START_ARGS:-}}" ]; then
        DEFAULT_START_ARGS="${HYDROS_AGENT_START_ARGS:-${START_ARGS:-}}"
        read -r -a DEFAULT_ARGS <<< "$DEFAULT_START_ARGS"
        set -- "${DEFAULT_ARGS[@]}"
    fi

    if [ $# -eq 0 ]; then
        show_help
        exit 0
    fi

    PYTHON_ARGS=()
    SKIP_CONFIG_CHECK=0

    while [ $# -gt 0 ]; do
        case $1 in
            -h|--help)
                show_help
                exit 0
                ;;
            -l|--list)
                PYTHON_ARGS+=("--list")
                SKIP_CONFIG_CHECK=1
                shift
                ;;
            --check|--doctor)
                PYTHON_ARGS+=("$1")
                SKIP_CONFIG_CHECK=1
                shift
                ;;
            -L|--logs)
                view_logs
                exit 0
                ;;
            -a|--all)
                PYTHON_ARGS+=("--all")
                shift
                ;;
            -d|--debug)
                PYTHON_ARGS+=("--debug")
                shift
                ;;
            --debug-port)
                PYTHON_ARGS+=("--debug-port" "$2")
                shift 2
                ;;
            --debug-nowait)
                PYTHON_ARGS+=("--debug-nowait")
                shift
                ;;
            --full-log)
                PYTHON_ARGS+=("--full-log")
                shift
                ;;
            edge_control)
                echo -e "${YELLOW}警告: edge_control 不再作为 Agent 参数使用，已自动忽略；控制 API 服务会默认启动${NC}"
                shift
                ;;
            *)
                PYTHON_ARGS+=("$1")
                shift
                ;;
        esac
    done

    if [ "$SKIP_CONFIG_CHECK" != "1" ]; then
        if ! check_config; then
            exit 1
        fi
        apply_environment_overrides
        echo -e "${GREEN}启动 Hydros Agents...${NC}"
        echo ""
    fi

    trap cleanup_control_service EXIT INT TERM

    if [ "$SKIP_CONFIG_CHECK" != "1" ]; then
        if ! start_control_algorithm_service; then
            exit 1
        fi
    fi

    "${PYTHON_EXEC}" -m hydros_agent_sdk.launcher \
        --launcher-dir "${SCRIPT_DIR}" \
        --project-root "${PROJECT_ROOT}" \
        -- "${PYTHON_ARGS[@]}"
}

main "$@"
