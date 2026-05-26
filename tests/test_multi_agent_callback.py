from unittest.mock import patch

from hydros_agent_sdk.context_manager import ContextManager
from hydros_agent_sdk.multi_agent import MultiAgentCallback
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
    TickCmdRequest,
    TickCmdResponse,
)
from hydros_agent_sdk.protocol.models import (
    AgentStatus,
    AgentDriveMode,
    CommandStatus,
    HydroAgent,
    HydroAgentInstance,
    SimulationContext,
)
from hydros_agent_sdk.state_manager import AgentStateManager
from hydros_agent_sdk.utils import TopHydroObject as TopologyTopHydroObject, WaterwayTopology


def make_context():
    return SimulationContext(biz_scene_instance_id="TASK_001")


def make_instance(context, agent_code="TEST_AGENT"):
    return HydroAgentInstance(
        agent_code=agent_code,
        agent_type=agent_code,
        agent_name="Test Agent",
        agent_configuration_url="",
        agent_id=f"AGT_{agent_code}",
        biz_scene_instance_id=context.biz_scene_instance_id,
        hydros_cluster_id="cluster",
        hydros_node_id="node",
        context=context,
        agent_status=AgentStatus.ACTIVE,
        drive_mode=AgentDriveMode.SIM_TICK_DRIVEN,
    )


class FakeClient:
    def __init__(self):
        self.state_manager = AgentStateManager()
        self.enqueued = []

    def enqueue(self, response):
        self.enqueued.append(response)


class FakeAgent:
    def __init__(self, instance):
        self.instance = instance
        self.agent_code = instance.agent_code

    def on_init(self, request):
        return SimTaskInitResponse(
            command_id=request.command_id,
            context=request.context,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self.instance,
            created_agent_instances=[self.instance],
            managed_top_objects={},
            broadcast=False,
        )

    def on_tick(self, request):
        return TickCmdResponse(
            command_id=request.command_id,
            context=request.context,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self.instance,
            broadcast=False,
        )

    def on_terminate(self, request):
        return SimTaskTerminateResponse(
            command_id=request.command_id,
            context=request.context,
            command_status=CommandStatus.SUCCEED,
            source_agent_instance=self.instance,
            broadcast=False,
        )


class ContextAwareFakeAgent(FakeAgent):
    def __init__(self, instance):
        super().__init__(instance)
        self.context_on_init = None

    def on_init(self, request):
        self.context_on_init = ContextManager.get_context(request.context)
        return super().on_init(request)


class FakeFactory:
    def __init__(self, agent, agent_type=None):
        self.agent = agent
        self.agent_type = agent_type
        self.created = 0

    def create_agent(self, sim_coordination_client, context):
        self.created += 1
        return self.agent


def make_init_request(context, agent_code="TEST_AGENT", agent_type=None):
    return SimTaskInitRequest(
        command_id="CMD_INIT",
        context=context,
        agent_list=[
            HydroAgent(
                agent_code=agent_code,
                agent_type=agent_type or agent_code,
                agent_name="Test Agent",
                agent_configuration_url="",
            )
        ],
    )


def test_multi_agent_init_creates_context_from_scenario_config_before_agent_init():
    ContextManager.clear()
    context = make_context()
    instance = make_instance(context)
    agent = ContextAwareFakeAgent(instance)
    callback = MultiAgentCallback(node_id="node")
    callback.register_agent_factory("TEST_AGENT", FakeFactory(agent))
    client = FakeClient()
    callback.set_client(client)

    topology = WaterwayTopology(
        topObjects=[
            TopologyTopHydroObject(
                objectId=1001,
                objectName="Gate Station 1001",
                objectType="GateStation",
            )
        ]
    )
    request = make_init_request(context)
    request.biz_scene_configuration_url = "https://example.test/scenario.yaml"

    try:
        with patch(
            "hydros_agent_sdk.context_manager.YamlLoader.from_url",
            return_value={"hydrosObjectsModelingUrl": "https://example.test/topology.yaml"},
        ) as load_scenario_config, patch(
            "hydros_agent_sdk.context_manager.HydroObjectUtilsV2.build_waterway_topology",
            return_value=topology,
        ) as build_topology:
            response = callback.on_sim_task_init(request)
    finally:
        ContextManager.clear()

    assert isinstance(response, SimTaskInitResponse)
    assert agent.context_on_init is not None
    assert agent.context_on_init.topology is topology
    load_scenario_config.assert_called_once_with("https://example.test/scenario.yaml")
    build_topology.assert_called_once_with(
        modeling_yml_uri="https://example.test/topology.yaml",
        param_keys=None,
        with_metrics_code=True,
    )


def test_multi_agent_init_returns_response_without_direct_enqueue():
    context = make_context()
    instance = make_instance(context)
    callback = MultiAgentCallback(node_id="node")
    callback.register_agent_factory("TEST_AGENT", FakeFactory(FakeAgent(instance)))
    client = FakeClient()
    callback.set_client(client)

    response = callback.on_sim_task_init(make_init_request(context))

    assert isinstance(response, SimTaskInitResponse)
    assert response.command_id == "CMD_INIT"
    assert response.command_status == CommandStatus.SUCCEED
    assert response.created_agent_instances == [instance]
    assert client.enqueued == []
    assert "TEST_AGENT" in callback.agents[context.biz_scene_instance_id]


def test_default_central_scheduling_route_uses_system_factory_without_custom_factory():
    context = make_context()
    system_instance = make_instance(context, "CENTRAL_SCHEDULING_AGENT")
    system_factory = FakeFactory(FakeAgent(system_instance), agent_type="CENTRAL_SCHEDULING_AGENT")
    callback = MultiAgentCallback(node_id="node")
    callback.register_agent_factory("CENTRAL_SCHEDULING_AGENT", system_factory)
    client = FakeClient()
    callback.set_client(client)

    response = callback.on_sim_task_init(
        make_init_request(
            context,
            agent_code="CENTRAL_SCHEDULING_AGENT_POWER01",
            agent_type="CENTRAL_SCHEDULING_AGENT",
        )
    )

    assert isinstance(response, SimTaskInitResponse)
    assert response.created_agent_instances == [system_instance]
    assert system_factory.created == 1
    assert "CENTRAL_SCHEDULING_AGENT" in callback.agents[context.biz_scene_instance_id]
    assert "CENTRAL_SCHEDULING_AGENT_POWER01" not in callback.agents[context.biz_scene_instance_id]


def test_custom_central_scheduling_route_requires_exact_agent_code_when_custom_factory_exists():
    context = make_context()
    system_instance = make_instance(context, "CENTRAL_SCHEDULING_AGENT")
    custom_instance = make_instance(context, "CENTRAL_SCHEDULING_AGENT_POWER01")
    system_factory = FakeFactory(FakeAgent(system_instance), agent_type="CENTRAL_SCHEDULING_AGENT")
    custom_factory = FakeFactory(FakeAgent(custom_instance), agent_type="CENTRAL_SCHEDULING_AGENT")
    callback = MultiAgentCallback(node_id="node")
    callback.register_agent_factory("CENTRAL_SCHEDULING_AGENT", system_factory)
    callback.register_agent_factory("CENTRAL_SCHEDULING_AGENT_POWER01", custom_factory)
    client = FakeClient()
    callback.set_client(client)

    response = callback.on_sim_task_init(
        make_init_request(
            context,
            agent_code="CENTRAL_SCHEDULING_AGENT_POWER01",
            agent_type="CENTRAL_SCHEDULING_AGENT",
        )
    )

    assert isinstance(response, SimTaskInitResponse)
    assert response.created_agent_instances == [custom_instance]
    assert system_factory.created == 0
    assert custom_factory.created == 1
    assert "CENTRAL_SCHEDULING_AGENT_POWER01" in callback.agents[context.biz_scene_instance_id]


def test_multi_agent_tick_and_terminate_return_response_lists():
    context = make_context()
    instance = make_instance(context)
    callback = MultiAgentCallback(node_id="node")
    callback.agents[context.biz_scene_instance_id] = {
        "TEST_AGENT": FakeAgent(instance),
    }

    tick_responses = callback.on_tick(
        TickCmdRequest(command_id="CMD_TICK", context=context, step=1)
    )
    terminate_responses = callback.on_task_terminate(
        SimTaskTerminateRequest(command_id="CMD_TERM", context=context)
    )

    assert len(tick_responses) == 1
    assert isinstance(tick_responses[0], TickCmdResponse)
    assert tick_responses[0].command_status == CommandStatus.SUCCEED
    assert len(terminate_responses) == 1
    assert isinstance(terminate_responses[0], SimTaskTerminateResponse)
    assert context.biz_scene_instance_id not in callback.agents
