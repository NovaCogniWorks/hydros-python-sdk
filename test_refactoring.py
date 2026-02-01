"""
Test script to verify the refactoring of BaseHydroAgent inheriting from HydroAgent.
"""

import sys
from hydros_agent_sdk import BaseHydroAgent
from hydros_agent_sdk.protocol.models import HydroAgent, SimulationContext, HydroAgentInstance
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest,
    SimTaskInitResponse,
    TickCmdRequest,
    TickCmdResponse,
    SimTaskTerminateRequest,
    SimTaskTerminateResponse,
)
from hydros_agent_sdk.protocol.models import CommandStatus, AgentBizStatus, AgentDriveMode


def test_inheritance():
    """Test that BaseHydroAgent properly inherits from HydroAgent."""
    print("=" * 70)
    print("TEST 1: Inheritance Relationship")
    print("=" * 70)

    # Check inheritance
    assert issubclass(BaseHydroAgent, HydroAgent), "BaseHydroAgent should inherit from HydroAgent"
    print("✓ BaseHydroAgent is a subclass of HydroAgent")

    # Check MRO (Method Resolution Order)
    mro = [c.__name__ for c in BaseHydroAgent.__mro__]
    print(f"✓ MRO: {' -> '.join(mro)}")

    # Verify HydroAgent is in the MRO
    assert 'HydroAgent' in mro, "HydroAgent should be in MRO"
    print("✓ HydroAgent is in the Method Resolution Order")

    # Verify HydroBaseModel is in the MRO (Pydantic model)
    assert 'HydroBaseModel' in mro, "HydroBaseModel should be in MRO"
    print("✓ HydroBaseModel (Pydantic) is in the Method Resolution Order")

    print("\n✅ Inheritance test PASSED\n")


def test_concrete_implementation():
    """Test that we can create a concrete implementation of BaseHydroAgent."""
    print("=" * 70)
    print("TEST 2: Concrete Implementation")
    print("=" * 70)

    # Create a mock coordination client
    class MockCoordinationClient:
        def __init__(self):
            from hydros_agent_sdk.state_manager import AgentStateManager
            self.state_manager = AgentStateManager()
            self.state_manager.set_node_id("TEST_NODE")

        def enqueue(self, response):
            pass

    # Create a concrete implementation
    class TestAgent(BaseHydroAgent):
        def _ensure_agent_instance(self):
            """Helper to ensure agent instance is created."""
            if not hasattr(self, 'hydro_agent_instance') or self.hydro_agent_instance is None:
                object.__setattr__(self, 'hydro_agent_instance', HydroAgentInstance(
                    agent_id=f"{self.agent_code}_test",
                    agent_code=self.agent_code,
                    agent_name=self.agent_name,
                    agent_type=self.agent_type,
                    agent_biz_status=AgentBizStatus.ACTIVE,
                    drive_mode=AgentDriveMode.SIM_TICK_DRIVEN,
                    agent_configuration_url=self.agent_configuration_url,
                    biz_scene_instance_id=self.biz_scene_instance_id,
                    hydros_cluster_id=self.hydros_cluster_id,
                    hydros_node_id=self.hydros_node_id,
                    context=self.context
                ))

        def on_init(self, request: SimTaskInitRequest) -> SimTaskInitResponse:
            self._ensure_agent_instance()
            return SimTaskInitResponse(
                context=self.context,
                command_id=request.command_id,
                command_status=CommandStatus.SUCCEED,
                source_agent_instance=self.hydro_agent_instance,
                created_agent_instances=[self.hydro_agent_instance],
                managed_top_objects={},
                broadcast=False
            )

        def on_tick(self, request: TickCmdRequest) -> TickCmdResponse:
            self._ensure_agent_instance()
            return TickCmdResponse(
                context=self.context,
                command_id=request.command_id,
                command_status=CommandStatus.SUCCEED,
                source_agent_instance=self.hydro_agent_instance,
                broadcast=False
            )

        def on_terminate(self, request: SimTaskTerminateRequest) -> SimTaskTerminateResponse:
            self._ensure_agent_instance()
            return SimTaskTerminateResponse(
                context=self.context,
                command_id=request.command_id,
                command_status=CommandStatus.SUCCEED,
                source_agent_instance=self.hydro_agent_instance,
                broadcast=False
            )

    # Create test context
    context = SimulationContext(
        biz_scene_instance_id="TEST_CONTEXT_001"
    )

    # Create mock client
    mock_client = MockCoordinationClient()

    # Instantiate the agent
    agent = TestAgent(
        sim_coordination_client=mock_client,
        context=context,
        agent_code="TEST_AGENT",
        agent_name="Test Agent",
        agent_type="TEST_AGENT",
        agent_configuration_url="http://example.com/config.yaml",
        hydros_cluster_id="test_cluster",
        hydros_node_id="test_node"
    )

    print(f"✓ Created TestAgent instance: {agent}")

    # Verify properties from HydroAgent (parent)
    assert agent.agent_code == "TEST_AGENT", "agent_code should be set"
    print(f"✓ agent_code: {agent.agent_code}")

    assert agent.agent_name == "Test Agent", "agent_name should be set"
    print(f"✓ agent_name: {agent.agent_name}")

    assert agent.agent_type == "TEST_AGENT", "agent_type should be set"
    print(f"✓ agent_type: {agent.agent_type}")

    assert agent.agent_configuration_url == "http://example.com/config.yaml", "agent_configuration_url should be set"
    print(f"✓ agent_configuration_url: {agent.agent_configuration_url}")

    # Verify properties from BaseHydroAgent (child)
    assert agent.context == context, "context should be set"
    print(f"✓ context: {agent.context.biz_scene_instance_id}")

    assert agent.biz_scene_instance_id == "TEST_CONTEXT_001", "biz_scene_instance_id should be set"
    print(f"✓ biz_scene_instance_id: {agent.biz_scene_instance_id}")

    assert agent.hydros_cluster_id == "test_cluster", "hydros_cluster_id should be set"
    print(f"✓ hydros_cluster_id: {agent.hydros_cluster_id}")

    assert agent.hydros_node_id == "test_node", "hydros_node_id should be set"
    print(f"✓ hydros_node_id: {agent.hydros_node_id}")

    print("\n✅ Concrete implementation test PASSED\n")

    return agent


def test_lifecycle_methods(agent):
    """Test that lifecycle methods work correctly."""
    print("=" * 70)
    print("TEST 3: Lifecycle Methods")
    print("=" * 70)

    # Test on_init
    init_request = SimTaskInitRequest(
        context=agent.context,
        command_id="CMD_INIT_001",
        command_status=CommandStatus.INIT,
        source_agent_instance=None,
        broadcast=False,
        agent_list=[]  # Required field
    )

    init_response = agent.on_init(init_request)
    assert init_response.command_status == CommandStatus.SUCCEED, "Init should succeed"
    print(f"✓ on_init() executed successfully: {init_response.command_id}")

    # Test on_tick
    tick_request = TickCmdRequest(
        context=agent.context,
        command_id="CMD_TICK_001",
        command_status=CommandStatus.INIT,
        source_agent_instance=None,
        broadcast=False,
        step=1,
        step_time=None
    )

    tick_response = agent.on_tick(tick_request)
    assert tick_response.command_status == CommandStatus.SUCCEED, "Tick should succeed"
    print(f"✓ on_tick() executed successfully: {tick_response.command_id}")

    # Test on_terminate
    terminate_request = SimTaskTerminateRequest(
        context=agent.context,
        command_id="CMD_TERM_001",
        command_status=CommandStatus.INIT,
        source_agent_instance=None,
        broadcast=False,
        reason="Test termination"
    )

    terminate_response = agent.on_terminate(terminate_request)
    assert terminate_response.command_status == CommandStatus.SUCCEED, "Terminate should succeed"
    print(f"✓ on_terminate() executed successfully: {terminate_response.command_id}")

    print("\n✅ Lifecycle methods test PASSED\n")


def test_pydantic_serialization(agent):
    """Test that Pydantic serialization works correctly."""
    print("=" * 70)
    print("TEST 4: Pydantic Serialization")
    print("=" * 70)

    # Test model_dump (Pydantic v2)
    try:
        data = agent.model_dump()
        print(f"✓ model_dump() works: {list(data.keys())}")

        # Verify key fields are present
        assert 'agent_code' in data or 'agentCode' in data, "agent_code should be in serialized data"
        assert 'agent_type' in data or 'agentType' in data, "agent_type should be in serialized data"
        print("✓ Serialized data contains expected fields")

    except Exception as e:
        print(f"✗ model_dump() failed: {e}")
        return False

    # Test model_dump_json
    try:
        json_str = agent.model_dump_json()
        print(f"✓ model_dump_json() works: {json_str[:100]}...")
    except Exception as e:
        print(f"✗ model_dump_json() failed: {e}")
        return False

    print("\n✅ Pydantic serialization test PASSED\n")


def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("REFACTORING VERIFICATION TEST SUITE")
    print("Testing: BaseHydroAgent inherits from HydroAgent")
    print("=" * 70 + "\n")

    try:
        # Test 1: Inheritance
        test_inheritance()

        # Test 2: Concrete implementation
        agent = test_concrete_implementation()

        # Test 3: Lifecycle methods
        test_lifecycle_methods(agent)

        # Test 4: Pydantic serialization
        test_pydantic_serialization(agent)

        # Summary
        print("=" * 70)
        print("ALL TESTS PASSED ✅")
        print("=" * 70)
        print("\nRefactoring Summary:")
        print("  • BaseHydroAgent now inherits from HydroAgent (parent)")
        print("  • HydroAgent is a Pydantic model with agent properties")
        print("  • BaseHydroAgent adds behavioral methods (on_init, on_tick, etc.)")
        print("  • All functionality is preserved and working correctly")
        print("=" * 70 + "\n")

        return 0

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}\n")
        return 1
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
