#!/bin/bash
# Hydros Agent 启动脚本 - 在单个进程中运行多个 agents

set -e

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 获取脚本所在目录
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

# 设置 PYTHONPATH
export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH}"

# 优先使用项目虚拟环境，避免系统 Python 缺少 SDK 依赖
PYTHON_EXEC="${PROJECT_ROOT}/.venv/bin/python"
if [ ! -x "$PYTHON_EXEC" ]; then
    PYTHON_EXEC="python3"
fi

PUMP_FLOW_DMPC_SERVICE_PID=""
AGENT_LAUNCHER_PID=""

stop_child_processes() {
    local pid
    for pid in "$AGENT_LAUNCHER_PID" "$PUMP_FLOW_DMPC_SERVICE_PID"; do
        if [ -n "$pid" ]; then
            kill "$pid" >/dev/null 2>&1 || true
        fi
    done
    for pid in "$AGENT_LAUNCHER_PID" "$PUMP_FLOW_DMPC_SERVICE_PID"; do
        if [ -n "$pid" ]; then
            wait "$pid" >/dev/null 2>&1 || true
        fi
    done
}

start_pump_flow_dmpc_service() {
    if [ -z "${PUMP_FLOW_DMPC_MODEL_CONFIG:-}" ]; then
        echo -e "${YELLOW}未配置 PUMP_FLOW_DMPC_MODEL_CONFIG，不启动泵站流量 DMPC HTTP 服务${NC}"
        return
    fi

    local service_port="${PUMP_FLOW_DMPC_PORT:-8015}"
    echo -e "${GREEN}启动泵站流量 DMPC HTTP 服务: 0.0.0.0:${service_port}${NC}"
    "$PYTHON_EXEC" "${SCRIPT_DIR}/pump_flow_dmpc_service.py" \
        --model-config "${PUMP_FLOW_DMPC_MODEL_CONFIG}" \
        --host 0.0.0.0 \
        --port "${service_port}" &
    PUMP_FLOW_DMPC_SERVICE_PID=$!
}

# 显示帮助信息
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
    echo "  --enable-system-central-scheduling-agent"
    echo "                      显式注册 SDK 内置 CENTRAL_SCHEDULING_AGENT"
    echo "  --full-log          使用完整日志格式（生产环境），默认使用简化格式"
    echo ""
    echo "可用的 agent:"
    echo "  使用 $0 --list 查看当前目录自动发现的真实 agent 列表"
    echo ""
    echo "示例:"
    echo "  $0 outflowplan               # 启动出流计划智能体"
    echo "  $0 outflowplan scheduling    # 在同一进程中启动多个 agents"
    echo "  $0 --all                    # 启动所有 agents"
    echo "  $0 --logs                   # 查看日志"
    echo "  $0 --debug outflowplan       # 启用调试模式启动出流计划智能体"
    echo "  $0 -d outflowplan scheduling # 启用调试模式启动多个 agents"
    echo "  $0 --enable-system-central-scheduling-agent outflowplan scheduling"
    echo "                               # 注册 SDK 内置中央调度，并启动默认泵站 agents"
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
    echo "  • 配置 PUMP_FLOW_DMPC_MODEL_CONFIG 后，同时启动 8015 端口的边缘分配 HTTP 服务"
    echo "  • 边缘分配接口: POST /engine/v1/api/control-algorithms/{algorithm_type}/solve"
    echo "  • 前台运行，可以在控制台看到日志"
    echo "  • 所有日志保存到 custom-agent/logs/hydros.log"
    echo "  • 使用 Ctrl+C 优雅停止所有 agents"
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

# 查看日志
view_logs() {
    echo -e "${GREEN}日志文件:${NC}"
    echo ""

    if [ -f "${SCRIPT_DIR}/logs/hydros.log" ]; then
        echo "  ${SCRIPT_DIR}/logs/hydros.log"
        echo ""
        echo "查看日志命令:"
        echo "  tail -f ${SCRIPT_DIR}/logs/hydros.log"
        echo "  tail -100 ${SCRIPT_DIR}/logs/hydros.log"
        echo ""
        echo "过滤特定 agent 的日志:"
        echo "  grep 'TWINS_SIMULATION_AGENT' ${SCRIPT_DIR}/logs/hydros.log"
        echo "  grep 'ONTOLOGY_SIMULATION_AGENT' ${SCRIPT_DIR}/logs/hydros.log"
        echo ""

        # 显示最后几行日志
        if [ -s "${SCRIPT_DIR}/logs/hydros.log" ]; then
            echo "最近的日志:"
            tail -10 "${SCRIPT_DIR}/logs/hydros.log" | sed 's/^/  /'
        fi
    else
        echo "  (日志文件不存在)"
    fi

    echo ""
}

# 主函数
main() {
    if [ $# -eq 0 ] && [ -n "${HYDROS_AGENT_START_ARGS:-${START_ARGS:-}}" ]; then
        DEFAULT_START_ARGS="${HYDROS_AGENT_START_ARGS:-${START_ARGS:-}}"
        read -r -a DEFAULT_ARGS <<< "$DEFAULT_START_ARGS"
        set -- "${DEFAULT_ARGS[@]}"
    fi

    # 解析参数
    if [ $# -eq 0 ]; then
        show_help
        exit 0
    fi

    # 收集 Python 参数
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
    fi

    if [ "$SKIP_CONFIG_CHECK" != "1" ]; then
        echo -e "${GREEN}启动 Hydros Agents...${NC}"
        echo ""
    fi

    start_pump_flow_dmpc_service

    "$PYTHON_EXEC" -m hydros_agent_sdk.launcher \
        --launcher-dir "${SCRIPT_DIR}" \
        --project-root "${PROJECT_ROOT}" \
        -- "${PYTHON_ARGS[@]}" &
    AGENT_LAUNCHER_PID=$!

    trap 'stop_child_processes; exit 0' INT TERM
    trap stop_child_processes EXIT

    if [ -n "$PUMP_FLOW_DMPC_SERVICE_PID" ]; then
        wait -n "$AGENT_LAUNCHER_PID" "$PUMP_FLOW_DMPC_SERVICE_PID"
    else
        wait "$AGENT_LAUNCHER_PID"
    fi
}

# 运行主函数
main "$@"
