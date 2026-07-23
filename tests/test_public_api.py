"""Public import boundary for the unreleased SDK."""

import importlib

import pytest

import hydros_agent_sdk
import hydros_agent_sdk.agent_commands as agent_commands
import hydros_agent_sdk.launcher as launcher
import hydros_agent_sdk.protocol as protocol
import hydros_agent_sdk.runtime as runtime
import hydros_agent_sdk.transport as transport


ROOT_PUBLIC_API = {
    "__version__",
    "get_sdk_version",
    "AgentErrorContext",
    "AgentExecutionContext",
    "AgentIdentity",
    "ControlActuator",
    "ControlActuatorTarget",
    "ControlAlgorithm",
    "ControlAlgorithmContext",
    "ControlAlgorithmHttpService",
    "ControlAlgorithmInput",
    "ControlAlgorithmOutput",
    "ControlAlgorithmRuntime",
    "ControlAlgorithmStatus",
    "ControlSignal",
    "ControlTaskType",
    "ControlValueRange",
    "CustomAgent",
    "CustomAgentFactory",
    "ErrorCode",
    "ErrorCodes",
    "MultiAgentCallback",
    "SignalType",
    "SimCoordinationCallback",
    "SimCoordinationClient",
    "create_control_algorithm_http_server",
    "create_error_response",
    "handle_agent_errors",
    "safe_execute",
    "setup_logging",
    "validate_request",
}


def test_root_package_exports_only_stable_developer_api():
    assert set(hydros_agent_sdk.__all__) == ROOT_PUBLIC_API

    for internal_name in (
        "AgentBehavior",
        "AgentStateManager",
        "BaseHydroAgent",
        "BehaviorAgentFactory",
        "HydroAgentFactory",
        "InMemoryTransport",
        "MessageFilter",
        "ResponseFactory",
        "TaskRuntime",
    ):
        assert not hasattr(hydros_agent_sdk, internal_name)


def test_internal_packages_do_not_reexport_runtime_or_testing_helpers():
    assert runtime.__all__ == []
    assert agent_commands.__all__ == []
    assert launcher.__all__ == ["MultiAgentLauncherApp"]
    assert set(transport.__all__) == {
        "Transport",
        "MqttMetricsPublisher",
        "MqttMetricsSubscriber",
    }


def test_protocol_package_exports_dtos_without_decoder_or_registry_internals():
    assert {
        "SimTaskInitRequest",
        "SimTaskInitResponse",
        "SimulationContext",
        "HydroAgentInstance",
        "MpcPredictionResult",
    }.issubset(protocol.__all__)
    assert "AgentCommandDecoder" not in protocol.__all__
    assert "AgentCommandHandlerRegistry" not in protocol.__all__


def test_historical_composition_adapter_module_is_removed():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("hydros_agent_sdk.runtime.behavior_agent_adapter")
