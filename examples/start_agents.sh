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
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# 设置 PYTHONPATH
export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH}"

# 显示帮助信息
show_help() {
    echo -e "${GREEN}Hydros Agent 启动脚本${NC}"
    echo ""
    echo "用法: $0 [选项] [agent1] [agent2] ..."
    echo ""
    echo "选项:"
    echo "  -h, --help          显示帮助信息"
    echo "  -l, --list          列出所有可用的 agent"
    echo "  -a, --all           启动所有 agent"
    echo "  -L, --logs          查看日志"
    echo "  -d, --debug         启用远程调试模式 (debugpy)"
    echo "  --debug-port PORT   指定调试端口 (默认: 5678)"
    echo "  --debug-nowait      不等待调试器连接，直接启动"
    echo "  --full-log          使用完整日志格式（生产环境），默认使用简化格式"
    echo ""
    echo "可用的 agent:"
    echo "  twins               Twins Simulation Agent"
    echo "  ontology            Ontology Simulation Agent"
    echo "  lite                Lite Agent Example"
    echo ""
    echo "示例:"
    echo "  $0 twins                    # 启动 twins agent"
    echo "  $0 twins ontology           # 在同一进程中启动 twins 和 ontology agents"
    echo "  $0 --all                    # 启动所有 agents"
    echo "  $0 --logs                   # 查看日志"
    echo "  $0 --debug twins            # 启用调试模式启动 twins agent"
    echo "  $0 -d twins ontology        # 启用调试模式启动多个 agents"
    echo "  $0 --debug --debug-nowait twins  # 调试模式但不等待调试器"
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
    echo "  • 前台运行，可以在控制台看到日志"
    echo "  • 所有日志保存到 examples/logs/agent.log"
    echo "  • 使用 Ctrl+C 优雅停止所有 agents"
    echo ""
}

# 列出所有可用的 agent
list_agents() {
    echo -e "${GREEN}可用的 Agents:${NC}"
    echo ""

    if [ -f "${SCRIPT_DIR}/agents/twins/twins_agent.py" ]; then
        echo -e "  ${BLUE}twins${NC}      - Twins Simulation Agent"
        echo "                 路径: ${SCRIPT_DIR}/agents/twins/twins_agent.py"
    fi

    if [ -f "${SCRIPT_DIR}/agents/ontology/ontology_agent.py" ]; then
        echo -e "  ${BLUE}ontology${NC}   - Ontology Simulation Agent"
        echo "                 路径: ${SCRIPT_DIR}/agents/ontology/ontology_agent.py"
    fi

    if [ -f "${SCRIPT_DIR}/agents/lite/agent_example.py" ]; then
        echo -e "  ${BLUE}lite${NC}       - Lite Agent Example"
        echo "                 路径: ${SCRIPT_DIR}/agents/lite/agent_example.py"
    fi

    echo ""
}

# 检查配置文件
check_config() {
    if [ ! -f "${SCRIPT_DIR}/env.properties" ]; then
        echo -e "${YELLOW}警告: 共享配置文件不存在${NC}"
        echo -e "${YELLOW}正在从模板创建配置文件...${NC}"

        if [ -f "${SCRIPT_DIR}/env.properties.example" ]; then
            cp "${SCRIPT_DIR}/env.properties.example" "${SCRIPT_DIR}/env.properties"
            echo -e "${GREEN}✓ 配置文件已创建: ${SCRIPT_DIR}/env.properties${NC}"
            echo -e "${YELLOW}请编辑配置文件，填入实际的 MQTT broker 信息${NC}"
            echo ""
            return 1
        else
            echo -e "${RED}错误: 找不到配置模板文件${NC}"
            return 1
        fi
    fi
    return 0
}

# 查看日志
view_logs() {
    echo -e "${GREEN}日志文件:${NC}"
    echo ""

    if [ -f "${SCRIPT_DIR}/logs/agent.log" ]; then
        echo "  ${SCRIPT_DIR}/logs/agent.log"
        echo ""
        echo "查看日志命令:"
        echo "  tail -f ${SCRIPT_DIR}/logs/agent.log"
        echo "  tail -100 ${SCRIPT_DIR}/logs/agent.log"
        echo ""
        echo "过滤特定 agent 的日志:"
        echo "  grep 'TWINS_SIMULATION_AGENT' ${SCRIPT_DIR}/logs/agent.log"
        echo "  grep 'ONTOLOGY_SIMULATION_AGENT' ${SCRIPT_DIR}/logs/agent.log"
        echo ""

        # 显示最后几行日志
        if [ -s "${SCRIPT_DIR}/logs/agent.log" ]; then
            echo "最近的日志:"
            tail -10 "${SCRIPT_DIR}/logs/agent.log" | sed 's/^/  /'
        fi
    else
        echo "  (日志文件不存在)"
    fi

    echo ""
}

# 主函数
main() {
    # 解析参数
    if [ $# -eq 0 ]; then
        show_help
        exit 0
    fi

    # 收集 Python 参数
    PYTHON_ARGS=()

    while [ $# -gt 0 ]; do
        case $1 in
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

    # 检查配置
    if ! check_config; then
        exit 1
    fi

    # 使用 Python 启动器启动 agents
    echo -e "${GREEN}启动 Hydros Agents...${NC}"
    echo ""

    # 调用 Python 启动器
    python3 "${SCRIPT_DIR}/multi_agent_launcher.py" "${PYTHON_ARGS[@]}"
}

# 运行主函数
main "$@"
