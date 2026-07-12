"""Regression tests for the composition-based developer Agent API."""

from pathlib import Path

from hydros_agent_sdk import AgentBehavior, AgentIdentity, BehaviorAgentFactory
from hydros_agent_sdk.launcher.support import AgentClassResolver, AgentFactoryRegistrationService
from hydros_agent_sdk.multi_agent import MultiAgentCallback
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskTerminateRequest,
    TickCmdRequest,
)
from hydros_agent_sdk.protocol.models import HydroAgent, SimulationContext
from hydros_agent_sdk.runtime.behavior_agent_adapter import BehaviorAgentAdapter
from hydros_agent_sdk.state_manager import AgentStateManager


class FakeClient:
    def __init__(self):
        self.state_manager = AgentStateManager()
        self.enqueued = []

    def enqueue(self, response):
        self.enqueued.append(response)


class RecordingBehavior(AgentBehavior):
    def __init__(self):
        self.events = []

    def on_init(self, runtime, request):
        self.events.append(("init", runtime.agent, runtime.simulation_context))

    def on_tick(self, runtime, request):
        self.events.append(("tick", runtime.agent, request.step))

    def on_terminate(self, runtime, request):
        self.events.append(("terminate", runtime.agent, request.context))


def make_context():
    return SimulationContext(biz_scene_instance_id="TASK_COMPOSED_API")


def make_init_request(context, agent_type="COMPOSED_AGENT"):
    return SimTaskInitRequest(
        command_id="CMD_INIT",
        context=context,
        agent_list=[
            HydroAgent(
                agent_code="COMPOSED_AGENT",
                agent_type=agent_type,
                agent_name="Composed Agent",
                agent_configuration_url="",
            )
        ],
    )


def test_behavior_adapter_keeps_developer_behavior_outside_protocol_inheritance():
    context = make_context()
    client = FakeClient()
    behavior = RecordingBehavior()
    adapter = BehaviorAgentAdapter(
        behavior=behavior,
        sim_coordination_client=client,
        agent_id="AGT_COMPOSED",
        agent_code="COMPOSED_AGENT",
        agent_type="COMPOSED_AGENT",
        agent_name="Composed Agent",
        context=context,
        hydros_cluster_id="cluster",
        hydros_node_id="node",
    )

    init_response = adapter.on_init(make_init_request(context))
    tick_response = adapter.on_tick(TickCmdRequest(command_id="CMD_TICK", context=context, step=3))
    terminate_response = adapter.on_terminate(
        SimTaskTerminateRequest(command_id="CMD_TERM", context=context)
    )

    identity = behavior.events[0][1]
    assert isinstance(identity, AgentIdentity)
    assert identity.agent_id == "AGT_COMPOSED"
    assert not hasattr(adapter.execution_context, "agent_instance")
    assert not hasattr(behavior, "agent_id")
    assert init_response.source_agent_instance is adapter
    assert tick_response.completed_step == 3
    assert terminate_response.source_agent_instance is adapter
    assert [event[0] for event in behavior.events] == ["init", "tick", "terminate"]


def test_behavior_factory_and_multi_agent_own_task_lifecycle(tmp_path):
    config_file = tmp_path / "agent.properties"
    config_file.write_text(
        "agent_code=COMPOSED_AGENT\nagent_type=COMPOSED_AGENT\nagent_name=Composed Agent\n",
        encoding="utf-8",
    )
    client = FakeClient()
    callback = MultiAgentCallback(node_id="node")
    callback.set_client(client)
    factory = BehaviorAgentFactory(
        behavior_class=RecordingBehavior,
        config_file=str(config_file),
        env_config={"hydros_cluster_id": "cluster", "hydros_node_id": "node"},
    )
    callback.register_agent_factory("COMPOSED_AGENT", factory)
    context = make_context()

    init_response = callback.on_sim_task_init(make_init_request(context, agent_type="ROUTED_TYPE"))
    adapter = callback.agents[context.biz_scene_instance_id]["COMPOSED_AGENT"]
    assert client.state_manager.has_active_context(context)
    assert client.state_manager.is_local_agent(adapter)

    tick_response = callback.on_tick(TickCmdRequest(command_id="CMD_TICK", context=context, step=4))
    terminate_response = callback.on_task_terminate(
        SimTaskTerminateRequest(command_id="CMD_TERM", context=context)
    )

    assert init_response.source_agent_instance is adapter
    assert adapter.behavior.events[0][1].agent_type == "ROUTED_TYPE"
    assert tick_response[0].completed_step == 4
    assert terminate_response[0].source_agent_instance is adapter
    assert not client.state_manager.has_active_context(context)
    assert client.state_manager.get_agent_instance(adapter.agent_id) is None


def test_launcher_discovers_composition_based_template():
    template_dir = Path(__file__).parents[1] / "examples" / "agents" / "template"

    agent_class = AgentClassResolver().find_agent_class(str(template_dir))

    assert agent_class is not None
    assert issubclass(agent_class, AgentBehavior)


def test_launcher_registration_selects_behavior_factory(monkeypatch):
    class ModuleLoader:
        def load(self, _agent_name):
            return type(
                "ModuleInfo",
                (),
                {
                    "name": "composed",
                    "agent_class": RecordingBehavior,
                    "script_dir": "/tmp/composed",
                    "agent_code": "COMPOSED_AGENT",
                    "agent_type": "COMPOSED_AGENT",
                    "agent_display_name": "Composed Agent",
                },
            )()

    class Callback:
        def __init__(self):
            self.factory = None

        def register_agent_factory(self, _agent_code, factory):
            self.factory = factory

    monkeypatch.setattr(
        "hydros_agent_sdk.launcher.support.load_env_config",
        lambda _path: {"hydros_cluster_id": "cluster", "hydros_node_id": "node"},
    )
    callback = Callback()

    AgentFactoryRegistrationService(ModuleLoader(), "/tmp/env.properties").register_agents(
        callback,
        ["composed"],
    )

    assert isinstance(callback.factory, BehaviorAgentFactory)
    assert callback.factory.behavior_class is RecordingBehavior
