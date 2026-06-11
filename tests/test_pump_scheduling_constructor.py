import importlib
import os
import sys
import types
from unittest.mock import Mock


def _install_optional_dependency_stubs(monkeypatch):
    scipy_module = types.ModuleType("scipy")
    scipy_optimize_module = types.ModuleType("scipy.optimize")
    scipy_optimize_module.differential_evolution = lambda *args, **kwargs: None
    scipy_module.optimize = scipy_optimize_module

    numpy_module = types.ModuleType("numpy")
    pandas_module = types.ModuleType("pandas")
    pandas_module.DataFrame = lambda *args, **kwargs: []

    flow_depart_module = types.ModuleType("flow_depart")
    flow_depart_module.generate_flow_depart = lambda *args, **kwargs: None

    monkeypatch.setitem(sys.modules, "scipy", scipy_module)
    monkeypatch.setitem(sys.modules, "scipy.optimize", scipy_optimize_module)
    monkeypatch.setitem(sys.modules, "numpy", numpy_module)
    monkeypatch.setitem(sys.modules, "pandas", pandas_module)
    monkeypatch.setitem(sys.modules, "flow_depart", flow_depart_module)


def test_pump_scheduling_constructor_uses_base_rolling_optimization_binding(monkeypatch):
    _install_optional_dependency_stubs(monkeypatch)
    scheduling_dir = os.path.abspath("custom-agent/pump/scheduling")
    if scheduling_dir not in sys.path:
        sys.path.insert(0, scheduling_dir)

    module = importlib.import_module("pump_scheduling_agent")

    class FakeRollingRuntime:
        def set_rolling_cycle_runner(self, _runner):
            raise AssertionError("Pump scheduling should use the base optimize_step binding")

    def fake_base_init(self, *args, **kwargs):
        object.__setattr__(self, "_mpc_rolling_runtime", FakeRollingRuntime())

    monkeypatch.setattr(module.CentralSchedulingAgent, "__init__", fake_base_init)

    module.PumpCentralSchedulingAgent(
        sim_coordination_client=Mock(),
        agent_id="agent-001",
        agent_code="CENTRAL_SCHEDULING_AGENT_PUMP",
        agent_type="CENTRAL_SCHEDULING_AGENT",
        agent_name="Pump Scheduling Agent",
        context=Mock(biz_scene_instance_id="task-001"),
        hydros_cluster_id="cluster",
        hydros_node_id="node",
    )
