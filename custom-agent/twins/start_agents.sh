#!/usr/bin/env bash
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "${SCRIPT_DIR}")"

export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH:-}"

show_help() {
    echo -e "${GREEN}Hydros Agent 启动脚本${NC}"
    echo ""
    echo "用法: $0 [选项] [agent1] [agent2] ..."
    echo ""
    echo "选项:"
    echo "  -h, --help          显示帮助信息"
    echo "  -l, --list          列出可用 agent"
    echo "  -L, --logs          查看日志位置"
    echo "  -a, --all           启动全部 agent"
    echo "  -d, --debug         启用 debug 模式"
    echo "  --debug-port PORT   指定 debug 端口"
    echo "  --debug-nowait      不等待调试器连接"
    echo "  --full-log          使用完整日志格式"
    echo ""
    echo "示例:"
    echo "  $0 twins"
    echo "  $0 twins ontology"
}

list_agents() {
    echo -e "${GREEN}可用 Agents:${NC}"
    echo ""
    [ -f "${SCRIPT_DIR}/twins_agent.py" ] && echo -e "  ${BLUE}twins${NC}      - Twins Simulation Agent"
}

check_config() {
    if [ ! -f "${SCRIPT_DIR}/env.properties" ]; then
        echo -e "${YELLOW}警告: 未找到 ${SCRIPT_DIR}/env.properties${NC}"
        return 1
    fi
    return 0
}

view_logs() {
    echo -e "${GREEN}日志目录:${NC}"
    echo "  ${SCRIPT_DIR}/logs"
}

main() {
    if [ $# -eq 0 ]; then
        show_help
        exit 0
    fi

    PYTHON_ARGS=()

    while [ $# -gt 0 ]; do
        case "$1" in
            -h|--help)
                show_help
                exit 0
                ;;
            -l|--list)
                list_agents
                exit 0
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

    if ! check_config; then
        exit 1
    fi

    echo -e "${GREEN}启动 Hydros Agents...${NC}"
    echo ""

    python3 "${SCRIPT_DIR}/multi_agent_launcher.py" "${PYTHON_ARGS[@]}"
}

main "$@"
