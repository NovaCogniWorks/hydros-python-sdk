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

    # 使用 SDK 统一启动器启动 agents
    if [ "$SKIP_CONFIG_CHECK" != "1" ]; then
        echo -e "${GREEN}启动 Hydros Agents...${NC}"
        echo ""
    fi

    "$PYTHON_EXEC" -m hydros_agent_sdk.launcher \
        --launcher-dir "${SCRIPT_DIR}" \
        --project-root "${PROJECT_ROOT}" \
        -- "${PYTHON_ARGS[@]}"
}

# 运行主函数
main "$@"
