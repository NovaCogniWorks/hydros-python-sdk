from types import SimpleNamespace

import hydros_agent_sdk.launcher.support as support_module
from hydros_agent_sdk.launcher.support import (
    AgentDirectoryResolver,
    AgentFactoryRegistrationService,
    LauncherCli,
    LauncherLoggingConfigurator,
    MultiAgentCoordinator,
)


def test_agent_directory_resolver_has_no_business_aliases_by_default():
    resolver = AgentDirectoryResolver("/tmp/hydros-agents")

    assert resolver.normalize_agent_name("pump") == "pump"
    assert resolver.normalize_agent_name("outflowplan") == "outflowplan"


def test_launcher_cli_parses_explicit_agent_names_without_business_expansion():
    class DiscoveryService:
        def discover_all(self):
            return ["outflowplan", "scheduling"]

    cli = LauncherCli(DiscoveryService())

    options = cli.parse(["multi_agent_launcher.py", "outflowplan", "scheduling"])

    assert options.agent_names == ["outflowplan", "scheduling"]
    assert not options.all_requested


def test_launcher_cli_parses_system_default_central_opt_in():
    class DiscoveryService:
        def discover_all(self):
            return ["scheduling"]

    cli = LauncherCli(DiscoveryService())

    options = cli.parse([
        "multi_agent_launcher.py",
        "--enable-system-central-scheduling-agent",
        "scheduling",
    ])

    assert options.agent_names == ["scheduling"]
    assert options.enable_system_central_scheduling_agent


def test_launcher_cli_parses_check_and_doctor_aliases():
    class DiscoveryService:
        def discover_all(self):
            return ["template"]

    cli = LauncherCli(DiscoveryService())

    check_options = cli.parse(["multi_agent_launcher.py", "--check"])
    doctor_options = cli.parse(["multi_agent_launcher.py", "--doctor"])

    assert check_options.check_only
    assert doctor_options.check_only
    assert not check_options.agent_names
    assert not doctor_options.agent_names


def test_launcher_logging_does_not_invent_deployment_identity(monkeypatch, tmp_path):
    captured = {}

    def missing_env_config(_env_file):
        raise FileNotFoundError("missing env.properties")

    monkeypatch.delenv("HYDROS_CLUSTER_ID", raising=False)
    monkeypatch.delenv("HYDROS_NODE_ID", raising=False)
    monkeypatch.setattr(support_module, "load_env_config", missing_env_config)
    monkeypatch.setattr(
        support_module,
        "setup_logging",
        lambda **kwargs: captured.update(kwargs),
    )

    LauncherLoggingConfigurator(
        env_file=str(tmp_path / "env.properties"),
        log_file=str(tmp_path / "hydros.log"),
        log_dir=str(tmp_path),
    ).configure(["multi_agent_launcher.py", "--full-log"])

    assert captured["hydros_cluster_id"] is None
    assert captured["hydros_node_id"] is None


def test_launcher_doctor_returns_zero_when_env_and_agents_are_valid(monkeypatch, capsys):
    class FakeAgent:
        pass

    class DiscoveryService:
        def discover_all(self):
            return ["template"]

    class ModuleLoader:
        def load(self, agent_name):
            assert agent_name == "template"
            return SimpleNamespace(
                agent_code="TEMPLATE_AGENT",
                agent_class=FakeAgent,
            )

    monkeypatch.setattr(
        support_module,
        "load_env_config",
        lambda _env_file: {"hydros_cluster_id": "cluster", "hydros_node_id": "node"},
    )

    doctor = support_module.LauncherDoctor(
        launcher_dir="/tmp/hydros-agents",
        env_file="/tmp/hydros-agents/env.properties",
        discovery_service=DiscoveryService(),
        module_loader=ModuleLoader(),
    )

    assert doctor.run() == 0
    output = capsys.readouterr().out
    assert "[OK] env.properties" in output
    assert "[OK] agent:template" in output


def test_launcher_doctor_returns_nonzero_when_no_agents(monkeypatch, capsys):
    class DiscoveryService:
        def discover_all(self):
            return []

    class ModuleLoader:
        pass

    monkeypatch.setattr(
        support_module,
        "load_env_config",
        lambda _env_file: {"hydros_cluster_id": "cluster", "hydros_node_id": "node"},
    )

    doctor = support_module.LauncherDoctor(
        launcher_dir="/tmp/hydros-agents",
        env_file="/tmp/hydros-agents/env.properties",
        discovery_service=DiscoveryService(),
        module_loader=ModuleLoader(),
    )

    assert doctor.run() == 1
    output = capsys.readouterr().out
    assert "[FAIL] agents" in output


def test_multi_agent_coordinator_runs_generic_registration_flow():
    class Callback:
        def __init__(self):
            self.client = None

        def set_client(self, client):
            self.client = client

    class RegistrationService:
        def __init__(self):
            self.callback = None
            self.agent_names = None

        def register_agents(self, callback, agent_names):
            self.callback = callback
            self.agent_names = agent_names
            return {"mqtt_broker_url": "localhost", "mqtt_broker_port": "1883", "mqtt_topic": "topic"}, []

    class Client:
        def __init__(self):
            self.started = False
            self.stopped = False

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

    class ClientFactory:
        def __init__(self, client):
            self.client = client
            self.env_config = None
            self.callback = None

        def create(self, env_config, callback):
            self.env_config = env_config
            self.callback = callback
            return self.client

    class Reporter:
        def __init__(self):
            self.starting_agents = None
            self.started = False

        def log_starting(self, agent_names):
            self.starting_agents = agent_names

        def log_started(self, _env_config, _registered_agents):
            self.started = True

    callback = Callback()
    client = Client()
    registration_service = RegistrationService()
    client_factory = ClientFactory(client)
    reporter = Reporter()
    coordinator = MultiAgentCoordinator(
        launcher_dir="/tmp/hydros-agents",
        env_file="/tmp/hydros-agents/env.properties",
        log_file="/tmp/hydros-agents/logs/hydros.log",
        module_loader=object(),
        registration_service=registration_service,
        client_factory=client_factory,
        startup_reporter=reporter,
        callback_factory=lambda: callback,
    )

    assert coordinator.start_all(["outflowplan", "scheduling"])

    assert reporter.starting_agents == ["outflowplan", "scheduling"]
    assert registration_service.callback is callback
    assert registration_service.agent_names == ["outflowplan", "scheduling"]
    assert client_factory.callback is callback
    assert callback.client is client
    assert client.started
    assert reporter.started

    coordinator.stop_all()

    assert client.stopped
    assert not coordinator.running


def test_multi_agent_coordinator_returns_false_when_client_start_fails():
    class Callback:
        def __init__(self):
            self.client = None

        def set_client(self, client):
            self.client = client

    class RegistrationService:
        def register_agents(self, _callback, _agent_names):
            return {"mqtt_broker_url": "bad-host", "mqtt_broker_port": "1883", "mqtt_topic": "topic"}, []

    class Client:
        def start(self):
            raise RuntimeError("Failed to connect to MQTT broker bad-host:1883")

    class ClientFactory:
        def __init__(self, client):
            self.client = client

        def create(self, _env_config, _callback):
            return self.client

    class Reporter:
        def __init__(self):
            self.started = False

        def log_starting(self, _agent_names):
            return None

        def log_started(self, _env_config, _registered_agents):
            self.started = True

    callback = Callback()
    client = Client()
    reporter = Reporter()
    coordinator = MultiAgentCoordinator(
        launcher_dir="/tmp/hydros-agents",
        env_file="/tmp/hydros-agents/env.properties",
        log_file="/tmp/hydros-agents/logs/hydros.log",
        module_loader=object(),
        registration_service=RegistrationService(),
        client_factory=ClientFactory(client),
        startup_reporter=reporter,
        callback_factory=lambda: callback,
    )

    assert not coordinator.start_all(["scheduling"])

    assert callback.client is client
    assert not reporter.started
    assert not coordinator.running


def test_registration_service_does_not_register_system_default_central_scheduling_agent_by_default(monkeypatch):
    class FakeAgent:
        pass

    class ModuleLoader:
        def load(self, agent_name):
            assert agent_name == "scheduling"
            return SimpleNamespace(
                name="scheduling",
                agent_class=FakeAgent,
                script_dir="/tmp/hydros-agents/scheduling",
                agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
                agent_type="CENTRAL_SCHEDULING_AGENT_PUMP",
                agent_display_name="泵站调度智能体",
            )

    class Callback:
        def __init__(self):
            self.registered = []
            self.system_default_env_config = None

        def register_agent_factory(self, agent_code, agent_factory):
            self.registered.append((agent_code, agent_factory))

        def register_system_default_central_scheduling_agent(self, env_config):
            self.system_default_env_config = env_config
            self.registered.append(("CENTRAL_SCHEDULING_AGENT", "system-default-factory"))

    monkeypatch.setattr(
        support_module,
        "load_env_config",
        lambda _env_file: {"hydros_cluster_id": "cluster", "hydros_node_id": "node"},
    )
    monkeypatch.setattr(
        support_module,
        "HydroAgentFactory",
        lambda agent_class, config_file, env_config: {
            "agent_class": agent_class,
            "config_file": config_file,
            "env_config": env_config,
        },
    )

    callback = Callback()
    service = AgentFactoryRegistrationService(ModuleLoader(), "/tmp/hydros-agents/env.properties")

    env_config, registered_agents = service.register_agents(callback, ["scheduling"])

    assert env_config == {"hydros_cluster_id": "cluster", "hydros_node_id": "node"}
    assert callback.registered[0][0] == "CENTRAL_SCHEDULING_AGENT_PUMP"
    assert callback.system_default_env_config is None
    assert [agent.agent_code for agent in registered_agents] == ["CENTRAL_SCHEDULING_AGENT_PUMP"]


def test_registration_service_registers_system_default_central_scheduling_agent_when_enabled(monkeypatch):
    class FakeAgent:
        pass

    class ModuleLoader:
        def load(self, agent_name):
            assert agent_name == "scheduling"
            return SimpleNamespace(
                name="scheduling",
                agent_class=FakeAgent,
                script_dir="/tmp/hydros-agents/scheduling",
                agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
                agent_type="CENTRAL_SCHEDULING_AGENT_PUMP",
                agent_display_name="泵站调度智能体",
            )

    class Callback:
        def __init__(self):
            self.registered = []
            self.system_default_env_config = None

        def register_agent_factory(self, agent_code, agent_factory):
            self.registered.append((agent_code, agent_factory))

        def register_system_default_central_scheduling_agent(self, env_config):
            self.system_default_env_config = env_config
            self.registered.append(("CENTRAL_SCHEDULING_AGENT", "system-default-factory"))

    monkeypatch.setattr(
        support_module,
        "load_env_config",
        lambda _env_file: {"hydros_cluster_id": "cluster", "hydros_node_id": "node"},
    )
    monkeypatch.setattr(
        support_module,
        "HydroAgentFactory",
        lambda agent_class, config_file, env_config: {
            "agent_class": agent_class,
            "config_file": config_file,
            "env_config": env_config,
        },
    )

    callback = Callback()
    service = AgentFactoryRegistrationService(
        ModuleLoader(),
        "/tmp/hydros-agents/env.properties",
        register_default_central_scheduling_agent=True,
    )

    env_config, registered_agents = service.register_agents(callback, ["scheduling"])

    assert env_config == {"hydros_cluster_id": "cluster", "hydros_node_id": "node"}
    assert callback.registered[0][0] == "CENTRAL_SCHEDULING_AGENT_PUMP"
    assert callback.registered[1][0] == "CENTRAL_SCHEDULING_AGENT"
    assert callback.system_default_env_config == env_config
    assert [agent.agent_code for agent in registered_agents] == [
        "CENTRAL_SCHEDULING_AGENT_PUMP",
        "CENTRAL_SCHEDULING_AGENT",
    ]
    assert registered_agents[1].agent_class == "SystemCentralSchedulingAgent"
