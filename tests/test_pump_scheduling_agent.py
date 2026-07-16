import unittest
import sys
import os
import types
from unittest.mock import Mock
sys.path.insert(0, os.path.abspath('custom-agent/pump/scheduling'))
from pump_scheduling_agent import PumpCentralSchedulingAgent

class MockContext:
    def __init__(self):
        self.biz_scene_instance_id = "test_scene"
        self.tenant = None
        self.biz_scenario = None
        self.waterway = None

class MockClient:
    def __init__(self):
        self.state_manager = self
        self.transport = Mock()
        self.topic = "test/topic"
        self.enqueued = []
    def send_command(self, req): pass
    def subscribe(self, topic): pass
    def enqueue(self, command): self.enqueued.append(command)

class TestPumpSchedulingAgent(unittest.TestCase):
    def setUp(self):
        self._original_plot_tracker_module = sys.modules.get("plot_tracker")
        self._plot_tracker = Mock()
        self._plot_tracker.step_predictions = []
        fake_plot_tracker_module = types.ModuleType("plot_tracker")
        fake_plot_tracker_module.PlotHistoryTracker = Mock(
            return_value=self._plot_tracker
        )
        sys.modules["plot_tracker"] = fake_plot_tracker_module
        self.addCleanup(self._restore_plot_tracker_module)

        self.client = MockClient()
        self.agent = PumpCentralSchedulingAgent(
            sim_coordination_client=self.client,
            agent_id="agent1",
            agent_code="code",
            agent_type="type",
            agent_name="name",
            context=MockContext(),
            hydros_cluster_id="cluster",
            hydros_node_id="node"
        )
        self.agent.properties["mpc_config_url"] = "custom-agent/pump/data/config_xhh.yaml"
        mock_agent = Mock()
        mock_agent.agent_code = "mock_station_code"
        self.agent._target_agent_resolver.resolve_target_agent_for_object = Mock(return_value=mock_agent)
        self.agent._lazy_init_odd_mpc()

    def _restore_plot_tracker_module(self):
        if self._original_plot_tracker_module is None:
            sys.modules.pop("plot_tracker", None)
        else:
            sys.modules["plot_tracker"] = self._original_plot_tracker_module

    def test_rolling_optimization(self):
        print("\n--- Starting Rolling Optimization Test ---")
        steps = 3
        # 覆盖初始泵站状态
        z1, z2, z3 = 13.26, 23.1, 28.0
        
        def set_station_data(sid, u_lvl, d_lvl, q=0.0):
            import json
            units = self.agent.available_units_map[sid]
            for uid in units:
                attrs = json.dumps({"front_water_level": u_lvl, "back_water_level": d_lvl, "back_water_flow": q / len(units)})
                self.agent._metrics_data_cache.update({"object_id": uid, "metrics_code": "pump_status", "value": 0.0, "position_code": "none", "attributes": attrs})
                self.agent._metrics_data_cache.update({"object_id": uid, "metrics_code": "blade_angle", "value": 0.0, "position_code": "none"})

        # 泵站 S1
        set_station_data(1, 10.5, z1, 0.0)
        # 泵站 S2
        set_station_data(2, z1, z2, 0.0)
        # 泵站 S3
        set_station_data(3, z2, z3, 0.0)

        for t in range(steps):
            print(f"\nStep {t}:")
            commands = self.agent.on_optimization(t)
            self.assertIsInstance(commands, list)
            self.assertEqual(len(self.client.enqueued), t + 1)
            agent_res = self.agent.mpc_output
            lower_res = agent_res['lower']
            upper_res = agent_res['upper']
            
            # 打印上层 MPC 结果
            print("  Upper MPC Predicted Flow:")
            for sid, q_list in upper_res['q_planned'].items():
                print(f"    Station {sid}: {q_list[:3]}")
                
            # 打印下层 MPC 结果
            print("  Lower MPC Output:")
            for sid, res in lower_res.items():
                status = res['status'][0]
                openings = res['openings'][0]
                total_q = res['total_q'][0]
                print(f"    Station {sid} Target Flow: {total_q:.2f}, Status: {status}, Openings: {[round(o, 2) for o in openings]}")
                
            # 模拟一个简单步
            # 注意：该单元测试中假设理想跟踪并向前推进
            z1 += 0.01 * (lower_res[1]['total_q'][0] - lower_res[2]['total_q'][0])
            z2 += 0.01 * (lower_res[2]['total_q'][0] - lower_res[3]['total_q'][0])
            for u in self.agent.available_units_map[1]:
                self.agent._metrics_data_cache.update({"object_id": u, "metrics_code": "down_water_level", "value": z1, "position_code": "none"})
                
            for u in self.agent.available_units_map[2]:
                self.agent._metrics_data_cache.update({"object_id": u, "metrics_code": "up_water_level", "value": z1, "position_code": "none"})
                self.agent._metrics_data_cache.update({"object_id": u, "metrics_code": "down_water_level", "value": z2, "position_code": "none"})
                
            for u in self.agent.available_units_map[3]:
                self.agent._metrics_data_cache.update({"object_id": u, "metrics_code": "up_water_level", "value": z2, "position_code": "none"})
                self.agent._metrics_data_cache.update({"object_id": u, "metrics_code": "down_water_level", "value": z3, "position_code": "none"})
            
        self.assertTrue(True)

if __name__ == '__main__':
    unittest.main()
