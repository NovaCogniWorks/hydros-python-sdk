"""
Hydros Python 智能体应用的可复用启动器支撑对象。
"""

from __future__ import annotations

import importlib.util
import inspect
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple, Type

from hydros_agent_sdk.base_agent import BaseHydroAgent
from hydros_agent_sdk.config_loader import load_env_config
from hydros_agent_sdk.coordination_client import SimCoordinationClient
from hydros_agent_sdk.developer_api import CustomAgent
from hydros_agent_sdk.factory import CustomAgentFactory, HydroAgentFactory
from hydros_agent_sdk.logging_config import setup_logging
from hydros_agent_sdk.agent_constants import (
    CENTRAL_SCHEDULING_AGENT_TYPE,
    SYSTEM_CENTRAL_SCHEDULING_AGENT_CODE,
)
from hydros_agent_sdk.multi_agent import MultiAgentCallback

logger = logging.getLogger(__name__)


class ManagedRuntimeService(Protocol):
    """与多智能体进程共享生命周期的应用服务。"""

    def start(self) -> None:
        """启动服务；失败时抛出异常并阻止 Agent runtime 启动。"""

    def stop(self) -> None:
        """停止服务并释放端口、线程等运行时资源。"""


@dataclass(frozen=True)
class AgentModuleInfo:
    """启动器发现到的智能体模块信息。"""

    name: str
    agent_class: Type
    script_dir: str
    agent_code: str
    agent_type: str
    agent_display_name: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "agent_class": self.agent_class,
            "script_dir": self.script_dir,
            "agent_code": self.agent_code,
            "agent_type": self.agent_type,
            "agent_display_name": self.agent_display_name,
        }


@dataclass(frozen=True)
class LauncherOptions:
    """命令行解析后的启动选项。"""

    agent_names: List[str]
    debug_enabled: bool = False
    debug_wait: bool = True
    debug_port: int = 5678
    enable_system_central_scheduling_agent: bool = False
    list_only: bool = False
    check_only: bool = False
    show_help: bool = False
    all_requested: bool = False


@dataclass(frozen=True)
class LauncherServices:
    """启动器启动过程需要的服务对象。"""

    discovery_service: "AgentDiscoveryService"
    module_loader: "AgentModuleLoader"


@dataclass(frozen=True)
class RegisteredAgentInfo:
    """已注册到 MultiAgentCallback 的智能体摘要。"""

    name: str
    agent_code: str
    agent_type: str
    agent_display_name: str
    agent_class: str
    directory: str

    @classmethod
    def from_module(cls, agent_info: AgentModuleInfo) -> "RegisteredAgentInfo":
        return cls(
            name=agent_info.name,
            agent_code=agent_info.agent_code,
            agent_type=agent_info.agent_type or agent_info.agent_code.replace("_demo001", ""),
            agent_display_name=agent_info.agent_display_name,
            agent_class=agent_info.agent_class.__name__,
            directory=os.path.basename(agent_info.script_dir),
        )

    @classmethod
    def system_default_central_scheduling(cls) -> "RegisteredAgentInfo":
        return cls(
            name="中央调度智能体",
            agent_code=SYSTEM_CENTRAL_SCHEDULING_AGENT_CODE,
            agent_type=CENTRAL_SCHEDULING_AGENT_TYPE,
            agent_display_name="中央调度智能体",
            agent_class="SystemCentralSchedulingAgent",
            directory="(sdk built-in)",
        )


class PropertiesFileLoader:
    """读取 Java 风格 .properties 文件。"""

    def load(self, properties_file: str) -> Dict[str, str]:
        properties: Dict[str, str] = {}

        if not os.path.exists(properties_file):
            raise FileNotFoundError(f"Properties file not found: {properties_file}")

        with open(properties_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    properties[key.strip()] = value.strip()

        return properties


class AgentDirectoryResolver:
    """解析 launcher 下的智能体根目录和别名。"""

    def __init__(self, launcher_dir: str, aliases: Optional[Dict[str, str]] = None):
        self.launcher_dir = launcher_dir
        self.aliases = aliases or {}

    def agents_root(self) -> str:
        agents_dir = os.path.join(self.launcher_dir, "agents")
        if os.path.exists(agents_dir) and os.path.isdir(agents_dir):
            return agents_dir
        return self.launcher_dir

    def normalize_agent_name(self, agent_name: str) -> str:
        return self.aliases.get(agent_name, agent_name)

    def resolve_agent_dir(self, agent_name: str) -> str:
        normalized_name = self.normalize_agent_name(agent_name)
        return os.path.join(self.agents_root(), normalized_name)


class AgentClassResolver:
    """从智能体目录中寻找组合式 CustomAgent 或旧式 BaseHydroAgent。"""

    def __init__(self):
        self.last_import_errors: List[str] = []

    def find_agent_class(self, agent_dir: str) -> Optional[Type]:
        self.last_import_errors = []
        py_files = [
            f for f in os.listdir(agent_dir)
            if f.endswith(".py") and not f.startswith("__") and not f.startswith("test_")
        ]

        if not py_files:
            logger.warning("No Python files found in %s", agent_dir)
            return None

        preferred = self._scan_classes(agent_dir, py_files, preferred_only=True)
        if preferred is not None:
            return preferred

        return self._scan_classes(agent_dir, py_files, preferred_only=False)

    def _scan_classes(
        self,
        agent_dir: str,
        py_files: List[str],
        preferred_only: bool,
    ) -> Optional[Type]:
        for py_file in py_files:
            module_name = py_file[:-3]
            try:
                module = self._load_module(module_name, os.path.join(agent_dir, py_file))
            except Exception as exc:
                import_error = f"{py_file}: {type(exc).__name__}: {exc}"
                if import_error not in self.last_import_errors:
                    self.last_import_errors.append(import_error)
                logger.debug("Failed to import %s: %s", py_file, exc)
                continue

            for name, obj in inspect.getmembers(module, inspect.isclass):
                if not self._is_agent_class(obj, module_name):
                    continue
                if preferred_only and any(marker in name for marker in ["With", "Test", "Demo"]):
                    continue
                logger.debug("Found agent class: %s in %s", name, py_file)
                return obj

        return None

    @staticmethod
    def _load_module(module_name: str, file_path: str):
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load module spec: {file_path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def _is_agent_class(obj, module_name: str) -> bool:
        if obj.__module__ != module_name:
            return False
        return (
            (obj != CustomAgent and issubclass(obj, CustomAgent))
            or (obj != BaseHydroAgent and issubclass(obj, BaseHydroAgent))
        )


class AgentDiscoveryService:
    """发现 launcher 可启动的智能体目录。"""

    def __init__(
        self,
        directory_resolver: AgentDirectoryResolver,
        properties_loader: PropertiesFileLoader,
    ):
        self.directory_resolver = directory_resolver
        self.properties_loader = properties_loader

    def discover_all(self) -> List[str]:
        agents_dir = self.directory_resolver.agents_root()
        if not os.path.exists(agents_dir):
            logger.warning("Agents directory not found: %s", agents_dir)
            return []

        available_agents: List[str] = []
        for item in os.listdir(agents_dir):
            item_path = os.path.join(agents_dir, item)
            if not os.path.isdir(item_path) or item.startswith("__"):
                continue

            props_file = os.path.join(item_path, "agent.properties")
            if not os.path.exists(props_file):
                logger.debug("Skipping %s: no agent.properties found", item)
                continue

            py_files = [f for f in os.listdir(item_path) if f.endswith(".py") and not f.startswith("__")]
            if not py_files:
                logger.debug("Skipping %s: no Python implementation found", item)
                continue

            available_agents.append(item)
            logger.debug("Discovered agent: %s", item)

        return sorted(available_agents)

    def describe(self, agent_name: str) -> Dict[str, str]:
        agent_dir = self.directory_resolver.resolve_agent_dir(agent_name)
        props_file = os.path.join(agent_dir, "agent.properties")
        return self.properties_loader.load(props_file)


class AgentModuleLoader:
    """加载智能体配置和实现类。"""

    def __init__(
        self,
        directory_resolver: AgentDirectoryResolver,
        properties_loader: PropertiesFileLoader,
        class_resolver: AgentClassResolver,
    ):
        self.directory_resolver = directory_resolver
        self.properties_loader = properties_loader
        self.class_resolver = class_resolver

    def load(self, agent_name: str) -> AgentModuleInfo:
        normalized_name = self.directory_resolver.normalize_agent_name(agent_name)
        agent_dir = self.directory_resolver.resolve_agent_dir(agent_name)

        if not os.path.exists(agent_dir):
            raise ValueError(f"Agent directory not found: {agent_dir}")
        if not os.path.isdir(agent_dir):
            raise ValueError(f"Not a directory: {agent_dir}")

        props_file = os.path.join(agent_dir, "agent.properties")
        try:
            properties = self.properties_loader.load(props_file)
        except FileNotFoundError:
            raise ValueError(f"agent.properties not found in {agent_dir}")
        except Exception as exc:
            raise ValueError(f"Failed to parse agent.properties: {exc}")

        agent_code = properties.get("agent_code")
        agent_type = properties.get("agent_type", "")
        agent_display_name = properties.get("agent_name", normalized_name)
        if not agent_code:
            raise ValueError(f"agent_code not found in {props_file}")

        logger.debug("Loaded properties for %s:", normalized_name)
        logger.debug("  agent_code: %s", agent_code)
        logger.debug("  agent_type: %s", agent_type)
        logger.debug("  agent_name: %s", agent_display_name)

        agent_class = self.class_resolver.find_agent_class(agent_dir)
        if agent_class is None:
            import_details = ""
            if self.class_resolver.last_import_errors:
                import_details = " Import failures: " + "; ".join(self.class_resolver.last_import_errors)
            raise ValueError(
                f"No CustomAgent or BaseHydroAgent subclass found in {agent_dir}. "
                f"Please define a CustomAgent implementation (recommended) or an existing BaseHydroAgent subclass."
                f"{import_details}"
            )

        logger.debug("Found agent class: %s", agent_class.__name__)

        return AgentModuleInfo(
            name=normalized_name,
            agent_class=agent_class,
            script_dir=agent_dir,
            agent_code=agent_code,
            agent_type=agent_type,
            agent_display_name=agent_display_name,
        )


class LauncherServiceFactory:
    """组装 launcher 的发现、解析和模块加载服务。"""

    def __init__(self, launcher_dir: str):
        self.launcher_dir = launcher_dir

    def create(self) -> LauncherServices:
        properties_loader = PropertiesFileLoader()
        directory_resolver = AgentDirectoryResolver(self.launcher_dir)
        discovery_service = AgentDiscoveryService(directory_resolver, properties_loader)
        module_loader = AgentModuleLoader(
            directory_resolver=directory_resolver,
            properties_loader=properties_loader,
            class_resolver=AgentClassResolver(),
        )
        return LauncherServices(
            discovery_service=discovery_service,
            module_loader=module_loader,
        )


class AgentFactoryRegistrationService:
    """把发现到的智能体模块注册为可由 callback 创建的 factory。"""

    def __init__(
        self,
        module_loader: AgentModuleLoader,
        env_file: str,
        register_default_central_scheduling_agent: bool = False,
        logger: Optional[logging.Logger] = None,
    ):
        self.module_loader = module_loader
        self.env_file = env_file
        self.register_default_central_scheduling_agent = register_default_central_scheduling_agent
        self.logger = logger or logging.getLogger(__name__)

    def register_agents(
        self,
        callback: MultiAgentCallback,
        agent_names: List[str],
    ) -> Tuple[Dict[str, str], List[RegisteredAgentInfo]]:
        env_config: Optional[Dict[str, str]] = None
        registered_agents: List[RegisteredAgentInfo] = []

        for agent_name in agent_names:
            self.logger.info("Registering %s agent...", agent_name.upper())
            agent_info = self.module_loader.load(agent_name)

            if env_config is None:
                env_config = load_env_config(self.env_file)
                self.logger.info("  Cluster ID: %s", env_config["hydros_cluster_id"])
                self.logger.info("  Node ID: %s", env_config["hydros_node_id"])

            config_file = os.path.join(agent_info.script_dir, "agent.properties")
            agent_factory = self._create_agent_factory(agent_info, config_file, env_config)
            callback.register_agent_factory(agent_info.agent_code, agent_factory)

            registered_agent = RegisteredAgentInfo.from_module(agent_info)
            registered_agents.append(registered_agent)
            self._log_registered_agent(agent_name, registered_agent)

        if env_config is None:
            env_config = load_env_config(self.env_file)
            self.logger.info("  Cluster ID: %s", env_config["hydros_cluster_id"])
            self.logger.info("  Node ID: %s", env_config["hydros_node_id"])

        if self.register_default_central_scheduling_agent:
            callback.register_system_default_central_scheduling_agent(env_config)
            if not any(
                agent.agent_code == SYSTEM_CENTRAL_SCHEDULING_AGENT_CODE
                for agent in registered_agents
            ):
                registered_agent = RegisteredAgentInfo.system_default_central_scheduling()
                registered_agents.append(registered_agent)
                self._log_registered_agent(registered_agent.name, registered_agent)

        return env_config, registered_agents

    @staticmethod
    def _create_agent_factory(
        agent_info: AgentModuleInfo,
        config_file: str,
        env_config: Dict[str, str],
    ):
        if issubclass(agent_info.agent_class, CustomAgent):
            return CustomAgentFactory(
                custom_agent_class=agent_info.agent_class,
                config_file=config_file,
                env_config=env_config,
            )
        return HydroAgentFactory(
            agent_class=agent_info.agent_class,
            config_file=config_file,
            env_config=env_config,
        )

    def _log_registered_agent(self, agent_name: str, agent: RegisteredAgentInfo) -> None:
        self.logger.info("  ✓ %s agent registered", agent_name.upper())
        self.logger.info("    Display Name: %s", agent.agent_display_name)
        self.logger.info("    Agent Code: %s", agent.agent_code)
        self.logger.info("    Agent Class: %s", agent.agent_class)


class CoordinationClientFactory:
    """根据共享环境配置创建统一的 SimCoordinationClient。"""

    def create(
        self,
        env_config: Dict[str, str],
        callback: MultiAgentCallback,
    ) -> SimCoordinationClient:
        return SimCoordinationClient(
            broker_url=env_config["mqtt_broker_url"],
            broker_port=int(env_config["mqtt_broker_port"]),
            topic=env_config["mqtt_topic"],
            sim_coordination_callback=callback,
            mqtt_username=env_config.get("mqtt_username"),
            mqtt_password=env_config.get("mqtt_password"),
        )


class LauncherStartupReporter:
    """集中输出 multi-agent launcher 启动摘要。"""

    def __init__(self, log_file: str, logger: Optional[logging.Logger] = None):
        self.log_file = log_file
        self.logger = logger or logging.getLogger(__name__)

    def log_starting(self, agent_names: List[str]) -> None:
        self.logger.info("=" * 70)
        self.logger.info("Multi-Agent Launcher")
        self.logger.info("=" * 70)
        self.logger.info("Starting %s agent types: %s", len(agent_names), ", ".join(agent_names))
        self.logger.info("Log file: %s", self.log_file)
        self.logger.info("=" * 70)
        self.logger.info("")

    def log_started(
        self,
        env_config: Dict[str, str],
        registered_agents: List[RegisteredAgentInfo],
    ) -> None:
        self.logger.info("")
        self.logger.info("=" * 70)
        self.logger.info("Multi-Agent System Started!")
        self.logger.info("=" * 70)
        self.logger.info("  MQTT Broker: %s:%s", env_config["mqtt_broker_url"], int(env_config["mqtt_broker_port"]))
        self.logger.info("  MQTT Topic: %s", env_config["mqtt_topic"])
        self.logger.info("")
        self.logger.info("Registered agent types:")
        for agent in registered_agents:
            self.logger.info("  • %s", agent.name.upper())
            self.logger.info("      Agent Code:   %s", agent.agent_code)
            self.logger.info("      Agent Type:   %s", agent.agent_type)
            self.logger.info("      Display Name: %s", agent.agent_display_name)
            self.logger.info("      Class Name:   %s", agent.agent_class)
            self.logger.info("      Directory:    agents/%s/", agent.directory)
        self.logger.info("")
        self.logger.info("Press Ctrl+C to stop all agents...")
        self.logger.info("")


class LauncherLoggingConfigurator:
    """根据启动参数和 env.properties 配置 launcher 日志。"""

    def __init__(
        self,
        env_file: str,
        log_file: str,
        log_dir: str,
    ):
        self.env_file = env_file
        self.log_file = log_file
        self.log_dir = log_dir

    def configure(self, argv: List[str]) -> None:
        os.makedirs(self.log_dir, exist_ok=True)
        hydros_cluster_id, hydros_node_id = self._resolve_logging_context()
        setup_logging(
            level=logging.DEBUG if "--debug" in argv else logging.INFO,
            hydros_cluster_id=hydros_cluster_id,
            hydros_node_id=hydros_node_id,
            console=True,
            log_file=self.log_file,
            simple="--full-log" not in argv,
            use_rolling=True,
        )

    def _resolve_logging_context(self) -> Tuple[Optional[str], Optional[str]]:
        try:
            env_config = load_env_config(self.env_file)
        except (FileNotFoundError, ValueError):
            return os.getenv("HYDROS_CLUSTER_ID"), os.getenv("HYDROS_NODE_ID")
        return env_config["hydros_cluster_id"], env_config["hydros_node_id"]


class LauncherDebugSupport:
    """配置 debugpy 远程调试。"""

    def __init__(self, project_root: str, logger: Optional[logging.Logger] = None):
        self.project_root = project_root
        self.logger = logger or logging.getLogger(__name__)

    def setup(self, port: int = 5678, wait_for_client: bool = True) -> None:
        try:
            import debugpy
        except ImportError:
            self._log_debugpy_missing()
            sys.exit(1)

        debugpy.listen(("0.0.0.0", port))
        self._log_debug_configuration(port)

        if wait_for_client:
            self.logger.info("⏳ Waiting for debugger to attach...")
            self.logger.info("   (Press Ctrl+C to skip and continue)")
            try:
                debugpy.wait_for_client()
                self.logger.info("✓ Debugger attached!")
            except KeyboardInterrupt:
                self.logger.info("⚠ Skipped waiting for debugger")

        self.logger.info("")

    def _log_debug_configuration(self, port: int) -> None:
        self.logger.info("=" * 70)
        self.logger.info("🐛 DEBUG MODE ENABLED")
        self.logger.info("=" * 70)
        self.logger.info("Debugpy listening on port %s", port)
        self.logger.info("Connect your debugger to: localhost:%s", port)
        self.logger.info("")
        self.logger.info("VS Code launch.json configuration:")
        self.logger.info("{")
        self.logger.info('  "name": "Attach to Hydros Agent",')
        self.logger.info('  "type": "python",')
        self.logger.info('  "request": "attach",')
        self.logger.info('  "connect": {"host": "localhost", "port": %s},', port)
        self.logger.info('  "pathMappings": [')
        self.logger.info('    {')
        self.logger.info('      "localRoot": "${workspaceFolder}",')
        self.logger.info('      "remoteRoot": "%s"', self.project_root)
        self.logger.info('    }')
        self.logger.info('  ]')
        self.logger.info("}")
        self.logger.info("=" * 70)

    def _log_debugpy_missing(self) -> None:
        self.logger.error("=" * 70)
        self.logger.error("❌ debugpy not installed!")
        self.logger.error("=" * 70)
        self.logger.error("Install debugpy to enable debug mode:")
        self.logger.error("  pip install debugpy")
        self.logger.error("=" * 70)


class LauncherCli:
    """解析和展示 multi-agent launcher 命令行。"""

    def __init__(
        self,
        discovery_service: AgentDiscoveryService,
        default_debug_port: int = 5678,
    ):
        self.discovery_service = discovery_service
        self.default_debug_port = default_debug_port

    def parse(self, argv: List[str]) -> LauncherOptions:
        if len(argv) < 2 or "--help" in argv or "-h" in argv:
            return LauncherOptions(agent_names=[], show_help=True)

        debug_enabled = "--debug" in argv
        debug_wait = "--debug-nowait" not in argv
        debug_port = self._parse_debug_port(argv)
        enable_system_central = "--enable-system-central-scheduling-agent" in argv

        if "--list" in argv:
            return LauncherOptions(
                agent_names=[],
                debug_enabled=debug_enabled,
                debug_wait=debug_wait,
                debug_port=debug_port,
                enable_system_central_scheduling_agent=enable_system_central,
                list_only=True,
            )

        if "--check" in argv or "--doctor" in argv:
            return LauncherOptions(
                agent_names=[],
                debug_enabled=debug_enabled,
                debug_wait=debug_wait,
                debug_port=debug_port,
                enable_system_central_scheduling_agent=enable_system_central,
                check_only=True,
            )

        all_requested = "--all" in argv
        if all_requested:
            agent_names = self.discovery_service.discover_all()
        else:
            agent_names = [
                arg for arg in argv[1:]
                if not arg.startswith("--") and arg != str(debug_port)
            ]

        return LauncherOptions(
            agent_names=agent_names,
            debug_enabled=debug_enabled,
            debug_wait=debug_wait,
            debug_port=debug_port,
            enable_system_central_scheduling_agent=enable_system_central,
            all_requested=all_requested,
        )

    def print_help(self) -> None:
        available_agents = self.discovery_service.discover_all()
        agents_list = "\n".join(
            [f"    {agent:15} - Auto-discovered from agents/{agent}/" for agent in available_agents]
        )
        if not agents_list:
            agents_list = "    (No agents found in launcher directory or agents/)"

        print(f"""
Multi-Agent Launcher - 在单个进程中运行多个 agents

用法:
    python -m hydros_agent_sdk.launcher --launcher-dir <dir> -- [选项] [agent1] [agent2] ...
    python -m hydros_agent_sdk.launcher --launcher-dir <dir> -- --all
    python -m hydros_agent_sdk.launcher --launcher-dir <dir> -- --list

可用的 agents (自动发现):
{agents_list}

选项:
    --all              - 启动所有可用的 agents
    --list             - 列出所有可用的 agents
    --check, --doctor  - 检查配置、agent.properties 和 Agent 类加载，不连接 MQTT
    --debug            - 启用远程调试模式 (debugpy)
    --debug-port PORT  - 指定调试端口 (默认: 5678)
    --debug-nowait     - 不等待调试器连接，直接启动
    --enable-system-central-scheduling-agent
                       - 显式注册 SDK 内置 CENTRAL_SCHEDULING_AGENT（默认不注册）
    --full-log         - 使用完整日志格式（生产环境），默认使用简化格式
    --help             - 显示帮助信息

示例:
    # 列出所有可用的 agents
    python -m hydros_agent_sdk.launcher --launcher-dir <dir> -- --list

    # 检查 launcher 目录是否具备启动条件
    python -m hydros_agent_sdk.launcher --launcher-dir <dir> -- --check

    # 启动单个 agent
    python -m hydros_agent_sdk.launcher --launcher-dir <dir> -- myagent

    # 启动多个 agents（在同一个进程中）
    python -m hydros_agent_sdk.launcher --launcher-dir <dir> -- agent1 agent2

    # 启动所有 agents
    python -m hydros_agent_sdk.launcher --launcher-dir <dir> -- --all

    # 启用调试模式（等待调试器连接）
    python -m hydros_agent_sdk.launcher --launcher-dir <dir> -- --debug agent1 agent2

    # 启用调试模式（不等待，直接启动）
    python -m hydros_agent_sdk.launcher --launcher-dir <dir> -- --debug --debug-nowait myagent

    # 使用自定义调试端口
    python -m hydros_agent_sdk.launcher --launcher-dir <dir> -- --debug --debug-port 5679 myagent

调试模式:
    • 使用 debugpy 进行远程调试
    • 默认监听端口: 5678
    • 支持 VS Code、PyCharm 等 IDE
    • 可以设置断点、单步调试、查看变量等

特性:
    • 自动发现 launcher 目录或 agents/ 子目录下的所有 agent 实现
    • 从 agent.properties 读取配置（agent_code, agent_name）
    • 自动扫描并加载 BaseHydroAgent 子类
    • 无需硬编码 agent 列表，每个目录一个 agent 实现
    • 所有 agents 在同一个进程中运行
    • 前台运行，可以在控制台看到日志
    • 所有日志保存到 launcher 配置的日志文件
    • 日志内容中包含 agent 标识，可以区分不同的 agent
    • 使用 Ctrl+C 优雅停止所有 agents

添加新 Agent:
    1. 在 launcher 目录或 agents/ 子目录下创建新目录（如 myagent/）
    2. 创建 agent.properties 文件，包含 agent_code 和 agent_name
    3. 创建 Python 文件，实现 BaseHydroAgent 的子类
    4. 运行 python -m hydros_agent_sdk.launcher --launcher-dir <dir> -- myagent
""")

    def print_agent_list(self) -> int:
        print("\n" + "=" * 70)
        print("Available Agents (auto-discovered)")
        print("=" * 70)
        available_agents = self.discovery_service.discover_all()

        if not available_agents:
            print("No agents found in launcher directory or agents/")
            print("\nTo add a new agent:")
            print("  1. Create a directory in the launcher directory or agents/")
            print("  2. Add agent.properties with agent_code and agent_name")
            print("  3. Implement a BaseHydroAgent subclass")
        else:
            for agent_name in available_agents:
                try:
                    properties = self.discovery_service.describe(agent_name)
                    agent_code = properties.get("agent_code", "N/A")
                    agent_display_name = properties.get("agent_name", "N/A")

                    print(f"\n  {agent_name}")
                    print(f"    Display Name: {agent_display_name}")
                    print(f"    Agent Code:   {agent_code}")
                    print(f"    Directory:    agents/{agent_name}/")
                except Exception as exc:
                    print(f"\n  {agent_name}")
                    print(f"    Error: {exc}")

        print("\n" + "=" * 70)
        print(f"Total: {len(available_agents)} agent(s)")
        print("=" * 70 + "\n")
        return len(available_agents)

    def _parse_debug_port(self, argv: List[str]) -> int:
        if "--debug-port" not in argv:
            return self.default_debug_port

        try:
            port_idx = argv.index("--debug-port")
            if port_idx + 1 < len(argv):
                return int(argv[port_idx + 1])
        except (ValueError, IndexError):
            pass

        raise ValueError("Invalid --debug-port value")


class LauncherDoctor:
    """执行 launcher 目录的本地启动前检查。"""

    def __init__(
        self,
        launcher_dir: str,
        env_file: str,
        discovery_service: AgentDiscoveryService,
        module_loader: AgentModuleLoader,
    ):
        self.launcher_dir = launcher_dir
        self.env_file = env_file
        self.discovery_service = discovery_service
        self.module_loader = module_loader
        self._results: List[Tuple[bool, str, str]] = []

    def run(self) -> int:
        self._results = []
        print("\n" + "=" * 70)
        print("Hydros Launcher Doctor")
        print("=" * 70)
        print(f"Launcher directory: {self.launcher_dir}")
        print(f"Environment file:   {self.env_file}")
        print()

        self._check_env_config()
        self._check_agents()
        self._print_summary()
        return 0 if all(ok for ok, _title, _message in self._results) else 1

    def _check_env_config(self) -> None:
        try:
            env_config = load_env_config(self.env_file)
        except Exception as exc:
            self._record(
                False,
                "env.properties",
                f"{exc}. Create env.properties in the launcher directory and fill local values.",
            )
            return

        cluster_id = env_config.get("hydros_cluster_id", "(missing)")
        node_id = env_config.get("hydros_node_id", "(missing)")
        self._record(True, "env.properties", f"cluster={cluster_id}, node={node_id}")

    def _check_agents(self) -> None:
        agent_names = self.discovery_service.discover_all()
        if not agent_names:
            self._record(
                False,
                "agents",
                "No agents discovered. Add directories with agent.properties and a BaseHydroAgent subclass.",
            )
            return

        self._record(True, "agents", f"discovered {len(agent_names)}: {', '.join(agent_names)}")
        for agent_name in agent_names:
            try:
                agent_info = self.module_loader.load(agent_name)
            except Exception as exc:
                self._record(False, f"agent:{agent_name}", str(exc))
                continue

            self._record(
                True,
                f"agent:{agent_name}",
                f"{agent_info.agent_code} -> {agent_info.agent_class.__name__}",
            )

    def _record(self, ok: bool, title: str, message: str) -> None:
        self._results.append((ok, title, message))
        mark = "OK" if ok else "FAIL"
        print(f"[{mark}] {title}: {message}")

    def _print_summary(self) -> None:
        total = len(self._results)
        failed = len([result for result in self._results if not result[0]])
        print()
        print("=" * 70)
        if failed:
            print(f"Doctor found {failed} issue(s) out of {total} check(s).")
        else:
            print(f"Doctor passed {total} check(s).")
        print("=" * 70 + "\n")


class MultiAgentCoordinator:
    """在单个进程中管理多个 Hydros Agent。"""

    def __init__(
        self,
        launcher_dir: str,
        env_file: str,
        log_file: str,
        module_loader: Optional[AgentModuleLoader] = None,
        registration_service: Optional[AgentFactoryRegistrationService] = None,
        register_default_central_scheduling_agent: bool = False,
        client_factory: Optional[CoordinationClientFactory] = None,
        startup_reporter: Optional[LauncherStartupReporter] = None,
        callback_factory: Optional[Any] = None,
        managed_services: Optional[Sequence[ManagedRuntimeService]] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.launcher_dir = launcher_dir
        self.env_file = env_file
        self.log_file = log_file
        self.logger = logger or logging.getLogger(__name__)
        self.callback = None
        self.client = None
        if module_loader is None:
            module_loader = LauncherServiceFactory(launcher_dir).create().module_loader
        self.module_loader = module_loader
        self.registration_service = registration_service or AgentFactoryRegistrationService(
            module_loader=module_loader,
            env_file=env_file,
            register_default_central_scheduling_agent=register_default_central_scheduling_agent,
            logger=self.logger,
        )
        self.client_factory = client_factory or CoordinationClientFactory()
        self.startup_reporter = startup_reporter or LauncherStartupReporter(
            log_file=log_file,
            logger=self.logger,
        )
        self.callback_factory = callback_factory or self._create_callback
        self.managed_services = tuple(managed_services or ())
        self._started_managed_services: List[ManagedRuntimeService] = []
        self.running = False

    def load_agent_module(self, agent_name: str) -> AgentModuleInfo:
        """动态加载 agent 模块。"""
        return self.module_loader.load(agent_name)

    def start_all(self, agent_names: List[str]) -> bool:
        """启动所有指定的 agents。"""
        self.startup_reporter.log_starting(agent_names)

        self.logger.info("Creating unified MultiAgentCallback...")
        self.callback = self.callback_factory()

        try:
            env_config, registered_agents = self.registration_service.register_agents(
                self.callback,
                agent_names,
            )
        except Exception as exc:
            self.logger.error("Failed to register agents: %s", exc, exc_info=True)
            return False

        if not self._start_managed_services():
            return False

        self.logger.info("")
        self.logger.info("Creating SimCoordinationClient...")
        try:
            self.client = self.client_factory.create(env_config, self.callback)
            self.callback.set_client(self.client)

            self.logger.info("")
            self.logger.info("Starting coordination client...")
            self.client.start()
        except Exception as exc:
            self.logger.error("Failed to start coordination client: %s", exc, exc_info=True)
            self._stop_coordination_client()
            self._stop_managed_services()
            return False

        self.startup_reporter.log_started(env_config, registered_agents)
        self.running = True
        return True

    def stop_all(self) -> None:
        """停止所有 agents。"""
        if not self.running and not self._started_managed_services:
            return

        self.running = False
        self.logger.info("")
        self.logger.info("=" * 70)
        self.logger.info("Stopping multi-agent system...")
        self.logger.info("=" * 70)

        self._stop_managed_services()
        self._stop_coordination_client()

        self.logger.info("=" * 70)
        self.logger.info("Multi-agent system stopped")
        self.logger.info("=" * 70)

    def _start_managed_services(self) -> bool:
        for service in self.managed_services:
            service_name = service.__class__.__name__
            try:
                self.logger.info("Starting managed runtime service: %s", service_name)
                service.start()
                self._started_managed_services.append(service)
            except Exception as exc:
                self.logger.error(
                    "Failed to start managed runtime service %s: %s",
                    service_name,
                    exc,
                    exc_info=True,
                )
                self._stop_managed_services()
                return False
        return True

    def _stop_managed_services(self) -> None:
        while self._started_managed_services:
            service = self._started_managed_services.pop()
            service_name = service.__class__.__name__
            try:
                self.logger.info("Stopping managed runtime service: %s", service_name)
                service.stop()
            except Exception as exc:
                self.logger.error(
                    "Failed to stop managed runtime service %s: %s",
                    service_name,
                    exc,
                    exc_info=True,
                )

    def _stop_coordination_client(self) -> None:
        if self.client is None:
            return
        try:
            self.logger.info("Stopping coordination client...")
            self.client.stop()
            self.logger.info("  ✓ Client stopped")
        except Exception as exc:
            self.logger.error("  ✗ Error stopping client: %s", exc, exc_info=True)
        finally:
            self.client = None

    def run(self) -> None:
        """运行主循环，直到收到停止信号。"""
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.logger.info("")
            self.logger.info("Received interrupt signal...")
        finally:
            self.stop_all()

    @staticmethod
    def _create_callback() -> MultiAgentCallback:
        return MultiAgentCallback()


class LauncherRuntime:
    """运行 multi-agent coordinator 并管理进程信号。"""

    def __init__(self, coordinator, logger: Optional[logging.Logger] = None):
        self.coordinator = coordinator
        self.logger = logger or logging.getLogger(__name__)

    def install_signal_handlers(self) -> None:
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def run(self, agent_names: List[str]) -> int:
        self.install_signal_handlers()
        if self.coordinator.start_all(agent_names):
            self.coordinator.run()
            return 0

        self.logger.error("Failed to start agents")
        return 1

    def _signal_handler(self, _signum, _frame) -> None:
        self.logger.info("")
        self.logger.info("Received signal, stopping...")
        self.coordinator.stop_all()
        sys.exit(0)


class MultiAgentLauncherApp:
    """通用 multi-agent launcher 应用入口编排。"""

    def __init__(
        self,
        launcher_dir: str,
        env_file: str,
        log_file: str,
        log_dir: str,
        project_root: Optional[str] = None,
        default_debug_port: int = 5678,
        service_factory: Optional[LauncherServiceFactory] = None,
        managed_services: Optional[Sequence[ManagedRuntimeService]] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.launcher_dir = launcher_dir
        self.env_file = env_file
        self.log_file = log_file
        self.log_dir = log_dir
        self.project_root = project_root or launcher_dir
        self.default_debug_port = default_debug_port
        self.service_factory = service_factory or LauncherServiceFactory(launcher_dir)
        self.managed_services = tuple(managed_services or ())
        self.logger = logger or logging.getLogger(__name__)

    def run(self, argv: List[str]) -> int:
        LauncherLoggingConfigurator(
            env_file=self.env_file,
            log_file=self.log_file,
            log_dir=self.log_dir,
        ).configure(argv)

        services = self.service_factory.create()
        cli = LauncherCli(services.discovery_service, default_debug_port=self.default_debug_port)
        try:
            options = cli.parse(argv)
        except ValueError as exc:
            self.logger.error(str(exc))
            return 1

        if options.show_help:
            cli.print_help()
            return 0

        if options.list_only:
            cli.print_agent_list()
            return 0

        if options.check_only:
            return LauncherDoctor(
                launcher_dir=self.launcher_dir,
                env_file=self.env_file,
                discovery_service=services.discovery_service,
                module_loader=services.module_loader,
            ).run()

        agent_names = options.agent_names
        if options.all_requested:
            self.logger.info(
                "Auto-discovered %s agent(s): %s",
                len(agent_names),
                ", ".join(agent_names),
            )

        if not agent_names:
            self.logger.error("No agents specified!")
            cli.print_help()
            return 1

        if options.debug_enabled:
            LauncherDebugSupport(self.project_root, logger=self.logger).setup(
                port=options.debug_port,
                wait_for_client=options.debug_wait,
            )

        coordinator = MultiAgentCoordinator(
            launcher_dir=self.launcher_dir,
            env_file=self.env_file,
            log_file=self.log_file,
            module_loader=services.module_loader,
            register_default_central_scheduling_agent=options.enable_system_central_scheduling_agent,
            managed_services=self.managed_services,
            logger=self.logger,
        )
        runtime = LauncherRuntime(coordinator, logger=self.logger)
        return runtime.run(agent_names)
